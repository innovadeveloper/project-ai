"""Tests para adapters/make.py."""
from __future__ import annotations

from conftest import (
    MAKE_C_LIB, MAKE_CPP, MAKE_SIMPLE, MAKE_WITH_CMAKE, make_tree,
)

from project_ai.recon import recon


def _recon(tmp_path, fixture, *, only=None):
    make_tree(tmp_path, fixture)
    return recon(tmp_path, only=only or ["hints", "cmake", "make"], write=False)


# --------------------------------------------------------------------------
# Detect
# --------------------------------------------------------------------------

class TestDetect:
    def test_makefile_detected(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert any(m.build_system == "make" for m in info.modules)

    def test_cmake_takes_priority(self, tmp_path):
        """Con CMakeLists.txt presente, make NO debe activarse."""
        info = _recon(tmp_path, MAKE_WITH_CMAKE)
        assert not any(m.build_system == "make" for m in info.modules)

    def test_no_makefile_not_detected(self, tmp_path):
        (tmp_path / "main.cpp").write_text("int main(){}")
        info = recon(tmp_path, only=["make"], write=False)
        assert not any(m.build_system == "make" for m in info.modules)

    def test_simple_makefile_detected(self, tmp_path):
        info = _recon(tmp_path, MAKE_SIMPLE)
        assert any(m.build_system == "make" for m in info.modules)


# --------------------------------------------------------------------------
# Estándar C++/C
# --------------------------------------------------------------------------

class TestStandard:
    def test_cxx_standard_from_cxxflags(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "cxx_standard" in info.requirements
        assert info.requirements["cxx_standard"].value == "17"

    def test_c_standard_from_cflags(self, tmp_path):
        info = _recon(tmp_path, MAKE_C_LIB)
        assert "c_standard" in info.requirements
        assert info.requirements["c_standard"].value == "11"

    def test_no_standard_simple(self, tmp_path):
        info = _recon(tmp_path, MAKE_SIMPLE)
        assert "cxx_standard" not in info.requirements
        assert "c_standard" not in info.requirements


# --------------------------------------------------------------------------
# Compilador
# --------------------------------------------------------------------------

class TestCompiler:
    def test_cxx_compiler_fact(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "make.compiler" in info.facts
        assert info.facts["make.compiler"].value == "g++"

    def test_cc_compiler_fact(self, tmp_path):
        info = _recon(tmp_path, MAKE_C_LIB)
        assert "make.compiler" in info.facts
        assert info.facts["make.compiler"].value == "gcc"

    def test_no_compiler_simple(self, tmp_path):
        info = _recon(tmp_path, MAKE_SIMPLE)
        assert "make.compiler" not in info.facts


# --------------------------------------------------------------------------
# Module kind y nombre
# --------------------------------------------------------------------------

class TestModule:
    def test_executable_kind(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        mod = next(m for m in info.modules if m.build_system == "make")
        assert mod.kind == "executable"
        assert mod.name == "myserver"

    def test_library_kind(self, tmp_path):
        info = _recon(tmp_path, MAKE_C_LIB)
        mod = next(m for m in info.modules if m.build_system == "make")
        assert mod.kind == "library"
        assert mod.name == "libmylib.so"


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_build_command(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "build" in info.commands
        assert "make" in info.commands["build"].shell

    def test_test_command(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "test" in info.commands
        assert "make test" in info.commands["test"].shell

    def test_install_command(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "install" in info.commands

    def test_no_install_without_target(self, tmp_path):
        info = _recon(tmp_path, MAKE_SIMPLE)
        assert "install" not in info.commands

    def test_no_test_without_target(self, tmp_path):
        info = _recon(tmp_path, MAKE_SIMPLE)
        assert "test" not in info.commands

    def test_check_as_test(self, tmp_path):
        """make check también mapea a comando test."""
        make_tree(tmp_path, {
            "Makefile": "all:\n\techo x\ncheck:\n\techo ok\n.PHONY: all check\n",
        })
        info = recon(tmp_path, only=["make"], write=False)
        assert "test" in info.commands
        assert "make check" in info.commands["test"].shell


# --------------------------------------------------------------------------
# Hint bear
# --------------------------------------------------------------------------

class TestBearHint:
    def test_bear_hint_present(self, tmp_path):
        info = _recon(tmp_path, MAKE_CPP)
        assert "make.bear_hint" in info.facts
        assert "bear" in info.facts["make.bear_hint"].value
