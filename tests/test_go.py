"""Tests para adapters/go.py."""
from __future__ import annotations

from conftest import GO_GIN_API, GO_LIBRARY, GO_MULTI_CMD, GO_STD_HTTP, make_tree

from project_ai.recon import recon


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _recon(tmp_path, fixture, *, only=None):
    make_tree(tmp_path, fixture)
    return recon(tmp_path, only=only or ["hints", "go"], write=False)


# --------------------------------------------------------------------------
# Detect
# --------------------------------------------------------------------------

class TestDetect:
    def test_gin_api_detected(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert any(m.build_system == "go" for m in info.modules)

    def test_library_detected(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert any(m.build_system == "go" for m in info.modules)

    def test_no_go_mod_not_detected(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        info = recon(tmp_path, only=["go"], write=False)
        assert not any(m.build_system == "go" for m in info.modules)


# --------------------------------------------------------------------------
# Go version
# --------------------------------------------------------------------------

class TestGoVersion:
    def test_gin_go_version(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "go" in info.requirements
        assert info.requirements["go"].value == "1.21"

    def test_library_go_version(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert info.requirements["go"].value == "1.20"

    def test_std_http_go_version(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        assert info.requirements["go"].value == "1.22"


# --------------------------------------------------------------------------
# Module kind
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_gin_api_is_executable(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.kind == "executable"

    def test_library_kind(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.kind == "library"

    def test_std_http_is_executable(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.kind == "executable"

    def test_multi_cmd_kind(self, tmp_path):
        info = _recon(tmp_path, GO_MULTI_CMD)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.kind == "multi-cmd"


# --------------------------------------------------------------------------
# Module name
# --------------------------------------------------------------------------

class TestModuleName:
    def test_module_name_from_path(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.name == "device-api"

    def test_library_module_name(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        mod = next(m for m in info.modules if m.build_system == "go")
        assert mod.name == "go-utils"


# --------------------------------------------------------------------------
# Servicios
# --------------------------------------------------------------------------

class TestServices:
    def test_postgresql_from_lib_pq(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        kinds = {s.kind for s in info.services}
        assert "postgresql" in kinds

    def test_redis_from_go_redis(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        kinds = {s.kind for s in info.services}
        assert "redis" in kinds

    def test_kafka_from_franz_go(self, tmp_path):
        info = _recon(tmp_path, GO_MULTI_CMD)
        kinds = {s.kind for s in info.services}
        assert "kafka" in kinds

    def test_redis_from_multi_cmd(self, tmp_path):
        info = _recon(tmp_path, GO_MULTI_CMD)
        kinds = {s.kind for s in info.services}
        assert "redis" in kinds

    def test_postgresql_from_pgx(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        kinds = {s.kind for s in info.services}
        assert "postgresql" in kinds

    def test_library_no_services(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert not info.services


# --------------------------------------------------------------------------
# Framework
# --------------------------------------------------------------------------

class TestFramework:
    def test_gin_framework_fact(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "go.framework" in info.facts
        assert info.facts["go.framework"].value == "gin"

    def test_no_framework_library(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert "go.framework" not in info.facts

    def test_no_framework_stdlib(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        assert "go.framework" not in info.facts


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

class TestEndpoints:
    def test_gin_endpoints_detected(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        paths = {ep.path for ep in info.endpoints}
        assert "/api/devices" in paths

    def test_gin_post_endpoint(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        verbs = {(ep.method, ep.path) for ep in info.endpoints}
        assert ("POST", "/api/devices") in verbs

    def test_stdlib_endpoints(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        paths = {ep.path for ep in info.endpoints}
        assert "/health" in paths
        assert "/api/users" in paths

    def test_library_no_endpoints(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert not info.endpoints


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_deps_command(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "deps" in info.commands
        assert "go mod download" in info.commands["deps"].shell

    def test_build_command(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "build" in info.commands
        assert "go build" in info.commands["build"].shell

    def test_test_command(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "test" in info.commands
        assert "go test" in info.commands["test"].shell

    def test_run_command_uses_cmd_dir(self, tmp_path):
        info = _recon(tmp_path, GO_GIN_API)
        assert "run" in info.commands
        assert "cmd" in info.commands["run"].shell

    def test_library_no_build_no_run(self, tmp_path):
        info = _recon(tmp_path, GO_LIBRARY)
        assert "test" in info.commands
        assert "run" not in info.commands

    def test_stdlib_run_uses_main(self, tmp_path):
        info = _recon(tmp_path, GO_STD_HTTP)
        assert "run" in info.commands
        assert "main.go" in info.commands["run"].shell
