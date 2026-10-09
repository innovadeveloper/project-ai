"""Tests para adapters/conan.py."""
import pytest
from conftest import (CONAN1_BASIC, CONAN2_BASIC, CONAN_TXT_BASIC,
                      NETCLIENT_FULL, make_tree)

from project_ai.adapters import run_adapters
from project_ai.model import SourcePriority as P
from project_ai.scanner import ProjectScanner


@pytest.fixture
def conan2(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, CONAN2_BASIC), use_git=False)
    return run_adapters(sc, only=["cmake", "conan"])


@pytest.fixture
def conan1(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, CONAN1_BASIC), use_git=False)
    return run_adapters(sc, only=["cmake", "conan"])


@pytest.fixture
def conan_txt(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, CONAN_TXT_BASIC), use_git=False)
    return run_adapters(sc, only=["cmake", "conan"])


@pytest.fixture
def netclient(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, NETCLIENT_FULL), use_git=False)
    return run_adapters(sc, only=["hints", "cmake", "conan"])


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

def test_conan2_detects_stack(conan2):
    names = [s.adapter for s in conan2.stacks]
    assert "conan" in names


def test_conan1_detects_stack(conan1):
    names = [s.adapter for s in conan1.stacks]
    assert "conan" in names


def test_conan_txt_detects_stack(conan_txt):
    names = [s.adapter for s in conan_txt.stacks]
    assert "conan" in names


# ---------------------------------------------------------------------------
# Versión de la API
# ---------------------------------------------------------------------------

def test_conan2_api_version(conan2):
    assert conan2.requirements["conan"].value == "2"
    assert conan2.requirements["conan"].priority == P.BUILD


def test_conan1_api_version(conan1):
    assert conan1.requirements["conan"].value == "1"


# ---------------------------------------------------------------------------
# Requires en conanfile.py
# ---------------------------------------------------------------------------

def test_conan2_requires(conan2):
    reqs = conan2.facts.get("conan.requires")
    assert reqs is not None
    names = [r["name"] for r in reqs.value]
    assert "libcurl" in names
    assert "paho-mqtt-c" in names
    assert "libwebsockets" in names


def test_conan2_requires_versions(conan2):
    reqs = {r["name"]: r["version"] for r in conan2.facts["conan.requires"].value}
    assert reqs["libcurl"] == "8.5.0"
    assert reqs["paho-mqtt-c"] == "1.3.16"
    assert reqs["libwebsockets"] == "4.5.8"


def test_conan1_requires(conan1):
    reqs = conan1.facts.get("conan.requires")
    assert reqs is not None
    names = [r["name"] for r in reqs.value]
    assert "boost" in names
    assert "zlib" in names


# ---------------------------------------------------------------------------
# Requires en conanfile.txt
# ---------------------------------------------------------------------------

def test_conan_txt_requires(conan_txt):
    reqs = conan_txt.facts.get("conan.requires")
    assert reqs is not None
    names = [r["name"] for r in reqs.value]
    assert "fmt" in names
    assert "spdlog" in names
    assert "nlohmann_json" in names


def test_conan_txt_requires_versions(conan_txt):
    reqs = {r["name"]: r["version"] for r in conan_txt.facts["conan.requires"].value}
    assert reqs["fmt"] == "10.2.1"
    assert reqs["spdlog"] == "1.13.0"


# ---------------------------------------------------------------------------
# Generadores
# ---------------------------------------------------------------------------

def test_conan2_generators(conan2):
    gens = conan2.facts.get("conan.generators")
    assert gens is not None
    assert "CMakeToolchain" in gens.value
    assert "CMakeDeps" in gens.value


def test_conan_txt_generators(conan_txt):
    gens = conan_txt.facts.get("conan.generators")
    assert gens is not None
    assert "CMakeToolchain" in gens.value
    assert "CMakeDeps" in gens.value


# ---------------------------------------------------------------------------
# cmake_layout
# ---------------------------------------------------------------------------

def test_conan2_cmake_layout(conan2):
    assert conan2.facts.get("conan.cmake_layout") is not None
    assert conan2.facts["conan.cmake_layout"].value is True


def test_conan_txt_cmake_layout(conan_txt):
    assert conan_txt.facts.get("conan.cmake_layout") is not None


# ---------------------------------------------------------------------------
# Comando deps
# ---------------------------------------------------------------------------

def test_conan2_deps_command(conan2):
    assert "deps" in conan2.commands
    assert "conan install" in conan2.commands["deps"].shell
    assert "--build=missing" in conan2.commands["deps"].shell


def test_netclient_deps_from_tasks_json(netclient):
    """Cuando hints capturó 'conan install' de tasks.json, se usa esa versión."""
    assert "deps" in netclient.commands
    assert "conan install" in netclient.commands["deps"].shell


# ---------------------------------------------------------------------------
# netclient completo: cmake + conan integrados
# ---------------------------------------------------------------------------

def test_netclient_full_stacks(netclient):
    adapters = {s.adapter for s in netclient.stacks}
    assert "cmake" in adapters
    assert "conan" in adapters


def test_netclient_full_requirements(netclient):
    assert netclient.requirements["cmake"].value == "3.20"
    assert netclient.requirements["cxx_standard"].value == "17"
    assert netclient.requirements["conan"].value == "2"


def test_netclient_full_requires(netclient):
    reqs = {r["name"] for r in netclient.facts["conan.requires"].value}
    assert reqs == {"libcurl", "paho-mqtt-c", "libwebsockets"}


def test_netclient_full_targets(netclient):
    mods = {m.name for m in netclient.modules}
    assert "system_sora_ws" in mods
    assert "system_sora_ws_test" in mods
    assert "event_loop_demo" in mods


def test_netclient_full_commands_order(netclient):
    """deps → configure → build deben existir en ese orden lógico."""
    assert "deps" in netclient.commands
    assert "configure" in netclient.commands
    assert "build" in netclient.commands
    # configure usa el preset generado por conan
    assert "--preset" in netclient.commands["configure"].shell
