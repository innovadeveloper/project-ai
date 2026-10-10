"""Tests para adapters/platformio.py (PlatformIO, C/C++ embebido)."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    PLATFORMIO_ARDUINO, PLATFORMIO_ESP32, PLATFORMIO_MULTI_ENV, make_tree,
)
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["platformio"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_pio_detected(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert any(s.adapter == "platformio" for s in info.stacks)

    def test_no_pio_without_ini(self, tmp_path):
        make_tree(tmp_path, {"src/main.cpp": "void setup(){}\nvoid loop(){}\n"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["platformio"])
        assert not any(s.adapter == "platformio" for s in info.stacks)

    def test_confidence_high(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        pio = next(s for s in info.stacks if s.adapter == "platformio")
        assert pio.confidence >= 0.9


# --------------------------------------------------------------------------
# Hechos: plataforma, board, framework
# --------------------------------------------------------------------------

class TestFacts:
    def test_platform_extracted(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert info.facts.get("pio.platform") is not None
        assert info.facts["pio.platform"].value == "atmelavr"

    def test_platform_is_build(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert info.facts["pio.platform"].priority == SourcePriority.BUILD

    def test_board_extracted(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert info.facts["pio.board"].value == "uno"

    def test_framework_extracted(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert info.facts["pio.framework"].value == "arduino"

    def test_esp32_platform(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        assert info.facts["pio.platform"].value == "espressif32"

    def test_esp32_board(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        assert info.facts["pio.board"].value == "esp32dev"

    def test_monitor_speed_extracted(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        spd = info.facts.get("pio.monitor_speed")
        assert spd is not None
        assert spd.value == "115200"

    def test_no_monitor_speed_without_config(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert info.facts.get("pio.monitor_speed") is None


# --------------------------------------------------------------------------
# lib_deps
# --------------------------------------------------------------------------

class TestLibDeps:
    def test_lib_deps_extracted(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        libs = info.facts.get("pio.lib_deps")
        assert libs is not None
        assert "Ethernet" in libs.value or "Wire" in libs.value

    def test_esp32_lib_deps(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        libs = info.facts.get("pio.lib_deps")
        assert libs is not None
        assert "ArduinoJson" in libs.value


# --------------------------------------------------------------------------
# Kind de módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_arduino_kind(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        kinds = [m.kind for m in info.modules]
        assert "arduino-app" in kinds

    def test_esp32_arduino_kind(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        kinds = [m.kind for m in info.modules]
        assert "arduino-app" in kinds

    def test_multi_env_creates_multiple_modules(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_MULTI_ENV)
        pio_mods = [m for m in info.modules if m.build_system == "platformio"]
        assert len(pio_mods) == 2

    def test_multi_env_espidf_kind(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_MULTI_ENV)
        kinds = [m.kind for m in info.modules]
        assert "espidf-app" in kinds


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_build_command(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert "build" in info.commands
        assert "pio run" in info.commands["build"].shell

    def test_test_command(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert "test" in info.commands
        assert "pio test" in info.commands["test"].shell

    def test_run_is_upload(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert "run" in info.commands
        assert "upload" in info.commands["run"].shell

    def test_deps_command(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert "deps" in info.commands
        assert "pio" in info.commands["deps"].shell

    def test_monitor_command(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ARDUINO)
        assert "monitor" in info.commands
        assert "pio device monitor" in info.commands["monitor"].shell

    def test_monitor_includes_baud_rate(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_ESP32)
        assert "115200" in info.commands["monitor"].shell

    def test_multi_env_build_includes_env_flag(self, tmp_path):
        info = _info(tmp_path, PLATFORMIO_MULTI_ENV)
        assert "-e " in info.commands["build"].shell
