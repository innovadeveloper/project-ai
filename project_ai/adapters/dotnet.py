"""
adapters/dotnet.py — Proyectos .NET (ASP.NET Core, consola, bibliotecas, tests).

Qué descubre (todo con evidencia archivo:línea):
  Versión      TargetFramework (net8.0 → 8, net7.0 → 7, netcoreapp3.1 → 3.1);
               global.json sdk.version → EXPLICIT (gana sobre .csproj BUILD).
  Módulos      Sdk=Microsoft.NET.Sdk.Web → web-app; OutputType=Exe sin web → console;
               xunit/nunit/mstest → test; resto → library.
  Servicios    NuGet packages → postgresql, sqlserver, redis, mongodb, kafka, rabbitmq.
  Endpoints    Minimal API: app.MapGet/Post/Put/Delete/Patch("path") en Program.cs.
               Controllers: [ApiController] + [Route("...")] + [HttpGet/Post/...].
  Puertos      Properties/launchSettings.json applicationUrl → hints.ports.
  Comandos     deps (dotnet restore), build (dotnet build),
               test (dotnet test, si hay proyecto test),
               run (dotnet run [--project <web-csproj>]).

Prioridades:
  .csproj TargetFramework    → BUILD
  global.json sdk.version    → EXPLICIT
  Program.cs / *Controller.cs → BUILD
  launchSettings.json        → EXPLICIT
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import (Command, Endpoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "dotnet"

# --------------------------------------------------------------------------
# Patrones
# --------------------------------------------------------------------------

# NuGet packages → runtime services
_PKG_SERVICES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Npgsql|EntityFrameworkCore\.PostgreSQL", re.I), "postgresql"),
    (re.compile(r"EntityFrameworkCore\.SqlServer|System\.Data\.SqlClient|Microsoft\.Data\.SqlClient", re.I), "sqlserver"),
    (re.compile(r"StackExchange\.Redis|Extensions\.Caching\.StackExchangeRedis", re.I), "redis"),
    (re.compile(r"MongoDB\.Driver", re.I), "mongodb"),
    (re.compile(r"RabbitMQ\.Client|MassTransit\.RabbitMQ", re.I), "rabbitmq"),
    (re.compile(r"Confluent\.Kafka|MassTransit\.Kafka", re.I), "kafka"),
    (re.compile(r"Elasticsearch\.Net|NEST\b|Elastic\.Clients", re.I), "elasticsearch"),
]

# Packages de test
_TEST_PKG_RX = re.compile(r"xunit|nunit|mstest|TestAdapter|TestFramework", re.I)

# Minimal API: app.MapGet("/path", ...) — ignora variables entre app y el punto
_RX_MAP_EP = re.compile(
    r'app\s*\.\s*Map(Get|Post|Put|Delete|Patch)\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)

# Controller route attribute on class: [Route("api/[controller]")]
_RX_CLASS_ROUTE = re.compile(r'\[Route\("([^"]+)"\)\]', re.IGNORECASE)

# HTTP method attribute on method: [HttpGet], [HttpGet("{id}")], [HttpPost("create")]
_RX_HTTP_METHOD_ATTR = re.compile(
    r'\[Http(Get|Post|Put|Delete|Patch)(?:\("([^"]*)"\))?\]',
    re.IGNORECASE,
)

# Declaración de método público (buscar tras el atributo [HttpX])
_RX_METHOD_SIG = re.compile(
    r'(?:public|private|protected|internal)\s+'
    r'(?:(?:async|static|virtual|override|new)\s+)*'
    r'[\w<>\[\]?]+\s+'
    r'(\w+)\s*[(<]',
    re.IGNORECASE,
)

# Clase controladora: class FooController
_RX_CTRL_CLASS = re.compile(r'class\s+(\w+Controller)\b')

# launchSettings.json: extraer puerto de applicationUrl
_RX_APP_URL_PORT = re.compile(r'https?://[^:,\s]+:(\d+)', re.IGNORECASE)


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class DotnetAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        sig = next((f for f in sc.files if f.endswith((".csproj", ".sln"))), None)
        if not sig:
            return []
        return [StackDetection(
            adapter=NAME, confidence=0.95,
            evidence=[ev(sig, None, ".csproj/.sln encontrado")],
        )]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)

        # 1. global.json → versión del SDK pinneada (EXPLICIT)
        global_version = _parse_global_json(root, info)

        # 2. .csproj → módulos, versiones, servicios
        csproj_files = [f for f in sc.files if f.endswith(".csproj")]
        has_test_proj = False
        web_project: str | None = None

        for rel in csproj_files:
            kind = _process_csproj(root / rel, rel, info, global_version)
            if kind == "test":
                has_test_proj = True
            elif kind == "web-app" and web_project is None:
                web_project = rel

        # 3. launchSettings.json → puertos
        _find_launch_settings(root, sc.files, info)

        # 4. Endpoints: Minimal API + Controllers
        _find_endpoints(root, sc.files, info)

        # 5. Comandos
        _add_commands(info, csproj_files, web_project, has_test_proj)


# --------------------------------------------------------------------------
# global.json
# --------------------------------------------------------------------------

def _parse_global_json(root: Path, info: ProjectInfo) -> str | None:
    """Lee global.json y extrae la versión del SDK. Devuelve la versión mayor."""
    path = root / "global.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version_str = data.get("sdk", {}).get("version", "")
    except Exception:
        return None
    if not version_str:
        return None
    # "8.0.100" → "8"
    dotnet_ver = _tf_to_version(f"net{version_str}")
    if not dotnet_ver:
        m = re.match(r"(\d+)\.", version_str)
        dotnet_ver = m.group(1) if m else None
    if dotnet_ver:
        req(info, "dotnet", dotnet_ver, P.EXPLICIT,
            "global.json", None, f"sdk.version={version_str}",
            adapter=NAME)
    return dotnet_ver


# --------------------------------------------------------------------------
# .csproj
# --------------------------------------------------------------------------

def _process_csproj(path: Path, rel: str, info: ProjectInfo,
                    global_version: str | None) -> str:
    """Parsea un .csproj; devuelve el kind del módulo ('web-app','console','test','library')."""
    try:
        tree = ET.parse(path)
        root_el = tree.getroot()
    except ET.ParseError:
        info.warnings.append(f"{rel}: XML inválido, se omite")
        return "library"

    # Sdk attribute → tipo de proyecto
    sdk = root_el.get("Sdk", "")

    # PropertyGroup children
    props: dict[str, str] = {}
    for pg in root_el.iter("PropertyGroup"):
        for child in pg:
            props[child.tag] = (child.text or "").strip()

    # PackageReference
    packages: list[tuple[str, str]] = []
    for pr in root_el.iter("PackageReference"):
        pkg_name = pr.get("Include", "")
        pkg_ver  = pr.get("Version", "")
        if pkg_name:
            packages.append((pkg_name, pkg_ver))

    target_fw = props.get("TargetFramework", "") or props.get("TargetFrameworks", "").split(";")[0]
    output_type = props.get("OutputType", "").lower()
    is_web = "web" in sdk.lower() or "razor" in sdk.lower() or "blazor" in sdk.lower()
    is_test = any(_TEST_PKG_RX.search(pkg) for pkg, _ in packages)

    # Versión de .NET desde TargetFramework (solo si global.json no la dio ya)
    if target_fw and global_version is None:
        ver = _tf_to_version(target_fw)
        if ver:
            req(info, "dotnet", ver, P.BUILD,
                rel, None, f"TargetFramework={target_fw}",
                adapter=NAME)
    elif target_fw and global_version is not None:
        # global.json ya registró la versión con EXPLICIT; acumulamos evidencia
        ver = _tf_to_version(target_fw)
        if ver:
            req(info, "dotnet", ver, P.BUILD,
                rel, None, f"TargetFramework={target_fw}",
                adapter=NAME)

    # Servicios de runtime
    for pkg_name, pkg_ver in packages:
        for rx, svc_kind in _PKG_SERVICES:
            if rx.search(pkg_name):
                add_service(info, svc_kind, pkg_ver or None, P.BUILD,
                            rel, None, pkg_name, adapter=NAME)
                break

    # Advertir si el framework es específico de plataforma
    if target_fw:
        m_plat = re.match(r'net[\d.]+-(\w+)', target_fw, re.IGNORECASE)
        if m_plat:
            platform = m_plat.group(1).lower()
            note = f"{rel}: TargetFramework={target_fw} — solo compila en {platform}."
            if platform == "windows":
                note += " No compila en macOS/Linux."
            info.warnings.append(note)

    # Kind del módulo
    if is_test:
        kind = "test"
    elif is_web:
        kind = "web-app"
    elif output_type == "exe":
        kind = "console"
    elif output_type == "winexe":
        kind = "windows-app"
    else:
        kind = "library"

    name = Path(path).stem
    mod_path = str(Path(rel).parent) if str(Path(rel).parent) != "." else "."
    info.modules.append(Module(
        name=name, path=mod_path, build_system=NAME, kind=kind,
    ))
    return kind


# --------------------------------------------------------------------------
# launchSettings.json
# --------------------------------------------------------------------------

def _find_launch_settings(root: Path, files: list[str], info: ProjectInfo) -> None:
    for rel in files:
        if not rel.endswith("launchSettings.json"):
            continue
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8"))
        except Exception:
            continue
        ports: list[str] = []
        for profile in data.get("profiles", {}).values():
            app_url = profile.get("applicationUrl", "")
            for m in _RX_APP_URL_PORT.finditer(app_url):
                port = m.group(1)
                if port not in ports:
                    ports.append(port)
        if ports:
            existing = info.facts.get("hints.ports")
            if existing is None:
                info.set_fact("hints.ports", Fact(
                    value=ports if len(ports) > 1 else ports[0],
                    priority=P.EXPLICIT,
                    evidence=[ev(rel, None, "applicationUrl")],
                    adapter=NAME,
                ))
            else:
                # Acumular puertos
                cur = existing.value if isinstance(existing.value, list) else [existing.value]
                for p in ports:
                    if p not in cur:
                        cur.append(p)
                existing.value = cur


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def _find_endpoints(root: Path, files: list[str], info: ProjectInfo) -> None:
    for rel in files:
        if not rel.endswith(".cs"):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _RX_MAP_EP.search(text):
            _parse_minimal_api(text, rel, info)
        if _RX_CTRL_CLASS.search(text) and _RX_HTTP_METHOD_ATTR.search(text):
            _parse_controller(text, rel, info)


def _parse_minimal_api(text: str, rel: str, info: ProjectInfo) -> None:
    """Extrae endpoints de Minimal API: app.MapGet("/path", ...)."""
    for i, line in enumerate(text.splitlines(), start=1):
        m = _RX_MAP_EP.search(line)
        if m:
            http_method = m.group(1).upper()
            path = m.group(2)
            info.endpoints.append(Endpoint(
                method=http_method, path=path,
                handler=f"lambda@{Path(rel).stem}:{i}",
                file=rel, line=i,
            ))


def _parse_controller(text: str, rel: str, info: ProjectInfo) -> None:
    """Extrae endpoints de un controlador MVC/API con atributos [HttpGet] etc."""
    lines = text.splitlines()

    # Dos pasadas: primero el nombre del controlador, luego la ruta base
    ctrl_name = ""
    raw_route = ""
    for ln in lines:
        m_cls = _RX_CTRL_CLASS.search(ln)
        if m_cls and not ctrl_name:
            ctrl_name = m_cls.group(1)
            if ctrl_name.endswith("Controller"):
                ctrl_name = ctrl_name[:-10]
        m_rt = _RX_CLASS_ROUTE.search(ln)
        if m_rt and not raw_route:
            raw_route = m_rt.group(1)
    base_route = raw_route.replace("[controller]", ctrl_name.lower())

    # Extraer métodos con atributos HTTP
    pending_method: str | None = None
    pending_sub: str = ""
    for i, ln in enumerate(lines, start=1):
        ln_s = ln.strip()
        m_attr = _RX_HTTP_METHOD_ATTR.search(ln_s)
        if m_attr:
            pending_method = m_attr.group(1).upper()
            pending_sub = m_attr.group(2) or ""
            continue
        if pending_method:
            if ln_s.startswith("["):
                continue  # otro atributo encadenado, mantener pending
            m_sig = _RX_METHOD_SIG.search(ln_s)
            if m_sig:
                method_name = m_sig.group(1)
                # Construir ruta completa
                if pending_sub.startswith("/"):
                    full_path = pending_sub
                else:
                    parts = [base_route.strip("/"), pending_sub.strip("/")]
                    full_path = "/" + "/".join(p for p in parts if p)
                info.endpoints.append(Endpoint(
                    method=pending_method,
                    path=full_path,
                    handler=f"{Path(rel).stem}#{method_name}",
                    file=rel, line=i,
                ))
            pending_method = None
            pending_sub = ""


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def _add_commands(info: ProjectInfo, csproj_files: list[str],
                  web_project: str | None, has_test_proj: bool) -> None:
    info.add_command(Command(
        name="deps",
        shell="dotnet restore",
        ide_hint="Visual Studio / Rider: Restore NuGet Packages",
        success_hint="Restore completed",
    ))
    info.add_command(Command(
        name="build",
        shell="dotnet build",
        ide_hint="Visual Studio: Build → Build Solution (Ctrl+Shift+B)",
        success_hint="Build succeeded",
    ))
    if has_test_proj:
        info.add_command(Command(
            name="test",
            shell="dotnet test",
            ide_hint="Visual Studio: Test → Run All Tests",
            success_hint="Passed!",
        ))
    # run: si hay proyecto web se pasa --project; si es consola simple, sin flag
    if web_project:
        run_shell = f"dotnet run --project {web_project}"
    else:
        run_shell = "dotnet run"
    info.add_command(Command(
        name="run",
        shell=run_shell,
        success_hint="Application started",
    ))


# --------------------------------------------------------------------------
# Utilidad: TargetFramework → versión mayor de .NET
# --------------------------------------------------------------------------

def _tf_to_version(tf: str) -> str | None:
    """'net8.0' → '8', 'net7.0' → '7', 'netcoreapp3.1' → '3'."""
    # net8.0, net7.0, net6.0, net5.0
    m = re.match(r"net(\d+)\.\d+", tf, re.IGNORECASE)
    if m:
        major = int(m.group(1))
        if major >= 5:
            return str(major)
        # net3.x, net2.x → netcoreapp, ya cubierto abajo
    # netcoreapp3.1
    m = re.match(r"netcoreapp(\d+)\.\d+", tf, re.IGNORECASE)
    if m:
        return m.group(1)
    return None
