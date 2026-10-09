"""
adapters/base.py — Contrato común de los adaptadores y utilidades compartidas.

Un ADAPTADOR sabe leer un tipo de proyecto (maven, gradle, cmake, conan...) o
un tipo de señal transversal (hints: CI, Docker, docs). Todos cumplen:

    detect(sc)                  -> list[StackDetection]
        ¿Está este stack en el proyecto? ¿Dónde? ¿Con qué confianza?
        Puede devolver varias detecciones (monorepo: varias raíces).
        Debe ser BARATO: mirar nombres de archivo, leer poco.

    analyze(sc, info, dets)     -> None
        Lee a fondo y vuelca hechos en `info` (ProjectInfo): requisitos,
        módulos, entry points, endpoints, servicios, comandos, hints.
        Nunca ejecuta nada ni modifica el proyecto.

Para añadir un stack nuevo (Python, C#...): crear adapters/<nombre>.py con
una clase decorada con @register e importarla en adapters/__init__.py.
El núcleo no cambia.

run_adapters() ejecuta todos los registrados. Si uno falla, se anota un
warning y se sigue: un adaptador roto no debe tumbar el reconocimiento.
"""

from __future__ import annotations

import re
import traceback
from abc import ABC, abstractmethod
from typing import ClassVar, Iterable

from ..model import (Evidence, Fact, ProjectInfo, SourcePriority,
                     StackDetection, Status)
from ..scanner import ProjectScanner

# --------------------------------------------------------------------------
# Claves estándar de requisitos (lo que doctor sabrá comprobar en tu máquina)
# --------------------------------------------------------------------------
REQUIREMENT_KEYS = {
    "jdk":            "JDK para compilar",
    "jdk_runtime":    "JDK/JRE con el que se ejecuta (si difiere del de build)",
    "maven":          "Apache Maven",
    "gradle":         "Gradle",
    "kotlin":         "Kotlin",
    "android_agp":    "Android Gradle Plugin",
    "android_compile_sdk": "compileSdk de Android",
    "tomcat":         "Apache Tomcat (servlet container)",
    "cmake":          "CMake (mínimo)",
    "conan":          "Conan (1.x o 2.x)",
    "ninja":          "Ninja",
    "gcc":            "GCC",
    "clang":          "Clang",
    "cxx_standard":   "Estándar de C++",
    "python":         "Python",
    "node":           "Node.js",
    "dotnet":         ".NET SDK",
    "go":             "Go",
}

# Nombre de herramienta (asdf/mise/sdkman/CI) -> clave de requisito
TOOL_ALIASES = {
    "java": "jdk", "jdk": "jdk", "openjdk": "jdk", "temurin": "jdk",
    "adoptopenjdk": "jdk", "corretto": "jdk", "zulu": "jdk", "graalvm": "jdk",
    "maven": "maven", "mvn": "maven", "gradle": "gradle", "kotlin": "kotlin",
    "cmake": "cmake", "conan": "conan", "ninja": "ninja",
    "gcc": "gcc", "clang": "clang", "llvm": "clang",
    "python": "python", "nodejs": "node", "node": "node",
    "dotnet": "dotnet", "dotnet-core": "dotnet", "golang": "go", "go": "go",
    "tomcat": "tomcat",
}

_NO_VERSION = {"latest", "lts", "system", "stable", "current", "*", "default"}

# Comandos de build/run reconocibles (para filtrar líneas de CI, Docker, docs)
BUILD_TOOL_RX = re.compile(
    r"(?:^|[\s;&|(])(?:\./)?(?:mvnw?|gradlew?|cmake|ctest|conan|make|ninja|meson|"
    r"npm|npx|yarn|pnpm|pip3?|poetry|dotnet|docker(?:-compose)?|java|"
    r"catalina\.sh|ant|bazel|cargo|go)(?=\s|$)")


# --------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------

class Adapter(ABC):
    name: ClassVar[str] = "base"
    always_run: ClassVar[bool] = False   # True para señales transversales

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        return []

    @abstractmethod
    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None: ...


REGISTRY: dict[str, type[Adapter]] = {}


def register(cls: type[Adapter]) -> type[Adapter]:
    if cls.name in REGISTRY:
        raise ValueError(f"Adaptador duplicado: {cls.name}")
    REGISTRY[cls.name] = cls
    return cls


def all_adapters(only: Iterable[str] | None = None) -> list[Adapter]:
    names = list(only) if only else list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"Adaptadores desconocidos: {unknown}. "
                       f"Disponibles: {sorted(REGISTRY)}")
    return [REGISTRY[n]() for n in names]


def run_adapters(sc: ProjectScanner, info: ProjectInfo | None = None, *,
                 only: Iterable[str] | None = None,
                 debug: bool = False) -> ProjectInfo:
    info = info or ProjectInfo(root=str(sc.root))
    for ad in all_adapters(only):
        try:
            dets = ad.detect(sc)
            for d in dets:
                info.add_stack(d)
            if dets or ad.always_run:
                ad.analyze(sc, info, dets)
        except Exception as e:  # noqa: BLE001 - un adaptador no tumba el resto
            msg = f"Adaptador '{ad.name}' falló: {e!r}"
            if debug:
                msg += "\n" + traceback.format_exc()
            info.warnings.append(msg)
    return info


# --------------------------------------------------------------------------
# Helpers para escribir adaptadores
# --------------------------------------------------------------------------

def ev(file: str, line: int | None = None, snippet: str | None = None) -> Evidence:
    if snippet is not None:
        snippet = " ".join(snippet.split())[:160]
    return Evidence(file=file, line=line, snippet=snippet)


def first_match(sc: ProjectScanner, file: str, pattern: str | re.Pattern,
                flags: int = 0) -> tuple[int, re.Match] | None:
    rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    for i, line in enumerate(sc.read_lines(file), start=1):
        m = rx.search(line)
        if m:
            return i, m
    return None


def all_matches(sc: ProjectScanner, file: str, pattern: str | re.Pattern,
                flags: int = 0) -> list[tuple[int, re.Match]]:
    rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    out = []
    for i, line in enumerate(sc.read_lines(file), start=1):
        for m in rx.finditer(line):
            out.append((i, m))
    return out


def normalize_tool(name: str) -> str | None:
    n = name.strip().lower()
    if n in TOOL_ALIASES:
        return TOOL_ALIASES[n]
    for alias, key in TOOL_ALIASES.items():   # "java-temurin", "openjdk17"...
        if len(alias) >= 4 and n.startswith(alias):
            return key
    return None


def jdk_major(raw: str) -> str | None:
    """'1.8.0_292'->'8', '17.0.12-tem'->'17', 'temurin-21.0.1+12'->'21',
    '8u342-b07'->'8', 'jdk17'->'17', 'zulu-11'->'11'."""
    m = re.search(r"(\d+)(?:\.(\d+))?", raw)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        return m.group(2)
    return str(major) if 5 <= major <= 40 else None


def normalize_version(key: str, raw: object) -> str | None:
    """Versión limpia o None si no aporta información (latest, ${VAR}...)."""
    if raw is None:
        return None
    s = str(raw).strip().strip("'\"")
    if (not s or s.lower() in _NO_VERSION
            or "${" in s or "$(" in s or "{{" in s or s.startswith("$")):
        return None
    if key in ("jdk", "jdk_runtime"):
        return jdk_major(s)
    m = re.search(r"\d+(?:\.\d+)*", s)
    return m.group(0) if m else None


def req(info: ProjectInfo, key: str, raw_value: object, priority: SourcePriority,
        file: str | None = None, line: int | None = None,
        snippet: str | None = None, *, adapter: str, note: str | None = None,
        status: Status = Status.INFERRED) -> Fact | None:
    """Registra un requisito de versión normalizando el valor."""
    v = normalize_version(key, raw_value)
    if v is None:
        return None
    fact = Fact(value=v, priority=priority, status=status,
                evidence=[ev(file, line, snippet)] if file else [],
                adapter=adapter, note=note)
    return info.add_requirement(key, fact)


def add_cmd_hint(info: ProjectInfo, cmd: str, *, origin: str,
                 priority: SourcePriority, file: str, line: int | None,
                 adapter: str) -> None:
    """Comando visto en CI/Docker/docs/IDE. El runbook los usará como pistas."""
    cmd = " ".join(cmd.split())
    if not cmd or len(cmd) > 400:
        return
    info.add_list_fact(
        "hints.commands",
        {"cmd": cmd, "origin": origin, "priority": priority.name,
         "source": f"{file}:{line}" if line else file},
        priority=priority, adapter=adapter,
        note="Comandos encontrados fuera de los archivos de build")


def add_service(info: ProjectInfo, kind: str, version: str | None,
                priority: SourcePriority, file: str, line: int | None,
                snippet: str | None, *, adapter: str, note: str | None = None) -> None:
    v = normalize_version(kind, version) if version else None
    info.add_service(kind, Fact(value=v or "*", priority=priority,
                                evidence=[ev(file, line, snippet)],
                                adapter=adapter, note=note))
