"""
doctor.py — Comprueba que la máquina tiene los requisitos del proyecto.

Lee requirements de un ProjectInfo (o corre recon si no se pasa) y
verifica versiones con comandos de versión. Solo lee la máquina;
nunca instala ni modifica el proyecto analizado.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .model import Fact, ProjectInfo


# --------------------------------------------------------------------------
# Tipos de salida
# --------------------------------------------------------------------------

class CheckStatus(str, Enum):
    OK            = "ok"
    MISSING       = "missing"        # herramienta no encontrada en PATH
    WRONG_VERSION = "wrong_version"  # fuera del rango requerido
    UNKNOWN       = "unknown"        # encontrada pero versión no parseable
    NA            = "na"             # no hay checker para esta clave


@dataclass
class Check:
    """Resultado de verificar un requisito en la máquina actual."""
    key: str
    needed: str | None       # versión requerida (de requirements)
    found: str | None        # versión detectada en PATH
    status: CheckStatus
    ceiling: str | None = None       # jdk_ceiling si aplica
    install_cmd: str | None = None   # cómo instalarlo si falta/incorrecto
    note: str | None = None
    available: list[str] = field(default_factory=list)  # JDKs instalados


@dataclass
class ServiceCheck:
    """Resultado de sondar un puerto TCP."""
    name: str
    port: int
    open: bool


@dataclass
class DoctorReport:
    root: str
    checks: list[Check]
    services: list[ServiceCheck]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def ok(self) -> bool:
        """True si no hay ningún ❌ (MISSING o WRONG_VERSION)."""
        return all(
            c.status not in (CheckStatus.MISSING, CheckStatus.WRONG_VERSION)
            for c in self.checks
        )

    def to_md(self) -> str:
        return _render_md(self)


# --------------------------------------------------------------------------
# Tabla de comandos de versión por clave de requisito
# --------------------------------------------------------------------------

# (args, regex sobre stdout+stderr combinado)
_TOOL_CMDS: dict[str, tuple[list[str], re.Pattern]] = {
    "maven":  (["mvn", "-v"],            re.compile(r'Apache Maven\s+(\S+)')),
    "gradle": (["gradle", "--version"],   re.compile(r'Gradle\s+(\S+)')),
    "cmake":  (["cmake", "--version"],    re.compile(r'cmake version\s+(\S+)')),
    "conan":  (["conan", "--version"],    re.compile(r'Conan version\s+(\S+)', re.I)),
    "ninja":  (["ninja", "--version"],    re.compile(r'(\d+\.\d+(?:\.\d+)?)')),
    "python": (["python3", "--version"],  re.compile(r'Python\s+(\S+)')),
    "node":   (["node", "-v"],            re.compile(r'v(\S+)')),
    "clang":  (["clang++", "--version"],  re.compile(r'version\s+(\d+\.\d+(?:\.\d+)?)')),
    "gcc":    (["g++", "--version"],      re.compile(r'(\d+\.\d+\.\d+)')),
}

# Puertos TCP por defecto para servicios de runtime
_SERVICE_PORTS: dict[str, int] = {
    "postgresql": 5432,
    "mysql":      3306,
    "redis":      6379,
    "mqtt":       1883,
    "kafka":      9092,
    "rabbitmq":   5672,
}

# Claves que se procesan junto con otra (no como entrada independiente)
_SKIP_KEYS = {"jdk_ceiling", "cxx_standard"}


# --------------------------------------------------------------------------
# Función principal
# --------------------------------------------------------------------------

def doctor(
    path: str | Path,
    *,
    info: ProjectInfo | None = None,
    skip_services: bool = False,
    os_hint: str | None = None,
    write: bool = False,
) -> DoctorReport:
    """Comprueba que la máquina tiene los requisitos detectados por recon.

    Si write=True, escribe .project-ai/env-report.md.
    Pasa info para evitar que doctor vuelva a ejecutar el scanner (útil en tests).
    """
    root = Path(path).resolve()
    if info is None:
        from .recon import recon as _recon
        json_path = root / ".project-ai" / "project.json"
        if json_path.exists():
            try:
                info = ProjectInfo.load(json_path)
            except (TypeError, ValueError, KeyError):
                # project.json con formato incompatible → regenerar
                info = _recon(root, write=True)
        else:
            info = _recon(root, write=False)

    os_ = os_hint or _detect_os()
    checks = _run_checks(info, os_)
    services = [] if skip_services else _check_services(info)
    report = DoctorReport(root=str(root), checks=checks, services=services)

    if write:
        _write_report(root, report)

    return report


# --------------------------------------------------------------------------
# Checks de requisitos
# --------------------------------------------------------------------------

def _run_checks(info: ProjectInfo, os_: str) -> list[Check]:
    checks = []
    for key, fact in info.requirements.items():
        if key in _SKIP_KEYS:
            continue
        check = _check_one(key, fact, info, os_)
        if check is not None:
            checks.append(check)
    return checks


def _check_one(key: str, fact: Fact, info: ProjectInfo, os_: str) -> Check | None:
    if key == "jdk":
        return _check_jdk(fact, info, os_)
    if key == "tomcat":
        return _check_tomcat(fact, os_)
    if key == "android":
        return _check_android(fact)

    tool = _TOOL_CMDS.get(key)
    if tool is None:
        return Check(key=key, needed=fact.value, found=None,
                     status=CheckStatus.NA,
                     note="sin checker para esta clave de requisito")

    args, pattern = tool
    raw = _run_cmd(args)
    if raw is None:
        return Check(key=key, needed=fact.value, found=None,
                     status=CheckStatus.MISSING,
                     install_cmd=_install_cmd(key, fact.value, os_))

    m = pattern.search(raw)
    if not m:
        return Check(key=key, needed=fact.value, found=None,
                     status=CheckStatus.UNKNOWN,
                     note="herramienta disponible pero versión no parseable")

    found = m.group(1)
    status = _compare(found, fact.value, None)
    return Check(
        key=key, needed=fact.value, found=found, status=status,
        install_cmd=_install_cmd(key, fact.value, os_) if status != CheckStatus.OK else None,
    )


def _check_jdk(fact: Fact, info: ProjectInfo, os_: str) -> Check:
    needed = fact.value
    ceiling_fact = info.requirements.get("jdk_ceiling")
    ceiling = ceiling_fact.value if ceiling_fact else None

    raw = _run_cmd(["java", "-version"])
    avail = _list_jdks(os_)

    if raw is None:
        return Check(key="jdk", needed=needed, found=None, ceiling=ceiling,
                     status=CheckStatus.MISSING,
                     install_cmd=_install_cmd("jdk", needed, os_),
                     available=avail)

    found_tuple = _parse_jdk_major(raw)
    if not found_tuple:
        return Check(key="jdk", needed=needed, found=None, ceiling=ceiling,
                     status=CheckStatus.UNKNOWN, available=avail)

    # Mostrar versión completa ("17.0.12") para el informe, comparar el número mayor
    found_full = ".".join(str(n) for n in found_tuple)
    status = _compare(found_full, needed, ceiling)
    return Check(
        key="jdk", needed=needed, found=found_full, ceiling=ceiling,
        status=status,
        install_cmd=_install_cmd("jdk", needed, os_) if status != CheckStatus.OK else None,
        available=avail,
    )


def _check_tomcat(fact: Fact, os_: str) -> Check:
    needed = fact.value
    version_sh = _find_tomcat_version_sh(os_)
    if version_sh is None:
        return Check(key="tomcat", needed=needed, found=None,
                     status=CheckStatus.MISSING,
                     install_cmd=_install_cmd("tomcat", needed, os_))

    raw = _run_cmd([str(version_sh)])
    if raw:
        m = re.search(r'Server number:\s+(\S+)', raw)
        if m:
            found = m.group(1)       # p.ej. "9.0.82.0"
            major = found.split(".")[0]
            status = _compare(major, needed, None)
            return Check(key="tomcat", needed=needed, found=found, status=status,
                         install_cmd=_install_cmd("tomcat", needed, os_) if status != CheckStatus.OK else None)
    return Check(key="tomcat", needed=needed, found=None, status=CheckStatus.UNKNOWN)


def _check_android(fact: Fact) -> Check:
    needed = fact.value
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk and Path(sdk).exists():
        return Check(key="android", needed=needed, found=sdk, status=CheckStatus.OK)
    for p in [
        Path.home() / "Library" / "Android" / "sdk",
        Path.home() / "Android" / "Sdk",
    ]:
        if p.exists():
            return Check(key="android", needed=needed, found=str(p), status=CheckStatus.OK)
    return Check(key="android", needed=needed, found=None, status=CheckStatus.MISSING,
                 install_cmd="Instala Android Studio y configura ANDROID_HOME")


# --------------------------------------------------------------------------
# Checks de servicios TCP
# --------------------------------------------------------------------------

def _check_services(info: ProjectInfo) -> list[ServiceCheck]:
    checks: list[ServiceCheck] = []
    seen: set[str] = set()
    for svc in info.services:
        if svc.kind in seen:
            continue
        seen.add(svc.kind)
        port = _SERVICE_PORTS.get(svc.kind)
        if port is None:
            continue
        checks.append(ServiceCheck(name=svc.kind, port=port,
                                   open=_probe_tcp("localhost", port)))
    return checks


# --------------------------------------------------------------------------
# Helpers de bajo nivel
# --------------------------------------------------------------------------

def _run_cmd(args: list[str], *, timeout: int = 10) -> str | None:
    """Ejecuta un comando y devuelve stdout+stderr combinados, o None si falla."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        combined = (r.stdout + "\n" + r.stderr).strip()
        return combined or None
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
        return None


def _probe_tcp(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_jdk_major(raw: str) -> tuple[int, ...]:
    """Extrae versión Java de la salida de 'java -version'.
    "1.8.0_392" → (8, 0, 392); "17.0.12" → (17, 0, 12)
    """
    m = re.search(r'version\s+"?([\d._]+)"?', raw, re.I)
    if not m:
        return ()
    vs = re.split(r'[._]', m.group(1))
    nums: list[int] = []
    for v in vs:
        try:
            nums.append(int(v))
        except ValueError:
            break
    if not nums:
        return ()
    # Legacy: "1.8.x" es Java 8
    if nums[0] == 1 and len(nums) > 1:
        return tuple(nums[1:])
    return tuple(nums)


def _parse_ver(s: str) -> tuple[int, ...]:
    """"3.27.4" → (3, 27, 4). Para comparación semántica."""
    parts = re.split(r'[._-]', s.strip())
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            break
    return tuple(nums) if nums else (0,)


def _compare(found: str, needed: str | None, ceiling: str | None) -> CheckStatus:
    """Compara versiones semánticamente. Devuelve OK o WRONG_VERSION."""
    fv = _parse_ver(found)
    if needed:
        nv = _parse_ver(needed)
        if fv < nv:
            return CheckStatus.WRONG_VERSION
    if ceiling:
        cv = _parse_ver(ceiling)
        if fv > cv:
            return CheckStatus.WRONG_VERSION
    return CheckStatus.OK


def _detect_os() -> str:
    return "macos" if sys.platform == "darwin" else "linux"


def _find_tomcat_version_sh(os_: str) -> Path | None:
    for var in ("CATALINA_HOME", "CATALINA_BASE"):
        val = os.environ.get(var)
        if val:
            p = Path(val) / "bin" / "version.sh"
            if p.exists():
                return p
    if os_ == "macos":
        for base in [
            Path("/opt/homebrew/opt/tomcat/libexec"),
            Path("/opt/homebrew/opt/tomcat@9/libexec"),
            Path("/opt/homebrew/opt/tomcat@10/libexec"),
            Path("/opt/homebrew/opt/tomcat@11/libexec"),
            Path("/usr/local/opt/tomcat/libexec"),
            Path("/usr/local/opt/tomcat@9/libexec"),
        ]:
            p = base / "bin" / "version.sh"
            if p.exists():
                return p
    return None


def _list_jdks(os_: str) -> list[str]:
    jdks: list[str] = []
    if os_ == "macos":
        jdks.extend(_list_jdks_macos())
    jdks.extend(_list_jdks_sdkman())
    return jdks


def _list_jdks_macos() -> list[str]:
    raw = _run_cmd(["/usr/libexec/java_home", "-V"])
    if not raw:
        return []
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and re.match(r'\d', line.strip())
    ]


def _list_jdks_sdkman() -> list[str]:
    sdkman_dir = Path.home() / ".sdkman" / "candidates" / "java"
    if not sdkman_dir.exists():
        return []
    return sorted(
        d.name for d in sdkman_dir.iterdir()
        if d.is_dir() and d.name != "current"
    )


def _install_cmd(key: str, needed: str | None, os_: str) -> str | None:
    if os_ == "macos":
        cmds: dict[str, str] = {
            "jdk":    "sdk install java <versión>  # SDKMAN   o   brew install --cask temurin",
            "maven":  "brew install maven           # o: sdk install maven",
            "cmake":  "brew install cmake",
            "conan":  "pip install conan",
            "ninja":  "brew install ninja",
            "python": "brew install python",
            "node":   "brew install node",
            "clang":  "brew install llvm",
            "gcc":    "brew install gcc",
            "tomcat": (f"brew install tomcat@{needed}" if needed else "brew install tomcat"),
        }
    else:
        cmds = {
            "jdk":    "sdk install java <versión>  # SDKMAN   o   apt install default-jdk",
            "maven":  "apt install maven",
            "cmake":  "apt install cmake",
            "conan":  "pip install conan",
            "ninja":  "apt install ninja-build",
            "python": "apt install python3",
            "node":   "apt install nodejs npm",
            "clang":  "apt install clang",
            "gcc":    "apt install g++",
            "tomcat": f"apt install tomcat{needed or ''}",
        }
    return cmds.get(key)


# --------------------------------------------------------------------------
# Render Markdown
# --------------------------------------------------------------------------

_STATUS_ICON = {
    CheckStatus.OK:            "✅",
    CheckStatus.MISSING:       "❌",
    CheckStatus.WRONG_VERSION: "❌",
    CheckStatus.UNKNOWN:       "⚠️",
    CheckStatus.NA:            "⚠️",
}

_STATUS_LABEL = {
    CheckStatus.OK:            "OK",
    CheckStatus.MISSING:       "No encontrado",
    CheckStatus.WRONG_VERSION: "Versión incorrecta",
    CheckStatus.UNKNOWN:       "No determinado",
    CheckStatus.NA:            "Sin verificador",
}


def _render_md(report: DoctorReport) -> str:
    lines: list[str] = [
        "# Informe de entorno\n",
        f"_Generado: {report.generated_at}_\n",
    ]

    lines += ["## Requisitos\n",
              "| Clave | Necesario | Encontrado | Estado |",
              "|---|---|---|---|"]
    for c in report.checks:
        if c.ceiling:
            needed_col = f"≥ {c.needed}, ≤ {c.ceiling}"
        elif c.needed:
            needed_col = f"≥ {c.needed}"
        else:
            needed_col = "—"
        found_col = c.found or "—"
        icon = _STATUS_ICON[c.status]
        label = _STATUS_LABEL[c.status]
        lines.append(f"| {c.key} | {needed_col} | {found_col} | {icon} {label} |")
    lines.append("")

    jdk_check = next((c for c in report.checks if c.key == "jdk"), None)
    if jdk_check and jdk_check.available:
        lines += ["### JDKs disponibles en esta máquina\n"]
        for j in jdk_check.available:
            lines.append(f"- {j}")
        lines.append("")

    if report.services:
        lines += ["## Servicios de runtime\n",
                  "| Servicio | Puerto | Estado |",
                  "|---|---|---|"]
        for s in report.services:
            icon = "✅" if s.open else "❌"
            label = "Activo" if s.open else "No responde"
            lines.append(f"| {s.name} | {s.port} | {icon} {label} |")
        lines.append("")

    actions: list[str] = []
    for c in report.checks:
        if c.status in (CheckStatus.MISSING, CheckStatus.WRONG_VERSION) and c.install_cmd:
            if c.status == CheckStatus.WRONG_VERSION:
                desc = f"versión incorrecta (encontrado {c.found}"
                if c.ceiling:
                    desc += f", necesario entre {c.needed} y {c.ceiling})"
                else:
                    desc += f", necesario ≥ {c.needed})"
            else:
                desc = "no encontrado"
            actions.append(f"**{c.key}**: {desc} — `{c.install_cmd}`")
    for s in report.services:
        if not s.open:
            svc_cmd = _SERVICE_START_CMDS.get(s.name)
            entry = f"**{s.name}** (:{s.port}): puerto no responde"
            if svc_cmd:
                entry += f" — `{svc_cmd}`"
            actions.append(entry)

    if actions:
        lines += ["## Acciones recomendadas\n"]
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    return "\n".join(lines)


_SERVICE_START_CMDS: dict[str, str] = {
    "postgresql": "brew services start postgresql",
    "mysql":      "brew services start mysql",
    "redis":      "brew services start redis",
    "kafka":      "brew services start kafka",
    "rabbitmq":   "brew services start rabbitmq",
}


# --------------------------------------------------------------------------
# Escritura de env-report.md
# --------------------------------------------------------------------------

def _write_report(root: Path, report: DoctorReport) -> Path:
    out_dir = root / ".project-ai"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "env-report.md"
    out_file.write_text(report.to_md(), encoding="utf-8")
    return out_file
