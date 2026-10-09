"""
adapters/hints.py — Señales transversales (no dependen del lenguaje).

Se ejecuta SIEMPRE, antes o junto a los adaptadores de stack. Busca pistas de
"cómo lo construyó/ejecutó otra persona" en:

  1. Archivos de toolchain (EXPLICIT): .tool-versions, mise.toml, .sdkmanrc,
     .java-version, .python-version, .nvmrc, global.json
  2. Dockerfiles (CI): imágenes FROM -> versiones (maven:3.9-eclipse-temurin-17
     => maven 3.9 + jdk 17), ARG resueltos, RUN con comandos de build, EXPOSE.
     En imágenes de runtime (tomcat, *-jre) el JDK va a 'jdk_runtime'.
  3. docker-compose (CI): servicios de runtime (postgres, redis, kafka...).
  4. CI (CI): GitHub Actions (setup-java, run:), GitLab, Jenkinsfile, etc.
  5. IDE (BUILD/HEURISTIC): .vscode/tasks.json|launch.json, run configs de
     IntelliJ, .smarttomcat, context.xml => qué ejecutable / main / Tomcat.
  6. Documentación (HEURISTIC): README, BUILD.txt, INSTALL.txt... líneas de
     comandos y menciones de versiones ("Java 8", "Tomcat 9", "PostgreSQL 13").

Resultado en ProjectInfo:
  requirements[...]        versiones con evidencia y prioridad
  services[...]            postgresql, redis...
  facts["hints.commands"]  comandos vistos (origen ci|docker|docs|ide)
  facts["hints.ports"], facts["hints.executables"], facts["hints.main_classes"],
  facts["hints.deploy"], facts["hints.base_os"], facts["runtime.servlet_container"],
  facts["ide.run_configs"], facts["toolchain.other"]
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import PurePosixPath

from ..model import Fact, ProjectInfo, SourcePriority as P
from ..scanner import ProjectScanner
from .base import (BUILD_TOOL_RX, Adapter, add_cmd_hint, add_service, ev,
                   jdk_major, normalize_tool, register, req)

NAME = "hints"

# ----------------------------------------------------------------------------
# Imágenes Docker
# ----------------------------------------------------------------------------
JDK_IMAGES = {"eclipse-temurin", "temurin", "openjdk", "amazoncorretto",
              "zulu-openjdk", "sapmachine", "ibm-semeru-runtimes", "ibmjava",
              "adoptopenjdk", "java", "graalvm-ce", "jdk"}
RUNTIME_IMAGES = {"tomcat", "jetty", "wildfly", "payara", "open-liberty",
                  "websphere-liberty"}
OS_IMAGES = {"ubuntu", "debian", "alpine", "centos", "fedora", "rockylinux",
             "almalinux", "amazonlinux", "ubi8", "ubi9"}
SERVICE_IMAGES = {
    "postgres": "postgresql", "postgis": "postgresql", "mysql": "mysql",
    "mariadb": "mariadb", "redis": "redis", "mongo": "mongodb",
    "rabbitmq": "rabbitmq", "kafka": "kafka", "cp-kafka": "kafka",
    "zookeeper": "zookeeper", "cp-zookeeper": "zookeeper",
    "elasticsearch": "elasticsearch", "opensearch": "opensearch",
    "keycloak": "keycloak", "minio": "minio", "memcached": "memcached",
    "cassandra": "cassandra", "nats": "nats", "mosquitto": "mqtt",
    "eclipse-mosquitto": "mqtt", "emqx": "mqtt", "mailhog": "smtp",
    "mailpit": "smtp", "mssql": "sqlserver", "server": None,  # ver _service_kind
}
_JDK_IN_TAG = re.compile(
    r"(?:jdk|jre|temurin|openjdk|corretto|zulu|sapmachine|semeru)[-_]?(\d+(?:\.\d+)?)",
    re.I)


def split_image(image: str) -> tuple[str, str, str]:
    """'registry:5000/org/maven:3.9-x@sha256..' -> (full_name, base, tag)."""
    image = image.split("@", 1)[0]
    name, tag = image, ""
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = image.rsplit(":", 1)
    base = name.rsplit("/", 1)[-1].lower()
    return name.lower(), base, tag


def _num_prefix(tag: str) -> str | None:
    m = re.match(r"v?(\d+(?:\.\d+)*)", tag)
    return m.group(1) if m else None


def parse_image(image: str) -> list[tuple[str, str]]:
    """Imagen Docker -> [(clave_requisito, versión)]. Lista vacía si no aporta."""
    if "$" in image:
        return []
    name, base, tag = split_image(image)
    out: list[tuple[str, str]] = []
    jdk_tag = _JDK_IN_TAG.search(tag)
    is_runtime = base in RUNTIME_IMAGES or "jre" in tag.lower()
    jdk_key = "jdk_runtime" if is_runtime else "jdk"

    if base == "maven":
        if v := _num_prefix(tag):
            out.append(("maven", v))
        if jdk_tag:
            out.append(("jdk", jdk_tag.group(1)))
    elif base == "gradle":
        if v := _num_prefix(tag):
            out.append(("gradle", v))
        if jdk_tag:
            out.append(("jdk", jdk_tag.group(1)))
    elif base in JDK_IMAGES:
        if v := jdk_major(tag or ""):
            out.append((jdk_key, v))
    elif base in RUNTIME_IMAGES:
        if base == "tomcat" and (v := _num_prefix(tag)):
            out.append(("tomcat", v))
        if jdk_tag:
            out.append((jdk_key, jdk_tag.group(1)))
    elif base in ("gcc", "python", "node", "golang", "clang"):
        key = {"golang": "go"}.get(base, base)
        if v := _num_prefix(tag):
            out.append((key, v))
    elif "dotnet" in name and base in ("sdk", "aspnet", "runtime"):
        if v := _num_prefix(tag):
            out.append(("dotnet", v))
    elif name.startswith("conanio/"):          # conanio/gcc11, conanio/clang14
        if m := re.match(r"(gcc|clang)(\d+)", base):
            out.append((m.group(1), m.group(2)))
    return out


def _service_kind(image: str) -> tuple[str | None, str | None]:
    name, base, tag = split_image(image)
    if "mssql" in name:
        return "sqlserver", _num_prefix(tag)
    kind = SERVICE_IMAGES.get(base)
    return (kind, _num_prefix(tag)) if kind else (None, None)


# ----------------------------------------------------------------------------
# Utilidades de parseo
# ----------------------------------------------------------------------------

def _logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Une líneas con '\\' final (Dockerfile/shell). Devuelve (línea_inicial, texto)."""
    out, buf, start = [], [], 0
    for i, raw in enumerate(lines, start=1):
        s = raw.rstrip()
        if not buf:
            start = i
        if s.endswith("\\"):
            buf.append(s[:-1])
            continue
        buf.append(s)
        out.append((start, " ".join(x.strip() for x in buf)))
        buf = []
    if buf:
        out.append((start, " ".join(x.strip() for x in buf)))
    return out


_RUN_KEY = re.compile(r"^(\s*)(?:-\s+)?(run|script|command|commands)\s*:\s*(.*)$")


def _yaml_commands(lines: list[str]) -> list[tuple[int, str]]:
    """Extrae comandos de bloques run:/script:/command: de YAML de CI, sin
    depender de PyYAML. Soporta 'run: cmd', 'run: |' multilínea y listas."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        m = _RUN_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(3).strip()
        if rest in ("", "|", "|-", "|+", ">", ">-", ">+"):
            j = i + 1
            while j < len(lines):
                ln = lines[j]
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                    break
                t = ln.strip()
                if t.startswith("- "):
                    t = t[2:].strip()
                t = t.strip("'\"")
                if t and not t.startswith("#"):
                    out.append((j + 1, t))
                j += 1
            i = j
            continue
        if not rest.startswith("["):
            out.append((i + 1, rest.strip("'\"")))
        i += 1
    return out


def _is_build_cmd(cmd: str) -> bool:
    return bool(BUILD_TOOL_RX.search(" " + cmd))


# ----------------------------------------------------------------------------
# Adaptador
# ----------------------------------------------------------------------------

@register
class HintsAdapter(Adapter):
    name = NAME
    always_run = True

    def analyze(self, sc: ProjectScanner, info: ProjectInfo, detections) -> None:
        self._toolchain_files(sc, info)
        self._dockerfiles(sc, info)
        self._compose(sc, info)
        self._ci(sc, info)
        self._ide(sc, info)
        self._docs(sc, info)
        self._previous_builds(sc, info)

    # ---------------------------------------------------------------- 1. toolchain
    def _toolchain_files(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        if sc.exists(".tool-versions"):
            for i, line in enumerate(sc.read_lines(".tool-versions"), 1):
                parts = line.split("#", 1)[0].split()
                if len(parts) >= 2:
                    self._tool(info, parts[0], parts[1], ".tool-versions", i, line)

        for f in ("mise.toml", ".mise.toml"):
            if not sc.exists(f):
                continue
            try:
                data = tomllib.loads(sc.read_text(f) or "")
            except tomllib.TOMLDecodeError as e:
                info.warnings.append(f"{f} no es TOML válido: {e}")
                continue
            lines = sc.read_lines(f)
            for tool, val in (data.get("tools") or {}).items():
                if isinstance(val, list):
                    val = val[0] if val else None
                if isinstance(val, dict):
                    val = val.get("version")
                ln = next((i for i, l in enumerate(lines, 1)
                           if re.match(rf'\s*"?{re.escape(tool)}"?\s*=', l)), None)
                self._tool(info, tool, val, f, ln, f"{tool} = {val}")

        if sc.exists(".sdkmanrc"):
            for i, line in enumerate(sc.read_lines(".sdkmanrc"), 1):
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    self._tool(info, k, v, ".sdkmanrc", i, line)

        for f, key in ((".java-version", "jdk"), (".python-version", "python"),
                       (".nvmrc", "node"), (".node-version", "node")):
            if sc.exists(f):
                lines = sc.read_lines(f)
                if lines:
                    req(info, key, lines[0], P.EXPLICIT, f, 1, lines[0], adapter=NAME)

        if sc.exists("global.json"):
            try:
                v = json.loads(sc.read_text("global.json") or "{}").get("sdk", {}).get("version")
                req(info, "dotnet", v, P.EXPLICIT, "global.json", None, f"sdk {v}",
                    adapter=NAME)
            except (json.JSONDecodeError, AttributeError):
                pass

    def _tool(self, info, tool, version, file, line, snippet) -> None:
        key = normalize_tool(str(tool))
        if key:
            req(info, key, version, P.EXPLICIT, file, line, snippet, adapter=NAME,
                note=f"declarado en {file}")
        else:
            info.add_list_fact("toolchain.other", f"{tool} {version}", priority=P.EXPLICIT,
                               evidence=ev(file, line, snippet), adapter=NAME)

    # ---------------------------------------------------------------- 2. Docker
    def _dockerfiles(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        files = set(sc.glob("**/Dockerfile", icase=True))
        files |= set(sc.glob("**/Dockerfile.*", icase=True))
        files |= set(sc.glob("**/*.Dockerfile", icase=True))
        for f in sorted(files, key=lambda p: (p.count("/"), p)):
            logical = _logical_lines(sc.read_lines(f))
            args: dict[str, str] = {}
            stages: list[tuple[int, str, str | None]] = []   # (line, image, alias)
            for ln, text in logical:
                t = text.strip()
                if m := re.match(r"(?i)^ARG\s+(\w+)(?:=(\S+))?", t):
                    if m.group(2):
                        args[m.group(1)] = m.group(2).strip("'\"")
                elif m := re.match(r"(?i)^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", t):
                    img = re.sub(r"\$\{?(\w+)\}?",
                                 lambda mm: args.get(mm.group(1), mm.group(0)), m.group(1))
                    stages.append((ln, img, m.group(2)))
                elif m := re.match(r"(?i)^RUN\s+(.*)", t):
                    if _is_build_cmd(m.group(1)):
                        add_cmd_hint(info, m.group(1), origin="docker", priority=P.CI,
                                     file=f, line=ln, adapter=NAME)
                elif m := re.match(r"(?i)^EXPOSE\s+(.*)", t):
                    for port in m.group(1).split():
                        info.add_list_fact("hints.ports", port.split("/")[0],
                                           priority=P.CI, evidence=ev(f, ln, t), adapter=NAME)
                elif re.match(r"(?i)^(COPY|ADD)\s", t) and re.search(r"webapps|\.war\b|\.jar\b", t):
                    info.add_list_fact("hints.deploy", t, priority=P.CI,
                                       evidence=ev(f, ln, t), adapter=NAME)

            aliases = {a.lower() for _, _, a in stages if a}
            multi = len(stages) > 1
            for idx, (ln, img, alias) in enumerate(stages):
                if img.lower() in aliases:          # FROM <etapa anterior>
                    continue
                last = idx == len(stages) - 1
                stage = ("runtime" if last else "build") if multi else "única"
                _, base, tag = split_image(img)
                if base in OS_IMAGES:
                    info.add_list_fact("hints.base_os", f"{base}:{tag or 'latest'}",
                                       priority=P.CI, evidence=ev(f, ln, img), adapter=NAME)
                for key, ver in parse_image(img):
                    if key == "jdk" and multi and last:
                        key = "jdk_runtime"
                    req(info, key, ver, P.CI, f, ln, f"FROM {img}", adapter=NAME,
                        note=f"imagen Docker (etapa {stage})")

    # ---------------------------------------------------------------- 3. compose
    def _compose(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        pats = ("**/docker-compose*.yml", "**/docker-compose*.yaml",
                "**/compose*.yml", "**/compose*.yaml")
        files = sorted({f for p in pats for f in sc.glob(p, icase=True)})
        for f in files:
            for i, line in enumerate(sc.read_lines(f), 1):
                m = re.match(r"""^\s*image:\s*["']?([^"'\s#]+)""", line)
                if not m:
                    continue
                kind, ver = _service_kind(m.group(1))
                if kind:
                    add_service(info, kind, ver, P.CI, f, i, line, adapter=NAME,
                                note="docker-compose")
                else:
                    info.add_list_fact("hints.compose_images", m.group(1), priority=P.CI,
                                       evidence=ev(f, i, line), adapter=NAME)

    # ---------------------------------------------------------------- 4. CI
    SETUP_KEYS = {"java-version": "jdk", "python-version": "python",
                  "node-version": "node", "dotnet-version": "dotnet",
                  "cmake-version": "cmake", "gradle-version": "gradle",
                  "maven-version": "maven", "go-version": "go"}

    def _ci(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        yaml_ci = (sc.glob(".github/workflows/*.yml") + sc.glob(".github/workflows/*.yaml")
                   + [f for f in (".gitlab-ci.yml", "azure-pipelines.yml",
                                  ".circleci/config.yml", "bitbucket-pipelines.yml",
                                  ".travis.yml") if sc.exists(f)])
        for f in yaml_ci:
            lines = sc.read_lines(f)
            for i, line in enumerate(lines, 1):
                if m := re.match(r"^\s*-?\s*([\w-]+-version)\s*:\s*(.+?)\s*(?:#.*)?$", line):
                    key = self.SETUP_KEYS.get(m.group(1))
                    if key:
                        vals = re.findall(r"[\w.\-+]+", m.group(2))
                        if vals:
                            note = "setup en CI" + (f" (matriz: {', '.join(vals)})"
                                                    if len(vals) > 1 else "")
                            req(info, key, vals[0], P.CI, f, i, line, adapter=NAME, note=note)
                if m := re.match(r"""^\s*-?\s*image:\s*["']?([^"'\s#]+)""", line):
                    for key, ver in parse_image(m.group(1)):
                        req(info, key, ver, P.CI, f, i, line, adapter=NAME,
                            note="imagen usada en CI")
            for ln, cmd in _yaml_commands(lines):
                if _is_build_cmd(cmd):
                    add_cmd_hint(info, cmd, origin="ci", priority=P.CI,
                                 file=f, line=ln, adapter=NAME)

        if sc.exists("Jenkinsfile"):
            f = "Jenkinsfile"
            for i, line in enumerate(sc.read_lines(f), 1):
                if m := re.search(r"""\b(?:sh|bat)\s*\(?\s*(?:script:\s*)?(['"]{1,3})(.+?)\1""",
                                  line):
                    if _is_build_cmd(m.group(2)):
                        add_cmd_hint(info, m.group(2), origin="ci", priority=P.CI,
                                     file=f, line=i, adapter=NAME)
                if m := re.match(r"""^\s*(jdk|maven|gradle)\s+['"]([^'"]+)['"]""", line):
                    req(info, normalize_tool(m.group(1)) or m.group(1), m.group(2),
                        P.HEURISTIC, f, i, line, adapter=NAME,
                        note="etiqueta de herramienta en Jenkins (puede no ser la versión)")

    # ---------------------------------------------------------------- 5. IDE
    def _ide(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        def run_cfg(f: str, what: str) -> None:
            info.add_list_fact("ide.run_configs", {"file": f, "type": what},
                               priority=P.BUILD, adapter=NAME)

        if sc.exists(".vscode/tasks.json"):
            f = ".vscode/tasks.json"
            run_cfg(f, "vscode-tasks")
            for i, line in enumerate(sc.read_lines(f), 1):
                if m := re.search(r'"command"\s*:\s*"([^"]+)"', line):
                    if _is_build_cmd(m.group(1)):
                        add_cmd_hint(info, m.group(1), origin="ide", priority=P.BUILD,
                                     file=f, line=i, adapter=NAME)
        if sc.exists(".vscode/launch.json"):
            f = ".vscode/launch.json"
            run_cfg(f, "vscode-launch")
            for i, line in enumerate(sc.read_lines(f), 1):
                if m := re.search(r'"program"\s*:\s*"([^"]+)"', line):
                    info.add_list_fact("hints.executables", m.group(1), priority=P.BUILD,
                                       evidence=ev(f, i, line), adapter=NAME)
                if m := re.search(r'"mainClass"\s*:\s*"([^"]+)"', line):
                    info.add_list_fact("hints.main_classes", m.group(1), priority=P.BUILD,
                                       evidence=ev(f, i, line), adapter=NAME)

        for f in sc.glob(".idea/runConfigurations/*.xml") + sc.glob(".run/*.xml"):
            text = sc.read_text(f) or ""
            m = re.search(r'<configuration[^>]*\btype="([^"]+)"', text)
            ctype = m.group(1) if m else "intellij"
            run_cfg(f, ctype)
            for i, line in enumerate(text.splitlines(), 1):
                if m := re.search(r'name="MAIN_CLASS_NAME"\s+value="([^"]+)"', line):
                    info.add_list_fact("hints.main_classes", m.group(1), priority=P.BUILD,
                                       evidence=ev(f, i, line), adapter=NAME)
            if "tomcat" in ctype.lower():
                self._servlet(info, f, None, f"run config {ctype}")

        smart = sc.glob(".smarttomcat/**")
        if smart:
            run_cfg(".smarttomcat/", "intellij-smart-tomcat")
            self._servlet(info, smart[0], None, "plugin Smart Tomcat de IntelliJ")
            for f in smart:
                if hit := re.search(r"tomcat[-_ ]?(\d+(?:\.\d+)+)", sc.read_text(f) or "", re.I):
                    req(info, "tomcat", hit.group(1), P.HEURISTIC, f, None, hit.group(0),
                        adapter=NAME, note="ruta de Tomcat en config del IDE")
                    break

        for f in sc.glob("context.xml") + sc.glob("**/META-INF/context.xml"):
            self._servlet(info, f, None, "context.xml de Tomcat")

    def _servlet(self, info: ProjectInfo, f: str, line: int | None, why: str) -> None:
        info.set_fact("runtime.servlet_container",
                      Fact(value="tomcat", priority=P.HEURISTIC,
                           evidence=[ev(f, line, why)], adapter=NAME,
                           note="se despliega como WAR en un servlet container"))

    # ---------------------------------------------------------------- 6. docs
    DOC_GLOBS = ("README*", "BUILD*", "INSTALL*", "CONTRIBUTING*", "TROUBLESHOOT*",
                 "HACKING*", "DEVELOP*", "SETUP*", "*.md", "docs/*.md")
    NOT_DOCS = {"cmakelists.txt", "license", "license.txt", "license.md",
                "notice", "notice.txt", "agents.md", "claude.md"}
    DOC_CMD = re.compile(
        r"^(?:[$>]\s+)?(?:sudo\s+)?((?:\./)?(?:mvnw?|gradlew?|cmake|ctest|conan|make|ninja|"
        r"npm|yarn|pip3?|dotnet|docker(?:[- ]compose)?|java\s+-jar|catalina\.sh|psql|"
        r"createdb|bash|sh)\b.*|\./[\w./-]+\.(?:sh|bat)\b.*)")
    DOC_VERSIONS = [
        ("jdk", re.compile(r"\b(?:jdk|java|openjdk)\s*(?:version\s*)?[:\-]?\s*"
                           r"(1\.[5-8]|\d{1,2})(?:\.\d+)*\b(?!\s*(?:ms|mb|gb|%))", re.I)),
        ("tomcat", re.compile(r"\btomcat\s*(?:version\s*)?v?(\d+(?:\.\d+)*)", re.I)),
        ("maven", re.compile(r"\bmaven\s*(?:version\s*)?v?(3(?:\.\d+)*)\b", re.I)),
        ("cmake", re.compile(r"\bcmake\s*(?:version\s*)?(?:>=?\s*)?v?(3\.\d+(?:\.\d+)?)", re.I)),
        ("conan", re.compile(r"\bconan\s*(?:version\s*)?v?([12](?:\.\d+)*)\b", re.I)),
    ]
    DOC_PG = re.compile(r"\bpostgres(?:ql)?\s*(?:version\s*)?v?(\d{1,2}(?:\.\d+)?)\b", re.I)

    def _docs(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        files = sorted({f for g in self.DOC_GLOBS for f in sc.glob(g, icase=True)
                        if PurePosixPath(f).name.lower() not in self.NOT_DOCS})
        for f in files:
            text = sc.read_text(f)
            if text is None or len(text) > 300_000:
                continue
            n_cmds, seen_keys = 0, set()
            in_code = False
            for i, raw in enumerate(text.splitlines(), 1):
                line = raw.strip()
                if line.startswith("```"):
                    in_code = not in_code
                    continue
                if n_cmds < 40 and 0 < len(line) <= 240:
                    m = self.DOC_CMD.match(line)
                    if m and (in_code or raw[:1] in (" ", "\t", "$")
                              or not line.endswith((".", ":"))):
                        add_cmd_hint(info, m.group(1), origin="docs", priority=P.HEURISTIC,
                                     file=f, line=i, adapter=NAME)
                        n_cmds += 1
                for key, rx in self.DOC_VERSIONS:
                    if key in seen_keys:
                        continue
                    if m := rx.search(line):
                        req(info, key, m.group(1), P.HEURISTIC, f, i, line, adapter=NAME,
                            note="mencionado en documentación")
                        seen_keys.add(key)
                if "pg" not in seen_keys and (m := self.DOC_PG.search(line)):
                    add_service(info, "postgresql", m.group(1), P.HEURISTIC, f, i, line,
                                adapter=NAME, note="mencionado en documentación")
                    seen_keys.add("pg")

    # ---------------------------------------------------------------- 7. builds previos
    def _previous_builds(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        """CMakeCache.txt dice qué compilador/generador/tipo se usó la última vez."""
        for f in sc.build_artifacts.get("cmake_cache", [])[:5]:
            try:
                text = (sc.root / f).read_text(errors="replace")
            except OSError:
                continue
            data = {}
            for k in ("CMAKE_CXX_COMPILER", "CMAKE_GENERATOR", "CMAKE_BUILD_TYPE",
                      "CMAKE_TOOLCHAIN_FILE", "CMAKE_COMMAND"):
                if m := re.search(rf"^{k}:\w+=(.*)$", text, re.M):
                    data[k] = m.group(1).strip()
            if data:
                info.add_list_fact("hints.previous_cmake_builds", {"cache": f, **data},
                                   priority=P.HEURISTIC, adapter=NAME,
                                   note="build anterior encontrado en el árbol")
        cc = sc.build_artifacts.get("compile_commands", [])
        if cc:
            info.set_fact("hints.compile_commands",
                          Fact(value=cc, priority=P.HEURISTIC, adapter=NAME,
                               note="útil para clangd/Serena; puede estar desactualizado"))
