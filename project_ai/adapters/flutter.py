"""
adapters/flutter.py — Proyectos Flutter y paquetes Dart.

Qué descubre (todo con evidencia archivo:línea):
  Dart SDK    pubspec.yaml environment.sdk '>=3.0.0 <4.0.0' → mínimo '3.0.0' (EXPLICIT).
  Flutter SDK pubspec.yaml environment.flutter '>=3.16.0' → '3.16.0' (EXPLICIT).
              Solo si la sección flutter: está presente (no paquetes Dart puros).
  Módulo kind flutter: plugin: → 'flutter-plugin';
              flutter: (sin plugin) → 'flutter-app';
              sin flutter: → 'dart-package'.
  Plataformas directorios android/ ios/ web/ linux/ macos/ windows/ → hecho flutter.platforms.
  Servicios   deps: firebase_* → firebase; supabase → supabase;
              postgres/postgres_pool → postgresql; mqtt_client → mqtt;
              sqflite/drift → sqlite.
  Rutas       GoRoute(path: '...') en lib/**/*.dart → HEURISTIC.
  Comandos    flutter pub get / flutter run / flutter test / flutter build apk
              (paquete Dart puro → dart pub get / dart test).

Prioridades:
  pubspec.yaml environment.*   → EXPLICIT
  pubspec.yaml deps/flutter:   → BUILD
  directorios de plataforma    → BUILD

Parser de pubspec.yaml: regex sobre bloques indentados (sin PyYAML).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..model import (Command, Endpoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "flutter"

# --------------------------------------------------------------------------
# Servicios detectables en pubspec.yaml
# --------------------------------------------------------------------------

_SERVICE_PREFIXES: list[tuple[str, re.Pattern]] = [
    ("firebase",    re.compile(r'\bfirebase_\w+')),
    ("supabase",    re.compile(r'\bsupabase(?:_flutter)?\b')),
    ("postgresql",  re.compile(r'\bpostgres(?:_pool)?\b')),
    ("mqtt",        re.compile(r'\bmqtt_client\b')),
    ("sqlite",      re.compile(r'\b(?:sqflite|drift)\b')),
    ("graphql",     re.compile(r'\b(?:graphql_flutter|ferry)\b')),
    ("websocket",   re.compile(r'\bweb_socket_channel\b')),
]

# Plataformas reconocidas (nombre del directorio)
_PLATFORMS = ("android", "ios", "web", "linux", "macos", "windows")

# GoRoute(path: '/...')
_RX_GOROUTE = re.compile(
    r"GoRoute\s*\([^)]*?path\s*:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# Named routes: '/path': (context) => ... o '/path': SomeWidget()
_RX_NAMED_ROUTE = re.compile(r"""['\"](/[^'\"]+)['\"]\s*:""")

# --------------------------------------------------------------------------
# Parser mínimo de pubspec.yaml
# --------------------------------------------------------------------------

def _parse_pubspec(text: str) -> dict:
    """Extrae campos clave de pubspec.yaml sin depender de PyYAML."""
    out: dict = {
        "name": "", "version": "",
        "env_sdk": "", "env_flutter": "",
        "deps": [],
        "has_flutter_section": False,
        "is_plugin": False,
    }

    # Campos escalares de nivel raíz
    for field in ("name", "version"):
        m = re.search(rf'^{field}\s*:\s*([^\n#]+)', text, re.MULTILINE)
        if m:
            out[field] = m.group(1).strip().strip("'\"")

    # environment: block (captura líneas indentadas después de "environment:")
    env_m = re.search(r'^environment\s*:\s*\n((?:[ \t]+[^\n]*\n?)*)', text, re.MULTILINE)
    if env_m:
        env_block = env_m.group(1)
        m = re.search(r"sdk\s*:\s*['\"]([^'\"]+)['\"]", env_block)
        if m:
            out["env_sdk"] = m.group(1)
        m = re.search(r"flutter\s*:\s*['\"]([^'\"]+)['\"]", env_block)
        if m:
            out["env_flutter"] = m.group(1)

    # dependencies + dev_dependencies: collect dep names
    for section in ("dependencies", "dev_dependencies"):
        sec_m = re.search(
            rf'^{section}\s*:\s*\n((?:[ \t]+[^\n]*\n?)*)',
            text, re.MULTILINE,
        )
        if sec_m:
            block = sec_m.group(1)
            for dep_m in re.finditer(r'^  ([\w_-]+)\s*:', block, re.MULTILINE):
                name = dep_m.group(1)
                if name not in ("flutter", "sdk"):
                    out["deps"].append(name)

    # flutter: section
    out["has_flutter_section"] = bool(re.search(r'^flutter\s*:', text, re.MULTILINE))
    out["is_plugin"] = bool(re.search(r'^\s+plugin\s*:', text, re.MULTILINE))

    return out


def _min_version(constraint: str) -> str | None:
    """'>=3.0.0 <4.0.0' → '3.0.0'; '>=3.16.0' → '3.16.0'."""
    m = re.search(r'>=\s*(\d+\.\d+(?:\.\d+)?)', constraint)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class FlutterAdapter(Adapter):
    """Flutter apps, plugins y paquetes Dart puros."""

    name = NAME

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        pkg = next((f for f in sc.files if f == "pubspec.yaml"), None)
        if pkg:
            return [StackDetection(adapter=NAME, confidence=0.97,
                                   evidence=[ev(pkg, None)])]
        return []

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)

        # Leer pubspec.yaml
        pkg_rel = next((f for f in sc.files if f == "pubspec.yaml"), None)
        if not pkg_rel:
            return
        try:
            pkg_text = (root / pkg_rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        pub = _parse_pubspec(pkg_text)

        # ----------------------------------------------------------------
        # Versión de Dart SDK
        # ----------------------------------------------------------------
        dart_min = _min_version(pub["env_sdk"]) if pub["env_sdk"] else None
        if dart_min:
            req(info, "dart", dart_min, P.EXPLICIT,
                pkg_rel, None, f"sdk: '{pub['env_sdk']}'", adapter=NAME)

        # ----------------------------------------------------------------
        # Versión de Flutter SDK (solo si es proyecto Flutter)
        # ----------------------------------------------------------------
        if pub["has_flutter_section"] and pub["env_flutter"]:
            flutter_min = _min_version(pub["env_flutter"])
            if flutter_min:
                req(info, "flutter", flutter_min, P.EXPLICIT,
                    pkg_rel, None, f"flutter: '{pub['env_flutter']}'",
                    adapter=NAME)

        # ----------------------------------------------------------------
        # Tipo de módulo
        # ----------------------------------------------------------------
        if pub["is_plugin"]:
            kind = "flutter-plugin"
        elif pub["has_flutter_section"]:
            kind = "flutter-app"
        else:
            kind = "dart-package"

        name = pub["name"] or Path(sc.root).name
        info.modules.append(Module(
            name=name, path=".", build_system=NAME, kind=kind,
        ))

        # ----------------------------------------------------------------
        # Plataformas
        # ----------------------------------------------------------------
        platforms = [
            p for p in _PLATFORMS
            if any(f.startswith(f"{p}/") for f in sc.files)
        ]
        if platforms:
            info.set_fact("flutter.platforms", Fact(
                value=platforms, priority=P.BUILD,
                evidence=[ev(pkg_rel, None)], adapter=NAME,
            ))

        # ----------------------------------------------------------------
        # Servicios
        # ----------------------------------------------------------------
        deps_text = "\n".join(pub["deps"])
        for svc_kind, rx in _SERVICE_PREFIXES:
            if rx.search(deps_text):
                add_service(info, svc_kind, None, P.BUILD,
                            pkg_rel, None, None, adapter=NAME)

        # ----------------------------------------------------------------
        # Rutas GoRouter (solo apps Flutter)
        # ----------------------------------------------------------------
        if kind == "flutter-app":
            self._extract_routes(root, sc, info)

        # ----------------------------------------------------------------
        # Comandos
        # ----------------------------------------------------------------
        is_flutter = pub["has_flutter_section"]
        self._add_commands(info, is_flutter, kind, platforms)

    # ----------------------------------------------------------------
    # Rutas GoRouter / Navigator
    # ----------------------------------------------------------------

    def _extract_routes(self, root: Path, sc: ProjectScanner,
                         info: ProjectInfo) -> None:
        dart_files = [
            f for f in sc.files
            if f.endswith(".dart") and f.startswith("lib/")
        ]
        seen: set[str] = set()
        for rel in dart_files:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # GoRoute(path: '...') — solo rutas absolutas (empiezan con /)
            # Las sub-rutas relativas (':id') necesitarían parseo del árbol
            for m in _RX_GOROUTE.finditer(text):
                path = m.group(1)
                if not path.startswith("/"):
                    continue
                if path in seen:
                    continue
                seen.add(path)
                # Calcular línea aproximada
                line = text[: m.start()].count("\n") + 1
                info.endpoints.append(Endpoint(
                    method="GET", path=path,
                    handler=f"go_router:{Path(rel).stem}",
                    file=rel, line=line,
                ))

            # Named routes: '/path': ...
            if "routes:" in text or "initialRoute:" in text:
                for m in _RX_NAMED_ROUTE.finditer(text):
                    path = m.group(1)
                    if path in seen:
                        continue
                    seen.add(path)
                    line = text[: m.start()].count("\n") + 1
                    info.endpoints.append(Endpoint(
                        method="GET", path=path,
                        handler=f"navigator:{Path(rel).stem}",
                        file=rel, line=line,
                    ))

    # ----------------------------------------------------------------
    # Comandos
    # ----------------------------------------------------------------

    def _add_commands(self, info: ProjectInfo, is_flutter: bool,
                       kind: str, platforms: list[str]) -> None:
        if not is_flutter:
            # Paquete Dart puro
            info.add_command(Command(
                name="deps", shell="dart pub get",
                success_hint="Got dependencies!",
            ), overwrite=True)
            info.add_command(Command(
                name="test", shell="dart test",
                success_hint="All tests passed!",
            ), overwrite=True)
            return

        # Flutter (app o plugin): overwrite=True porque pubspec.yaml es la
        # fuente de verdad; el adaptador gradle del subdirectorio android/ no
        # debe ganar cuando conviven ambos stacks en el mismo proyecto.
        info.add_command(Command(
            name="deps", shell="flutter pub get",
            success_hint="Got dependencies!",
        ), overwrite=True)
        info.add_command(Command(
            name="run", shell="flutter run",
            ide_hint="Android Studio / VS Code: Run → Flutter Run",
            success_hint="Syncing files to device",
        ), overwrite=True)
        info.add_command(Command(
            name="test", shell="flutter test",
            success_hint="All tests passed!",
        ), overwrite=True)

        if kind == "flutter-app":
            # Comando de build: APK si hay Android, iOS si solo iOS
            target = "apk" if "android" in platforms else "ios"
            info.add_command(Command(
                name="build", shell=f"flutter build {target}",
                success_hint="Built build/",
            ), overwrite=True)
