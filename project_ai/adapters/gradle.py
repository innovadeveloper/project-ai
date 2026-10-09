"""
adapters/gradle.py — Proyectos Gradle (Android, Spring Boot/Kotlin, Java puro).

Qué descubre (todo con evidencia archivo:línea):
  Gradle         gradle-wrapper.properties → versión exacta (EXPLICIT).
  AGP            libs.versions.toml [versions].agp o classpath en build.gradle → BUILD/EXPLICIT.
  JDK            java { toolchain { languageVersion = JavaLanguageVersion.of(N) } } (EXPLICIT);
                 sourceCompatibility/jvmTarget → BUILD;
                 inferido de AGP si nada más → HEURISTIC.
  Android        compileSdk, minSdk, targetSdk, namespace, applicationId → BUILD.
  NDK            externalNativeBuild { cmake/ndkBuild } → fact + aviso.
  Módulos        settings.gradle(.kts) include(":app", ":core") → módulos; kind por plugin.
  Servicios      spring-kafka, spring-data-redis, spring-data-mongodb, firebase → kind.
  Endpoints      @GetMapping/@PostMapping/… en .kt/.java con @RequestMapping de clase.
  Comandos       ./gradlew assembleDebug/test/installDebug (Android);
                 ./gradlew build/test/run (Java/Spring).

Prioridades:
  gradle-wrapper.properties  → EXPLICIT
  libs.versions.toml         → EXPLICIT
  build.gradle(.kts)         → BUILD
  Inferencia AGP→JDK         → HEURISTIC

DSL soportado: Kotlin DSL (.gradle.kts) y Groovy DSL (.gradle).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..model import (Command, Endpoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register, req

NAME = "gradle"

# --------------------------------------------------------------------------
# Patrones
# --------------------------------------------------------------------------

_RX_GRADLE_VER = re.compile(
    r'gradle-(\d+\.\d+(?:\.\d+)?)-(?:bin|all)\.zip'
)

# settings: include(":app") include ':app', ':core'
_RX_INCLUDE = re.compile(r'''["'](:\w[\w/.-]*)["']''')

# Plugin declaration: id("...") id '...' apply plugin: '...'
_RX_PLUGIN_ID = re.compile(
    r'''(?:id\s*\(?\s*["']\s*|apply\s+plugin\s*:\s*["'])([\w.-]+)["')\s]'''
)
# kotlin("jvm") kotlin("android")
_RX_KOTLIN_PLUGIN = re.compile(r'''kotlin\s*\(\s*["']([\w.]+)["']\s*\)''')
# AGP version inline: id("com.android.application") version "8.x"
_RX_AGP_INLINE_VER = re.compile(
    r'com\.android\.(?:application|library)["\)]\s+version\s+["\']([\d.]+)["\']'
)
# AGP classpath (old style): 'com.android.tools.build:gradle:7.4.2'
_RX_AGP_CLASSPATH = re.compile(r'com\.android\.tools\.build:gradle:([\d.]+)')

# Android block fields (Groovy: no =; Kotlin DSL: with =)
_RX_COMPILE_SDK  = re.compile(r'compileSdk(?:Version)?\s*[=()\s]+(\d{2})')
_RX_MIN_SDK      = re.compile(r'minSdk(?:Version)?\s*[=()\s]+(\d+)')
_RX_TARGET_SDK   = re.compile(r'targetSdk(?:Version)?\s*[=()\s]+(\d{2})')
_RX_NAMESPACE    = re.compile(r'''namespace\s*[=\s]+["']([^"']+)["']''')
_RX_APP_ID       = re.compile(r'''applicationId\s*[=\s]+["']([^"']+)["']''')

# JDK: toolchain (Kotlin DSL)
_RX_TOOLCHAIN_JDK = re.compile(
    r'JavaLanguageVersion\.of\s*\(\s*(\d+)'
)
# jvmToolchain(N) shorthand
_RX_JVM_TOOLCHAIN = re.compile(r'jvmToolchain\s*\(\s*(\d+)')
# sourceCompatibility = JavaVersion.VERSION_17 / "17" / 17
_RX_SOURCE_COMPAT = re.compile(
    r'sourceCompatibility\s*[=\s]+(?:JavaVersion\.VERSION_(\d+)|"(\d+)"|\'(\d+)\'|(\d+))'
)
# kotlinOptions { jvmTarget = "17" }
_RX_JVM_TARGET = re.compile(r'''jvmTarget\s*=\s*["'](\d+)["']''')

# NDK
_RX_NDK = re.compile(r'externalNativeBuild\s*\{|ndkVersion\s*[=\s]', re.IGNORECASE)

# Spring/Kotlin HTTP endpoint annotations
_RX_HTTP_ANNOT = re.compile(
    r'@(Get|Post|Put|Delete|Patch)Mapping\s*(?:\(\s*(?:value\s*=\s*)?["[]\s*"([^"]*)")?',
    re.IGNORECASE,
)
_RX_CLASS_REQ_MAP = re.compile(
    r'@RequestMapping\s*\([^)]*?"([^"]+)"',
    re.IGNORECASE,
)
_RX_FUN_NAME = re.compile(
    r'(?:fun|public\s+\w+\s+|private\s+\w+\s+)\s*(\w+)\s*[(<]'
)

# Dependencias → servicios
_DEP_SERVICES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'spring-kafka|kafka-clients', re.I), 'kafka'),
    (re.compile(r'spring-data-redis|lettuce-core|jedis\b', re.I), 'redis'),
    (re.compile(r'spring-data-mongodb|mongodb-driver', re.I), 'mongodb'),
    (re.compile(r'firebase-firestore|firebase-database|firebase-auth|firebase-bom', re.I), 'firebase'),
    (re.compile(r'spring-data-jpa|hibernate-core', re.I), 'database'),
    (re.compile(r'postgresql|mysql-connector', re.I), 'postgresql'),
]

# AGP version → JDK mínimo (tabla explícita; fuente: developer.android.com/build/releases/gradle-plugin)
_AGP_JDK_MATRIX = [
    ((8, 0), "17"),
    ((7, 4), "11"),
    ((7, 0), "11"),
    ((4, 2), "8"),
    ((4, 0), "8"),
    ((3, 0), "8"),
]


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class GradleAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        sig = next(
            (f for f in sc.files if Path(f).name in {
                "build.gradle", "build.gradle.kts",
                "settings.gradle", "settings.gradle.kts",
            }),
            None,
        )
        if not sig:
            return []
        return [StackDetection(
            adapter=NAME, confidence=0.9,
            evidence=[ev(sig, None, "build.gradle/.kts encontrado")],
        )]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)

        # 1. Gradle wrapper → versión EXPLICIT
        _parse_gradle_wrapper(root, sc.files, info)

        # 2. libs.versions.toml → versiones (AGP, Kotlin)
        catalog = _parse_version_catalog(root, sc.files, info)

        # 3. settings → lista de módulos
        module_dirs = _parse_settings(root, sc.files)

        # 4. Procesar cada módulo
        is_android = False
        for mod_dir in module_dirs:
            kind = _process_module(root, mod_dir, info, catalog)
            if kind in ("android-app", "android-library"):
                is_android = True

        # 5. Si no hay módulos, procesar raíz
        if not module_dirs:
            kind = _process_module(root, ".", info, catalog)
            if kind in ("android-app", "android-library"):
                is_android = True

        # 6. JDK: inferir de AGP si no hay evidencia directa
        _infer_jdk_from_agp(info, catalog)

        # 7. Endpoints Spring/Kotlin
        _find_spring_endpoints(root, sc.files, info)

        # 8. Comandos
        _add_commands(info, is_android)


# --------------------------------------------------------------------------
# Gradle wrapper
# --------------------------------------------------------------------------

def _parse_gradle_wrapper(root: Path, files: list[str], info: ProjectInfo) -> None:
    wrapper = next(
        (f for f in files if f.endswith("gradle-wrapper.properties")), None
    )
    if not wrapper:
        return
    try:
        text = (root / wrapper).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    m = _RX_GRADLE_VER.search(text)
    if m:
        req(info, "gradle", m.group(1), P.EXPLICIT,
            wrapper, None, f"distributionUrl gradle-{m.group(1)}",
            adapter=NAME)


# --------------------------------------------------------------------------
# libs.versions.toml (Version Catalog)
# --------------------------------------------------------------------------

def _parse_version_catalog(root: Path, files: list[str],
                            info: ProjectInfo) -> dict[str, str]:
    """Devuelve dict name→version. Registra AGP si está en [versions]."""
    catalog_file = next(
        (f for f in files if f.endswith("libs.versions.toml")), None
    )
    if not catalog_file:
        return {}
    try:
        text = (root / catalog_file).read_text(encoding="utf-8")
        data = tomllib.loads(text)
    except Exception:
        return {}

    versions: dict[str, str] = {
        k: str(v) for k, v in data.get("versions", {}).items()
    }

    # Registrar AGP
    agp_ver = versions.get("agp", "")
    if agp_ver:
        info.set_fact("android.agp_version", Fact(
            value=agp_ver, priority=P.EXPLICIT,
            evidence=[ev(catalog_file, None, f"agp = \"{agp_ver}\"")],
            adapter=NAME,
        ))

    return versions


# --------------------------------------------------------------------------
# settings.gradle(.kts)
# --------------------------------------------------------------------------

def _parse_settings(root: Path, files: list[str]) -> list[str]:
    """Extrae rutas de módulos desde settings.gradle(.kts). Devuelve dirs relativos."""
    settings = next(
        (f for f in files if Path(f).name in {
            "settings.gradle", "settings.gradle.kts"
        }),
        None,
    )
    if not settings:
        return []
    try:
        text = (root / settings).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    dirs = []
    for m in _RX_INCLUDE.finditer(text):
        mod_id = m.group(1)
        # ':app' → 'app';  ':feature:login' → 'feature/login'
        mod_dir = mod_id.lstrip(":").replace(":", "/")
        dirs.append(mod_dir)
    return dirs


# --------------------------------------------------------------------------
# Procesado de un módulo
# --------------------------------------------------------------------------

def _process_module(root: Path, mod_dir: str, info: ProjectInfo,
                    catalog: dict[str, str]) -> str:
    """Parsea build.gradle(.kts) en mod_dir. Devuelve el kind del módulo."""
    # Buscar build.gradle.kts o build.gradle
    build_file: Path | None = None
    for name in ("build.gradle.kts", "build.gradle"):
        candidate = root / mod_dir / name if mod_dir != "." else root / name
        if candidate.exists():
            build_file = candidate
            break
    if build_file is None:
        return "library"

    rel = str(build_file.relative_to(root))
    try:
        text = build_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "library"

    plugins = _get_plugins(text)
    kind = _kind_from_plugins(plugins)

    # Android SDK facts (solo del módulo app principal)
    is_android = kind in ("android-app", "android-library")
    if is_android:
        _extract_android_facts(text, rel, info)

    # JDK directo
    _extract_jdk(text, rel, info)

    # AGP desde classpath (antiguo)
    m_agp = _RX_AGP_CLASSPATH.search(text)
    if m_agp and "android.agp_version" not in info.facts:
        info.set_fact("android.agp_version", Fact(
            value=m_agp.group(1), priority=P.BUILD,
            evidence=[ev(rel, None, f"com.android.tools.build:gradle:{m_agp.group(1)}")],
            adapter=NAME,
        ))
    # AGP inline version
    m_agp_inline = _RX_AGP_INLINE_VER.search(text)
    if m_agp_inline and "android.agp_version" not in info.facts:
        info.set_fact("android.agp_version", Fact(
            value=m_agp_inline.group(1), priority=P.BUILD,
            evidence=[ev(rel, None, m_agp_inline.group(0)[:80])],
            adapter=NAME,
        ))

    # NDK
    if _RX_NDK.search(text):
        info.set_fact("android.ndk", Fact(
            value="true", priority=P.BUILD,
            evidence=[ev(rel, None, "externalNativeBuild")],
            adapter=NAME,
        ))
        info.warnings.append(
            f"{rel}: proyecto con código C++ nativo (NDK). "
            "Necesitas Android NDK instalado y compile_commands.json para clangd."
        )

    # Servicios de runtime
    for line in text.splitlines():
        for rx, svc_kind in _DEP_SERVICES:
            if rx.search(line):
                add_service(info, svc_kind, None, P.BUILD,
                            rel, None, line.strip()[:80], adapter=NAME)
                break

    # Módulo
    name = Path(mod_dir).name if mod_dir != "." else root.name
    info.modules.append(Module(
        name=name, path=mod_dir, build_system=NAME, kind=kind,
    ))
    return kind


# Mapeo de alias de libs.versions.toml a plugin IDs canónicos
_ALIAS_TO_PLUGIN: dict[str, str] = {
    "android.application":      "com.android.application",
    "android.library":          "com.android.library",
    "android.test":             "com.android.test",
    "android.dynamic.feature":  "com.android.dynamic-feature",
    "kotlin.android":           "org.jetbrains.kotlin.android",
    "kotlin.jvm":               "org.jetbrains.kotlin.jvm",
    "kotlin.multiplatform":     "org.jetbrains.kotlin.multiplatform",
}


def _get_plugins(text: str) -> set[str]:
    plugins: set[str] = set()
    for m in _RX_PLUGIN_ID.finditer(text):
        plugins.add(m.group(1))
    for m in _RX_KOTLIN_PLUGIN.finditer(text):
        plugins.add(f"kotlin-{m.group(1)}")
    # alias(libs.plugins.android.application) — Kotlin DSL con version catalog
    for m in re.finditer(r'alias\s*\(\s*libs\.plugins\.([\w.]+)\s*\)', text):
        alias = m.group(1)
        plugins.add(_ALIAS_TO_PLUGIN.get(alias, alias))
    return plugins


def _kind_from_plugins(plugins: set[str]) -> str:
    for p in plugins:
        if "com.android.application" in p:
            return "android-app"
        if "com.android.library" in p or "com.android.test" in p:
            return "android-library"
    if "application" in plugins or any("application" in p for p in plugins):
        return "app"
    if "java-library" in plugins:
        return "library"
    if any("spring" in p for p in plugins):
        return "app"
    return "library"


# --------------------------------------------------------------------------
# Hechos del bloque android {}
# --------------------------------------------------------------------------

def _extract_android_facts(text: str, rel: str, info: ProjectInfo) -> None:
    for rx, key in [
        (_RX_COMPILE_SDK, "android.compileSdk"),
        (_RX_MIN_SDK,     "android.minSdk"),
        (_RX_TARGET_SDK,  "android.targetSdk"),
    ]:
        m = rx.search(text)
        if m:
            info.set_fact(key, Fact(
                value=m.group(1), priority=P.BUILD,
                evidence=[ev(rel, None, m.group(0)[:60])],
                adapter=NAME,
            ))
    for rx, key in [
        (_RX_NAMESPACE, "android.namespace"),
        (_RX_APP_ID,    "android.applicationId"),
    ]:
        m = rx.search(text)
        if m:
            info.set_fact(key, Fact(
                value=m.group(1), priority=P.BUILD,
                evidence=[ev(rel, None, m.group(0)[:80])],
                adapter=NAME,
            ))


# --------------------------------------------------------------------------
# JDK directo desde build file
# --------------------------------------------------------------------------

def _extract_jdk(text: str, rel: str, info: ProjectInfo) -> None:
    # toolchain { languageVersion = JavaLanguageVersion.of(N) }  → EXPLICIT
    m = _RX_TOOLCHAIN_JDK.search(text) or _RX_JVM_TOOLCHAIN.search(text)
    if m:
        req(info, "jdk", m.group(1), P.EXPLICIT, rel, None,
            m.group(0)[:60], adapter=NAME)
        return

    # sourceCompatibility = JavaVersion.VERSION_17 → BUILD
    m = _RX_SOURCE_COMPAT.search(text)
    if m:
        ver = next(g for g in m.groups() if g)
        req(info, "jdk", ver, P.BUILD, rel, None, m.group(0)[:60], adapter=NAME)
        return

    # jvmTarget = "17"  → BUILD
    m = _RX_JVM_TARGET.search(text)
    if m:
        req(info, "jdk", m.group(1), P.BUILD, rel, None,
            m.group(0)[:60], adapter=NAME)


# --------------------------------------------------------------------------
# Inferencia JDK desde AGP (HEURISTIC si no hay evidencia directa)
# --------------------------------------------------------------------------

def _infer_jdk_from_agp(info: ProjectInfo, catalog: dict[str, str]) -> None:
    if "jdk" in info.requirements:
        return
    agp_fact = info.facts.get("android.agp_version")
    agp_ver = agp_fact.value if agp_fact else catalog.get("agp", "")
    if not agp_ver:
        return
    jdk = _agp_min_jdk(agp_ver)
    if jdk:
        req(info, "jdk", jdk, P.HEURISTIC, None, None,
            f"AGP {agp_ver} requiere JDK >= {jdk}", adapter=NAME)


def _agp_min_jdk(agp_ver: str) -> str | None:
    m = re.match(r"(\d+)\.(\d+)", agp_ver)
    if not m:
        return None
    ver = (int(m.group(1)), int(m.group(2)))
    for threshold, jdk in _AGP_JDK_MATRIX:
        if ver >= threshold:
            return jdk
    return None


# --------------------------------------------------------------------------
# Endpoints Spring / Kotlin
# --------------------------------------------------------------------------

def _find_spring_endpoints(root: Path, files: list[str], info: ProjectInfo) -> None:
    for rel in files:
        if not rel.endswith((".kt", ".java")):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _RX_HTTP_ANNOT.search(text):
            continue
        _parse_spring_file(text, rel, info)


def _parse_spring_file(text: str, rel: str, info: ProjectInfo) -> None:
    lines = text.splitlines()

    # Clase con @RequestMapping → prefijo
    class_prefix = ""
    m_cls = _RX_CLASS_REQ_MAP.search(text)
    if m_cls:
        class_prefix = m_cls.group(1).rstrip("/")

    pending_method: str | None = None
    pending_sub: str = ""
    for i, ln in enumerate(lines, start=1):
        ln_s = ln.strip()
        m_annot = _RX_HTTP_ANNOT.match(ln_s)
        if m_annot:
            pending_method = m_annot.group(1).upper()
            pending_sub = m_annot.group(2) or ""
            continue
        if pending_method:
            if ln_s.startswith("@"):
                continue
            m_fn = _RX_FUN_NAME.search(ln_s)
            if m_fn:
                fn_name = m_fn.group(1)
                if pending_sub.startswith("/"):
                    full_path = class_prefix + pending_sub
                else:
                    full_path = class_prefix + ("/" if pending_sub else "") + pending_sub
                if not full_path:
                    full_path = class_prefix or "/"
                info.endpoints.append(Endpoint(
                    method=pending_method,
                    path=full_path,
                    handler=f"{Path(rel).stem}#{fn_name}",
                    file=rel, line=i,
                ))
            pending_method = None
            pending_sub = ""


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def _add_commands(info: ProjectInfo, is_android: bool) -> None:
    gradlew = "./gradlew"

    info.add_command(Command(
        name="deps",
        shell=f"{gradlew} dependencies",
        ide_hint="Android Studio / IntelliJ: Gradle → Reload All Gradle Projects",
        success_hint="BUILD SUCCESSFUL",
    ))

    if is_android:
        info.add_command(Command(
            name="build",
            shell=f"{gradlew} assembleDebug",
            ide_hint="Android Studio: Build → Make Project",
            success_hint="BUILD SUCCESSFUL",
        ))
        info.add_command(Command(
            name="test",
            shell=f"{gradlew} test",
            success_hint="BUILD SUCCESSFUL",
        ))
        info.add_command(Command(
            name="run",
            shell=f"{gradlew} installDebug",
            ide_hint="Android Studio: Run → Run 'app'",
            success_hint="Installed on device",
        ))
    else:
        info.add_command(Command(
            name="build",
            shell=f"{gradlew} build",
            ide_hint="IntelliJ: Gradle → build",
            success_hint="BUILD SUCCESSFUL",
        ))
        info.add_command(Command(
            name="test",
            shell=f"{gradlew} test",
            success_hint="BUILD SUCCESSFUL",
        ))
        info.add_command(Command(
            name="run",
            shell=f"{gradlew} run",
            success_hint="BUILD SUCCESSFUL",
        ))
