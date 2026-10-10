"""Tests para adapters/javascript.py (Node.js, Angular, React, NestJS, static HTML)."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    ANGULAR_APP, NESTJS_API, NODEJS_EXPRESS, REACT_VITE, STATIC_HTML,
    make_tree,
)
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.recon import recon
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["javascript"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_express_detected(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert any(s.adapter == "javascript" for s in info.stacks)

    def test_angular_detected(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert any(s.adapter == "javascript" for s in info.stacks)

    def test_react_detected(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        assert any(s.adapter == "javascript" for s in info.stacks)

    def test_nestjs_detected(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        assert any(s.adapter == "javascript" for s in info.stacks)

    def test_static_html_detected(self, tmp_path):
        info = _info(tmp_path, STATIC_HTML)
        assert any(s.adapter == "javascript" for s in info.stacks)

    def test_empty_dir_not_detected(self, tmp_path):
        make_tree(tmp_path, {"README.md": "# hello"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["javascript"])
        assert not any(s.adapter == "javascript" for s in info.stacks)


# --------------------------------------------------------------------------
# Versión de Node.js
# --------------------------------------------------------------------------

class TestNodeVersion:
    def test_node_version_from_nvmrc(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert "node" in info.requirements
        assert info.requirements["node"].value == "20.11.0"

    def test_node_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert info.requirements["node"].priority == SourcePriority.EXPLICIT

    def test_node_version_from_node_version_file(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert "node" in info.requirements
        assert info.requirements["node"].value == "20"

    def test_node_version_node_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert info.requirements["node"].priority == SourcePriority.EXPLICIT


# --------------------------------------------------------------------------
# Gestor de paquetes
# --------------------------------------------------------------------------

class TestPackageManager:
    def test_npm_from_lockfile(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        pm = info.facts.get("js.package_manager")
        assert pm is not None
        assert pm.value == "npm"

    def test_yarn_from_lockfile(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        pm = info.facts.get("js.package_manager")
        assert pm is not None
        assert pm.value == "yarn"

    def test_pnpm_from_lockfile(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        pm = info.facts.get("js.package_manager")
        assert pm is not None
        assert pm.value == "pnpm"

    def test_npm_lockfile_is_explicit(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert info.facts["js.package_manager"].priority == SourcePriority.EXPLICIT


# --------------------------------------------------------------------------
# Framework / tipo de proyecto
# --------------------------------------------------------------------------

class TestFramework:
    def test_express_framework(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        fw = info.facts.get("js.framework")
        assert fw is not None
        assert fw.value == "express"

    def test_angular_framework(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        fw = info.facts.get("js.framework")
        assert fw is not None
        assert fw.value == "angular"

    def test_react_framework(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        fw = info.facts.get("js.framework")
        assert fw is not None
        assert fw.value == "react"

    def test_nestjs_framework(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        fw = info.facts.get("js.framework")
        assert fw is not None
        assert fw.value == "nestjs"

    def test_static_no_framework(self, tmp_path):
        info = _info(tmp_path, STATIC_HTML)
        fw = info.facts.get("js.framework")
        # puede ser None o "static"
        assert fw is None or fw.value in ("static", "vite")


# --------------------------------------------------------------------------
# Tipo de módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_express_api_server(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        kinds = [m.kind for m in info.modules]
        assert "api-server" in kinds

    def test_angular_frontend(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        kinds = [m.kind for m in info.modules]
        assert "frontend-app" in kinds

    def test_react_frontend(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        kinds = [m.kind for m in info.modules]
        assert "frontend-app" in kinds

    def test_nestjs_api_server(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        kinds = [m.kind for m in info.modules]
        assert "api-server" in kinds

    def test_static_bundled_frontend(self, tmp_path):
        info = _info(tmp_path, STATIC_HTML)
        kinds = [m.kind for m in info.modules]
        assert "bundled-frontend" in kinds or "static-site" in kinds


# --------------------------------------------------------------------------
# Servicios
# --------------------------------------------------------------------------

class TestServices:
    def test_postgresql_from_pg_dep(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        kinds = [s.kind for s in info.services]
        assert "postgresql" in kinds

    def test_redis_from_dep(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        kinds = [s.kind for s in info.services]
        assert "redis" in kinds

    def test_mssql_from_tedious(self, tmp_path):
        """tedious (SQL Server TDS) → servicio mssql."""
        pkg = {
            "package.json": '{"name":"api","dependencies":{"tedious":"^2.7.1","express":"^4.0.0"}}'
        }
        info = _info(tmp_path, pkg)
        kinds = [s.kind for s in info.services]
        assert "mssql" in kinds

    def test_mssql_from_mssql_package(self, tmp_path):
        pkg = {
            "package.json": '{"name":"api","dependencies":{"mssql":"^9.0.0","express":"^4.0.0"}}'
        }
        info = _info(tmp_path, pkg)
        kinds = [s.kind for s in info.services]
        assert "mssql" in kinds

    def test_no_services_for_angular(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert len(info.services) == 0

    def test_no_services_for_react(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        assert len(info.services) == 0


class TestTypeScriptVersion:
    def test_ts_version_from_dependencies(self, tmp_path):
        """typescript en dependencies → req typescript BUILD."""
        pkg = {
            "package.json": '{"name":"api","dependencies":{"typescript":"^2.9.2","express":"^4.0.0"}}'
        }
        info = _info(tmp_path, pkg)
        assert "typescript" in info.requirements
        assert info.requirements["typescript"].value == "2.9.2"

    def test_ts_version_from_devdependencies(self, tmp_path):
        """typescript en devDependencies también se captura."""
        pkg = {
            "package.json": '{"name":"api","dependencies":{"express":"^4.0.0"},"devDependencies":{"typescript":"^5.0.4"}}'
        }
        info = _info(tmp_path, pkg)
        assert "typescript" in info.requirements
        assert info.requirements["typescript"].value == "5.0.4"

    def test_no_ts_without_dep(self, tmp_path):
        pkg = {
            "package.json": '{"name":"api","dependencies":{"express":"^4.0.0"}}'
        }
        info = _info(tmp_path, pkg)
        assert "typescript" not in info.requirements


# --------------------------------------------------------------------------
# Endpoints Express
# --------------------------------------------------------------------------

class TestEndpointsExpress:
    def test_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert len(info.endpoints) > 0

    def test_get_route_found(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        paths = [ep.path for ep in info.endpoints]
        assert any("/" in p for p in paths)

    def test_post_route_found(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        methods = {ep.method for ep in info.endpoints}
        assert "POST" in methods

    def test_delete_route_found(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        methods = {ep.method for ep in info.endpoints}
        assert "DELETE" in methods

    def test_health_endpoint(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        paths = [ep.path for ep in info.endpoints]
        assert any("/health" in p for p in paths)


# --------------------------------------------------------------------------
# Endpoints NestJS
# --------------------------------------------------------------------------

class TestEndpointsNestJS:
    def test_nestjs_endpoints_detected(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        assert len(info.endpoints) > 0

    def test_nestjs_controller_prefix(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        paths = [ep.path for ep in info.endpoints]
        assert any("/users" in p for p in paths)

    def test_nestjs_products_prefix(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        paths = [ep.path for ep in info.endpoints]
        assert any("/products" in p for p in paths)

    def test_nestjs_post_endpoint(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        methods = {ep.method for ep in info.endpoints}
        assert "POST" in methods

    def test_nestjs_delete_endpoint(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        methods = {ep.method for ep in info.endpoints}
        assert "DELETE" in methods


# --------------------------------------------------------------------------
# Rutas cliente Angular / React
# --------------------------------------------------------------------------

class TestClientRoutes:
    def test_angular_routes_detected(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert len(info.endpoints) > 0

    def test_angular_dashboard_route(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        paths = [ep.path for ep in info.endpoints]
        assert any("dashboard" in p for p in paths)

    def test_angular_users_route(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        paths = [ep.path for ep in info.endpoints]
        assert any("users" in p for p in paths)

    def test_react_routes_detected(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        assert len(info.endpoints) > 0

    def test_react_dashboard_route(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        paths = [ep.path for ep in info.endpoints]
        assert any("dashboard" in p for p in paths)

    def test_react_users_route(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        paths = [ep.path for ep in info.endpoints]
        assert any("users" in p for p in paths)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_express_run_command(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert "run" in info.commands
        shell = info.commands["run"].shell
        assert "npm" in shell or "node" in shell

    def test_express_test_command(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert "test" in info.commands
        assert "test" in info.commands["test"].shell.lower()

    def test_angular_run_command(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert "run" in info.commands
        assert "ng serve" in info.commands["run"].shell or "start" in info.commands["run"].shell

    def test_angular_build_command(self, tmp_path):
        info = _info(tmp_path, ANGULAR_APP)
        assert "build" in info.commands
        assert "ng build" in info.commands["build"].shell or "build" in info.commands["build"].shell

    def test_react_dev_command(self, tmp_path):
        info = _info(tmp_path, REACT_VITE)
        assert "run" in info.commands
        shell = info.commands["run"].shell
        assert "pnpm" in shell or "vite" in shell or "dev" in shell

    def test_nestjs_dev_command(self, tmp_path):
        info = _info(tmp_path, NESTJS_API)
        assert "run" in info.commands
        assert "start" in info.commands["run"].shell or "dev" in info.commands["run"].shell

    def test_deps_install_command(self, tmp_path):
        info = _info(tmp_path, NODEJS_EXPRESS)
        assert "deps" in info.commands
        shell = info.commands["deps"].shell
        assert "npm install" in shell or "npm ci" in shell

    def test_static_build_command(self, tmp_path):
        info = _info(tmp_path, STATIC_HTML)
        assert "build" in info.commands
        assert "build" in info.commands["build"].shell.lower()


# --------------------------------------------------------------------------
# Integración con recon (round-trip project.json)
# --------------------------------------------------------------------------

class TestReconIntegration:
    def test_express_roundtrip(self, tmp_path):
        make_tree(tmp_path, NODEJS_EXPRESS)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert any(s.adapter == "javascript" for s in info.stacks)
        assert "node" in info.requirements

    def test_angular_roundtrip(self, tmp_path):
        make_tree(tmp_path, ANGULAR_APP)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert len(info.endpoints) > 0

    def test_nestjs_roundtrip(self, tmp_path):
        make_tree(tmp_path, NESTJS_API)
        recon(tmp_path, write=True)
        info = ProjectInfo.load(tmp_path / ".project-ai" / "project.json")
        assert len(info.endpoints) > 0
