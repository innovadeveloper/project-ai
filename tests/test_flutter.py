"""Tests para adapters/flutter.py (Flutter apps, plugins y paquetes Dart)."""
from __future__ import annotations

from pathlib import Path

from conftest import DART_PACKAGE, FLUTTER_APP, FLUTTER_MONOREPO, FLUTTER_PLUGIN, make_tree
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.recon import recon
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["flutter"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_flutter_app_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert any(s.adapter == "flutter" for s in info.stacks)

    def test_flutter_plugin_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        assert any(s.adapter == "flutter" for s in info.stacks)

    def test_dart_package_detected(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert any(s.adapter == "flutter" for s in info.stacks)

    def test_empty_dir_not_detected(self, tmp_path):
        make_tree(tmp_path, {"README.md": "# hello"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["flutter"])
        assert not any(s.adapter == "flutter" for s in info.stacks)


# --------------------------------------------------------------------------
# Versión de Dart SDK
# --------------------------------------------------------------------------

class TestDartVersion:
    def test_dart_version_from_pubspec(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "dart" in info.requirements
        assert info.requirements["dart"].value == "3.0.0"

    def test_dart_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert info.requirements["dart"].priority == SourcePriority.EXPLICIT

    def test_dart_version_pure_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert "dart" in info.requirements
        assert info.requirements["dart"].value == "3.0.0"

    def test_dart_version_plugin(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        assert "dart" in info.requirements
        assert info.requirements["dart"].value.startswith("3")


# --------------------------------------------------------------------------
# Versión de Flutter SDK
# --------------------------------------------------------------------------

class TestFlutterVersion:
    def test_flutter_version_from_pubspec(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "flutter" in info.requirements
        assert info.requirements["flutter"].value == "3.16.0"

    def test_flutter_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert info.requirements["flutter"].priority == SourcePriority.EXPLICIT

    def test_no_flutter_req_for_dart_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert "flutter" not in info.requirements


# --------------------------------------------------------------------------
# Tipo de módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_flutter_app_kind(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        kinds = [m.kind for m in info.modules]
        assert "flutter-app" in kinds

    def test_flutter_plugin_kind(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        kinds = [m.kind for m in info.modules]
        assert "flutter-plugin" in kinds

    def test_dart_package_kind(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        kinds = [m.kind for m in info.modules]
        assert "dart-package" in kinds


# --------------------------------------------------------------------------
# Plataformas
# --------------------------------------------------------------------------

class TestPlatforms:
    def test_android_platform_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        platforms = info.facts.get("flutter.platforms")
        assert platforms is not None
        assert "android" in platforms.value

    def test_ios_platform_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        platforms = info.facts.get("flutter.platforms")
        assert platforms is not None
        assert "ios" in platforms.value

    def test_plugin_has_platforms(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        platforms = info.facts.get("flutter.platforms")
        assert platforms is not None
        assert len(platforms.value) >= 1

    def test_dart_package_no_platforms(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        platforms = info.facts.get("flutter.platforms")
        assert platforms is None or len(platforms.value) == 0


# --------------------------------------------------------------------------
# Servicios (Firebase, etc.)
# --------------------------------------------------------------------------

class TestServices:
    def test_firebase_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        kinds = [s.kind for s in info.services]
        assert "firebase" in kinds

    def test_no_services_for_dart_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert len(info.services) == 0

    def test_no_services_for_minimal_plugin(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        assert len(info.services) == 0


# --------------------------------------------------------------------------
# Rutas (GoRouter)
# --------------------------------------------------------------------------

class TestRoutes:
    def test_routes_detected(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert len(info.endpoints) > 0

    def test_root_route(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        paths = [ep.path for ep in info.endpoints]
        assert "/" in paths or any(p.endswith("/") for p in paths)

    def test_dashboard_route(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        paths = [ep.path for ep in info.endpoints]
        assert any("/dashboard" in p for p in paths)

    def test_users_route(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        paths = [ep.path for ep in info.endpoints]
        assert any("/users" in p for p in paths)

    def test_settings_route(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        paths = [ep.path for ep in info.endpoints]
        assert any("/settings" in p for p in paths)

    def test_no_routes_for_plugin(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        assert len(info.endpoints) == 0

    def test_no_routes_for_dart_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert len(info.endpoints) == 0


# --------------------------------------------------------------------------
# Nombre del paquete
# --------------------------------------------------------------------------

class TestPackageName:
    def test_package_name_from_pubspec(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        modules = [m.name for m in info.modules]
        assert "my_flutter_app" in modules

    def test_plugin_name(self, tmp_path):
        info = _info(tmp_path, FLUTTER_PLUGIN)
        modules = [m.name for m in info.modules]
        assert "my_camera_plugin" in modules

    def test_dart_package_name(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        modules = [m.name for m in info.modules]
        assert "my_utils" in modules


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_flutter_pub_get(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "deps" in info.commands
        assert "flutter pub get" in info.commands["deps"].shell

    def test_flutter_run(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "run" in info.commands
        assert "flutter run" in info.commands["run"].shell

    def test_flutter_test(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "test" in info.commands
        assert "flutter test" in info.commands["test"].shell

    def test_flutter_build_apk(self, tmp_path):
        info = _info(tmp_path, FLUTTER_APP)
        assert "build" in info.commands
        shell = info.commands["build"].shell
        assert "flutter build" in shell

    def test_dart_pub_get_for_pure_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert "deps" in info.commands
        assert "dart pub get" in info.commands["deps"].shell

    def test_dart_test_for_pure_package(self, tmp_path):
        info = _info(tmp_path, DART_PACKAGE)
        assert "test" in info.commands
        assert "dart test" in info.commands["test"].shell


# --------------------------------------------------------------------------
# Integración con recon (round-trip project.json)
# --------------------------------------------------------------------------

class TestReconIntegration:
    def test_flutter_app_roundtrip(self, tmp_path):
        make_tree(tmp_path, FLUTTER_APP)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert any(s.adapter == "flutter" for s in info.stacks)
        assert "dart" in info.requirements

    def test_flutter_plugin_roundtrip(self, tmp_path):
        make_tree(tmp_path, FLUTTER_PLUGIN)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        kinds = [m.kind for m in info.modules]
        assert "flutter-plugin" in kinds

    def test_dart_package_roundtrip(self, tmp_path):
        make_tree(tmp_path, DART_PACKAGE)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert "dart" in info.requirements


# --------------------------------------------------------------------------
# Monorepo: pubspec.yaml en subdirectorio
# --------------------------------------------------------------------------

class TestMonorepo:
    def test_flutter_detected_in_subdir(self, tmp_path):
        """pubspec.yaml en beex_mobile/ → flutter se detecta igual."""
        info = _info(tmp_path, FLUTTER_MONOREPO)
        assert any(s.adapter == "flutter" for s in info.stacks)

    def test_dart_version_from_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        assert "dart" in info.requirements
        assert info.requirements["dart"].value == "3.0.0"

    def test_flutter_version_from_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        assert "flutter" in info.requirements
        assert info.requirements["flutter"].value == "3.16.0"

    def test_flutter_app_kind_in_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        kinds = [m.kind for m in info.modules]
        assert "flutter-app" in kinds

    def test_android_platform_detected_in_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        plat = info.facts.get("flutter.platforms")
        assert plat is not None
        assert "android" in plat.value

    def test_ios_platform_detected_in_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        plat = info.facts.get("flutter.platforms")
        assert plat is not None
        assert "ios" in plat.value

    def test_firebase_service_from_subdir(self, tmp_path):
        info = _info(tmp_path, FLUTTER_MONOREPO)
        kinds = [s.kind for s in info.services]
        assert "firebase" in kinds

    def test_commands_have_cwd_in_subdir(self, tmp_path):
        """Comandos flutter deben indicar cwd=beex_mobile."""
        info = _info(tmp_path, FLUTTER_MONOREPO)
        assert "run" in info.commands
        assert info.commands["run"].cwd == "beex_mobile"

    def test_gradle_not_overrides_flutter_in_monorepo(self, tmp_path):
        """El adaptador gradle del android/ no debe ganar sobre flutter."""
        info = _info(tmp_path, FLUTTER_MONOREPO)
        assert "run" in info.commands
        assert "flutter" in info.commands["run"].shell
