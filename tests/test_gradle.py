"""Tests para adapters/gradle.py (Gradle, Android, Kotlin Spring)."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    ANDROID_APP, ANDROID_LIBRARY_ID_STYLE, ANDROID_MULTI, GRADLE_JAVA,
    GRADLE_JAVA_LEGACY_COMPAT, KOTLIN_SPRING, make_tree,
)
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.recon import recon
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["gradle"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_android_app_detected(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert any(s.adapter == "gradle" for s in info.stacks)

    def test_android_multi_detected(self, tmp_path):
        info = _info(tmp_path, ANDROID_MULTI)
        assert any(s.adapter == "gradle" for s in info.stacks)

    def test_kotlin_spring_detected(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        assert any(s.adapter == "gradle" for s in info.stacks)

    def test_gradle_java_detected(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        assert any(s.adapter == "gradle" for s in info.stacks)

    def test_empty_dir_not_detected(self, tmp_path):
        make_tree(tmp_path, {"README.md": "# hello"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["gradle"])
        assert not any(s.adapter == "gradle" for s in info.stacks)


# --------------------------------------------------------------------------
# Versión de Gradle (gradle-wrapper.properties)
# --------------------------------------------------------------------------

class TestGradleVersion:
    def test_gradle_version_from_wrapper(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "gradle" in info.requirements
        assert info.requirements["gradle"].value == "8.7"

    def test_gradle_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert info.requirements["gradle"].priority == SourcePriority.EXPLICIT

    def test_gradle_version_java(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        assert "gradle" in info.requirements
        assert info.requirements["gradle"].value == "7.6"


# --------------------------------------------------------------------------
# Versión de AGP y SDK Android
# --------------------------------------------------------------------------

class TestAndroidSDK:
    def test_agp_version_from_catalog(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        agp = info.facts.get("android.agp_version")
        assert agp is not None
        assert agp.value == "8.3.2"

    def test_compile_sdk(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert info.facts.get("android.compileSdk") is not None
        assert info.facts["android.compileSdk"].value == "34"

    def test_min_sdk(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert info.facts.get("android.minSdk") is not None
        assert info.facts["android.minSdk"].value == "24"

    def test_target_sdk(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert info.facts.get("android.targetSdk") is not None
        assert info.facts["android.targetSdk"].value == "34"

    def test_namespace(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        ns = info.facts.get("android.namespace")
        assert ns is not None
        assert ns.value == "com.example.myapp"


# --------------------------------------------------------------------------
# Tipo de módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_android_app_kind(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        kinds = [m.kind for m in info.modules]
        assert "android-app" in kinds

    def test_android_library_kind(self, tmp_path):
        info = _info(tmp_path, ANDROID_MULTI)
        kinds = [m.kind for m in info.modules]
        assert "android-library" in kinds

    def test_multi_module_count(self, tmp_path):
        info = _info(tmp_path, ANDROID_MULTI)
        assert len(info.modules) >= 2

    def test_java_app_kind(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        kinds = [m.kind for m in info.modules]
        assert any(k in ("app", "application") for k in kinds)

    def test_android_library_id_style_kind(self, tmp_path):
        # Bug: id("com.android.library") en Kotlin DSL sin version catalog
        info = _info(tmp_path, ANDROID_LIBRARY_ID_STYLE)
        kinds = [m.kind for m in info.modules]
        assert "android-library" in kinds

    def test_android_library_id_style_detected(self, tmp_path):
        info = _info(tmp_path, ANDROID_LIBRARY_ID_STYLE)
        assert any(s.adapter == "gradle" for s in info.stacks)


# --------------------------------------------------------------------------
# Requisito JDK
# --------------------------------------------------------------------------

class TestJDK:
    def test_jdk_from_jvm_target(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "jdk" in info.requirements
        assert info.requirements["jdk"].value == "17"

    def test_jdk_inferred_from_agp(self, tmp_path):
        # AGP 8.x → JDK >= 17 (HEURISTIC si no hay toolchain explícito)
        info = _info(tmp_path, ANDROID_APP)
        assert "jdk" in info.requirements
        assert int(info.requirements["jdk"].value) >= 17

    def test_jdk_from_toolchain(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        assert "jdk" in info.requirements
        assert info.requirements["jdk"].value == "21"

    def test_jdk_from_source_compat(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        assert "jdk" in info.requirements
        assert info.requirements["jdk"].value == "17"

    def test_jdk_from_legacy_version_1_8(self, tmp_path):
        """sourceCompatibility JavaVersion.VERSION_1_8 → jdk='8', no '1'."""
        info = _info(tmp_path, GRADLE_JAVA_LEGACY_COMPAT)
        assert "jdk" in info.requirements
        assert info.requirements["jdk"].value == "8"

    def test_jdk_legacy_not_version_1(self, tmp_path):
        """VERSION_1_8 no debe capturar solo el '1' del prefijo."""
        info = _info(tmp_path, GRADLE_JAVA_LEGACY_COMPAT)
        assert info.requirements["jdk"].value != "1"


# --------------------------------------------------------------------------
# NDK / C++ nativo
# --------------------------------------------------------------------------

class TestNDK:
    def test_ndk_fact_detected(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert info.facts.get("android.ndk") is not None

    def test_ndk_warning_present(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        # Avisa que hay código C++ nativo (necesita NDK instalado)
        assert any("ndk" in w.lower() or "nativo" in w.lower() or "native" in w.lower()
                   for w in info.warnings)


# --------------------------------------------------------------------------
# Endpoints Spring / Kotlin
# --------------------------------------------------------------------------

class TestSpringEndpoints:
    def test_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        assert len(info.endpoints) > 0

    def test_get_endpoint_path(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        paths = [ep.path for ep in info.endpoints]
        assert any("/api/products" in p for p in paths)

    def test_post_endpoint(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        endpoints = [(ep.method, ep.path) for ep in info.endpoints]
        assert any(m == "POST" for m, _ in endpoints)

    def test_delete_endpoint(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        methods = {ep.method for ep in info.endpoints}
        assert "DELETE" in methods

    def test_class_level_prefix_applied(self, tmp_path):
        # @RequestMapping("/api/products") en clase → prefijo en todos los endpoints
        info = _info(tmp_path, KOTLIN_SPRING)
        paths = [ep.path for ep in info.endpoints]
        assert all("/api/products" in p or p.startswith("/api") for p in paths)


# --------------------------------------------------------------------------
# Servicios de runtime
# --------------------------------------------------------------------------

class TestServices:
    def test_kafka_from_spring_deps(self, tmp_path):
        info = _info(tmp_path, KOTLIN_SPRING)
        kinds = [s.kind for s in info.services]
        assert "kafka" in kinds

    def test_no_services_for_android_basic(self, tmp_path):
        # ANDROID_APP solo tiene androidx y junit, sin servicios cloud
        info = _info(tmp_path, ANDROID_APP)
        assert len(info.services) == 0

    def test_no_crash_without_services(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        assert isinstance(info, ProjectInfo)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_android_build_command(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "build" in info.commands
        shell = info.commands["build"].shell
        assert "gradlew" in shell or "gradle" in shell

    def test_android_assemble_debug(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        shell = info.commands["build"].shell
        assert "assembleDebug" in shell or "assemble" in shell.lower() or "build" in shell

    def test_android_test_command(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "test" in info.commands
        assert "test" in info.commands["test"].shell.lower()

    def test_android_install_command(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "run" in info.commands
        assert "install" in info.commands["run"].shell.lower()

    def test_gradle_java_run_command(self, tmp_path):
        info = _info(tmp_path, GRADLE_JAVA)
        assert "run" in info.commands
        assert "gradlew" in info.commands["run"].shell or "gradle" in info.commands["run"].shell

    def test_has_deps_command(self, tmp_path):
        info = _info(tmp_path, ANDROID_APP)
        assert "deps" in info.commands


# --------------------------------------------------------------------------
# Integración con recon (round-trip project.json)
# --------------------------------------------------------------------------

class TestReconIntegration:
    def test_android_app_roundtrip(self, tmp_path):
        make_tree(tmp_path, ANDROID_APP)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert any(s.adapter == "gradle" for s in info.stacks)
        assert "jdk" in info.requirements

    def test_spring_kotlin_roundtrip(self, tmp_path):
        make_tree(tmp_path, KOTLIN_SPRING)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert len(info.endpoints) > 0

    def test_multi_module_no_crash(self, tmp_path):
        make_tree(tmp_path, ANDROID_MULTI)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert len(info.modules) >= 2
