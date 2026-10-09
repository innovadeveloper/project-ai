"""
adapters/python.py — Proyectos Python (FastAPI, Django, Flask, scripts, librerías).

Qué descubre (todo con evidencia archivo:línea):
  Gestor     uv (uv.lock), poetry (poetry.lock), hatch/flit (pyproject), pip puro
             (requirements*.txt), setup.py/setup.cfg legacy.
  Versión    requires-python de pyproject / setup.py / .python-version.
  Framework  FastAPI, Django, Flask, Starlette, Litestar, Tornado → fact 'framework'.
  Servicios  PostgreSQL, MySQL, Redis, MongoDB, RabbitMQ, Kafka, Celery (por deps).
  Entrypoints main() en scripts, @app.route en Flask, uvicorn.run en main.
  Endpoints  FastAPI: @router.get/post/put/delete/patch + app.include_router prefixes.
             Flask:   @app.route / @bp.route con methods=[].
             Django:  path()/re_path() en urls.py.
  Comandos   deps (install), run (uvicorn/gunicorn/manage.py runserver/flask run),
             test (pytest/unittest), build (build/hatch build).

Prioridades:
  pyproject.toml → BUILD
  .python-version, uv.lock, poetry.lock → EXPLICIT
  Deducción de framework por deps → HEURISTIC
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..model import (Command, Endpoint, EntryPoint, Fact, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "python"

# --------------------------------------------------------------------------
# Patrones
# --------------------------------------------------------------------------

# pyproject.toml: requires-python = ">=3.11"
_RX_REQUIRES_PYTHON = re.compile(
    r'requires[-_]python\s*[=:]\s*["\']?([^"\'>\s,;]+)', re.IGNORECASE
)
# setup.py:       python_requires=">=3.8"  (orden invertido)
_RX_PYTHON_REQUIRES_SETUP = re.compile(
    r'python_requires\s*=\s*["\']([^"\']+)', re.IGNORECASE
)
_RX_PYTHON_VERSION_FILE = re.compile(r"^(\d+\.\d+(?:\.\d+)?)")

# Dependencias → servicio de runtime
_DEP_SERVICES = [
    (r"psycopg2|psycopg[^2\w]|asyncpg|pg8000", "postgresql"),
    (r"pymysql|mysql-connector|aiomysql", "mysql"),
    (r"redis|aioredis|redis-py", "redis"),
    (r"pymongo|motor\b", "mongodb"),
    (r"pika\b|aio-pika|amqp\b", "rabbitmq"),
    (r"kafka-python|confluent-kafka|aiokafka", "kafka"),
    (r"celery\b", "celery"),
    (r"elasticsearch\b|elastic-transport", "elasticsearch"),
]

# Dependencias → framework
_FRAMEWORK_DEPS = [
    (r"\bfastapi\b", "fastapi"),
    (r"\bdjango\b", "django"),
    (r"\bflask\b", "flask"),
    (r"\bstarlette\b", "starlette"),
    (r"\blitestar\b", "litestar"),
    (r"\btornado\b", "tornado"),
    (r"\baiohttp\b", "aiohttp"),
]

# Archivos de señal de detección
_SIGNAL_FILES = {
    "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "requirements-dev.txt",
    "Pipfile", "Pipfile.lock",
    "uv.lock", "poetry.lock",
    ".python-version",
    "manage.py",   # Django
    "app.py", "wsgi.py", "asgi.py",
}

# FastAPI endpoints
_RX_FA_DECORATOR = re.compile(
    r'@(\w+)\.(get|post|put|delete|patch|options|head)\s*\(\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
# Flask route
_RX_FLASK_ROUTE = re.compile(
    r'@(\w+)\.route\s*\(\s*["\']([^"\']*)["\']'
    r'(?:[^)]*methods\s*=\s*\[([^\]]*)\])?',
    re.IGNORECASE,
)
# Django urls.py path/re_path
_RX_DJANGO_PATH = re.compile(
    r'(?:re_)?path\s*\(\s*["\']([^"\']*)["\']'
    r'\s*,\s*(\w[\w.]*)',
    re.IGNORECASE,
)
# include_router con prefix
_RX_INCLUDE_ROUTER = re.compile(
    r'include_router\s*\(\s*(\w+)\.router'
    r'(?:[^)]*prefix\s*=\s*["\']([^"\']*)["\'])?',
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class PythonAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        kf = sc.key_files()
        found = [f for f in kf.get("build", [])
                 + kf.get("config", [])
                 + kf.get("scripts", [])
                 if Path(f).name in _SIGNAL_FILES]
        if not found:
            return []
        return [StackDetection(
            adapter=NAME, confidence=0.95,
            evidence=[ev(found[0], None, "archivo Python detectado")],
        )]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        # 1. pyproject.toml
        pyproject_data = _parse_pyproject(sc, info)

        # 2. .python-version
        _parse_python_version_file(sc, info)

        # 3. requirements*.txt y setup.py
        _parse_requirements(sc, info)

        # 4. Gestor de paquetes → comandos
        _detect_package_manager(sc, info, pyproject_data)

        # 5. Framework → endpoints y entrypoints
        framework = info.facts.get("framework")
        fw_name = framework.value if framework else None
        _detect_endpoints(sc, info, fw_name)


# --------------------------------------------------------------------------
# Parseo de pyproject.toml
# --------------------------------------------------------------------------

def _parse_pyproject(sc: ProjectScanner, info: ProjectInfo) -> dict:
    text = sc.read_text("pyproject.toml")
    if not text:
        return {}
    try:
        data = tomllib.loads(text)
    except Exception:
        info.warnings.append(
            "pyproject.toml no se pudo parsear con tomllib; "
            "comprueba la sintaxis TOML."
        )
        return {}

    project = data.get("project", {})
    f = "pyproject.toml"

    # requires-python
    rp = project.get("requires-python", "")
    if not rp:
        # Poetry usa [tool.poetry.dependencies].python
        rp = data.get("tool", {}).get("poetry", {}).get(
            "dependencies", {}).get("python", "")
    if rp:
        ver = _clean_version_spec(rp)
        if ver:
            req(info, "python", ver, P.BUILD, f, None,
                f"requires-python = {rp!r}", adapter=NAME)

    # Dependencias → framework y servicios
    deps_raw = _collect_deps(data)
    _classify_deps(info, deps_raw, f)

    # Scripts de entrada
    scripts = project.get("scripts", {})
    for script_name, target in scripts.items():
        module, _, attr = target.partition(":")
        info.entry_points.append(EntryPoint(
            kind="script", symbol=f"{script_name}={target}",
            file=module.replace(".", "/") + ".py",
        ))

    return data


def _collect_deps(data: dict) -> list[str]:
    """Extrae todas las dependencias en texto plano desde las distintas secciones."""
    deps: list[str] = []
    # PEP 621
    for d in data.get("project", {}).get("dependencies", []):
        deps.append(d)
    # Poetry
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    deps.extend(poetry_deps.keys())
    # uv dev-dependencies
    uv_dev = data.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
    deps.extend(uv_dev)
    # extras / optional-dependencies
    for extra_deps in data.get("project", {}).get(
            "optional-dependencies", {}).values():
        deps.extend(extra_deps)
    return deps


def _classify_deps(info: ProjectInfo, deps: list[str], file: str) -> None:
    deps_lower = " ".join(d.lower() for d in deps)

    for pattern, fw in _FRAMEWORK_DEPS:
        if re.search(pattern, deps_lower):
            if "framework" not in info.facts:
                info.set_fact("framework", Fact(
                    value=fw, priority=P.BUILD, adapter=NAME,
                    evidence=[ev(file, None, f"dependencia: {fw}")],
                ))
            break

    for pattern, svc in _DEP_SERVICES:
        if re.search(pattern, deps_lower):
            add_service(info, svc, None, P.BUILD, file, None, None, adapter=NAME)


# --------------------------------------------------------------------------
# requirements*.txt y setup.py
# --------------------------------------------------------------------------

def _parse_requirements(sc: ProjectScanner, info: ProjectInfo) -> None:
    kf = sc.key_files()
    req_files = [f for f in (kf.get("build", []) + kf.get("config", []))
                 if re.match(r"requirements.*\.txt$", Path(f).name)]

    all_deps: list[str] = []
    for rf in req_files:
        lines = sc.read_lines(rf) or []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                all_deps.append(line)

    if all_deps:
        _classify_deps(info, all_deps, req_files[0] if req_files else "requirements.txt")

    # setup.py: buscar python_requires (orden distinto al de pyproject)
    setup_text = sc.read_text("setup.py") or ""
    m = _RX_PYTHON_REQUIRES_SETUP.search(setup_text)
    if m:
        ver = _clean_version_spec(m.group(1))
        if ver:
            req(info, "python", ver, P.BUILD, "setup.py", None,
                m.group(0).strip(), adapter=NAME)


# --------------------------------------------------------------------------
# .python-version
# --------------------------------------------------------------------------

def _parse_python_version_file(sc: ProjectScanner, info: ProjectInfo) -> None:
    text = sc.read_text(".python-version")
    if not text:
        return
    m = _RX_PYTHON_VERSION_FILE.match(text.strip())
    if m:
        req(info, "python", m.group(1), P.EXPLICIT, ".python-version", 1,
            text.strip(), adapter=NAME)


# --------------------------------------------------------------------------
# Gestor de paquetes → comandos
# --------------------------------------------------------------------------

def _detect_package_manager(sc: ProjectScanner, info: ProjectInfo,
                             pyproject_data: dict) -> None:
    root = sc.root   # ya es Path (resuelto)
    kf = sc.key_files()
    has_uv_lock     = (root / "uv.lock").exists()
    has_poetry_lock = (root / "poetry.lock").exists()
    has_pipfile     = (root / "Pipfile").exists()
    has_reqs        = any(Path(f).name == "requirements.txt"
                          for f in kf.get("build", []) + kf.get("config", []))
    has_setup_py    = (root / "setup.py").exists()
    has_pyproject   = bool(pyproject_data)

    # Determinar gestor (orden de confianza)
    if has_uv_lock:
        pm, install, run_prefix = "uv", "uv sync", "uv run"
        ev_src = ev("uv.lock", None, "uv.lock presente")
        info.set_fact("python.package_manager", Fact(
            value="uv", priority=P.EXPLICIT, adapter=NAME, evidence=[ev_src]))
    elif has_poetry_lock:
        pm, install, run_prefix = "poetry", "poetry install", "poetry run"
        ev_src = ev("poetry.lock", None, "poetry.lock presente")
        info.set_fact("python.package_manager", Fact(
            value="poetry", priority=P.EXPLICIT, adapter=NAME, evidence=[ev_src]))
    elif has_pipfile:
        pm, install, run_prefix = "pipenv", "pipenv install", "pipenv run"
        ev_src = ev("Pipfile", None, "Pipfile presente")
        info.set_fact("python.package_manager", Fact(
            value="pipenv", priority=P.BUILD, adapter=NAME, evidence=[ev_src]))
    elif has_reqs:
        pm, install, run_prefix = "pip", "pip install -r requirements.txt", ""
        ev_src = ev("requirements.txt", None, "requirements.txt presente")
        info.set_fact("python.package_manager", Fact(
            value="pip", priority=P.BUILD, adapter=NAME, evidence=[ev_src]))
    else:
        pm, install, run_prefix = "pip", "pip install -e .", ""
        ev_src = ev("setup.py" if has_setup_py else "pyproject.toml",
                    None, "sin lockfile")
        info.set_fact("python.package_manager", Fact(
            value="pip", priority=P.HEURISTIC, adapter=NAME, evidence=[ev_src]))

    info.add_command(Command(
        name="deps", shell=install,
        ide_hint="Terminal integrado del IDE",
        success_hint="Successfully installed" if "pip" in pm else "Resolved",
        fact=Fact(value=install, priority=P.BUILD if has_uv_lock or has_poetry_lock
                  else P.HEURISTIC, adapter=NAME),
    ))

    # Comando run — depende del framework
    framework = info.facts.get("framework")
    fw = framework.value if framework else None
    _add_run_command(info, fw, run_prefix, sc)

    # Test
    info.add_command(Command(
        name="test",
        shell=f"{run_prefix} pytest" if run_prefix else "pytest",
        ide_hint="Run > pytest",
        success_hint="passed",
        fact=Fact(value="pytest", priority=P.HEURISTIC, adapter=NAME),
    ))

    # Build wheel (solo si hay pyproject)
    if has_pyproject and not has_uv_lock and not has_poetry_lock:
        info.add_command(Command(
            name="build",
            shell="python -m build",
            success_hint="Successfully built",
            fact=Fact(value="build", priority=P.HEURISTIC, adapter=NAME),
        ))


def _add_run_command(info: ProjectInfo, framework: str | None,
                     run_prefix: str, sc: ProjectScanner) -> None:
    prefix = f"{run_prefix} " if run_prefix else ""

    if framework == "fastapi":
        # Buscar el módulo con uvicorn.run o app = FastAPI()
        main_module = _find_fastapi_main(sc)
        shell = f"{prefix}uvicorn {main_module}:app --reload"
        info.add_command(Command(
            name="run", shell=shell,
            ide_hint="Run configuration: uvicorn",
            success_hint="Application startup complete",
            fact=Fact(value=shell, priority=P.HEURISTIC, adapter=NAME),
        ))
    elif framework == "django":
        shell = f"{prefix}python manage.py runserver"
        info.add_command(Command(
            name="run", shell=shell,
            ide_hint="Run > Django: runserver",
            success_hint="Starting development server",
            fact=Fact(value=shell, priority=P.BUILD, adapter=NAME),
        ))
    elif framework == "flask":
        app_file = _find_flask_app(sc)
        shell = f"{prefix}flask --app {app_file} run --debug"
        info.add_command(Command(
            name="run", shell=shell,
            ide_hint="Run > Flask: run",
            success_hint="Running on http://",
            fact=Fact(value=shell, priority=P.HEURISTIC, adapter=NAME),
        ))
    else:
        # Buscar __main__ o entry point
        main_file = _find_main_script(sc)
        if main_file:
            shell = f"{prefix}python {main_file}"
            info.add_command(Command(
                name="run", shell=shell,
                fact=Fact(value=shell, priority=P.HEURISTIC, adapter=NAME),
            ))


# --------------------------------------------------------------------------
# Detección de endpoints
# --------------------------------------------------------------------------

def _detect_endpoints(sc: ProjectScanner, info: ProjectInfo,
                      framework: str | None) -> None:
    py_files = [f for f in sc.files if f.endswith(".py")]

    if framework == "fastapi":
        _endpoints_fastapi(sc, info, py_files)
    elif framework == "flask":
        _endpoints_flask(sc, info, py_files)
    elif framework == "django":
        _endpoints_django(sc, info, py_files)


def _endpoints_fastapi(sc: ProjectScanner, info: ProjectInfo,
                       py_files: list[str]) -> None:
    # Paso 1: recoger prefijos de include_router por módulo → prefix.
    # "include_router(devices.router, prefix='/api/devices')" → {"devices": "/api/devices"}
    # También busca "include_router(router_var, prefix=...)" sin punto.
    file_prefix: dict[str, str] = {}   # stem del archivo → prefix
    for f in py_files:
        text = sc.read_text(f) or ""
        for m in _RX_INCLUDE_ROUTER.finditer(text):
            module_name = m.group(1)   # "devices" de "devices.router"
            prefix = m.group(2) or ""
            file_prefix[module_name] = prefix

    # Paso 2: decoradores de ruta en cada archivo
    for f in py_files:
        # Prefijo para este archivo: buscar por stem (devices.py → "devices")
        stem = Path(f).stem
        prefix = file_prefix.get(stem, "")
        text = sc.read_text(f) or ""
        for m in _RX_FA_DECORATOR.finditer(text):
            method = m.group(2).upper()
            path_suffix = m.group(3)
            full_path = (prefix.rstrip("/") + "/" + path_suffix.lstrip("/")
                         if prefix else path_suffix)
            lineno = text[:m.start()].count("\n") + 1
            handler = _next_func_name(text, m.end())
            info.endpoints.append(Endpoint(
                method=method, path=full_path,
                handler=handler or path_suffix,
                file=f, line=lineno,
            ))


def _endpoints_flask(sc: ProjectScanner, info: ProjectInfo,
                     py_files: list[str]) -> None:
    for f in py_files:
        text = sc.read_text(f) or ""
        for m in _RX_FLASK_ROUTE.finditer(text):
            path = m.group(2)
            methods_raw = m.group(3) or "GET"
            methods = [x.strip().strip("'\"") for x in methods_raw.split(",")
                       if x.strip().strip("'\"")]
            lineno = text[:m.start()].count("\n") + 1
            handler = _next_func_name(text, m.end())
            for method in methods:
                info.endpoints.append(Endpoint(
                    method=method.upper(), path=path,
                    handler=handler or path,
                    file=f, line=lineno,
                ))


def _endpoints_django(sc: ProjectScanner, info: ProjectInfo,
                      py_files: list[str]) -> None:
    url_files = [f for f in py_files if "urls.py" in f]
    for f in url_files:
        text = sc.read_text(f) or ""
        for m in _RX_DJANGO_PATH.finditer(text):
            raw_path = m.group(1)
            handler = m.group(2)
            # Ignorar include() — no es un endpoint directo
            if handler.startswith("include"):
                continue
            # Django paths no llevan método; usamos GET como marcador
            lineno = text[:m.start()].count("\n") + 1
            info.endpoints.append(Endpoint(
                method="GET", path=raw_path,
                handler=handler, file=f, line=lineno,
            ))


# --------------------------------------------------------------------------
# Helpers de búsqueda de archivos
# --------------------------------------------------------------------------

def _find_fastapi_main(sc: ProjectScanner) -> str:
    """Devuelve el módulo Python con uvicorn.run o app = FastAPI()."""
    for f in sc.files:
        if not f.endswith(".py"):
            continue
        text = sc.read_text(f) or ""
        if "uvicorn.run" in text or re.search(r"app\s*=\s*FastAPI\s*\(", text):
            # Convertir path a módulo: src/myapi/main.py → myapi.main
            rel = f.replace("/", ".").removesuffix(".py")
            for prefix in ("src.", "app."):
                if rel.startswith(prefix):
                    rel = rel[len(prefix):]
            return rel
    return "main"


def _find_flask_app(sc: ProjectScanner) -> str:
    for f in sc.files:
        if not f.endswith(".py"):
            continue
        text = sc.read_text(f) or ""
        if re.search(r"app\s*=\s*Flask\s*\(", text):
            return Path(f).stem
    return "app"


def _find_main_script(sc: ProjectScanner) -> str | None:
    for f in sc.files:
        if not f.endswith(".py"):
            continue
        text = sc.read_text(f) or ""
        if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
            return f
    return None


def _next_func_name(text: str, pos: int) -> str | None:
    """Extrae el nombre de la función justo después de pos."""
    m = re.search(r"def\s+(\w+)\s*\(", text[pos:pos + 200])
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Helpers de versión
# --------------------------------------------------------------------------

def _clean_version_spec(spec: str) -> str:
    """Extrae solo el número de una spec como '>=3.11', '^3.10', '~=3.9'."""
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", spec)
    return m.group(1) if m else ""
