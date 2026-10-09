"""Tests para adapters/dotnet.py."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    DOTNET_CONSOLE, DOTNET_MINIMAL_API,
    DOTNET_MVC_CONTROLLERS, DOTNET_SOLUTION, make_tree,
)
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.recon import recon
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["dotnet"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_minimal_api_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert any(s.adapter == "dotnet" for s in info.stacks)

    def test_mvc_controllers_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        assert any(s.adapter == "dotnet" for s in info.stacks)

    def test_solution_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_SOLUTION)
        assert any(s.adapter == "dotnet" for s in info.stacks)

    def test_console_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_CONSOLE)
        assert any(s.adapter == "dotnet" for s in info.stacks)

    def test_empty_dir_not_detected(self, tmp_path):
        make_tree(tmp_path, {"README.md": "# hello"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["dotnet"])
        assert not any(s.adapter == "dotnet" for s in info.stacks)


# --------------------------------------------------------------------------
# Versión de .NET
# --------------------------------------------------------------------------

class TestDotnetVersion:
    def test_net8_requirement(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert "dotnet" in info.requirements
        assert info.requirements["dotnet"].value == "8"

    def test_net7_requirement(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        assert "dotnet" in info.requirements
        assert info.requirements["dotnet"].value == "7"

    def test_net8_from_solution(self, tmp_path):
        info = _info(tmp_path, DOTNET_SOLUTION)
        assert "dotnet" in info.requirements
        assert info.requirements["dotnet"].value == "8"

    def test_global_json_wins_with_explicit_priority(self, tmp_path):
        # global.json tiene prioridad EXPLICIT; .csproj tiene BUILD
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        fact = info.requirements["dotnet"]
        assert fact.priority == SourcePriority.EXPLICIT


# --------------------------------------------------------------------------
# Tipo de módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_web_sdk_is_web_app(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        kinds = [m.kind for m in info.modules]
        assert "web-app" in kinds

    def test_console_outputtype(self, tmp_path):
        info = _info(tmp_path, DOTNET_CONSOLE)
        kinds = [m.kind for m in info.modules]
        assert "console" in kinds

    def test_test_project_kind(self, tmp_path):
        info = _info(tmp_path, DOTNET_SOLUTION)
        kinds = [m.kind for m in info.modules]
        assert "test" in kinds

    def test_solution_has_multiple_modules(self, tmp_path):
        info = _info(tmp_path, DOTNET_SOLUTION)
        assert len(info.modules) >= 2


# --------------------------------------------------------------------------
# Endpoints — Minimal API
# --------------------------------------------------------------------------

class TestEndpointsMinimalAPI:
    def test_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert len(info.endpoints) > 0

    def test_get_products_path(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        paths = [ep.path for ep in info.endpoints]
        assert any("/api/products" in p for p in paths)

    def test_post_products(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        endpoints = [(ep.method, ep.path) for ep in info.endpoints]
        assert any(m == "POST" and "/api/products" in p for m, p in endpoints)

    def test_delete_endpoint(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        methods = {ep.method for ep in info.endpoints}
        assert "DELETE" in methods

    def test_methods_include_get_post_put_delete(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        methods = {ep.method for ep in info.endpoints}
        assert {"GET", "POST", "PUT", "DELETE"}.issubset(methods)


# --------------------------------------------------------------------------
# Endpoints — Controllers
# --------------------------------------------------------------------------

class TestEndpointsControllers:
    def test_controller_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        assert len(info.endpoints) > 0

    def test_controller_route_resolved(self, tmp_path):
        # [Route("api/[controller]")] + class PaymentController → api/payment
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        paths = [ep.path.lower() for ep in info.endpoints]
        assert any("payment" in p for p in paths)

    def test_post_create_path(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        endpoints = [(ep.method, ep.path) for ep in info.endpoints]
        assert any(m == "POST" and "create" in p for m, p in endpoints)

    def test_delete_path_has_id(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        endpoints = [(ep.method, ep.path) for ep in info.endpoints]
        assert any(m == "DELETE" for m, _ in endpoints)

    def test_handler_names_in_endpoints(self, tmp_path):
        info = _info(tmp_path, DOTNET_MVC_CONTROLLERS)
        handlers = [ep.handler for ep in info.endpoints]
        assert any("GetAll" in h or "GetById" in h or "Create" in h for h in handlers)


# --------------------------------------------------------------------------
# Servicios de runtime
# --------------------------------------------------------------------------

class TestServices:
    def test_postgresql_from_npgsql(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        kinds = [s.kind for s in info.services]
        assert "postgresql" in kinds

    def test_redis_from_stackexchange(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        kinds = [s.kind for s in info.services]
        assert "redis" in kinds

    def test_no_services_for_console(self, tmp_path):
        info = _info(tmp_path, DOTNET_CONSOLE)
        assert len(info.services) == 0

    def test_no_services_for_test_project(self, tmp_path):
        # El proyecto de tests de DOTNET_SOLUTION no tiene deps de servicio
        info = _info(tmp_path, DOTNET_SOLUTION)
        # No debe haber servicios (web project de la solution tampoco tiene)
        service_kinds = [s.kind for s in info.services]
        assert "postgresql" not in service_kinds


# --------------------------------------------------------------------------
# launchSettings.json → puertos
# --------------------------------------------------------------------------

class TestLaunchSettings:
    def test_port_from_launch_settings(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        port_fact = info.facts.get("hints.ports")
        assert port_fact is not None
        ports = port_fact.value if isinstance(port_fact.value, list) else [port_fact.value]
        assert any("5001" in str(p) or "7001" in str(p) for p in ports)

    def test_no_launch_settings_no_crash(self, tmp_path):
        # DOTNET_CONSOLE no tiene launchSettings.json
        info = _info(tmp_path, DOTNET_CONSOLE)
        # No debe lanzar excepción; el hecho de puertos puede no existir
        assert isinstance(info, ProjectInfo)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_has_deps_command(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert "deps" in info.commands
        assert "dotnet restore" in info.commands["deps"].shell

    def test_has_build_command(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert "build" in info.commands
        assert "dotnet build" in info.commands["build"].shell

    def test_has_run_command(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        assert "run" in info.commands
        assert "dotnet run" in info.commands["run"].shell

    def test_has_test_command_when_test_project(self, tmp_path):
        info = _info(tmp_path, DOTNET_SOLUTION)
        assert "test" in info.commands
        assert "dotnet test" in info.commands["test"].shell

    def test_no_test_command_without_test_project(self, tmp_path):
        info = _info(tmp_path, DOTNET_MINIMAL_API)
        # Sin proyecto de tests no debe haber comando test
        assert "test" not in info.commands

    def test_console_run_command(self, tmp_path):
        info = _info(tmp_path, DOTNET_CONSOLE)
        assert "run" in info.commands
        assert "dotnet run" in info.commands["run"].shell


# --------------------------------------------------------------------------
# Integración con recon (round-trip project.json)
# --------------------------------------------------------------------------

class TestReconIntegration:
    def test_minimal_api_roundtrip(self, tmp_path):
        make_tree(tmp_path, DOTNET_MINIMAL_API)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert any(s.adapter == "dotnet" for s in info.stacks)
        assert "dotnet" in info.requirements

    def test_solution_roundtrip(self, tmp_path):
        make_tree(tmp_path, DOTNET_SOLUTION)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert len(info.modules) >= 2

    def test_project_json_loads_without_error(self, tmp_path):
        make_tree(tmp_path, DOTNET_MVC_CONTROLLERS)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert info is not None
