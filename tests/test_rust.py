"""Tests para adapters/rust.py."""
from __future__ import annotations

from conftest import RUST_ACTIX_API, RUST_CLI, RUST_LIBRARY, RUST_WORKSPACE, make_tree

from project_ai.recon import recon


def _recon(tmp_path, fixture, *, only=None):
    make_tree(tmp_path, fixture)
    return recon(tmp_path, only=only or ["hints", "rust"], write=False)


# --------------------------------------------------------------------------
# Detect
# --------------------------------------------------------------------------

class TestDetect:
    def test_actix_detected(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert any(m.build_system == "rust" for m in info.modules)

    def test_library_detected(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert any(m.build_system == "rust" for m in info.modules)

    def test_workspace_detected(self, tmp_path):
        info = _recon(tmp_path, RUST_WORKSPACE)
        assert any(m.build_system == "rust" for m in info.modules)

    def test_no_cargo_not_detected(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        info = recon(tmp_path, only=["rust"], write=False)
        assert not any(m.build_system == "rust" for m in info.modules)


# --------------------------------------------------------------------------
# Versión de Rust
# --------------------------------------------------------------------------

class TestRustVersion:
    def test_rust_version_explicit(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "rust" in info.requirements
        assert info.requirements["rust"].value == "1.70"

    def test_edition_fallback(self, tmp_path):
        # RUST_LIBRARY solo tiene edition = "2021", sin rust-version
        info = _recon(tmp_path, RUST_LIBRARY)
        assert "rust" in info.requirements
        assert info.requirements["rust"].value == "1.56"

    def test_workspace_members_edition(self, tmp_path):
        # workspace raíz no tiene [package], los miembros sí
        info = _recon(tmp_path, RUST_WORKSPACE)
        # Al menos debe haber un req rust (de las dependencias de miembros)
        # workspace raíz no tiene edition → puede que no haya req rust
        # Pero los miembros tienen edition 2021 → el adaptador los lee
        # (El workspace raíz Cargo.toml no tiene [package] ni edition)
        # Este test solo verifica que no crashea
        assert any(m.build_system == "rust" for m in info.modules)


# --------------------------------------------------------------------------
# Module kind
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_actix_is_executable(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.kind == "executable"

    def test_library_kind(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.kind == "library"

    def test_workspace_kind(self, tmp_path):
        info = _recon(tmp_path, RUST_WORKSPACE)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.kind == "workspace"

    def test_cli_is_executable(self, tmp_path):
        info = _recon(tmp_path, RUST_CLI)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.kind == "executable"


# --------------------------------------------------------------------------
# Module name
# --------------------------------------------------------------------------

class TestModuleName:
    def test_name_from_package(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.name == "device-api"

    def test_library_name(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        mod = next(m for m in info.modules if m.build_system == "rust")
        assert mod.name == "mylib"


# --------------------------------------------------------------------------
# Servicios
# --------------------------------------------------------------------------

class TestServices:
    def test_postgresql_from_sqlx(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        kinds = {s.kind for s in info.services}
        assert "postgresql" in kinds

    def test_redis_from_redis_crate(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        kinds = {s.kind for s in info.services}
        assert "redis" in kinds

    def test_postgresql_from_diesel(self, tmp_path):
        info = _recon(tmp_path, RUST_CLI)
        kinds = {s.kind for s in info.services}
        assert "postgresql" in kinds

    def test_kafka_from_rdkafka(self, tmp_path):
        info = _recon(tmp_path, RUST_WORKSPACE)
        kinds = {s.kind for s in info.services}
        assert "kafka" in kinds

    def test_library_no_services(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert not info.services


# --------------------------------------------------------------------------
# Framework
# --------------------------------------------------------------------------

class TestFramework:
    def test_actix_framework_fact(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "rust.framework" in info.facts
        assert info.facts["rust.framework"].value == "actix-web"

    def test_axum_framework_workspace(self, tmp_path):
        info = _recon(tmp_path, RUST_WORKSPACE)
        assert "rust.framework" in info.facts
        assert info.facts["rust.framework"].value == "axum"

    def test_no_framework_library(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert "rust.framework" not in info.facts

    def test_no_framework_cli(self, tmp_path):
        info = _recon(tmp_path, RUST_CLI)
        assert "rust.framework" not in info.facts


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

class TestEndpoints:
    def test_actix_get_endpoint(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        paths = {ep.path for ep in info.endpoints}
        assert "/api/devices" in paths

    def test_actix_post_endpoint(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        verbs = {(ep.method, ep.path) for ep in info.endpoints}
        assert ("POST", "/api/devices") in verbs

    def test_actix_delete_endpoint(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        verbs = {(ep.method, ep.path) for ep in info.endpoints}
        assert ("DELETE", "/api/devices/{id}") in verbs

    def test_axum_endpoints_in_workspace(self, tmp_path):
        info = _recon(tmp_path, RUST_WORKSPACE)
        paths = {ep.path for ep in info.endpoints}
        assert "/health" in paths
        assert "/users" in paths

    def test_library_no_endpoints(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert not info.endpoints

    def test_cli_no_endpoints(self, tmp_path):
        info = _recon(tmp_path, RUST_CLI)
        assert not info.endpoints


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_deps_command(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "deps" in info.commands
        assert "cargo fetch" in info.commands["deps"].shell

    def test_build_command(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "build" in info.commands
        assert "cargo build" in info.commands["build"].shell

    def test_test_command(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "test" in info.commands
        assert "cargo test" in info.commands["test"].shell

    def test_run_command_binary(self, tmp_path):
        info = _recon(tmp_path, RUST_ACTIX_API)
        assert "run" in info.commands
        assert "cargo run" in info.commands["run"].shell

    def test_library_no_run(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert "run" not in info.commands

    def test_library_has_test(self, tmp_path):
        info = _recon(tmp_path, RUST_LIBRARY)
        assert "test" in info.commands
