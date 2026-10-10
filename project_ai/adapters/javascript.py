"""
adapters/javascript.py — Proyectos JavaScript/TypeScript (Node.js, Angular,
React, NestJS, sitios HTML estáticos).

Qué descubre (todo con evidencia archivo:línea):
  Node.js    .nvmrc / .node-version → EXPLICIT; engines.node en package.json → BUILD.
  PM         package-lock.json → npm, yarn.lock → yarn, pnpm-lock.yaml → pnpm,
             bun.lockb → bun (todos EXPLICIT).
  Framework  @angular/core → angular, react → react, @nestjs/core → nestjs,
             express → express, next → nextjs, … (BUILD/HEURISTIC desde deps).
  Módulo     express/nestjs/koa/fastify → api-server; angular/react/vue → frontend-app;
             nextjs/nuxt → fullstack-app; vite sin framework → bundled-frontend.
  Servicios  pg/redis/mongoose/mysql2/kafkajs/amqplib → postgresql/redis/mongodb/…
  Endpoints  Express: app.get/router.post('path', …) en .js/.ts
             NestJS: @Controller('prefix') + @Get/@Post/@Put/@Delete/@Patch('sub')
             Angular routes: path: '...' en *.routes.ts / *-routing.module.ts
             React Router: <Route path="..."> y createBrowserRouter([{path:…}])
  Comandos   npm/yarn/pnpm/bun install → deps; dev/start/serve → run;
             build → build; test → test.  Comandos de Angular CLI si angular.json.

Prioridades:
  .nvmrc / .node-version            → EXPLICIT
  package-lock.json / yarn.lock …   → EXPLICIT (PM)
  package.json engines.node         → BUILD
  package.json deps (framework)     → BUILD
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..model import (Command, Endpoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "javascript"

# --------------------------------------------------------------------------
# Framework/dependencias → kind del módulo
# --------------------------------------------------------------------------

_FRAMEWORK_DEPS: list[tuple[str, re.Pattern]] = [
    ("nestjs",   re.compile(r'"@nestjs/core"\s*:')),
    ("angular",  re.compile(r'"@angular/core"\s*:')),
    ("nextjs",   re.compile(r'"next"\s*:')),
    ("nuxt",     re.compile(r'"nuxt"\s*:')),
    ("react",    re.compile(r'"react"\s*:')),
    ("vue",      re.compile(r'"vue"\s*:')),
    ("svelte",   re.compile(r'"svelte"\s*:')),
    ("express",  re.compile(r'"express"\s*:')),
    ("fastify",  re.compile(r'"fastify"\s*:')),
    ("koa",      re.compile(r'"koa"\s*:')),
]

_FRAMEWORK_KIND: dict[str, str] = {
    "nestjs":   "api-server",
    "express":  "api-server",
    "fastify":  "api-server",
    "koa":      "api-server",
    "hapi":     "api-server",
    "angular":  "frontend-app",
    "react":    "frontend-app",
    "vue":      "frontend-app",
    "svelte":   "frontend-app",
    "solid":    "frontend-app",
    "nextjs":   "fullstack-app",
    "nuxt":     "fullstack-app",
    "sveltekit":"fullstack-app",
    "remix":    "fullstack-app",
}

_SERVICE_DEPS: list[tuple[str, re.Pattern]] = [
    ("postgresql",    re.compile(r'"(?:pg|postgres|postgresql)"\s*:')),
    ("redis",         re.compile(r'"(?:redis|ioredis)"\s*:')),
    ("mongodb",       re.compile(r'"(?:mongoose|mongodb)"\s*:')),
    ("mysql",         re.compile(r'"(?:mysql2|mysql)"\s*:')),
    ("mssql",         re.compile(r'"(?:tedious|mssql|tedious-connection-pool)"\s*:')),
    ("kafka",         re.compile(r'"(?:kafkajs|kafka-node)"\s*:')),
    ("rabbitmq",      re.compile(r'"(?:amqplib|amqp)"\s*:')),
    ("elasticsearch", re.compile(r'"(?:@elastic/elasticsearch|elasticsearch)"\s*:')),
]

# --------------------------------------------------------------------------
# Patrones de endpoints
# --------------------------------------------------------------------------

# Express: app.get('/path', ...) router.post('/path', ...)
_RX_EXPRESS = re.compile(
    r'(?:app|router)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)

# NestJS: @Controller('prefix') — el prefijo puede estar vacío
_RX_NEST_CTRL = re.compile(r'@Controller\s*\(\s*[\'"]([^\'"]*)[\'"]')

# NestJS: @Get('sub') @Post() @Put(':id') @Delete(':id') @Patch()
_RX_NEST_METHOD = re.compile(
    r'@(Get|Post|Put|Delete|Patch)\s*\(\s*(?:[\'"]([^\'"]*)[\'"])?\s*\)'
)

# React Router JSX: <Route path="..." ...>
_RX_REACT_ROUTE = re.compile(r'<Route[^>]+path\s*=\s*[\'"]([^\'"]+)[\'"]')

# createBrowserRouter / loader: { path: '/...' } — solo con barra inicial
_RX_ROUTER_PATH = re.compile(r'\bpath\s*:\s*[\'"](/[^\'"]*)[\'"]')

# Angular: path: 'segment' o path: '' (sin barra inicial, convención Angular)
_RX_ANGULAR_PATH = re.compile(r'''\bpath\s*:\s*(?:'([^']*)'|"([^"]*)")''')


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class JavascriptAdapter(Adapter):
    """JavaScript / TypeScript — Node.js, Angular, React, NestJS, HTML."""

    name = NAME

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        pkg = next((f for f in sc.files if f == "package.json"), None)
        if pkg:
            return [StackDetection(adapter=NAME, confidence=0.95,
                                   evidence=[ev(pkg, None)])]
        # Sitio HTML sin npm: index.html en la raíz
        html = next((f for f in sc.files if f == "index.html"), None)
        if html:
            return [StackDetection(adapter=NAME, confidence=0.7,
                                   evidence=[ev(html, None)])]
        return []

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)

        # Leer package.json (raíz)
        pkg_text = ""
        pkg_data: dict = {}
        pkg_rel = next((f for f in sc.files if f == "package.json"), None)
        if pkg_rel:
            try:
                pkg_text = (root / pkg_rel).read_text(encoding="utf-8", errors="replace")
                pkg_data = json.loads(pkg_text)
            except Exception:
                pass

        # ----------------------------------------------------------------
        # Versión de Node.js
        # ----------------------------------------------------------------
        self._parse_node_version(root, sc, info, pkg_data)

        # ----------------------------------------------------------------
        # Gestor de paquetes (lockfiles)
        # ----------------------------------------------------------------
        pm = self._detect_package_manager(sc, info)

        # ----------------------------------------------------------------
        # Framework
        # ----------------------------------------------------------------
        framework = self._detect_framework(sc, info, pkg_text, pkg_rel)

        # ----------------------------------------------------------------
        # Servicios
        # ----------------------------------------------------------------
        if pkg_text and pkg_rel:
            for svc_kind, rx in _SERVICE_DEPS:
                m = rx.search(pkg_text)
                if m:
                    add_service(info, svc_kind, None, P.BUILD,
                                pkg_rel, None, None, adapter=NAME)

        # ----------------------------------------------------------------
        # Módulo principal
        # ----------------------------------------------------------------
        name = pkg_data.get("name") or Path(sc.root).name
        kind = _FRAMEWORK_KIND.get(framework or "", "")
        if not kind:
            # Vite/webpack sin framework → bundled-frontend
            has_bundler = any(
                f in sc.files for f in
                ("vite.config.ts", "vite.config.js", "vite.config.mts",
                 "webpack.config.js", "webpack.config.ts")
            )
            kind = "bundled-frontend" if has_bundler else "static-site"
        info.modules.append(Module(
            name=name, path=".", build_system=NAME, kind=kind,
        ))

        # ----------------------------------------------------------------
        # Endpoints
        # ----------------------------------------------------------------
        if framework == "nestjs":
            self._extract_nestjs_endpoints(root, sc, info)
        elif framework == "express":
            self._extract_express_endpoints(root, sc, info)
        elif framework == "angular":
            self._extract_angular_routes(root, sc, info)
        elif framework in ("react", "nextjs"):
            self._extract_react_routes(root, sc, info)
        else:
            # Probar Express por si hay rutas aunque el framework no detectó
            self._extract_express_endpoints(root, sc, info)

        # ----------------------------------------------------------------
        # Comandos
        # ----------------------------------------------------------------
        scripts: dict = pkg_data.get("scripts", {})
        self._add_commands(info, pm, framework, scripts, sc)

    # ----------------------------------------------------------------
    # Parseo de versión Node.js
    # ----------------------------------------------------------------

    def _parse_node_version(self, root: Path, sc: ProjectScanner,
                             info: ProjectInfo, pkg_data: dict) -> None:
        # .nvmrc (mayor prioridad de archivos de versión)
        for nvmrc in (".nvmrc", ".node-version"):
            if nvmrc in sc.files:
                try:
                    raw = (root / nvmrc).read_text(encoding="utf-8").strip()
                    # "lts/iron" → no hay versión numérica extraíble
                    m = re.match(r'v?(\d[\d.]*)', raw)
                    if m:
                        req(info, "node", m.group(1), P.EXPLICIT,
                            nvmrc, None, raw, adapter=NAME)
                        return
                except Exception:
                    pass

        # package.json engines.node
        engine = pkg_data.get("engines", {}).get("node", "")
        if engine:
            req(info, "node", engine, P.BUILD, "package.json", None,
                f'"node": "{engine}"', adapter=NAME)

        # TypeScript version de dependencies o devDependencies
        all_deps: dict = {}
        all_deps.update(pkg_data.get("dependencies", {}))
        all_deps.update(pkg_data.get("devDependencies", {}))
        ts_ver_raw = all_deps.get("typescript", "")
        if ts_ver_raw:
            m = re.match(r'[\^~]?(\d[\d.]*)', ts_ver_raw)
            if m:
                req(info, "typescript", m.group(1), P.BUILD,
                    "package.json", None,
                    f'"typescript": "{ts_ver_raw}"', adapter=NAME)

    # ----------------------------------------------------------------
    # Gestor de paquetes
    # ----------------------------------------------------------------

    def _detect_package_manager(self, sc: ProjectScanner,
                                  info: ProjectInfo) -> str:
        lockfiles = [
            ("package-lock.json", "npm"),
            ("yarn.lock",         "yarn"),
            ("pnpm-lock.yaml",    "pnpm"),
            ("bun.lockb",         "bun"),
        ]
        for lockfile, pm in lockfiles:
            if lockfile in sc.files:
                info.set_fact("js.package_manager", Fact(
                    value=pm, priority=P.EXPLICIT,
                    evidence=[ev(lockfile, None)],
                    adapter=NAME,
                ))
                return pm
        # Sin lockfile: inferir de scripts o defaults
        if "package.json" in sc.files:
            info.set_fact("js.package_manager", Fact(
                value="npm", priority=P.HEURISTIC,
                evidence=[ev("package.json", None)],
                adapter=NAME,
            ))
        return "npm"

    # ----------------------------------------------------------------
    # Framework
    # ----------------------------------------------------------------

    def _detect_framework(self, sc: ProjectScanner, info: ProjectInfo,
                           pkg_text: str, pkg_rel: str | None) -> str | None:
        # angular.json es señal definitiva de Angular
        if "angular.json" in sc.files:
            info.set_fact("js.framework", Fact(
                value="angular", priority=P.EXPLICIT,
                evidence=[ev("angular.json", None)], adapter=NAME,
            ))
            return "angular"

        if not pkg_text or not pkg_rel:
            return None

        for fw, rx in _FRAMEWORK_DEPS:
            if rx.search(pkg_text):
                info.set_fact("js.framework", Fact(
                    value=fw, priority=P.BUILD,
                    evidence=[ev(pkg_rel, None)], adapter=NAME,
                ))
                return fw
        return None

    # ----------------------------------------------------------------
    # Endpoints Express
    # ----------------------------------------------------------------

    def _extract_express_endpoints(self, root: Path, sc: ProjectScanner,
                                    info: ProjectInfo) -> None:
        js_files = [f for f in sc.files
                    if f.endswith((".js", ".ts"))
                    and not f.startswith(("node_modules/", "dist/", "build/",
                                          ".next/", "coverage/"))]
        for rel in js_files:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for m in _RX_EXPRESS.finditer(line):
                    method = m.group(1).upper()
                    path = m.group(2)
                    info.endpoints.append(Endpoint(
                        method=method, path=path,
                        handler=f"express:{Path(rel).stem}",
                        file=rel, line=i,
                    ))

    # ----------------------------------------------------------------
    # Endpoints NestJS
    # ----------------------------------------------------------------

    def _extract_nestjs_endpoints(self, root: Path, sc: ProjectScanner,
                                   info: ProjectInfo) -> None:
        ctrl_files = [f for f in sc.files if f.endswith(".controller.ts")]
        if not ctrl_files:
            # Fallback: cualquier .ts con @Controller
            ctrl_files = [f for f in sc.files
                          if f.endswith(".ts") and "controller" in f.lower()
                          and not f.startswith(("node_modules/", "dist/"))]
        for rel in ctrl_files:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lines = text.splitlines()

            # Primera pasada: extraer prefijo del controlador
            ctrl_prefix = ""
            for line in lines:
                m = _RX_NEST_CTRL.search(line)
                if m:
                    ctrl_prefix = "/" + m.group(1).strip("/")
                    break

            # Segunda pasada: métodos HTTP
            for i, line in enumerate(lines, 1):
                m = _RX_NEST_METHOD.search(line)
                if not m:
                    continue
                method = m.group(1).upper()
                sub = (m.group(2) or "").strip("/")
                path = ctrl_prefix + ("/" + sub if sub else "")
                info.endpoints.append(Endpoint(
                    method=method, path=path,
                    handler=f"nestjs:{Path(rel).stem}",
                    file=rel, line=i,
                ))

    # ----------------------------------------------------------------
    # Rutas Angular
    # ----------------------------------------------------------------

    def _extract_angular_routes(self, root: Path, sc: ProjectScanner,
                                  info: ProjectInfo) -> None:
        route_files = [
            f for f in sc.files
            if (f.endswith(".routes.ts") or "routing.module" in f.lower()
                or f.endswith("-routing.ts"))
            and not f.startswith(("node_modules/", "dist/"))
        ]
        for rel in route_files:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for m in _RX_ANGULAR_PATH.finditer(line):
                    segment = m.group(1) if m.group(1) is not None else m.group(2)
                    # Ignorar wildcards y rutas de redirección vacías sin componente
                    if segment == "**":
                        continue
                    path = "/" + segment if segment else "/"
                    info.endpoints.append(Endpoint(
                        method="GET", path=path,
                        handler=f"angular-route:{Path(rel).stem}",
                        file=rel, line=i,
                    ))

    # ----------------------------------------------------------------
    # Rutas React Router
    # ----------------------------------------------------------------

    def _extract_react_routes(self, root: Path, sc: ProjectScanner,
                               info: ProjectInfo) -> None:
        react_files = [
            f for f in sc.files
            if f.endswith((".tsx", ".jsx"))
            and not f.startswith(("node_modules/", "dist/", "build/", ".next/"))
        ]
        for rel in react_files:
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lines = text.splitlines()

            # <Route path="...">
            for i, line in enumerate(lines, 1):
                for m in _RX_REACT_ROUTE.finditer(line):
                    path = m.group(1)
                    if path == "*":
                        continue
                    info.endpoints.append(Endpoint(
                        method="GET", path=path,
                        handler=f"react-route:{Path(rel).stem}",
                        file=rel, line=i,
                    ))

            # createBrowserRouter([{path: '/...'}])  — solo si el archivo lo usa
            if "createBrowserRouter" in text or "RouterProvider" in text:
                for i, line in enumerate(lines, 1):
                    for m in _RX_ROUTER_PATH.finditer(line):
                        path = m.group(1)
                        if path == "*":
                            continue
                        # Evitar duplicar lo que ya extrajo <Route>
                        existing = {ep.path for ep in info.endpoints}
                        if path not in existing:
                            info.endpoints.append(Endpoint(
                                method="GET", path=path,
                                handler=f"react-route:{Path(rel).stem}",
                                file=rel, line=i,
                            ))

    # ----------------------------------------------------------------
    # Comandos
    # ----------------------------------------------------------------

    def _add_commands(self, info: ProjectInfo, pm: str, framework: str | None,
                       scripts: dict, sc: ProjectScanner) -> None:
        pm_run = {
            "npm":  "npm run",
            "yarn": "yarn",
            "pnpm": "pnpm run",
            "bun":  "bun run",
        }.get(pm, "npm run")
        pm_install = {
            "npm":  "npm install",
            "yarn": "yarn install",
            "pnpm": "pnpm install",
            "bun":  "bun install",
        }.get(pm, "npm install")

        # deps: instalar dependencias
        info.add_command(Command(
            name="deps", shell=pm_install,
            success_hint="node_modules/ creado",
        ))

        # Angular CLI toma prioridad sobre scripts genéricos
        if framework == "angular":
            info.add_command(Command(
                name="run",   shell="ng serve",
                ide_hint="Angular CLI: ng serve",
                success_hint="Compiled successfully",
            ))
            info.add_command(Command(
                name="build", shell="ng build",
                success_hint="Build at:",
            ))
            info.add_command(Command(
                name="test",  shell="ng test",
                success_hint="SUMMARY: SUCCESS",
            ))
            return

        # Comandos desde package.json scripts
        run_script = None
        for key in ("dev", "start:dev", "serve", "start"):
            if key in scripts:
                run_script = key
                break
        if run_script:
            info.add_command(Command(
                name="run", shell=f"{pm_run} {run_script}",
                success_hint="listening on port",
            ))

        if "build" in scripts:
            info.add_command(Command(
                name="build", shell=f"{pm_run} build",
                success_hint="built in",
            ))

        test_key = next((k for k in ("test", "test:unit", "test:e2e") if k in scripts), None)
        if test_key:
            info.add_command(Command(
                name="test", shell=f"{pm_run} {test_key}",
                success_hint="Tests passed",
            ))
