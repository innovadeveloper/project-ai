"""Tests para adapters/cmake.py."""
import pytest
from conftest import (CMAKE_BASIC, CMAKE_MISSING_PRESET, NETCLIENT_FULL,
                      make_tree)

from project_ai.adapters import run_adapters
from project_ai.model import SourcePriority as P
from project_ai.scanner import ProjectScanner


@pytest.fixture
def netclient(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, NETCLIENT_FULL), use_git=False)
    return run_adapters(sc, only=["hints", "cmake", "conan"])


@pytest.fixture
def cmake_basic(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, CMAKE_BASIC), use_git=False)
    return run_adapters(sc, only=["cmake"])


@pytest.fixture
def missing_preset(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, CMAKE_MISSING_PRESET), use_git=False)
    return run_adapters(sc, only=["cmake"])


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

def test_cmake_detects_stack(cmake_basic):
    names = [s.adapter for s in cmake_basic.stacks]
    assert "cmake" in names


def test_no_cmake_no_stack(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, {"main.py": "print('hi')\n"}), use_git=False)
    info = run_adapters(sc, only=["cmake"])
    assert not any(s.adapter == "cmake" for s in info.stacks)


# ---------------------------------------------------------------------------
# Requisitos
# ---------------------------------------------------------------------------

def test_cmake_min_version(cmake_basic):
    assert cmake_basic.requirements["cmake"].value == "3.15"
    assert cmake_basic.requirements["cmake"].priority == P.BUILD


def test_cmake_cxx_standard(cmake_basic):
    assert cmake_basic.requirements["cxx_standard"].value == "17"
    assert cmake_basic.requirements["cxx_standard"].priority == P.BUILD


def test_netclient_cmake_version(netclient):
    assert netclient.requirements["cmake"].value == "3.20"


def test_netclient_cxx_standard(netclient):
    assert netclient.requirements["cxx_standard"].value == "17"


# ---------------------------------------------------------------------------
# Módulos y entry points
# ---------------------------------------------------------------------------

def test_cmake_library_module(cmake_basic):
    mods = {m.name: m for m in cmake_basic.modules}
    assert "mylib" in mods
    assert mods["mylib"].kind == "library"
    assert mods["mylib"].build_system == "cmake"


def test_cmake_executable_module(cmake_basic):
    mods = {m.name: m for m in cmake_basic.modules}
    assert "myapp" in mods
    assert mods["myapp"].kind == "executable"


def test_cmake_entry_points(cmake_basic):
    ep_kinds = {ep.kind for ep in cmake_basic.entry_points}
    assert "cmake-library" in ep_kinds
    assert "cmake-executable" in ep_kinds


def test_netclient_targets(netclient):
    mods = {m.name: m for m in netclient.modules}
    assert "system_sora_ws" in mods
    assert mods["system_sora_ws"].kind == "library"
    assert "system_sora_ws_test" in mods
    assert mods["system_sora_ws_test"].kind == "executable"
    assert "event_loop_demo" in mods
    assert mods["event_loop_demo"].kind == "executable"


# ---------------------------------------------------------------------------
# find_package
# ---------------------------------------------------------------------------

def test_cmake_find_packages(cmake_basic):
    pkgs = cmake_basic.facts.get("cmake.find_packages")
    assert pkgs is not None
    names = [p["name"] for p in pkgs.value]
    assert "CURL" in names
    assert "Threads" in names


def test_netclient_find_packages(netclient):
    pkgs = netclient.facts.get("cmake.find_packages")
    assert pkgs is not None
    names = [p["name"] for p in pkgs.value]
    assert "CURL" in names
    assert "eclipse-paho-mqtt-c" in names
    assert "Libwebsockets" in names


# ---------------------------------------------------------------------------
# Tests y comandos
# ---------------------------------------------------------------------------

def test_cmake_generates_test_command(cmake_basic):
    assert "test" in cmake_basic.commands
    assert "ctest" in cmake_basic.commands["test"].shell


def test_netclient_no_tests(netclient):
    # NETCLIENT_FULL no tiene enable_testing()
    assert "test" not in netclient.commands


def test_cmake_configure_command(cmake_basic):
    assert "configure" in cmake_basic.commands
    shell = cmake_basic.commands["configure"].shell
    assert "cmake" in shell


def test_cmake_build_command(cmake_basic):
    assert "build" in cmake_basic.commands
    assert "cmake --build" in cmake_basic.commands["build"].shell


def test_cmake_run_command(cmake_basic):
    assert "run" in cmake_basic.commands
    assert "myapp" in cmake_basic.commands["run"].shell


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def test_netclient_uses_preset(netclient):
    """Cuando CMakeUserPresets.json incluye un archivo existente con presets, se usan."""
    assert "configure" in netclient.commands
    assert "--preset" in netclient.commands["configure"].shell
    assert "conan-debug" in netclient.commands["configure"].shell


def test_missing_preset_warns(missing_preset):
    """CMakeUserPresets.json que incluye archivos no existentes → aviso."""
    assert any("conan install" in w for w in missing_preset.warnings)
    assert "cmake.preset_files_missing" in missing_preset.facts


def test_missing_preset_still_emits_configure_command(missing_preset):
    """Incluso con presets ausentes se emite el comando configure (con --preset)."""
    assert "configure" in missing_preset.commands


# ---------------------------------------------------------------------------
# Sugerencia compile_commands
# ---------------------------------------------------------------------------

def test_cmake_no_export_cc_suggests_flag(tmp_path):
    """CMakeLists.txt sin CMAKE_EXPORT_COMPILE_COMMANDS → sugerencia."""
    files = {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.15)\nproject(x LANGUAGES CXX)\n",
             "main.cpp": "int main() {}\n"}
    sc = ProjectScanner(make_tree(tmp_path, files), use_git=False)
    info = run_adapters(sc, only=["cmake"])
    assert "cmake.missing_export_compile_commands" in info.facts


def test_cmake_with_export_cc_no_suggestion(cmake_basic):
    """CMakeLists.txt CON CMAKE_EXPORT_COMPILE_COMMANDS → sin sugerencia."""
    assert "cmake.missing_export_compile_commands" not in cmake_basic.facts
