"""
adapters/platformio.py — Proyectos PlatformIO (C/C++ embebido: Arduino, ESP-IDF, Zephyr…).

Señal: platformio.ini en la raíz del proyecto.

Qué descubre:
  Plataforma     platform = espressif32 / atmelavr / teensy / … → fact pio.platform (BUILD)
  Board          board = esp32dev / uno / …                     → fact pio.board (BUILD)
  Framework      framework = arduino / espidf / zephyr / …     → fact pio.framework (BUILD)
  Librerías      lib_deps (multilínea)                          → fact pio.lib_deps (BUILD)
  Monitor serie  monitor_speed                                  → fact pio.monitor_speed (BUILD)
  Módulos        un módulo por entorno [env:xxx]; kind según framework
  Comandos       pio pkg install / pio run / pio test /
                 pio run --target upload / pio device monitor

Prioridades:
  platformio.ini → BUILD para todos los hechos (es la fuente de build)
"""
from __future__ import annotations

import configparser
from pathlib import Path

from ..model import Command, Fact, Module, ProjectInfo, SourcePriority as P, StackDetection
from ..scanner import ProjectScanner
from .base import Adapter, ev, register

NAME = "platformio"

_FRAMEWORK_KINDS: dict[str, str] = {
    "arduino":    "arduino-app",
    "espidf":     "espidf-app",
    "zephyr":     "zephyr-app",
    "mbed":       "mbed-app",
    "stm32cube":  "stm32cube-app",
    "libopencm3": "libopencm3-app",
    "cmsis":      "cmsis-app",
}


@register
class PlatformIOAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        sig = next((f for f in sc.files if Path(f).name == "platformio.ini"), None)
        if not sig:
            return []
        return [StackDetection(
            adapter=NAME, confidence=0.95,
            evidence=[ev(sig, None, "platformio.ini encontrado")],
        )]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)
        ini_rel = next(
            (f for f in sc.files if Path(f).name == "platformio.ini"), None
        )
        if not ini_rel:
            return

        envs = _parse_platformio_ini(root / ini_rel, ini_rel, info)

        if envs:
            for env_name, env_data in envs.items():
                fw = env_data.get("framework", "").lower()
                kind = _FRAMEWORK_KINDS.get(fw, "embedded-app")
                info.modules.append(Module(
                    name=env_name, path=".", build_system=NAME, kind=kind,
                ))
        else:
            info.modules.append(Module(
                name=root.name, path=".", build_system=NAME, kind="embedded-app",
            ))

        _add_commands(info, envs)


def _parse_platformio_ini(path: Path, rel: str,
                           info: ProjectInfo) -> dict[str, dict[str, str]]:
    """Parsea platformio.ini. Devuelve dict env_name → {platform, board, framework, …}."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    cfg = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=(";", "#"),
    )
    try:
        cfg.read_string(text)
    except configparser.Error:
        return {}

    envs: dict[str, dict[str, str]] = {}
    first = True

    for section in cfg.sections():
        if not section.startswith("env:"):
            continue
        env_name = section[4:]
        env_data: dict[str, str] = {}

        for key in ("platform", "board", "framework", "upload_port", "monitor_speed"):
            if cfg.has_option(section, key):
                env_data[key] = cfg.get(section, key).strip()

        if cfg.has_option(section, "lib_deps"):
            raw = cfg.get(section, "lib_deps")
            libs = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if libs:
                env_data["lib_deps_raw"] = ", ".join(libs)

        envs[env_name] = env_data

        # Registrar hechos del primer entorno
        if first:
            first = False
            for fact_key, cfg_key in [
                ("pio.platform",      "platform"),
                ("pio.board",         "board"),
                ("pio.framework",     "framework"),
                ("pio.monitor_speed", "monitor_speed"),
            ]:
                val = env_data.get(cfg_key, "")
                if val:
                    info.set_fact(fact_key, Fact(
                        value=val, priority=P.BUILD,
                        evidence=[ev(rel, None, f"{cfg_key} = {val}")],
                        adapter=NAME,
                    ))
            if env_data.get("lib_deps_raw"):
                info.set_fact("pio.lib_deps", Fact(
                    value=env_data["lib_deps_raw"], priority=P.BUILD,
                    evidence=[ev(rel, None, "lib_deps")],
                    adapter=NAME,
                ))

    return envs


def _add_commands(info: ProjectInfo, envs: dict[str, dict[str, str]]) -> None:
    # Si hay múltiples envs, usar el primero como ejemplo
    env_flag = ""
    if len(envs) > 1:
        env_flag = f" -e {next(iter(envs))}"

    # Velocidad del monitor serie
    monitor_speed = ""
    if envs:
        first_env = next(iter(envs.values()))
        monitor_speed = first_env.get("monitor_speed", "")
    baud = f" --baud {monitor_speed}" if monitor_speed else ""

    info.add_command(Command(
        name="deps",
        shell="pio pkg install",
        ide_hint="PlatformIO IDE: PIO Home → Libraries",
        success_hint="packages installed",
    ))
    info.add_command(Command(
        name="build",
        shell=f"pio run{env_flag}",
        ide_hint="PlatformIO IDE: Build (✓ en barra inferior)",
        success_hint="SUCCESS",
    ))
    info.add_command(Command(
        name="test",
        shell=f"pio test{env_flag}",
        success_hint="PASSED",
    ))
    info.add_command(Command(
        name="run",
        shell=f"pio run{env_flag} --target upload",
        ide_hint="PlatformIO IDE: Upload (→ en barra inferior)",
        success_hint="SUCCESS",
    ))
    info.add_command(Command(
        name="monitor",
        shell=f"pio device monitor{baud}",
        ide_hint="PlatformIO IDE: Monitor (enchufe en barra inferior)",
        success_hint="--- Miniterm on",
    ))
