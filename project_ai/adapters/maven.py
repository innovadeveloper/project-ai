"""
adapters/maven.py — Proyectos Maven (Spring Boot, WAR clásico, librerías, multi-módulo).

No asume Spring Boot: averigua qué tipo de proyecto es cada módulo.

Qué descubre (todo con evidencia archivo:línea):
  Estructura   árbol de módulos (incl. perfiles), herencia de parents locales,
               orden de build (reactor), artefacto final de cada módulo
               (p.ej. server/target/launcher.war).
  Tipo         por módulo: aggregator | war | spring-boot-app | application | library
               framework: Spring Boot X / Jersey / ... ; javax vs jakarta.
  Requisitos   jdk (máximo entre módulos de release/source/target, java.version,
               enforcer), maven (wrapper, enforcer), kotlin, tomcat deducido.
  Riesgos      jdk_ceiling (JDK máximo razonable: lombok viejo, source <= 7),
               javax.servlet con Tomcat >= 10 (o jakarta con Tomcat <= 9),
               repos privados, dependencias system/SNAPSHOT externas,
               plugins que generan código (hay que correr generate-sources).
  Runtime      servicios por dependencias (driver postgres, kafka, paho mqtt...)
               y por URLs jdbc: en configuración; migraciones (flyway/liquibase).
  Código       entry points (@SpringBootApplication, main, web.xml, @WebServlet,
               listeners) y endpoints REST (JAX-RS @Path/@GET y Spring
               @GetMapping/@RequestMapping), con clase#método y línea.
  Comandos     deps / build / build_app (-pl -am) / test / generate / run,
               usando ./mvnw si existe, con equivalente en IntelliJ.

Prioridades: lo declarado en pom.xml es BUILD; wrapper es EXPLICIT; lo deducido
(Tomcat por javax, JDK por Spring Boot) es HEURISTIC.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..model import (Command, Endpoint, EntryPoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, jdk_major, register, req

NAME = "maven"

# --------------------------------------------------------------------------
# Tablas de conocimiento (ampliables)
# --------------------------------------------------------------------------
DEP_SERVICES = [  # (groupId, artifactId) con comodines -> servicio de runtime
    ("org.postgresql", "postgresql", "postgresql"), ("postgresql", "postgresql", "postgresql"),
    ("mysql", "mysql-connector-java", "mysql"), ("com.mysql", "mysql-connector-j", "mysql"),
    ("org.mariadb.jdbc", "mariadb-java-client", "mariadb"),
    ("com.oracle*", "ojdbc*", "oracle"), ("com.microsoft.sqlserver", "mssql-jdbc", "sqlserver"),
    ("org.mongodb", "*", "mongodb"), ("org.springframework.boot", "*data-mongodb*", "mongodb"),
    ("org.apache.kafka", "kafka-clients", "kafka"), ("org.springframework.kafka", "*", "kafka"),
    ("redis.clients", "jedis", "redis"), ("io.lettuce", "lettuce-core", "redis"),
    ("org.springframework.boot", "*data-redis*", "redis"),
    ("com.rabbitmq", "amqp-client", "rabbitmq"), ("org.springframework.boot", "*amqp*", "rabbitmq"),
    ("org.eclipse.paho", "*", "mqtt"), ("com.hivemq", "hivemq-mqtt-client", "mqtt"),
    ("org.elasticsearch.client", "*", "elasticsearch"),
]
JDBC_KINDS = {"postgresql": "postgresql", "mysql": "mysql", "mariadb": "mariadb",
              "oracle": "oracle", "sqlserver": "sqlserver"}
EMBEDDED_DBS = {"h2", "hsqldb", "sqlite", "derby"}
CODEGEN_PLUGINS = {
    "frontend-maven-plugin": "descarga Node y ejecuta npm durante el build",
    "openapi-generator-maven-plugin": "genera código desde OpenAPI",
    "swagger-codegen-maven-plugin": "genera código desde Swagger",
    "protobuf-maven-plugin": "genera código desde .proto",
    "jaxb2-maven-plugin": "genera clases JAXB", "maven-jaxb2-plugin": "genera clases JAXB",
    "jaxws-maven-plugin": "genera clientes SOAP", "cxf-codegen-plugin": "genera clientes SOAP",
    "build-helper-maven-plugin": "añade carpetas de fuentes generadas",
    "maven-antrun-plugin": "ejecuta tareas Ant arbitrarias",
    "exec-maven-plugin": "ejecuta programas durante el build",
    "jib-maven-plugin": "construye imágenes Docker",
    "docker-maven-plugin": "construye imágenes Docker",
    "querydsl-apt": "genera clases Q* (apt)",
}
CENTRAL_HOSTS = ("repo.maven.apache.org", "repo1.maven.org", "repo.maven.org")
HTTP_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
SPRING_MAPPINGS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
                   "DeleteMapping": "DELETE", "PatchMapping": "PATCH"}

_PROP_RX = re.compile(r"\$\{([^}]+)\}")
_ANN_RX = re.compile(r"@([\w.]+)\s*(\((?:[^()]|\([^()]*\))*\))?")
_CLASS_RX = re.compile(r"\b(class|interface|enum|record)\s+(\w+)")
_METHOD_RX = re.compile(
    r"^(?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)*"
    r"[\w<>\[\],.?\s]+?\s+(\w+)\s*\(")
_NOT_METHOD = ("return ", "if ", "if(", "for ", "for(", "while", "new ", "throw ", "else")


# --------------------------------------------------------------------------
# Modelo interno de un pom
# --------------------------------------------------------------------------

@dataclass
class Pom:
    file: str
    dir: str                      # "" = raíz
    el: ET.Element
    lines: list[str]
    artifact: str
    group: str | None
    version: str | None
    packaging: str
    parent: tuple[str | None, str | None, str | None, str | None] | None  # g,a,v,relPath
    modules: list[str]
    props: dict[str, str]
    parent_pom: "Pom | None" = None
    _eff: dict[str, tuple[str, str]] | None = field(default=None, repr=False)

    @property
    def dir_or_dot(self) -> str:
        return self.dir or "."

    @property
    def gid(self) -> str | None:
        return self.group or (self.parent[0] if self.parent else None)

    @property
    def ver(self) -> str | None:
        return self.version or (self.parent[2] if self.parent else None)

    def line(self, pattern: str) -> int | None:
        rx = re.compile(pattern)
        return next((i for i, l in enumerate(self.lines, 1) if rx.search(l)), None)

    def eff(self) -> dict[str, tuple[str, str]]:
        """Propiedades efectivas (heredadas + propias): clave -> (valor, archivo)."""
        if self._eff is None:
            base = dict(self.parent_pom.eff()) if self.parent_pom else {}
            base.update({k: (v, self.file) for k, v in self.props.items()})
            for k, v in (("project.version", self.ver), ("version", self.ver),
                         ("pom.version", self.ver), ("project.groupId", self.gid),
                         ("project.artifactId", self.artifact),
                         ("project.parent.version", self.parent[2] if self.parent else None)):
                if v:
                    base[k] = (v, self.file)
            self._eff = base
        return self._eff

    def resolve(self, s: str | None) -> str | None:
        if s is None:
            return None
        eff = self.eff()
        for _ in range(6):
            new = _PROP_RX.sub(lambda m: eff[m.group(1)][0] if m.group(1) in eff
                               else m.group(0), s)
            if new == s:
                break
            s = new
        return s

    def prop_origin(self, key: str) -> str | None:
        return self.eff().get(key, (None, None))[1]


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _t(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    x = el.find(path)
    return x.text.strip() if x is not None and x.text and x.text.strip() else None


def _join(base: str, rel: str) -> str:
    p = posixpath.normpath(posixpath.join(base, rel)) if base else posixpath.normpath(rel)
    return "" if p == "." else p


def _vtuple(v: str | None) -> tuple[int, ...] | None:
    if not v or "$" in v:
        return None
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums[:3]) if nums else None


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class MavenAdapter(Adapter):
    name = NAME

    def __init__(self) -> None:
        self.poms: dict[str, Pom] = {}
        self.errors: list[tuple[str, str]] = []
        self._loaded = False

    # ------------------------------------------------------------------ carga
    def _load(self, sc: ProjectScanner) -> None:
        if self._loaded:
            return
        self._loaded = True
        for f in sc.glob("**/pom.xml"):
            if "/src/" in "/" + f:          # poms de prueba dentro de src/
                continue
            text = (sc.read_text(f) or "").lstrip("﻿")
            try:
                root = ET.fromstring(text)
            except ET.ParseError as e:
                self.errors.append((f, str(e)))
                continue
            _strip_ns(root)
            d = f.rsplit("/", 1)[0] if "/" in f else ""
            par = root.find("parent")
            parent = None
            if par is not None:
                rel_el = par.find("relativePath")
                rel = "../pom.xml" if rel_el is None else (rel_el.text or "").strip() or None
                parent = (_t(par, "groupId"), _t(par, "artifactId"), _t(par, "version"), rel)
            mods = [m.text.strip() for m in root.findall("modules/module")
                    + root.findall("profiles/profile/modules/module") if m.text]
            props_el = root.find("properties")
            props = {c.tag: (c.text or "").strip() for c in props_el} if props_el is not None else {}
            self.poms[f] = Pom(
                file=f, dir=d, el=root, lines=text.splitlines(),
                artifact=_t(root, "artifactId") or d or "root",
                group=_t(root, "groupId"), version=_t(root, "version"),
                packaging=(_t(root, "packaging") or "jar").lower(),
                parent=parent, modules=list(dict.fromkeys(mods)), props=props)
        by_ga = {(p.gid, p.artifact): p for p in self.poms.values()}
        for p in self.poms.values():
            if not p.parent:
                continue
            g, a, _, rel = p.parent
            cand = None
            if rel:
                path = _join(p.dir, rel)
                path = path if path.endswith(".xml") else _join(path, "pom.xml")
                cand = self.poms.get(path)
                if cand is not None and cand.artifact != a:
                    cand = None
            p.parent_pom = cand or by_ga.get((g, a))

    def _module_file(self, p: Pom, m: str) -> str:
        path = _join(p.dir, m)
        return path if path.endswith(".xml") else _join(path, "pom.xml")

    # ------------------------------------------------------------------ detect
    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        self._load(sc)
        referenced = {self._module_file(p, m) for p in self.poms.values() for m in p.modules}
        out = []
        for p in self.poms.values():
            if p.file in referenced:
                continue
            conf = 0.95 if p.dir == "" else 0.7
            out.append(StackDetection(NAME, conf, root=p.dir_or_dot,
                                      evidence=[ev(p.file, None, f"{p.gid}:{p.artifact}")]))
        if not out and self.errors:      # hay pom.xml pero ninguno legible: avisar igual
            out.append(StackDetection(NAME, 0.3, root=".",
                                      evidence=[ev(f, None, "XML inválido") for f, _ in self.errors]))
        return out

    # ------------------------------------------------------------------ analyze
    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        self._load(sc)
        for f, err in self.errors:
            info.warnings.append(f"{f}: XML inválido, se ignora ({err})")
        poms = list(self.poms.values())
        if not poms:
            return
        local_ga = {(p.gid, p.artifact): p for p in poms}

        self._wrapper(sc, info)
        kinds = {p.file: self._kind(p) for p in poms}
        self._modules(info, poms, local_ga, kinds)
        self._jdk(info, poms)
        self._enforcer_and_kotlin(info, poms)
        boot = self._spring_boot(info, poms)
        ns = self._namespace(sc, info, poms, boot)
        self._tomcat(info, poms, kinds, ns)
        self._ceiling(info, poms)
        self._dependencies(info, poms, local_ga)
        self._jdbc_config(sc, info, poms)
        self._repositories(info, poms)
        self._plugins(info, poms)
        self._entry_points(sc, info, poms, kinds)
        self._endpoints(sc, info, poms)
        self._commands(sc, info, poms, kinds, detections)

    # ------------------------------------------------------------------ partes
    def _wrapper(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        f = ".mvn/wrapper/maven-wrapper.properties"
        if sc.exists(f):
            for i, line in enumerate(sc.read_lines(f), 1):
                if m := re.search(r"apache-maven-(\d+(?:\.\d+)+)-bin", line):
                    req(info, "maven", m.group(1), P.EXPLICIT, f, i, line, adapter=NAME,
                        note="Maven Wrapper (./mvnw lo descarga solo)")
        for f in (".mvn/jvm.config", ".mvn/maven.config"):
            if sc.exists(f):
                info.set_fact(f"maven.{f.rsplit('/', 1)[1]}", Fact(
                    value=" ".join(sc.read_lines(f)).strip(), priority=P.EXPLICIT,
                    evidence=[ev(f)], adapter=NAME))

    def _kind(self, p: Pom) -> str:
        if p.packaging == "pom":
            return "aggregator"
        if p.packaging in ("war", "ear"):
            return p.packaging
        own_plugins = {_t(x, "artifactId") for x in p.el.findall("build/plugins/plugin")}
        if "spring-boot-maven-plugin" in own_plugins:
            return "spring-boot-app"
        if p.packaging == "maven-plugin":
            return "maven-plugin"
        if any("<mainClass>" in l for l in p.lines):
            return "application"
        return "library"

    def _artifact(self, p: Pom) -> str:
        final = p.resolve(_t(p.el, "build/finalName")) or f"{p.artifact}-{p.resolve(p.ver) or 'VERSION'}"
        ext = "jar" if p.packaging in ("jar", "maven-plugin") else p.packaging
        return _join(p.dir, f"target/{final}.{ext}")

    def _deps(self, p: Pom, mgmt: bool = False):
        path = "dependencyManagement/dependencies/dependency" if mgmt else "dependencies/dependency"
        for d in p.el.findall(path):
            yield (p.resolve(_t(d, "groupId")), p.resolve(_t(d, "artifactId")),
                   p.resolve(_t(d, "version")), _t(d, "scope") or "compile", d)

    def _modules(self, info, poms, local_ga, kinds) -> None:
        graph: dict[str, set[str]] = {}
        for p in poms:
            deps = {local_ga[(g, a)].artifact for g, a, _, _, _ in self._deps(p)
                    if (g, a) in local_ga}
            if p.parent_pom:
                deps.add(p.parent_pom.artifact)
            graph[p.artifact] = deps
            info.modules.append(Module(name=p.artifact, path=p.dir_or_dot, build_system=NAME,
                                       kind=kinds[p.file], depends_on=sorted(deps)))
            if kinds[p.file] in ("war", "ear", "spring-boot-app", "application"):
                info.add_list_fact("maven.artifacts",
                                   {"module": p.artifact, "path": self._artifact(p),
                                    "kind": kinds[p.file]},
                                   priority=P.BUILD, evidence=ev(p.file), adapter=NAME,
                                   note="lo que produce el build y hay que ejecutar/desplegar")
        order, done = [], set()
        while len(done) < len(graph):
            ready = sorted(n for n, ds in graph.items() if n not in done and ds <= done | {n})
            if not ready:   # ciclo: añadir el resto tal cual
                ready = sorted(n for n in graph if n not in done)
            order += ready
            done |= set(ready)
        if len(order) > 1:
            info.set_fact("maven.build_order", Fact(value=order, priority=P.BUILD, adapter=NAME,
                                                    note="orden del reactor (dependencias locales)"))
        profiles = sorted({_t(x, "id") for p in poms for x in p.el.findall("profiles/profile")
                           if _t(x, "id")})
        if profiles:
            info.set_fact("maven.profiles", Fact(value=profiles, priority=P.BUILD, adapter=NAME))

    def _compiler_cfg(self, p: Pom) -> ET.Element | None:
        for x in p.el.findall("build/plugins/plugin") + p.el.findall(
                "build/pluginManagement/plugins/plugin"):
            if _t(x, "artifactId") == "maven-compiler-plugin":
                return x.find("configuration")
        return None

    def _jdk_of(self, p: Pom) -> tuple[str, str, str] | None:
        """(versión_major, archivo, clave) del nivel de Java de un pom."""
        eff = p.eff()
        for key in ("maven.compiler.release", "maven.compiler.source",
                    "maven.compiler.target", "java.version"):
            if key in eff:
                v = jdk_major(p.resolve(eff[key][0]) or "")
                if v:
                    return v, eff[key][1], key
        q: Pom | None = p
        while q is not None:
            cfg = self._compiler_cfg(q)
            for tag in ("release", "source", "target"):
                raw = q.resolve(_t(cfg, tag)) if cfg is not None else None
                if raw and (v := jdk_major(raw)):
                    return v, q.file, f"maven-compiler-plugin/{tag}"
            q = q.parent_pom
        return None

    def _jdk(self, info, poms) -> None:
        found = [(p, r) for p in poms if p.packaging != "pom" or not p.modules
                 if (r := self._jdk_of(p))]
        found += [(p, r) for p in poms if p.packaging == "pom" and p.modules
                  if (r := self._jdk_of(p))]
        if not found:
            info.set_fact("maven.jdk_undeclared", Fact(
                value=True, priority=P.BUILD, adapter=NAME,
                note="ningún pom declara release/source/target: el compiler plugin usará su "
                     "default (antiguo). Pide confirmación al usuario"))
            return
        best_p, (v, file, key) = max(found, key=lambda x: int(x[1][0]))
        others = sorted({r[0] for _, r in found} - {v}, key=int)
        pom = self.poms.get(file, best_p)
        line = pom.line(rf"<{re.escape(key.split('/')[-1])}>")
        note = f"{key} (máximo entre módulos)" if len(found) > 1 else key
        if others:
            note += f"; otros módulos: {', '.join(others)}"
        req(info, "jdk", v, P.BUILD, file, line, f"<{key.split('/')[-1]}>",
            adapter=NAME, note=note)

    def _plugin_cfg(self, poms, artifact: str):
        for p in poms:
            for x in p.el.findall("build/plugins/plugin") + p.el.findall(
                    "build/pluginManagement/plugins/plugin"):
                if _t(x, "artifactId") == artifact:
                    yield p, x

    def _enforcer_and_kotlin(self, info, poms) -> None:
        for p, x in self._plugin_cfg(poms, "maven-enforcer-plugin"):
            for tag, key in ((".//requireJavaVersion/version", "jdk"),
                             (".//requireMavenVersion/version", "maven")):
                if raw := p.resolve(_t(x, tag)):
                    req(info, key, raw, P.BUILD, p.file, p.line(tag.split("/")[-2]), raw,
                        adapter=NAME, note=f"maven-enforcer: rango {raw} (mínimo)")
        for p, x in self._plugin_cfg(poms, "kotlin-maven-plugin"):
            v = p.resolve(_t(x, "version")) or p.resolve(p.eff().get("kotlin.version", ("",))[0])
            req(info, "kotlin", v, P.BUILD, p.file, p.line("kotlin-maven-plugin"), v,
                adapter=NAME)

    def _spring_boot(self, info, poms) -> str | None:
        version, where = None, None
        for p in poms:
            if p.parent and p.parent[1] in ("spring-boot-starter-parent", "spring-boot-parent",
                                            "spring-boot-dependencies"):
                version, where = p.parent[2], (p.file, p.line("spring-boot-starter-parent|"
                                                              "spring-boot-parent|"
                                                              "spring-boot-dependencies"))
                break
            for g, a, v, _, _ in self._deps(p, mgmt=True):
                if a == "spring-boot-dependencies" and v:
                    version, where = v, (p.file, p.line("spring-boot-dependencies"))
                    break
            if version:
                break
        if not version:
            for p, x in self._plugin_cfg(poms, "spring-boot-maven-plugin"):
                if v := p.resolve(_t(x, "version")):
                    version, where = v, (p.file, p.line("spring-boot-maven-plugin"))
                    break
        if not version:
            return None
        info.set_fact("framework", Fact(value=f"spring-boot {version}", priority=P.BUILD,
                                        evidence=[ev(where[0], where[1])], adapter=NAME))
        vt = _vtuple(version)
        if vt and vt[0] >= 3:
            req(info, "jdk", "17", P.HEURISTIC, where[0], where[1], f"Spring Boot {version}",
                adapter=NAME, note="Spring Boot 3 exige JDK >= 17")
        return version

    def _namespace(self, sc, info, poms, boot) -> str | None:
        votes: dict[str, list] = {"javax": [], "jakarta": []}
        for p in poms:
            for g, a, v, _, _ in self._deps(p):
                if not a:
                    continue
                if a in ("javax.servlet-api", "servlet-api", "javax.ws.rs-api", "jsr311-api"):
                    votes["javax"].append(ev(p.file, p.line(re.escape(a)), a))
                elif a in ("jakarta.servlet-api", "jakarta.ws.rs-api"):
                    votes["jakarta"].append(ev(p.file, p.line(re.escape(a)), a))
                elif g and g.startswith("org.glassfish.jersey") and (vt := _vtuple(v)):
                    votes["javax" if vt[0] < 3 else "jakarta"].append(
                        ev(p.file, p.line(re.escape(a)), f"{a} {v}"))
        java = [f for p in poms for f in sc.glob(_join(p.dir, "src/main/**/*.java"))]
        rx = re.compile(r"^import\s+(javax|jakarta)\.(servlet|ws\.rs)\b")
        for f in sorted(set(java))[:4000]:
            for i, line in enumerate(sc.read_lines(f)[:80], 1):
                if m := rx.match(line):
                    if len(votes[m.group(1)]) < 50:
                        votes[m.group(1)].append(ev(f, i, line.strip()))
                    break
        if boot and (vt := _vtuple(boot)):
            votes["jakarta" if vt[0] >= 3 else "javax"].append(ev("pom.xml", None,
                                                                  f"Spring Boot {boot}"))
        nj, nk = len(votes["javax"]), len(votes["jakarta"])
        if not nj and not nk:
            return None
        ns = "javax" if nj and not nk else "jakarta" if nk and not nj else "mixed"
        evid = (votes["javax"][:3] + votes["jakarta"][:3])
        info.set_fact("java.ee_namespace", Fact(
            value=ns, priority=P.BUILD, evidence=evid, adapter=NAME,
            note=f"javax: {nj} señales, jakarta: {nk}. javax => Tomcat <= 9; "
                 f"jakarta => Tomcat >= 10"))
        return ns

    def _tomcat(self, info, poms, kinds, ns) -> None:
        if ns not in ("javax", "jakarta"):
            return
        has_war = any(k == "war" for k in kinds.values())
        if has_war:
            req(info, "tomcat", "9" if ns == "javax" else "10.1", P.HEURISTIC,
                next(p.file for p in poms if kinds[p.file] == "war"), None,
                f"WAR + {ns}", adapter=NAME, note=f"deducido de WAR + {ns}.*")
        # Coherencia con Tomcat requerido y con el del IDE (lo aporta 'hints')
        checks = [("el Tomcat requerido", info.requirements.get("tomcat")),
                  ("el Tomcat configurado en el IDE", info.facts.get("ide.tomcat_local"))]
        for label, f in checks:
            vt = _vtuple(str(f.value)) if f else None
            if not vt:
                continue
            if ns == "javax" and vt[0] >= 10:
                info.warnings.append(
                    f"El código usa javax.* pero {label} es la versión {f.value} ({f.source}). "
                    f"Tomcat >= 10 usa jakarta.*: el WAR no arrancará. Usa Tomcat 9.x.")
            elif ns == "jakarta" and vt[0] <= 9:
                info.warnings.append(
                    f"El código usa jakarta.* pero {label} es la versión {f.value} ({f.source}). "
                    f"Necesitas Tomcat >= 10.")

    def _ceiling(self, info, poms) -> None:
        limits: list[tuple[int, str, str, int | None]] = []
        for p in poms:
            r = self._jdk_of(p)
            if r and int(r[0]) <= 6:
                limits.append((11, f"source/target {r[0]} (javac >= 12 ya no lo soporta)",
                               r[1], None))
            elif r and int(r[0]) == 7:
                limits.append((19, "source/target 7 (javac >= 20 ya no lo soporta)", r[1], None))
            for g, a, v, _, _ in self._deps(p):
                if a == "lombok" and (vt := _vtuple(v)):
                    line = p.line("lombok")
                    if vt < (1, 18, 22):
                        limits.append((16, f"lombok {v} no funciona con JDK >= 17", p.file, line))
                    elif vt < (1, 18, 30):
                        limits.append((20, f"lombok {v} no funciona con JDK >= 21", p.file, line))
        if not limits:
            return
        ceil = min(l[0] for l in limits)
        reasons = sorted({l[1] for l in limits if l[0] == ceil})
        info.set_fact("jdk_ceiling", Fact(
            value=str(ceil), priority=P.HEURISTIC,
            evidence=[ev(l[2], l[3], l[1]) for l in limits if l[0] == ceil][:3], adapter=NAME,
            note="JDK máximo razonable para compilar: " + "; ".join(reasons)))
        jdk = info.requirements.get("jdk")
        if jdk and str(jdk.value).isdigit() and int(jdk.value) > ceil:
            info.warnings.append(f"El JDK requerido ({jdk.value}) supera el techo estimado "
                                 f"({ceil}): {'; '.join(reasons)}")

    def _dependencies(self, info, poms, local_ga) -> None:
        for p in poms:
            for g, a, v, scope, d in self._deps(p):
                if not g or not a:
                    continue
                line = p.line(rf"<artifactId>{re.escape(a)}</artifactId>")
                for gp, ap, kind in DEP_SERVICES:
                    if fnmatch.fnmatchcase(g, gp) and fnmatch.fnmatchcase(a, ap):
                        add_service(info, kind, None, P.BUILD, p.file, line, f"{g}:{a}",
                                    adapter=NAME, note="dependencia del proyecto")
                        break
                if a in ("flyway-core", "liquibase-core"):
                    info.add_list_fact("db.migrations", a, priority=P.BUILD,
                                       evidence=ev(p.file, line), adapter=NAME,
                                       note="el esquema se crea/migra al arrancar")
                if scope == "system":
                    info.add_list_fact("maven.system_deps",
                                       {"dep": f"{g}:{a}", "path": p.resolve(_t(d, "systemPath"))},
                                       priority=P.BUILD, evidence=ev(p.file, line), adapter=NAME,
                                       note="JAR local con ruta fija: comprueba que existe")
                if v and v.endswith("-SNAPSHOT") and (g, a) not in local_ga:
                    info.add_list_fact("maven.external_snapshots", f"{g}:{a}:{v}",
                                       priority=P.BUILD, evidence=ev(p.file, line), adapter=NAME,
                                       note="SNAPSHOT externo: puede no existir en ningún repo")

    def _jdbc_config(self, sc, info, poms) -> None:
        dirs = {p.dir for p in poms}
        exts = (".properties", ".yml", ".yaml", ".xml", ".conf", ".env", ".example")
        files = [f for f in sc.files if f.endswith(exts) and not f.endswith("pom.xml")
                 and ("/src/test/" not in "/" + f)
                 and any(d == "" or f.startswith(d + "/") for d in dirs)]
        rx = re.compile(r"jdbc:(\w+):")
        seen: set[str] = set()
        for f in files[:3000]:
            for i, line in enumerate(sc.read_lines(f), 1):
                m = rx.search(line)
                if not m:
                    continue
                k = m.group(1).lower()
                if k in JDBC_KINDS and k not in seen:
                    add_service(info, JDBC_KINDS[k], None, P.BUILD, f, i, line.strip(),
                                adapter=NAME, note="URL JDBC en configuración")
                    seen.add(k)
                elif k in EMBEDDED_DBS and k not in seen:
                    info.add_list_fact("db.embedded", k, priority=P.BUILD,
                                       evidence=ev(f, i, line.strip()), adapter=NAME)
                    seen.add(k)
        sql = [f for f in sc.files if f.lower().endswith(".sql") and "/src/test/" not in "/" + f]
        if sql:
            info.set_fact("db.sql_scripts", Fact(value=sql[:15], priority=P.BUILD, adapter=NAME,
                                                 note=f"{len(sql)} scripts .sql en el repo"))

    def _repositories(self, info, poms) -> None:
        for p in poms:
            for r in p.el.findall("repositories/repository") + p.el.findall(
                    "pluginRepositories/pluginRepository"):
                url = p.resolve(_t(r, "url")) or ""
                if url and not any(h in url for h in CENTRAL_HOSTS):
                    info.add_list_fact(
                        "maven.repositories", {"id": _t(r, "id"), "url": url},
                        priority=P.BUILD, evidence=ev(p.file, p.line(re.escape(url[:40]))),
                        adapter=NAME,
                        note="repos no-Central: si son privados necesitas credenciales en "
                             "~/.m2/settings.xml (<server><id>...)")

    def _plugins(self, info, poms) -> None:
        for p in poms:
            for x in p.el.findall("build/plugins/plugin"):
                a = _t(x, "artifactId")
                if a in CODEGEN_PLUGINS:
                    info.add_list_fact("maven.notable_plugins", f"{a}: {CODEGEN_PLUGINS[a]}",
                                       priority=P.BUILD, evidence=ev(p.file, p.line(re.escape(a))),
                                       adapter=NAME,
                                       note="si el IDE no compila, ejecuta antes "
                                            "'mvn generate-sources' o el build completo")

    def _entry_points(self, sc, info, poms, kinds) -> None:
        n = 0
        for p in poms:
            if kinds[p.file] in ("aggregator",):
                continue
            src = [f for f in sc.glob(_join(p.dir, "src/main/**/*")) if f.endswith((".java", ".kt"))]
            for f in src:
                text = sc.read_text(f) or ""
                if not re.search(r"@SpringBootApplication|static\s+void\s+main\s*\(|"
                                 r"fun\s+main\s*\(|@WebServlet|@WebListener|@ApplicationPath|"
                                 r"extends\s+(?:GuiceServletContextListener|HttpServlet|"
                                 r"ResourceConfig|Application)\b", text):
                    continue
                cls = m.group(2) if (m := _CLASS_RX.search(text)) else f.rsplit("/", 1)[-1]
                for i, line in enumerate(text.splitlines(), 1):
                    kind = None
                    if "@SpringBootApplication" in line:
                        kind = "spring-boot-app"
                    elif re.search(r"static\s+void\s+main\s*\(|^fun\s+main\s*\(", line):
                        kind = "main-function"
                    elif re.search(r"@WebServlet|extends\s+HttpServlet\b", line):
                        kind = "servlet"
                    elif re.search(r"@WebListener|extends\s+GuiceServletContextListener", line):
                        kind = "servlet-listener"
                    elif re.search(r"@ApplicationPath|extends\s+(?:ResourceConfig|Application)\b",
                                   line):
                        kind = "jaxrs-application"
                    if kind and n < 40:
                        info.entry_points.append(EntryPoint(kind, cls, f, i))
                        n += 1
            for f in sc.glob(_join(p.dir, "src/main/webapp/WEB-INF/web.xml")):
                info.entry_points.append(EntryPoint("webapp-descriptor", "web.xml", f, None))
                for i, line in enumerate(sc.read_lines(f), 1):
                    if m := re.search(r"<(listener|servlet|filter)-class>\s*([\w.$]+)", line):
                        info.entry_points.append(
                            EntryPoint(f"web.xml-{m.group(1)}", m.group(2), f, i))

    def _endpoints(self, sc, info, poms) -> None:
        files = sorted({f for p in poms for f in sc.glob(_join(p.dir, "src/main/**/*.java"))})
        for f in files:
            text = sc.read_text(f) or ""
            if not re.search(r"@(?:Path|\w*Mapping)\b", text):
                continue
            info.endpoints.extend(_parse_endpoints(f, text.splitlines()))
            if len(info.endpoints) > 3000:
                info.warnings.append("Más de 3000 endpoints: lista truncada")
                break

    def _commands(self, sc, info, poms, kinds, detections) -> None:
        if not detections:
            return
        root = min(detections, key=lambda d: (d.root.count("/"), d.root)).root
        mvn = "./mvnw" if sc.exists(_join("" if root == "." else root, "mvnw")) else "mvn"
        rp = self.poms.get(_join("" if root == "." else root, "pom.xml"))
        multi = bool(rp and rp.modules)
        evid = [ev(rp.file)] if rp else []
        base = Fact(value="pom.xml", priority=P.BUILD, evidence=evid, adapter=NAME)

        def cmd(name, shell, ide=None, ok=None):
            info.add_command(Command(name=name, shell=shell, cwd=root, ide_hint=ide,
                                     success_hint=ok, fact=base))

        apps = [p for p in poms if kinds[p.file] in ("war", "ear", "spring-boot-app", "application")]
        main = apps[0] if len(apps) == 1 else None
        cmd("deps", f"{mvn} -DskipTests dependency:go-offline",
            "IntelliJ: Maven → Reload All Maven Projects",
            "BUILD SUCCESS; dependencias en ~/.m2/repository")
        if info.facts.get("maven.notable_plugins"):
            cmd("generate", f"{mvn} -DskipTests generate-sources",
                "IntelliJ: Maven → Generate Sources and Update Folders")
        art = self._artifact(main) if main else None
        cmd("build", f"{mvn} -DskipTests package",
            "IntelliJ: Maven → Lifecycle → package (con 'Skip Tests')",
            f"BUILD SUCCESS y existe {art}" if art else "BUILD SUCCESS")
        if multi and main and main.dir:
            cmd("build_app", f"{mvn} -pl {main.dir} -am -DskipTests package",
                f"IntelliJ: Maven → {main.artifact} → Lifecycle → package",
                f"existe {art}")
        cmd("test", f"{mvn} test", "IntelliJ: Maven → Lifecycle → test / clic derecho en "
                                   "src/test/java → Run All Tests", "Tests run: N, Failures: 0")
        if not main:
            return
        k = kinds[main.file]
        if k == "spring-boot-app":
            pl = f"-pl {main.dir} " if multi and main.dir else ""
            cmd("run", f"{mvn} {pl}spring-boot:run",
                "IntelliJ: Run sobre la clase @SpringBootApplication",
                "log 'Started ... in N seconds' y el puerto responde")
        elif k in ("war", "ear"):
            cmd("run", f'cp {art} "$CATALINA_HOME/webapps/ROOT.war" && '
                       f'"$CATALINA_HOME/bin/catalina.sh" run',
                f"IntelliJ: Run Configuration 'Tomcat Server → Local' (o Smart Tomcat) "
                f"desplegando {art} con contexto '/'",
                "Tomcat log 'Deployment of web application ... has finished' y "
                "http://localhost:8080/ responde")
        elif k == "application":
            cmd("run", f"java -jar {art}", "IntelliJ: Run sobre la clase con main()")


# --------------------------------------------------------------------------
# Endpoints (parser ligero, sin AST)
# --------------------------------------------------------------------------

def _statements(lines: list[str]):
    """Une anotaciones multilínea (paréntesis abiertos). Devuelve (línea, texto)."""
    i, n = 0, len(lines)
    while i < n:
        s, start = lines[i].strip(), i
        if s.startswith("@"):
            depth = s.count("(") - s.count(")")
            while depth > 0 and i + 1 < n:
                i += 1
                t = lines[i].strip()
                s += " " + t
                depth += t.count("(") - t.count(")")
        yield start + 1, s
        i += 1


def _literal(args: str | None) -> str | None:
    if not args:
        return None
    m = re.search(r'(?:value|path)\s*=\s*\{?\s*"([^"]*)"', args) or re.search(r'"([^"]*)"', args)
    if m:
        return m.group(1)
    inner = args.strip("() ")
    return "{" + inner + "}" if inner else None


def _url(*parts: str | None) -> str:
    segs = [s.strip("/") for s in parts if s and s.strip("/")]
    return "/" + "/".join(segs)


def _parse_endpoints(file: str, lines: list[str]) -> list[Endpoint]:
    out: list[Endpoint] = []
    cls, prefix = None, None
    pending: list[tuple[str, str | None]] = []
    in_comment = False
    for ln, s in _statements(lines):
        if in_comment:
            if "*/" in s:
                in_comment = False
            continue
        if s.startswith("/*"):
            in_comment = "*/" not in s
            continue
        if not s or s.startswith(("//", "*", "import ", "package ")):
            continue
        if s.startswith("@"):
            last = 0
            for m in _ANN_RX.finditer(s):
                if m.start() != last and s[last:m.start()].strip():
                    break
                pending.append((m.group(1).split(".")[-1], m.group(2)))
                last = m.end()
            s = s[last:].strip()
            if not s:
                continue
        if m := _CLASS_RX.search(s):
            if cls is None:
                cls = m.group(2)
                prefix = next((_literal(a) for n, a in pending if n in ("Path", "RequestMapping")),
                              None)
            pending = []
            continue
        if pending and not s.startswith(_NOT_METHOD) and (m := _METHOD_RX.match(s)):
            names = [n for n, _ in pending]
            verb, sub = None, None
            for n, a in pending:
                if n in HTTP_VERBS:
                    verb = n
                elif n in SPRING_MAPPINGS:
                    verb, sub = SPRING_MAPPINGS[n], _literal(a)
                elif n == "RequestMapping":
                    mm = re.search(r"RequestMethod\.(\w+)", a or "")
                    verb, sub = (mm.group(1) if mm else "ANY"), _literal(a)
            if verb and "Path" in names:
                sub = _literal(dict(pending)["Path"])
            if verb:
                out.append(Endpoint(verb, _url(prefix, sub), f"{cls}#{m.group(1)}", file, ln))
            pending = []
            continue
        if s.endswith((";", "}", "{")):
            pending = []
    return out
