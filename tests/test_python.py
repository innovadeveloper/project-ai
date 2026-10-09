"""Tests para adapters/python.py."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    DJANGO_POETRY, FASTAPI_UV, FLASK_REQS, PYTHON_SETUP_PY, make_tree,
)
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo
from project_ai.recon import recon
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["python"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_fastapi_detected(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert any(s.adapter == "python" for s in info.stacks)

    def test_django_detected(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert any(s.adapter == "python" for s in info.stacks)

    def test_flask_detected(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        assert any(s.adapter == "python" for s in info.stacks)

    def test_setup_py_detected(self, tmp_path):
        info = _info(tmp_path, PYTHON_SETUP_PY)
        assert any(s.adapter == "python" for s in info.stacks)

    def test_empty_dir_not_detected(self, tmp_path):
        make_tree(tmp_path, {"README.md": "# hello"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["python"])
        assert not any(s.adapter == "python" for s in info.stacks)


# --------------------------------------------------------------------------
# Requisito de versión Python
# --------------------------------------------------------------------------

class TestPythonVersion:
    def test_fastapi_uv_python_version_file(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert "python" in info.requirements
        assert info.requirements["python"].value == "3.11"

    def test_fastapi_pyproject_requires_python(self, tmp_path):
        # Sin .python-version → versión del pyproject
        files = {k: v for k, v in FASTAPI_UV.items() if k != ".python-version"}
        info = _info(tmp_path, files)
        assert "python" in info.requirements
        assert info.requirements["python"].value == "3.11"

    def test_django_poetry_python_version(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert "python" in info.requirements
        assert info.requirements["python"].value == "3.10"

    def test_python_version_file_wins_over_pyproject(self, tmp_path):
        # .python-version es EXPLICIT, pyproject es BUILD → gana EXPLICIT
        info = _info(tmp_path, FASTAPI_UV)
        pyv = info.requirements["python"]
        from project_ai.model import SourcePriority
        assert pyv.priority == SourcePriority.EXPLICIT

    def test_setup_py_python_requires(self, tmp_path):
        info = _info(tmp_path, PYTHON_SETUP_PY)
        assert "python" in info.requirements
        assert info.requirements["python"].value == "3.8"


# --------------------------------------------------------------------------
# Framework
# --------------------------------------------------------------------------

class TestFramework:
    def test_fastapi_framework(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert info.facts.get("framework") is not None
        assert info.facts["framework"].value == "fastapi"

    def test_django_framework(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert info.facts["framework"].value == "django"

    def test_flask_framework(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        assert info.facts["framework"].value == "flask"

    def test_no_framework_for_library(self, tmp_path):
        info = _info(tmp_path, PYTHON_SETUP_PY)
        fw = info.facts.get("framework")
        assert fw is None or fw.value not in ("fastapi", "django", "flask")


# --------------------------------------------------------------------------
# Gestor de paquetes
# --------------------------------------------------------------------------

class TestPackageManager:
    def test_fastapi_uses_uv(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        pm = info.facts.get("python.package_manager")
        assert pm is not None and pm.value == "uv"

    def test_django_uses_poetry(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        pm = info.facts.get("python.package_manager")
        assert pm is not None and pm.value == "poetry"

    def test_flask_uses_pip(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        pm = info.facts.get("python.package_manager")
        assert pm is not None and pm.value == "pip"


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_fastapi_has_deps_command(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert "deps" in info.commands
        assert "uv sync" in info.commands["deps"].shell

    def test_fastapi_has_run_command(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert "run" in info.commands
        assert "uvicorn" in info.commands["run"].shell

    def test_fastapi_has_test_command(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert "test" in info.commands
        assert "pytest" in info.commands["test"].shell

    def test_django_run_uses_manage_py(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert "run" in info.commands
        assert "manage.py" in info.commands["run"].shell

    def test_flask_run_uses_flask_cli(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        assert "run" in info.commands
        assert "flask" in info.commands["run"].shell

    def test_poetry_install_in_deps(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert "poetry install" in info.commands["deps"].shell

    def test_pip_install_in_deps(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        assert "pip install" in info.commands["deps"].shell


# --------------------------------------------------------------------------
# Endpoints — FastAPI
# --------------------------------------------------------------------------

class TestFastAPIEndpoints:
    def test_fastapi_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        assert len(info.endpoints) > 0

    def test_fastapi_includes_get_devices(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        paths = [ep.path for ep in info.endpoints]
        assert any("/api/devices" in p for p in paths)

    def test_fastapi_includes_post_login(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        endpoints = [(ep.method, ep.path) for ep in info.endpoints]
        assert any(m == "POST" and "login" in p for m, p in endpoints)

    def test_fastapi_methods_correct(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        methods = {ep.method for ep in info.endpoints}
        assert "GET" in methods
        assert "POST" in methods

    def test_fastapi_handler_names(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        handlers = [ep.handler for ep in info.endpoints]
        assert any("list_devices" in h or "get" in h.lower() for h in handlers)


# --------------------------------------------------------------------------
# Endpoints — Flask
# --------------------------------------------------------------------------

class TestFlaskEndpoints:
    def test_flask_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        assert len(info.endpoints) > 0

    def test_flask_items_route(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        paths = [ep.path for ep in info.endpoints]
        assert any("/api/items" in p for p in paths)

    def test_flask_methods_from_methods_list(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        methods = {ep.method for ep in info.endpoints}
        assert "GET" in methods
        assert "POST" in methods


# --------------------------------------------------------------------------
# Endpoints — Django
# --------------------------------------------------------------------------

class TestDjangoEndpoints:
    def test_django_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        assert len(info.endpoints) > 0

    def test_django_devices_path(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        handlers = [ep.handler for ep in info.endpoints]
        assert any("view" in h.lower() or "device" in h.lower() for h in handlers)


# --------------------------------------------------------------------------
# Servicios de runtime
# --------------------------------------------------------------------------

class TestServices:
    def test_fastapi_postgresql_service(self, tmp_path):
        info = _info(tmp_path, FASTAPI_UV)
        kinds = [s.kind for s in info.services]
        assert "postgresql" in kinds

    def test_django_postgresql_service(self, tmp_path):
        info = _info(tmp_path, DJANGO_POETRY)
        kinds = [s.kind for s in info.services]
        assert "postgresql" in kinds

    def test_flask_redis_service(self, tmp_path):
        info = _info(tmp_path, FLASK_REQS)
        kinds = [s.kind for s in info.services]
        assert "redis" in kinds

    def test_no_services_for_library(self, tmp_path):
        info = _info(tmp_path, PYTHON_SETUP_PY)
        assert len(info.services) == 0


# --------------------------------------------------------------------------
# Integración con recon (round-trip project.json)
# --------------------------------------------------------------------------

class TestReconIntegration:
    def test_fastapi_roundtrip(self, tmp_path):
        make_tree(tmp_path, FASTAPI_UV)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert any(s.adapter == "python" for s in info.stacks)
        assert "python" in info.requirements

    def test_project_json_loads_without_error(self, tmp_path):
        make_tree(tmp_path, DJANGO_POETRY)
        recon(tmp_path, write=True)
        # Si hay bug de Evidence anidada esto lanzaría TypeError
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert info is not None

    def test_adapters_only_python(self, tmp_path):
        make_tree(tmp_path, FASTAPI_UV)
        info = recon(tmp_path, only=["python"], write=False)
        assert any(s.adapter == "python" for s in info.stacks)
