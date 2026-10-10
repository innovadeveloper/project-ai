"""
adapters/rust.py — Proyectos Rust (Cargo.toml).

Qué descubre (todo con evidencia archivo:línea):
  Rust edition    Cargo.toml  "edition = \"2021\"" → BUILD.
  rust-version    Cargo.toml  "rust-version = \"1.70\"" → EXPLICIT.
  Módulo kind     [[bin]] sin workspace → executable; [lib] → library;
                  [workspace] con members → workspace.
  Framework       dependencies → actix-web/axum/rocket/warp/poem/tide → api-server.
  Servicios       dependencies → sqlx/diesel/postgres → postgresql;
                  redis → redis; mongodb → mongodb; kafka rdkafka → kafka;
                  rabbitmq lapin → rabbitmq; sqlite rusqlite/diesel sqlite → sqlite.
  Endpoints       src/main.rs y src/**/*.rs: actix .route("/path", web::get()),
                  axum Router::new().route("/path", get(h)),
                  rocket #[get("/path")].
  Comandos        cargo fetch → deps; cargo build → build; cargo test → test;
                  cargo run → run (solo binary/workspace).

Prioridades:
  rust-version      → EXPLICIT
  edition, deps     → BUILD
"""
from __future__ import annotations

import re
from pathlib import Path

from ..model import Command, Endpoint, Fact, Module, ProjectInfo, SourcePriority as P, StackDetection
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "rust"

# --------------------------------------------------------------------------
# Servicios detectables en Cargo.toml dependencies
# --------------------------------------------------------------------------

_SERVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("postgresql", re.compile(r'\b(?:sqlx|diesel|postgres|tokio-postgres)\b')),
    ("mysql",      re.compile(r'\b(?:mysql|sqlx)\b.*mysql|mysql.*\b(?:sqlx)\b')),
    ("redis",      re.compile(r'\bredis\b')),
    ("mongodb",    re.compile(r'\bmongodb\b')),
    ("kafka",      re.compile(r'\brdkafka\b')),
    ("rabbitmq",   re.compile(r'\blapin\b')),
    ("sqlite",     re.compile(r'\brusqlite\b')),
]

# Frameworks web (nombre canónico → crate)
_FRAMEWORK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("actix-web", re.compile(r'\bactix-web\b')),
    ("axum",      re.compile(r'\baxum\b')),
    ("rocket",    re.compile(r'\brocket\b')),
    ("warp",      re.compile(r'\bwarp\b')),
    ("poem",      re.compile(r'\bpoem\b')),
    ("tide",      re.compile(r'\btide\b')),
]

# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

# Extrae secciones [dependencies] / [[bin]] / [lib] / [workspace] con regex
# sencillo; no parsea TOML completo (solo stdlib).
_RX_SECTION   = re.compile(r'^\[+(\w[\w. -]*)\]+', re.MULTILINE)
_RX_KV        = re.compile(r'^(\w[\w-]*)\s*=\s*"([^"]*)"', re.MULTILINE)
_RX_KV_TABLE  = re.compile(r'^(\w[\w-]*)\s*=\s*\{[^}]*\}', re.MULTILINE)

# Extrae la versión de rust-version / edition del bloque [package]
_RX_RUST_VER  = re.compile(r'^rust-version\s*=\s*"([^"]+)"', re.MULTILINE)
_RX_EDITION   = re.compile(r'^edition\s*=\s*"([^"]+)"', re.MULTILINE)

# Workspace members = ["a", "b", ...]
_RX_WS_MEMBER = re.compile(r'"([\w/-]+)"')

# --------------------------------------------------------------------------
# Endpoints por framework
# --------------------------------------------------------------------------

# actix-web: .route("/path", web::get()) | .route("/path", web::post()) ...
_RX_ACTIX = re.compile(
    r'\.route\s*\(\s*"([^"]+)"\s*,\s*web::(\w+)\s*\(',
)
# axum: .route("/path", get(h)) | .route("/path", post(h)) ...
_RX_AXUM = re.compile(
    r'\.route\s*\(\s*"([^"]+)"\s*,\s*(\w+)\s*\(',
)
# rocket + actix-web attribute macros: #[get("/path")] | #[post("/path")] ...
_RX_ROCKET = re.compile(
    r'#\[(\w+)\s*\(\s*"([^"]+)"\s*\)\]',
)

_AXUM_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
_ROCKET_VERBS = {"get", "post", "put", "delete", "patch", "head"}
_ACTIX_ATTR_VERBS = {"get", "post", "put", "delete", "patch", "head"}


def _parse_cargo_toml(text: str) -> dict:
    """Extrae package, dependencies y secciones relevantes de Cargo.toml."""
    out: dict = {
        "name": "",
        "version": "",
        "edition": "",
        "rust_version": "",
        "is_workspace": False,
        "workspace_members": [],
        "has_bin": False,
        "has_lib": False,
        "dep_names": [],   # nombres de crates en [dependencies]
    }

    # Workspace raíz
    if re.search(r'^\[workspace\]', text, re.MULTILINE):
        out["is_workspace"] = True
        m = re.search(r'\[workspace\].*?members\s*=\s*\[(.*?)\]', text, re.DOTALL)
        if m:
            out["workspace_members"] = _RX_WS_MEMBER.findall(m.group(1))

    # Campos de [package]
    pkg_m = re.search(r'^\[package\](.*?)(?=^\[|\Z)', text, re.MULTILINE | re.DOTALL)
    if pkg_m:
        pkg_block = pkg_m.group(1)
        for k, v in _RX_KV.findall(pkg_block):
            if k == "name":
                out["name"] = v
            elif k == "version":
                out["version"] = v
            elif k == "edition":
                out["edition"] = v
            elif k == "rust-version":
                out["rust_version"] = v

    # [[bin]] y [lib]
    out["has_bin"] = bool(re.search(r'^\[\[bin\]\]', text, re.MULTILINE))
    out["has_lib"] = bool(re.search(r'^\[lib\]', text, re.MULTILINE))

    # [dependencies] — nombres de crates (líneas con crate = "version" o crate = {...})
    dep_m = re.search(r'^\[dependencies\](.*?)(?=^\[|\Z)', text, re.MULTILINE | re.DOTALL)
    if dep_m:
        dep_block = dep_m.group(1)
        # nombre = "version" o nombre = { ... }
        names: list[str] = []
        for m in re.finditer(r'^([\w-]+)\s*=', dep_block, re.MULTILINE):
            names.append(m.group(1))
        out["dep_names"] = names

    return out


def _has_main(sc: ProjectScanner) -> bool:
    """True si existe al menos un src/main.rs o src/*/main.rs."""
    for f in sc.files:
        p = Path(f)
        if p.name == "main.rs":
            return True
    return False


def _find_main_files(sc: ProjectScanner) -> list[str]:
    return [f for f in sc.files if Path(f).name == "main.rs"]


def _extract_endpoints(root: Path, rs_files: list[str], framework: str | None,
                       ) -> list[tuple[str, str, str, int | None]]:
    """Devuelve (method, path, file, line)."""
    results: list[tuple[str, str, str, int | None]] = []
    seen: set[tuple[str, str]] = set()

    for rel in rs_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()

        if framework in ("actix-web", None):
            # builder style: .route("/path", web::get())
            for m in _RX_ACTIX.finditer(text):
                path, verb = m.group(1), m.group(2).upper()
                if (verb, path) not in seen:
                    seen.add((verb, path))
                    line = text[: m.start()].count("\n") + 1
                    results.append((verb, path, rel, line))
            # attribute macro style (actix-web 4): #[get("/path")]
            for i, ln in enumerate(lines, 1):
                m = _RX_ROCKET.match(ln.strip())
                if m and m.group(1).lower() in _ACTIX_ATTR_VERBS:
                    verb = m.group(1).upper()
                    path = m.group(2)
                    if (verb, path) not in seen:
                        seen.add((verb, path))
                        results.append((verb, path, rel, i))

        if framework in ("axum", None):
            for m in _RX_AXUM.finditer(text):
                path, verb = m.group(1), m.group(2).lower()
                if verb not in _AXUM_VERBS:
                    continue
                verb = verb.upper()
                if (verb, path) not in seen:
                    seen.add((verb, path))
                    line = text[: m.start()].count("\n") + 1
                    results.append((verb, path, rel, line))

        if framework in ("rocket", None):
            for i, ln in enumerate(lines, 1):
                m = _RX_ROCKET.match(ln.strip())
                if m and m.group(1).lower() in _ROCKET_VERBS:
                    verb = m.group(1).upper()
                    path = m.group(2)
                    if (verb, path) not in seen:
                        seen.add((verb, path))
                        results.append((verb, path, rel, i))

    return results


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class RustAdapter(Adapter):
    """Proyectos Rust (Cargo.toml)."""

    name = NAME

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        cargo = next((f for f in sc.files if f == "Cargo.toml"), None)
        if cargo:
            return [StackDetection(adapter=NAME, confidence=0.97,
                                   evidence=[ev(cargo, None)])]
        return []

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)
        cargo_rel = next((f for f in sc.files if f == "Cargo.toml"), None)
        if not cargo_rel:
            return

        try:
            cargo_text = (root / cargo_rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        parsed = _parse_cargo_toml(cargo_text)
        cargo_ev = ev(cargo_rel, None)

        # ----------------------------------------------------------------
        # Versión de Rust (rust-version → EXPLICIT; edition → BUILD)
        # ----------------------------------------------------------------
        if parsed["rust_version"]:
            req(info, "rust", parsed["rust_version"], P.EXPLICIT,
                cargo_rel, None, f'rust-version = "{parsed["rust_version"]}"',
                adapter=NAME)
        elif parsed["edition"]:
            # edition 2021 → infiere mínimo Rust 1.56
            _EDITION_MIN = {"2015": "1.0", "2018": "1.31", "2021": "1.56"}
            min_ver = _EDITION_MIN.get(parsed["edition"], "1.0")
            req(info, "rust", min_ver, P.BUILD,
                cargo_rel, None, f'edition = "{parsed["edition"]}"',
                adapter=NAME)

        # ----------------------------------------------------------------
        # Tipo de módulo
        # ----------------------------------------------------------------
        if parsed["is_workspace"]:
            kind = "workspace"
            module_name = Path(sc.root).name
        elif parsed["has_lib"] and not parsed["has_bin"] and not _has_main(sc):
            kind = "library"
            module_name = parsed["name"] or Path(sc.root).name
        else:
            kind = "executable"
            module_name = parsed["name"] or Path(sc.root).name

        info.modules.append(Module(
            name=module_name,
            path=".",
            build_system=NAME,
            kind=kind,
        ))

        # ----------------------------------------------------------------
        # Para workspaces: recolectar deps de todos los crates miembros
        # ----------------------------------------------------------------
        all_dep_names: list[str] = list(parsed["dep_names"])
        if parsed["is_workspace"]:
            for member in parsed["workspace_members"]:
                member_cargo = member.rstrip("/") + "/Cargo.toml"
                try:
                    mt = (root / member_cargo).read_text(encoding="utf-8", errors="replace")
                    mp = _parse_cargo_toml(mt)
                    all_dep_names.extend(mp["dep_names"])
                except Exception:
                    pass

        # ----------------------------------------------------------------
        # Servicios
        # ----------------------------------------------------------------
        deps_text = "\n".join(all_dep_names)
        for svc_kind, rx in _SERVICE_PATTERNS:
            if rx.search(deps_text):
                add_service(info, svc_kind, None, P.BUILD,
                            cargo_rel, None, None, adapter=NAME)

        # ----------------------------------------------------------------
        # Framework
        # ----------------------------------------------------------------
        framework: str | None = None
        for fw_name, rx in _FRAMEWORK_PATTERNS:
            if rx.search(deps_text):
                framework = fw_name
                info.set_fact("rust.framework", Fact(
                    value=fw_name, priority=P.BUILD,
                    evidence=[cargo_ev], adapter=NAME,
                ))
                break

        # ----------------------------------------------------------------
        # Endpoints (solo si hay binaries)
        # ----------------------------------------------------------------
        rs_files = [f for f in sc.files if f.endswith(".rs")]
        if kind != "library" and rs_files:
            for verb, path, file_rel, line in _extract_endpoints(root, rs_files, framework):
                info.endpoints.append(Endpoint(
                    method=verb, path=path,
                    handler=f"{framework or 'http'}:{Path(file_rel).stem}",
                    file=file_rel, line=line,
                ))

        # ----------------------------------------------------------------
        # Comandos
        # ----------------------------------------------------------------
        self._add_commands(info, kind)

    def _add_commands(self, info: ProjectInfo, kind: str) -> None:
        info.add_command(Command(
            name="deps", shell="cargo fetch",
            success_hint="(sin salida = OK)",
        ))
        info.add_command(Command(
            name="build", shell="cargo build",
            success_hint="Finished",
        ))
        info.add_command(Command(
            name="test", shell="cargo test",
            success_hint="test result: ok",
        ))
        if kind != "library":
            info.add_command(Command(
                name="run", shell="cargo run",
                success_hint="",
            ))
