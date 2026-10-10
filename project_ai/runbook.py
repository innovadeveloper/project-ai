"""
runbook.py — Genera RUNBOOK.md con pasos de build/test/run del proyecto.

Lee ProjectInfo (y opcionalmente DoctorReport) y produce pasos ordenados:
  setup → service → deps → configure → generate → build → test → run

Cada paso ejecutable lleva tee a .project-ai/logs/step-NN.log para
que el usuario pueda releerlo y pasarlo a triage si hay un error.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .model import ProjectInfo

OUTPUT_DIR   = ".project-ai"
LOG_DIR      = ".project-ai/logs"
RUNBOOK_FILE = "RUNBOOK.md"

# Orden canónico de pasos ejecutables del proyecto
_KIND_ORDER = ["deps", "configure", "generate", "build", "test", "run"]

_KIND_TITLES: dict[str, str] = {
    "setup":     "Preparación del entorno",
    "service":   "Servicios de soporte",
    "deps":      "Instalar dependencias",
    "configure": "Configurar el proyecto",
    "generate":  "Generar código / recursos",
    "build":     "Compilar",
    "test":      "Ejecutar pruebas",
    "run":       "Ejecutar la aplicación",
}

# Instrucciones de instalación de servicios por OS
_SERVICE_INSTALL: dict[str, dict[str, str]] = {
    "postgresql": {
        "macos": "brew install postgresql@15 && brew services start postgresql@15",
        "linux": "sudo apt-get install -y postgresql && sudo systemctl start postgresql",
    },
    "mysql": {
        "macos": "brew install mysql && brew services start mysql",
        "linux": "sudo apt-get install -y mysql-server && sudo systemctl start mysql",
    },
    "redis": {
        "macos": "brew install redis && brew services start redis",
        "linux": "sudo apt-get install -y redis-server && sudo systemctl start redis-server",
    },
    "mqtt": {
        "macos": "brew install mosquitto && brew services start mosquitto",
        "linux": "sudo apt-get install -y mosquitto && sudo systemctl start mosquitto",
    },
    "kafka": {
        "macos": ("brew install kafka && brew services start zookeeper"
                  " && brew services start kafka"),
        "linux": "# Ver https://kafka.apache.org/quickstart",
    },
    "rabbitmq": {
        "macos": "brew install rabbitmq && brew services start rabbitmq",
        "linux": ("sudo apt-get install -y rabbitmq-server"
                  " && sudo systemctl start rabbitmq-server"),
    },
    "mongodb": {
        "macos": ("brew install mongodb-community"
                  " && brew services start mongodb-community"),
        "linux": "# Ver https://www.mongodb.com/docs/manual/installation/",
    },
}


# --------------------------------------------------------------------------
# Tipos de salida
# --------------------------------------------------------------------------

@dataclass
class RunStep:
    """Un paso del runbook."""
    number: int
    kind: str       # setup | service | deps | configure | build | test | run | ...
    title: str
    shell: str | None = None    # comando (con tee si ejecutable); None = informativo
    cwd: str = "."
    ide_hint: str | None = None
    success_if: str | None = None
    on_fail: str | None = None
    note: str | None = None
    items: list[str] = field(default_factory=list)  # lista de acciones (paso setup)


@dataclass
class RunbookResult:
    """Resultado completo del runbook generado."""
    root: str
    steps: list[RunStep]
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def ok(self) -> bool:
        """True si no hay warnings ni pasos de setup pendientes."""
        return not self.warnings and not any(s.kind == "setup" for s in self.steps)

    def to_md(self) -> str:
        lines: list[str] = [
            "# RUNBOOK",
            "",
            f"Generado: {self.generated_at}",
            "",
            ("> Ejecuta cada paso en orden. Si falla, corre"
             " `project-ai triage .project-ai/logs/step-NN.log`."),
            "",
        ]

        if not self.steps:
            lines.append(
                "_No se detectaron pasos. Ejecuta `project-ai recon` primero._"
            )
            return "\n".join(lines)

        for step in self.steps:
            lines += ["---", ""]
            lines.append(f"## Paso {step.number} — {step.title}")
            lines.append("")

            if step.items:
                for item in step.items:
                    lines.append(f"- {item}")
                lines.append("")

            if step.shell:
                lines.append("```bash")
                if step.cwd != ".":
                    lines.append(f"# desde: {step.cwd}")
                lines.append(step.shell)
                lines.append("```")
                lines.append("")

            details: list[str] = []
            if step.ide_hint:
                details.append(f"**IDE**: {step.ide_hint}")
            if step.success_if:
                details.append(f"**Éxito si**: {step.success_if}")
            if step.on_fail:
                details.append(f"**Si falla**: `{step.on_fail}`")
            if details:
                lines += details
                lines.append("")

            if step.note:
                lines.append(f"> {step.note}")
                lines.append("")

        return "\n".join(lines)


# --------------------------------------------------------------------------
# Función principal
# --------------------------------------------------------------------------

def runbook(
    path: str | Path,
    *,
    info: ProjectInfo | None = None,
    doctor_report=None,
    os_hint: str | None = None,
    write: bool = True,
) -> RunbookResult:
    """Genera el runbook del proyecto en `path`.

    Args:
        path:          Raíz del proyecto.
        info:          ProjectInfo ya cargado; si None se carga/crea.
        doctor_report: DoctorReport opcional; sus fallos se añaden al paso 0.
        os_hint:       "macos" | "linux" para instrucciones de servicios.
        write:         Si True escribe .project-ai/RUNBOOK.md.
    """
    root = Path(path).resolve()

    if info is None:
        json_path = root / OUTPUT_DIR / "project.json"
        if json_path.exists():
            try:
                info = ProjectInfo.load(json_path)
            except (TypeError, ValueError, KeyError):
                from .recon import recon as _recon
                info = _recon(root, write=True)
        else:
            from .recon import recon as _recon
            info = _recon(root, write=True)

    os_ = os_hint or _detect_os()

    # --- Recopilar pasos en orden -------------------------------------------
    raw: list[RunStep] = []

    setup_items = _collect_setup_items(doctor_report, info)
    if setup_items:
        raw.append(RunStep(
            number=0, kind="setup",
            title=_KIND_TITLES["setup"],
            items=setup_items,
            note="Resuelve estos problemas antes de continuar con los pasos siguientes.",
        ))

    raw.extend(_make_service_steps(info, os_))
    raw.extend(_make_cmd_steps(info))

    # --- Numerar y añadir tee -----------------------------------------------
    for i, step in enumerate(raw):
        step.number = i
        if step.shell and step.kind != "setup":
            log = f"{LOG_DIR}/step-{i:02d}.log"
            step.shell = _with_tee(step.shell, log)
            step.on_fail = f"project-ai triage {log}"

    result = RunbookResult(
        root=str(root),
        steps=raw,
        warnings=list(info.warnings),
    )

    if write:
        _write_runbook(root, result)

    return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _collect_setup_items(doctor_report, info=None) -> list[str]:
    """Extrae ítems de setup de un DoctorReport y de config.required_env."""
    items: list[str] = []

    if doctor_report is not None:
        bad_statuses = {"missing", "wrong_version"}
        for check in doctor_report.checks:
            if check.status not in bad_statuses:
                continue
            msg = f"**{check.key}**"
            if check.needed:
                msg += f": necesitas `{check.needed}`"
            if check.found:
                msg += f", tienes `{check.found}`"
            elif check.status == "missing":
                msg += ", no encontrado en PATH"
            if check.install_cmd:
                msg += f" → `{check.install_cmd}`"
            items.append(msg)

    # Variables de entorno requeridas → generar .env.example si no existe
    if info is not None:
        env_fact = info.facts.get("config.required_env")
        if env_fact and isinstance(env_fact.value, list) and env_fact.value:
            var_lines = "\n".join(f"{v}=" for v in env_fact.value)
            items.append(
                f"**Variables de entorno requeridas** (sin valor por defecto):\n"
                f"  Crea un archivo `.env` con los valores reales:\n"
                f"  ```\n{var_lines}\n  ```"
            )

    return items


def _make_service_steps(info: ProjectInfo, os_: str) -> list[RunStep]:
    """Genera pasos para arrancar los servicios de soporte."""
    if not info.services:
        return []

    compose_files: list[str] = []
    f = info.facts.get("hints.compose_files")
    if f and isinstance(f.value, list):
        compose_files = f.value

    steps: list[RunStep] = []
    for svc in info.services:
        kind = svc.kind
        title = f"{_KIND_TITLES['service']} — {kind}"

        if compose_files:
            shell = f"docker compose up -d {kind}"
            note = f"Definido en {compose_files[0]}"
        else:
            install = _SERVICE_INSTALL.get(kind, {})
            shell = install.get(os_) or install.get("macos") or f"# instalar {kind}"
            note = "Instala el servicio si no está disponible en tu máquina."

        steps.append(RunStep(
            number=0, kind="service", title=title, shell=shell, note=note,
        ))

    return steps


def _run_success_hint(info: ProjectInfo) -> str | None:
    """Genera un hint de éxito para el paso 'run' si hay puerto Spring conocido."""
    port_fact = info.facts.get("spring.port")
    if not port_fact:
        return None
    port = port_fact.value
    ctx_fact = info.facts.get("spring.context_path")
    ctx = (ctx_fact.value if ctx_fact else "").rstrip("/")
    return f"log 'Started ... in N seconds' y: curl http://localhost:{port}{ctx}/actuator/health"


def _make_cmd_steps(info: ProjectInfo) -> list[RunStep]:
    """Construye pasos ejecutables a partir de info.commands en orden canónico."""
    steps: list[RunStep] = []
    seen: set[str] = set()

    # Calcular hint de éxito para el paso run basado en spring.port
    run_success = _run_success_hint(info)

    for kind in _KIND_ORDER:
        cmd = info.commands.get(kind)
        if cmd is None:
            continue
        success = cmd.success_hint
        if kind == "run" and run_success:
            success = run_success
        steps.append(RunStep(
            number=0,
            kind=kind,
            title=_KIND_TITLES.get(kind, kind.capitalize()),
            shell=cmd.shell,
            cwd=cmd.cwd,
            ide_hint=cmd.ide_hint,
            success_if=success,
        ))
        seen.add(kind)

    # Comandos con nombres personalizados fuera del orden canónico
    canonical_set = set(_KIND_ORDER) | {"setup", "service"}
    for name, cmd in info.commands.items():
        if name in canonical_set or name in seen:
            continue
        steps.append(RunStep(
            number=0,
            kind=name,
            title=_KIND_TITLES.get(name, name.replace("_", " ").capitalize()),
            shell=cmd.shell,
            cwd=cmd.cwd,
            ide_hint=cmd.ide_hint,
            success_if=cmd.success_hint,
        ))
        seen.add(name)

    return steps


def _with_tee(shell: str, log: str) -> str:
    """Envuelve un comando para guardar stdout+stderr con tee."""
    shell = shell.rstrip()
    # Subshell si el comando ya contiene tuberías o redirecciones
    if "|" in shell or ">" in shell:
        return f"({shell}) 2>&1 | tee {log}"
    return f"{shell} 2>&1 | tee {log}"


def _detect_os() -> str:
    return "macos" if sys.platform == "darwin" else "linux"


def _write_runbook(root: Path, result: RunbookResult) -> Path:
    out_dir = root / OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / RUNBOOK_FILE
    out_file.write_text(result.to_md(), encoding="utf-8")
    return out_file
