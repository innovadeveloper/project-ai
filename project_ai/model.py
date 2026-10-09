"""
model.py — Modelo de datos de project-ai.

Define cómo se representa TODO lo que el sistema descubre de un proyecto.
Principio central: ningún dato es "verdad" sin evidencia. Cada hecho (Fact)
lleva de dónde salió (archivo:línea), con qué prioridad de fuente y en qué
estado está (inferido, verificado, por defecto...).

No tiene dependencias externas (solo stdlib, Python >= 3.11).
Lo usan: scanner, adapters, recon, doctor, runbook, triage y finalize.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# Enumeraciones
# --------------------------------------------------------------------------

class Status(str, Enum):
    """Estado de confianza de un hecho."""
    INFERRED = "inferred"   # deducido de archivos, no comprobado
    VERIFIED = "verified"   # comprobado ejecutando algo (lo marca finalize)
    DEFAULT = "default"     # no hay evidencia; valor por defecto razonable
    MISSING = "missing"     # se necesita pero no se pudo determinar
    CONFLICT = "conflict"   # dos fuentes de igual prioridad discrepan


class SourcePriority(IntEnum):
    """Prioridad de la fuente de un dato. Mayor número = más fiable.

    EXPLICIT: el proyecto lo declara para herramientas (.tool-versions,
              .sdkmanrc, mise.toml, wrappers de Maven/Gradle, toolchain{} de
              Gradle, CMakePresets.json).
    CI:       lo que se usa al construir/ejecutar en otro sitio: workflows de
              CI, Jenkinsfile, Dockerfile, docker-compose. Fiable pero puede
              estar desactualizado o ser solo de runtime.
    BUILD:    archivos de build (pom.xml, build.gradle, CMakeLists.txt...).
    HEURISTIC: deducción indirecta (p.ej. Spring Boot 3 => JDK >= 17).
    DEFAULT:  sin evidencia, valor por defecto.
    """
    DEFAULT = 0
    HEURISTIC = 1
    BUILD = 2
    CI = 3
    EXPLICIT = 4


# --------------------------------------------------------------------------
# Piezas básicas
# --------------------------------------------------------------------------

@dataclass
class Evidence:
    """De dónde sale un dato: archivo relativo a la raíz, línea y fragmento."""
    file: str
    line: int | None = None
    snippet: str | None = None

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{loc}  {self.snippet}" if self.snippet else loc


@dataclass
class Fact:
    """Un dato descubierto, con su evidencia y nivel de confianza.

    value      -> el valor (p.ej. "17" para el JDK)
    priority   -> SourcePriority de la fuente que lo aportó
    status     -> Status
    evidence   -> lista de Evidence (puede haber varias fuentes coincidentes)
    adapter    -> qué adaptador lo produjo (maven, gradle, cmake...)
    note       -> explicación corta para humanos y LLM
    """
    value: Any
    priority: SourcePriority = SourcePriority.HEURISTIC
    status: Status = Status.INFERRED
    evidence: list[Evidence] = field(default_factory=list)
    adapter: str | None = None
    note: str | None = None
    alternatives: list[dict] = field(default_factory=list)  # valores descartados

    @property
    def source(self) -> str:
        return str(self.evidence[0]) if self.evidence else "(sin evidencia)"


@dataclass
class Command:
    """Un comando que el usuario (o el agente) puede ejecutar."""
    name: str                     # build | test | run | deps | configure ...
    shell: str                    # comando exacto para la terminal
    cwd: str = "."                # relativo a la raíz del proyecto
    ide_hint: str | None = None   # equivalente en IntelliJ/Android Studio/VS Code
    success_hint: str | None = None  # cómo saber que funcionó
    fact: Fact | None = None      # de dónde salió el comando
    status: Status = Status.INFERRED


@dataclass
class Module:
    name: str
    path: str                     # relativo a la raíz
    build_system: str             # maven | gradle | cmake | conan ...
    kind: str | None = None       # library | application | android-app | test ...
    depends_on: list[str] = field(default_factory=list)


@dataclass
class EntryPoint:
    kind: str                     # spring-boot-app | main-function | android-activity ...
    symbol: str
    file: str
    line: int | None = None


@dataclass
class Endpoint:
    method: str                   # GET | POST | ...
    path: str
    handler: str                  # Clase#metodo
    file: str
    line: int | None = None


@dataclass
class Service:
    """Servicio externo que el proyecto necesita en runtime (DB, broker...)."""
    kind: str                     # postgresql | mysql | redis | kafka ...
    fact: Fact


@dataclass
class StackDetection:
    """Resultado de detect() de un adaptador."""
    adapter: str
    confidence: float             # 0..1
    root: str = "."               # subcarpeta donde vive ese stack
    evidence: list[Evidence] = field(default_factory=list)


# --------------------------------------------------------------------------
# Contenedor principal
# --------------------------------------------------------------------------

@dataclass
class ProjectInfo:
    """Todo lo que se sabe del proyecto. Se serializa a .project-ai/project.json."""
    root: str
    schema_version: int = SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    stacks: list[StackDetection] = field(default_factory=list)
    requirements: dict[str, Fact] = field(default_factory=dict)  # "jdk", "cmake", ...
    modules: list[Module] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    commands: dict[str, Command] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)        # otros datos sueltos
    warnings: list[str] = field(default_factory=list)

    # ---- fusión de requisitos -------------------------------------------

    def add_requirement(self, key: str, fact: Fact) -> Fact:
        """Añade un requisito resolviendo conflictos por prioridad de fuente.

        - Si no existía: se guarda.
        - Si la nueva fuente tiene MÁS prioridad: reemplaza; la anterior
          queda en `alternatives`.
        - Si tiene MENOS: se guarda como alternativa.
        - Si tiene IGUAL prioridad y valor distinto: estado CONFLICT y warning.
        - Si el valor coincide: se acumula la evidencia (más confianza).
        """
        current = self.requirements.get(key)
        if current is None:
            self.requirements[key] = fact
            return fact

        if _same_value(current.value, fact.value):
            current.evidence.extend(fact.evidence)
            if fact.priority > current.priority:
                current.priority = fact.priority
            return current

        if fact.priority > current.priority:
            fact.alternatives.append(_alt(current))
            fact.alternatives.extend(current.alternatives)
            self.requirements[key] = fact
            return fact

        if fact.priority < current.priority:
            current.alternatives.append(_alt(fact))
            return current

        # misma prioridad, distinto valor
        current.status = Status.CONFLICT
        current.alternatives.append(_alt(fact))
        self.warnings.append(
            f"Conflicto en '{key}': {current.value!r} ({current.source}) "
            f"vs {fact.value!r} ({fact.source})"
        )
        return current

    def add_service(self, kind: str, fact: Fact) -> Service:
        """Añade un servicio de runtime (DB, broker...). Si ya existe ese tipo,
        acumula evidencia y guarda versiones distintas como alternativas."""
        for s in self.services:
            if s.kind == kind:
                cur = s.fact
                if _same_value(cur.value, fact.value) or fact.value == "*":
                    cur.evidence.extend(fact.evidence)
                elif cur.value == "*" or fact.priority > cur.priority:
                    fact.alternatives.append(_alt(cur))
                    fact.evidence.extend(cur.evidence)
                    s.fact = fact
                else:
                    cur.alternatives.append(_alt(fact))
                return s
        s = Service(kind=kind, fact=fact)
        self.services.append(s)
        return s

    def add_list_fact(self, key: str, item: Any, *, priority: SourcePriority,
                      evidence: Evidence | None = None, adapter: str | None = None,
                      note: str | None = None, limit: int = 200) -> None:
        """Añade un elemento a un hecho tipo lista (p.ej. 'hints.commands').
        Evita duplicados exactos y limita el tamaño."""
        f = self.facts.get(key)
        if f is None:
            f = Fact(value=[], priority=priority, adapter=adapter, note=note)
            self.facts[key] = f
        if item in f.value or len(f.value) >= limit:
            return
        f.value.append(item)
        if evidence is not None and len(f.evidence) < limit:
            f.evidence.append(evidence)
        if priority > f.priority:
            f.priority = priority

    def set_fact(self, key: str, fact: Fact) -> Fact:
        """Hecho escalar fuera de requirements; gana el de más prioridad."""
        cur = self.facts.get(key)
        if cur is None or fact.priority > cur.priority:
            if cur is not None:
                fact.alternatives.append(_alt(cur))
            self.facts[key] = fact
            return fact
        if _same_value(cur.value, fact.value):
            cur.evidence.extend(fact.evidence)
        else:
            cur.alternatives.append(_alt(fact))
        return cur

    def add_stack(self, det: StackDetection) -> None:
        for s in self.stacks:
            if s.adapter == det.adapter and s.root == det.root:
                s.confidence = max(s.confidence, det.confidence)
                s.evidence.extend(det.evidence)
                return
        self.stacks.append(det)

    def add_command(self, cmd: Command, overwrite: bool = False) -> None:
        if overwrite or cmd.name not in self.commands:
            self.commands[cmd.name] = cmd

    def stack_names(self) -> list[str]:
        return [s.adapter for s in sorted(self.stacks, key=lambda s: -s.confidence)]

    # ---- serialización --------------------------------------------------

    def to_dict(self) -> dict:
        return _to_jsonable(asdict(self))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "ProjectInfo":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectInfo":
        return cls(
            root=d["root"],
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            generated_at=d.get("generated_at", ""),
            stacks=[_stack_from(x) for x in d.get("stacks", [])],
            requirements={k: _fact_from(v) for k, v in d.get("requirements", {}).items()},
            modules=[Module(**x) for x in d.get("modules", [])],
            entry_points=[EntryPoint(**x) for x in d.get("entry_points", [])],
            endpoints=[Endpoint(**x) for x in d.get("endpoints", [])],
            services=[Service(kind=x["kind"], fact=_fact_from(x["fact"]))
                      for x in d.get("services", [])],
            commands={k: _command_from(v) for k, v in d.get("commands", {}).items()},
            facts={k: _fact_from(v) for k, v in d.get("facts", {}).items()},
            warnings=list(d.get("warnings", [])),
        )


# --------------------------------------------------------------------------
# Helpers internos
# --------------------------------------------------------------------------

def _same_value(a: Any, b: Any) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _alt(f: Fact) -> dict:
    return {"value": f.value, "priority": f.priority.name, "source": f.source}


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, IntEnum):
        return obj.name           # "BUILD" en vez de 2: más legible en el JSON
    if isinstance(obj, Enum):
        return obj.value
    return obj


def _fact_from(d: dict | None) -> Fact | None:
    if d is None:
        return None
    return Fact(
        value=d.get("value"),
        priority=SourcePriority[d.get("priority", "HEURISTIC")],
        status=Status(d.get("status", "inferred")),
        evidence=[Evidence(**e) for e in d.get("evidence", [])],
        adapter=d.get("adapter"),
        note=d.get("note"),
        alternatives=list(d.get("alternatives", [])),
    )


def _command_from(d: dict) -> Command:
    return Command(
        name=d["name"], shell=d["shell"], cwd=d.get("cwd", "."),
        ide_hint=d.get("ide_hint"), success_hint=d.get("success_hint"),
        fact=_fact_from(d.get("fact")), status=Status(d.get("status", "inferred")),
    )


def _stack_from(d: dict) -> StackDetection:
    return StackDetection(
        adapter=d["adapter"], confidence=d["confidence"], root=d.get("root", "."),
        evidence=[Evidence(**e) for e in d.get("evidence", [])],
    )
