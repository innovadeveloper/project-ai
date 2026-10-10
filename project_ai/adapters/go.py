"""
adapters/go.py — Proyectos Go (módulos go.mod).

Qué descubre (todo con evidencia archivo:línea):
  Go version    go.mod  "go 1.21" → EXPLICIT.
  Módulo        go.mod  "module github.com/acme/myapp".
  Module kind   ejecutable si cmd/**/main.go o main.go; library si no hay main.
  Framework     require → gin/echo/fiber/chi/gorilla → api-server; fullstack si next.js-go.
  Servicios     require → lib/pq|pgx → postgresql; go-redis|redigo → redis;
                go-sql-driver/mysql → mysql; mongo-driver → mongodb;
                sarama|franz-go|confluent-kafka-go → kafka; amqp|rabbitmq → rabbitmq.
  Endpoints     main.go/cmd/*: http.HandleFunc, r.GET/POST/PUT/DELETE/PATCH (Gin/Chi/Echo),
                router.HandleFunc (gorilla), e.GET/POST (Echo), app.Get/Post (Fiber).
  Comandos      go mod download → deps; go build → build; go test → test; go run → run.

Prioridades:
  go.mod go X.Y         → EXPLICIT
  go.mod require deps   → BUILD
"""
from __future__ import annotations

import re
from pathlib import Path

from ..model import Command, Endpoint, Fact, Module, ProjectInfo, SourcePriority as P, StackDetection
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "go"

# --------------------------------------------------------------------------
# Servicios detectables en go.mod require
# --------------------------------------------------------------------------

_SERVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("postgresql", re.compile(r'\blib/pq\b|\bjackc/pgx\b|\bgo-pg/pg\b|\bpgx/v\d+\b')),
    ("mysql",      re.compile(r'\bgo-sql-driver/mysql\b')),
    ("redis",      re.compile(r'\bgo-redis/redis\b|\bredis/go-redis\b|\bgomodule/redigo\b')),
    ("mongodb",    re.compile(r'\bmongo-driver\b')),
    ("kafka",      re.compile(r'\btwmb/franz-go\b|\bSegmentio/kafka-go\b|\bIBM/sarama\b|\bconfluentinc/confluent-kafka-go\b')),
    ("rabbitmq",   re.compile(r'\bstreadway/amqp\b|\brabbit-go\b|\brabbitmq/amqp091-go\b')),
    ("sqlite",     re.compile(r'\bmattn/go-sqlite3\b|\bmodernc\.org/sqlite\b')),
    ("nats",       re.compile(r'\bnats-io/nats\.go\b')),
]

# Framework web
_FRAMEWORK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("gin",          re.compile(r'\bgin-gonic/gin\b')),
    ("echo",         re.compile(r'\blabstack/echo\b')),
    ("fiber",        re.compile(r'\bgofiber/fiber\b')),
    ("chi",          re.compile(r'\bgo-chi/chi\b')),
    ("gorilla/mux",  re.compile(r'\bgorilla/mux\b')),
]

# Endpoints por framework (regex sobre código fuente)
_EP_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Gin: r.GET("/path", handler)
    (re.compile(r'\br\.(?:GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s*\("([^"]+)"'), "gin"),
    # Echo: e.GET("/path", ...)
    (re.compile(r'\be\.(?:GET|POST|PUT|DELETE|PATCH)\s*\("([^"]+)"'), "echo"),
    # Fiber: app.Get("/path", ...) — case-sensitive method
    (re.compile(r'\bapp\.(?:Get|Post|Put|Delete|Patch)\s*\("([^"]+)"'), "fiber"),
    # Chi / gorilla: r.HandleFunc("/path", ...) o router.HandleFunc
    (re.compile(r'\.HandleFunc\s*\("([^"]+)"'), "chi"),
    # net/http stdlib: http.HandleFunc("/path", ...)
    (re.compile(r'http\.HandleFunc\s*\("([^"]+)"'), "stdlib"),
]

_EP_VERB_RX = re.compile(
    r'\b(?:r|e|app|router)\.(?P<verb>GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch)\s*\("([^"]+)"',
)

# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

def _parse_go_mod(text: str) -> dict:
    out: dict = {
        "module": "",
        "go_version": "",
        "requires": [],
    }
    # module path
    m = re.search(r'^module\s+(\S+)', text, re.MULTILINE)
    if m:
        out["module"] = m.group(1)

    # go version
    m = re.search(r'^go\s+(\d+\.\d+(?:\.\d+)?)', text, re.MULTILINE)
    if m:
        out["go_version"] = m.group(1)

    # require block(s) — incluir las líneas con tab+pkg+version
    for req_m in re.finditer(r'^\t([\w./\-]+(?:/v\d+)?)\s+v[\d.]+', text, re.MULTILINE):
        pkg = req_m.group(1)
        if not pkg.endswith("// indirect"):
            out["requires"].append(pkg)

    return out


def _detect_framework(requires: list[str]) -> str | None:
    reqs_text = "\n".join(requires)
    for name, rx in _FRAMEWORK_PATTERNS:
        if rx.search(reqs_text):
            return name
    # net/http is stdlib → no explicit require needed
    return None


def _extract_endpoints(root: Path, go_files: list[str]) -> list[tuple[str, str, str]]:
    """Devuelve lista de (method, path, file) para endpoints HTTP detectados."""
    results: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    for rel in go_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Gin/Echo/Fiber con verbo explícito
        for m in _EP_VERB_RX.finditer(text):
            verb = m.group("verb").upper()
            # capturar la ruta del segundo argumento del match general
            full = m.group(0)
            path_m = re.search(r'"([^"]+)"', full)
            if not path_m:
                continue
            path = path_m.group(1)
            if (verb, path) not in seen:
                seen.add((verb, path))
                results.append((verb, path, rel))

        # net/http o gorilla HandleFunc → GET implícito
        for m in re.finditer(r'http\.HandleFunc\s*\(\s*"([^"]+)"', text):
            path = m.group(1)
            if ("GET", path) not in seen:
                seen.add(("GET", path))
                results.append(("GET", path, rel))

        # gorilla/chi router
        for m in re.finditer(r'\.HandleFunc\s*\(\s*"([^"]+)"', text):
            path = m.group(1)
            if ("GET", path) not in seen:
                seen.add(("GET", path))
                results.append(("GET", path, rel))

    return results


def _find_entry_points(sc: ProjectScanner) -> list[str]:
    """Devuelve rutas relativas de archivos main.go (pueden ser varios en cmd/)."""
    entries = []
    for f in sc.files:
        name = Path(f).name
        if name == "main.go":
            entries.append(f)
    return entries


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class GoAdapter(Adapter):
    """Proyectos Go (módulos go.mod)."""

    name = NAME

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        mod = next((f for f in sc.files if f == "go.mod"), None)
        if mod:
            return [StackDetection(adapter=NAME, confidence=0.97,
                                   evidence=[ev(mod, None)])]
        return []

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)
        mod_rel = next((f for f in sc.files if f == "go.mod"), None)
        if not mod_rel:
            return

        try:
            mod_text = (root / mod_rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        parsed = _parse_go_mod(mod_text)

        # ----------------------------------------------------------------
        # Versión de Go
        # ----------------------------------------------------------------
        if parsed["go_version"]:
            req(info, "go", parsed["go_version"], P.EXPLICIT,
                mod_rel, None, f"go {parsed['go_version']}", adapter=NAME)

        # ----------------------------------------------------------------
        # Tipo de módulo
        # ----------------------------------------------------------------
        entries = _find_entry_points(sc)
        go_files = [f for f in sc.files if f.endswith(".go")]

        if entries:
            # Distinguir multi-cmd de single-binary
            cmd_entries = [e for e in entries if "cmd/" in e]
            if len(cmd_entries) > 1:
                kind = "multi-cmd"
            else:
                kind = "executable"
        else:
            kind = "library"

        module_name = Path(parsed["module"]).name if parsed["module"] else Path(sc.root).name
        info.modules.append(Module(
            name=module_name,
            path=".",
            build_system=NAME,
            kind=kind,
        ))

        # ----------------------------------------------------------------
        # Servicios
        # ----------------------------------------------------------------
        reqs_text = "\n".join(parsed["requires"])
        for svc_kind, rx in _SERVICE_PATTERNS:
            if rx.search(reqs_text):
                add_service(info, svc_kind, None, P.BUILD,
                            mod_rel, None, None, adapter=NAME)

        # ----------------------------------------------------------------
        # Framework
        # ----------------------------------------------------------------
        framework = _detect_framework(parsed["requires"])
        if framework:
            info.set_fact("go.framework", Fact(
                value=framework, priority=P.BUILD,
                evidence=[ev(mod_rel, None)], adapter=NAME,
            ))

        # ----------------------------------------------------------------
        # Endpoints (solo si hay entry points)
        # ----------------------------------------------------------------
        if entries:
            ep_files = go_files  # buscar en todos los .go (el handler puede estar en otro paquete)
            for verb, path, file_rel in _extract_endpoints(root, ep_files):
                line = None
                try:
                    text = (root / file_rel).read_text(encoding="utf-8", errors="replace")
                    for i, ln in enumerate(text.splitlines(), 1):
                        if f'"{path}"' in ln:
                            line = i
                            break
                except Exception:
                    pass
                info.endpoints.append(Endpoint(
                    method=verb, path=path,
                    handler=f"{framework or 'http'}:{Path(file_rel).stem}",
                    file=file_rel, line=line,
                ))

        # ----------------------------------------------------------------
        # Comandos
        # ----------------------------------------------------------------
        self._add_commands(info, entries, kind, parsed["module"])

    def _add_commands(self, info: ProjectInfo, entries: list[str],
                      kind: str, module: str) -> None:
        info.add_command(Command(
            name="deps", shell="go mod download",
            success_hint="(sin salida = OK)",
        ))

        if kind == "library":
            info.add_command(Command(
                name="test", shell="go test ./...",
                success_hint="ok",
            ))
            return

        info.add_command(Command(
            name="build", shell="go build ./...",
            success_hint="(sin salida = OK)",
        ))
        info.add_command(Command(
            name="test", shell="go test ./...",
            success_hint="ok",
        ))

        # run: usar el primer entry point detectado
        if entries:
            cmd_entries = [e for e in entries if "cmd/" in e]
            if cmd_entries:
                # Usa el directorio del primer cmd
                cmd_dir = str(Path(cmd_entries[0]).parent)
                run_shell = f"go run ./{cmd_dir}"
            else:
                run_shell = f"go run {entries[0]}"
        else:
            run_shell = "go run main.go"

        info.add_command(Command(
            name="run", shell=run_shell,
            success_hint="",
        ))
