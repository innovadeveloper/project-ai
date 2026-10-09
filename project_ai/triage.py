"""
triage.py — Diagnostica un log de error: N0 (reglas) → N1/N2 (LLM) → N3 (humano).

Flujo:
  1. Recorta el log: primer ERROR/FAILED + 40 líneas, sin ruido de descargas.
  2. N0: busca coincidencia en rules/*.toml (determinista, sin LLM).
  3. N1: llama al modelo del nodo n1 de config; si confianza < 0.6 → N2.
  4. N2: llama al modelo del nodo n2; si falla o baja confianza → N3.
  5. N3: escalación a humano (escribe escalation note).
  Registra cada diagnóstico en .project-ai/journal.md.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .model import ProjectInfo


# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

# Busca reglas en la carpeta rules/ que está al mismo nivel que el paquete
RULES_DIR   = Path(__file__).parent.parent / "rules"
OUTPUT_DIR  = ".project-ai"
JOURNAL_FILE = "journal.md"

_CONTEXT_LINES = 40

_NOISE_RE = re.compile(
    r"^\s*(?:Downloading|Downloaded|Progress|Transferring|Resolving dependencies"
    r"|Fetching|Generating)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"\b(?:ERROR|FAILED|error:|Exception|fatal\s+error|BUILD\s+FAILURE)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Tipos de salida
# --------------------------------------------------------------------------

@dataclass
class TriageResult:
    """Diagnóstico de un log de error."""
    level:      str           # "N0" | "N1" | "N2" | "N3"
    cause:      str
    fix:        str
    confidence: float         # 0..1
    rule_id:    str | None = None
    command:    str | None = None    # comando sugerido para arreglar
    explanation: str | None = None
    snippet:    str = ""


# --------------------------------------------------------------------------
# Función principal
# --------------------------------------------------------------------------

def triage(
    log_path: str | Path,
    *,
    info: ProjectInfo | None = None,
    config=None,
    dry_run: bool = False,
    write: bool = True,
) -> TriageResult:
    """Diagnostica el log en `log_path`.

    Args:
        log_path: Ruta al archivo de log (p.ej. .project-ai/logs/step-01.log).
        info:     ProjectInfo del proyecto; si None se carga de project.json.
        config:   Config de nodos LLM; si None se carga de .project-ai/config.toml.
        dry_run:  Si True, solo aplica reglas N0 (sin llamadas LLM).
        write:    Si True, registra el diagnóstico en journal.md.
    """
    log_path = Path(log_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    snippet = _trim_log(text)

    root = _find_project_root(log_path)

    if info is None and root is not None:
        json_path = root / OUTPUT_DIR / "project.json"
        if json_path.exists():
            try:
                info = ProjectInfo.load(json_path)
            except Exception:
                pass

    stacks = info.stack_names() if info else []
    rules  = _load_rules(RULES_DIR)

    # --- N0: reglas deterministas -------------------------------------------
    matched = _match_n0(snippet, rules, stacks)
    if matched:
        result = TriageResult(
            level="N0",
            cause=matched["cause"],
            fix=matched["fix"],
            confidence=1.0,
            rule_id=matched["id"],
            snippet=snippet,
        )
        if write and root is not None:
            _write_journal(root, log_path.name, result)
        return result

    # --- N1 / N2: LLM -------------------------------------------------------
    if not dry_run:
        if config is None:
            from .config import Config
            config = Config.from_project(root) if root else Config.default()

        result = _escalate_llm(snippet, info, config)
        if result is not None:
            if write and root is not None:
                _write_journal(root, log_path.name, result)
            return result

    # --- N3: escalación a humano --------------------------------------------
    result = TriageResult(
        level="N3",
        cause="No se pudo diagnosticar automáticamente",
        fix=(
            "Revisa el log completo manualmente. "
            "Consulta la documentación del stack y, si el problema persiste, "
            "abre un ticket con el fragmento de log."
        ),
        confidence=0.0,
        snippet=snippet,
    )
    if write and root is not None:
        _write_journal(root, log_path.name, result)
    return result


# --------------------------------------------------------------------------
# Helpers internos
# --------------------------------------------------------------------------

def _trim_log(text: str, context: int = _CONTEXT_LINES) -> str:
    """Recorta el log: primer ERROR + contexto líneas, sin ruido de descargas."""
    lines = text.splitlines()
    lines = [ln for ln in lines if not _NOISE_RE.match(ln)]
    for i, line in enumerate(lines):
        if _ERROR_RE.search(line):
            return "\n".join(lines[i: i + context])
    return "\n".join(lines[-context:])


def _load_rules(rules_dir: Path) -> list[dict]:
    """Carga todas las reglas de los archivos *.toml en rules_dir."""
    rules: list[dict] = []
    if not rules_dir.is_dir():
        return rules
    for f in sorted(rules_dir.glob("*.toml")):
        with f.open("rb") as fh:
            data = tomllib.load(fh)
        rules.extend(data.get("rule", []))
    return rules


def _stack_matches(rule_stacks: list[str], project_stacks: list[str]) -> bool:
    if "*" in rule_stacks:
        return True
    return bool(set(rule_stacks) & set(project_stacks))


def _match_n0(snippet: str, rules: list[dict], stacks: list[str]) -> dict | None:
    """Devuelve la primera regla que coincide con el snippet, o None."""
    for rule in rules:
        if not _stack_matches(rule.get("stack", ["*"]), stacks):
            continue
        try:
            if re.search(rule["match"], snippet, re.IGNORECASE | re.MULTILINE):
                return rule
        except re.error:
            continue
    return None


def _escalate_llm(
    snippet: str, info: ProjectInfo | None, config
) -> TriageResult | None:
    """Intenta N1 y luego N2; devuelve el primero con confianza >= 0.6."""
    from .llm import LLMError, chat

    context = _build_context(info)
    user_msg = (
        f"Log de error:\n```\n{snippet}\n```\n\n"
        f"Contexto del proyecto:\n{context}"
    )

    for level, node in [("N1", config.n1), ("N2", config.n2)]:
        try:
            resp = chat(user_msg, node=node)
        except LLMError:
            continue
        if resp.confianza >= 0.6:
            return TriageResult(
                level=level,
                cause=resp.causa,
                fix=resp.comando or resp.explicacion or "Ver explicación",
                confidence=resp.confianza,
                command=resp.comando,
                explanation=resp.explicacion,
                snippet=snippet,
            )

    return None


def _build_context(info: ProjectInfo | None) -> str:
    if info is None:
        return "(sin contexto del proyecto)"
    stacks = ", ".join(info.stack_names()) or "desconocido"
    reqs = ", ".join(
        f"{k}={v.value}" for k, v in info.requirements.items() if v.value
    )
    return f"Stack: {stacks}\nRequisitos: {reqs or '(sin datos)'}"


def _find_project_root(log_path: Path) -> Path | None:
    """Sube por los directorios buscando .project-ai/project.json."""
    p = log_path.resolve().parent
    while p != p.parent:
        if (p / OUTPUT_DIR / "project.json").exists():
            return p
        p = p.parent
    return None


def _write_journal(root: Path, log_name: str, result: TriageResult) -> None:
    """Añade una entrada al journal del proyecto."""
    journal = root / OUTPUT_DIR / JOURNAL_FILE
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = (
        f"\n## {ts} — {log_name}\n\n"
        f"**Nivel**: {result.level}  \n"
        f"**Regla**: {result.rule_id or 'LLM'}  \n"
        f"**Confianza**: {result.confidence:.0%}  \n"
        f"**Causa**: {result.cause}  \n"
        f"**Arreglo**: {result.fix}\n"
    )
    try:
        with journal.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    except OSError:
        pass
