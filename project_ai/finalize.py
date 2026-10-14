"""
finalize.py — Cierra el ciclo: marca comandos verificados y genera AGENTS.md.

Flujo:
  1. Escanea .project-ai/logs/step-*.log buscando señales de éxito por kind.
  2. Marca los comandos exitosos como Status.VERIFIED en project.json.
  3. Lee .project-ai/journal.md para extraer trampas conocidas.
  4. Genera AGENTS.md (≤ 200 líneas) en la raíz del proyecto.

AGENTS.md es el archivo que lee el agente local (OpenCode + Ollama + Serena)
para trabajar sobre el proyecto sin explorar a ciegas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .model import ProjectInfo, Status
from .notes import ensure_notes_template, load_notes


OUTPUT_DIR   = ".project-ai"
LOGS_DIR     = ".project-ai/logs"
AGENTS_FILE  = "AGENTS.md"

_MAX_ENDPOINTS = 15   # cap para no superar 200 líneas

# --------------------------------------------------------------------------
# Señales de éxito por kind de comando
# (se buscan en el contenido del log con re.search)
# --------------------------------------------------------------------------
_SUCCESS: dict[str, list[re.Pattern]] = {
    "build": [
        re.compile(r"BUILD SUCCESS", re.IGNORECASE),
        re.compile(r"\[100%\] Built target"),
        re.compile(r"-- Build files have been written"),   # cmake --build exitoso a veces
        re.compile(r"make\[\d+\]: .* up to date"),
    ],
    "test": [
        re.compile(r"Tests run:\s*\d+,\s*Failures:\s*0,\s*Errors:\s*0"),
        re.compile(r"\d+ tests? passed"),
        re.compile(r"All tests passed"),
        re.compile(r"\d+/\d+ Test #\d+:.*Passed"),
    ],
    "deps": [
        re.compile(r"Install completed", re.IGNORECASE),
        re.compile(r"Graph nodes to build"),
        re.compile(r"BUILD SUCCESS", re.IGNORECASE),       # mvn dependency:go-offline
    ],
    "configure": [
        re.compile(r"-- Build files have been written"),
        re.compile(r"-- Configuring done"),
        re.compile(r"CMake generate step for .* completed"),
    ],
    "generate": [
        re.compile(r"BUILD SUCCESS", re.IGNORECASE),
    ],
    "run": [
        re.compile(r"Started\s+\w+\s+in\s+[\d.]+\s+seconds"),
        re.compile(r"Tomcat started on port"),
        re.compile(r"Listening on port"),
        re.compile(r"Server is running"),
    ],
}


# --------------------------------------------------------------------------
# Tipos de salida
# --------------------------------------------------------------------------

@dataclass
class FinalizeResult:
    """Resultado de finalizar un proyecto."""
    root:       str
    verified:   list[str]          # kinds de comandos verificados
    agents_md:  str                # contenido de AGENTS.md
    warnings:   list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Función principal
# --------------------------------------------------------------------------

def finalize(
    path: str | Path,
    *,
    info: ProjectInfo | None = None,
    write: bool = True,
) -> FinalizeResult:
    """Finaliza el proyecto en `path`.

    Args:
        path:  Raíz del proyecto.
        info:  ProjectInfo ya cargado; si None se carga de project.json.
        write: Si True, actualiza project.json y escribe AGENTS.md.
    """
    root = Path(path).resolve()

    if info is None:
        json_path = root / OUTPUT_DIR / "project.json"
        if json_path.exists():
            try:
                info = ProjectInfo.load(json_path)
            except Exception:
                from .recon import recon as _recon
                info = _recon(root, write=True)
        else:
            from .recon import recon as _recon
            info = _recon(root, write=True)

    # 1. Detectar comandos verificados por los logs
    verified_kinds = _detect_verified(root, info)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 2. Marcar en info
    for kind in verified_kinds:
        if kind in info.commands:
            info.commands[kind].status = Status.VERIFIED

    # 3. Leer trampas del journal
    traps = _parse_journal_traps(root)

    # 4. Notas de dominio del usuario
    domain_notes = load_notes(root)

    # 5. Generar AGENTS.md
    agents_md = _generate_agents_md(root, info, verified_kinds, now, traps,
                                    domain_notes=domain_notes)

    if write:
        # Crear plantilla de notes.md si no existe aún
        ensure_notes_template(root)
        # Sobrescribir project.json con los estados verificados
        import json
        out_json = root / OUTPUT_DIR / "project.json"
        out_json.parent.mkdir(exist_ok=True)
        out_json.write_text(
            json.dumps(info.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # Escribir AGENTS.md en la raíz del proyecto
        (root / AGENTS_FILE).write_text(agents_md, encoding="utf-8")

    return FinalizeResult(
        root=str(root),
        verified=verified_kinds,
        agents_md=agents_md,
        warnings=list(info.warnings),
    )


# --------------------------------------------------------------------------
# Detección de éxito en logs
# --------------------------------------------------------------------------

def _detect_verified(root: Path, info: ProjectInfo) -> list[str]:
    """Lee los logs y devuelve los kinds de comandos que tuvieron éxito."""
    logs_dir = root / LOGS_DIR
    if not logs_dir.is_dir():
        return []

    # Acumula todos los contenidos de logs en un único string para buscar
    all_text = "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in sorted(logs_dir.glob("step-*.log"))
    )

    verified: list[str] = []
    for kind, patterns in _SUCCESS.items():
        if kind not in info.commands:
            continue
        if any(rx.search(all_text) for rx in patterns):
            verified.append(kind)

    return verified


# --------------------------------------------------------------------------
# Lectura del journal
# --------------------------------------------------------------------------

def _parse_journal_traps(root: Path) -> list[str]:
    """Extrae ítems de trampas conocidas del journal (entradas N0)."""
    journal = root / OUTPUT_DIR / "journal.md"
    if not journal.exists():
        return []

    traps: list[str] = []
    text = journal.read_text(encoding="utf-8")
    # Cada bloque: ## <ts> — <log>  ...  Nivel: N0  ...  Causa: ...  Arreglo: ...
    for block in re.split(r"\n##\s+", text):
        if "**Nivel**: N0" not in block:
            continue
        causa  = re.search(r"\*\*Causa\*\*:\s*(.+)", block)
        arreglo = re.search(r"\*\*Arreglo\*\*:\s*(.+)", block)
        if causa and arreglo:
            traps.append(f"{causa.group(1).strip()} → {arreglo.group(1).strip()}")

    return list(dict.fromkeys(traps))  # deduplicar conservando orden


# --------------------------------------------------------------------------
# Generación de AGENTS.md (≤ 200 líneas)
# --------------------------------------------------------------------------

def _generate_agents_md(
    root: Path,
    info: ProjectInfo,
    verified: list[str],
    generated_at: str,
    traps: list[str],
    *,
    domain_notes: str | None = None,
) -> str:
    lines: list[str] = []

    # --- Cabecera -----------------------------------------------------------
    lines += [
        "# AGENTS.md",
        "",
        f"> Generado: {generated_at} · `project-ai finalize`",
        "> Lee este archivo antes de preguntar o editar código.",
        "",
    ]

    # --- §0. Contexto del proyecto (notas del usuario) ----------------------
    if domain_notes:
        lines += [
            "## 0. Contexto del proyecto",
            "",
            domain_notes.strip(),
            "",
        ]

    # --- 1. Proyecto --------------------------------------------------------
    stacks   = ", ".join(info.stack_names()) or "desconocido"
    n_mod    = len(info.modules)
    mod_txt  = f"{n_mod} módulo{'s' if n_mod != 1 else ''}" if n_mod else ""
    desc     = " · ".join(filter(None, [stacks, mod_txt]))
    proj_name = root.name

    lines += [
        "## 1. Proyecto",
        "",
        f"**Nombre**: `{proj_name}`  ",
        f"**Stack**: {desc}  ",
        f"**Raíz**: `{root}`  ",
        "",
    ]

    # --- 2. Comandos verificados --------------------------------------------
    lines += ["## 2. Comandos", ""]

    has_cmds = bool(info.commands)
    if has_cmds:
        lines.append("| Paso | Comando | Estado |")
        lines.append("|------|---------|--------|")
        for name, cmd in info.commands.items():
            estado = "✅ verificado" if name in verified else "⬜ sin verificar"
            shell_short = cmd.shell[:60] + ("…" if len(cmd.shell) > 60 else "")
            lines.append(f"| {name} | `{shell_short}` | {estado} |")
        lines.append("")
        lines.append("> Envuelve con `2>&1 | tee .project-ai/logs/step-NN.log`")
    else:
        lines.append("_Sin comandos detectados — ejecuta `project-ai recon`._")

    lines.append("")

    # --- 3. Entorno ---------------------------------------------------------
    lines += ["## 3. Entorno", ""]

    if info.requirements:
        lines.append("| Requisito | Versión mínima | Techo |")
        lines.append("|-----------|---------------|-------|")
        for key, fact in info.requirements.items():
            ceiling = info.requirements.get(f"{key}_ceiling")
            ceil_val = ceiling.value if ceiling else "—"
            lines.append(f"| {key} | {fact.value or '—'} | {ceil_val} |")
        lines.append("")

    if info.services:
        svc_txt = ", ".join(s.kind for s in info.services)
        lines.append(f"**Servicios requeridos**: {svc_txt}  ")
        lines.append("")

    env_vars = _get_env_vars(info)
    if env_vars:
        lines.append(f"**Variables de entorno**: {', '.join(f'`{v}`' for v in env_vars)}  ")
        lines.append("")

    if not info.requirements and not info.services:
        lines.append("_Sin requisitos de entorno detectados._")
        lines.append("")

    # --- 4. Mapa del proyecto -----------------------------------------------
    lines += ["## 4. Mapa", ""]

    if info.modules:
        mod_list = "  \n".join(
            f"- `{m.path}` ({m.kind or m.build_system})" for m in info.modules[:10]
        )
        lines.append("**Módulos**:  ")
        lines.append(mod_list)
        lines.append("")

    if info.entry_points:
        lines.append("**Entry points**:  ")
        for ep in info.entry_points[:5]:
            lines.append(f"- `{ep.symbol}` ({ep.kind}) — `{ep.file}`  ")
        lines.append("")

    if info.endpoints:
        lines.append(f"**Endpoints REST** ({len(info.endpoints)} total):  ")
        for ep in info.endpoints[:_MAX_ENDPOINTS]:
            lines.append(f"- `{ep.method} {ep.path}` → `{ep.handler}`  ")
        if len(info.endpoints) > _MAX_ENDPOINTS:
            lines.append(
                f"- _(y {len(info.endpoints) - _MAX_ENDPOINTS} más — ver repo-map.md)_  "
            )
        lines.append("")

    if not info.modules and not info.entry_points and not info.endpoints:
        lines.append("_Sin mapa disponible — ver `.project-ai/repo-map.md`._")
        lines.append("")

    # --- 5. Trampas conocidas -----------------------------------------------
    lines += ["## 5. Trampas conocidas", ""]

    if traps:
        for trap in traps[:8]:
            lines.append(f"- {trap}  ")
        lines.append("")
    else:
        lines.append("_(Sin entradas en el journal aún — se añaden tras triage.)_")
        lines.append("")

    # --- 6. Navegación ------------------------------------------------------
    nav_lines = [
        "- `.project-ai/repo-map.md` — mapa compacto de símbolos (clases, firmas)",
        "- `.project-ai/project.json` — datos completos del proyecto con evidencia",
    ]
    if (root / OUTPUT_DIR / "schema-map.md").exists():
        nav_lines.append(
            "- `.project-ai/schema-map.md` — esquema SQL (tablas, vistas, funciones)"
        )
    lines += ["## 6. Navegación", ""] + nav_lines + [""]

    # --- Reglas de Trabajo --------------------------------------------------
    lines += [
        "## Reglas de Trabajo (Prioridad Alta)",
        "",
        "- **Transparencia**: Si tu respuesta se basa en una lectura parcial, dilo explícitamente.",
        "- **Firma de métodos**: Antes de modificar un método, cita su firma actual tal como aparece en el archivo.",
        "- **Sugerir ≠ Aplicar**: Cuando propongas cambios de código, pregunta explícitamente si debo pedirte que los apliques con edit/write, o si solo quieres mostrarlos.",
        "- **Verificación previa**: Antes de proponer código nuevo, verifica si ya existe algo similar en el proyecto (grep de clases/dependencias relacionadas).",
        "- Responde siempre en español.",
        "- No afirmes formatos, valores, topics ni payloads sin haber leído el código que los genera. Cita archivo y línea.",
        "- **Lectura completa obligatoria**: Antes de listar, resumir o modificar un archivo, léelo COMPLETO.",
        "  Solo usa offset/limit si el archivo supera las 500 líneas, y en ese caso,",
        "  sigue leyendo en bloques consecutivos hasta el final.",
        "  NUNCA saltes a un offset arbitrario sin haber leído el rango anterior completo.",
        "",
    ]

    text = "\n".join(lines)
    return text


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _get_env_vars(info: ProjectInfo) -> list[str]:
    """Extrae variables de entorno requeridas de los facts."""
    env_fact = info.facts.get("config.required_env")
    if env_fact and isinstance(env_fact.value, list):
        return env_fact.value
    return []
