"""
context.py — Genera un paquete de contexto mínimo para una pregunta.

Uso:
    project-ai context "cómo funciona el auth" [--max-tokens 3000]

Salida: texto < max_tokens con resumen del proyecto + fragmentos de repo-map.md
relevantes a la pregunta. Listo para pegar en cualquier chat LLM local.
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import ProjectInfo
from .notes import load_notes

OUTPUT_DIR  = ".project-ai"
CHARS_PER_TOKEN = 4   # conservador: 1 token ≈ 4 chars


def context(
    path: str | Path,
    query: str,
    *,
    max_tokens: int = 3000,
) -> str:
    """Genera contexto compacto sobre el proyecto para la pregunta `query`.

    Prioriza:
    1. Resumen del proyecto (AGENTS.md §1–§2, o info básica si no existe).
    2. Símbolos y archivos de repo-map.md cuyos nombres coincidan con `query`.
    3. Endpoints cuya ruta o handler contenga tokens de `query`.

    Siempre cabe en `max_tokens` (se trunca con aviso si hay más material).
    """
    root   = Path(path).resolve()
    budget = max_tokens * CHARS_PER_TOKEN

    sections: list[str] = []

    # --- 1. Cabecera con la pregunta ----------------------------------------
    sections.append(f"## Pregunta\n\n{query}")

    # --- 1b. Notas de dominio del usuario ------------------------------------
    notes = load_notes(root)
    if notes:
        sections.append(f"## Contexto del proyecto\n\n{notes.strip()}")

    # --- 2. Resumen del proyecto (fuente: AGENTS.md o project.json) ----------
    summary = _load_summary(root)
    sections.append(f"## Proyecto\n\n{summary}")

    # --- 3. Fragmentos relevantes de repo-map.md -----------------------------
    relevant = _search_repo_map(root, query)
    if relevant:
        sections.append("## Símbolos relevantes\n\n" + "\n".join(relevant))

    # --- 4. Endpoints relevantes ----------------------------------------------
    ep_lines = _search_endpoints(root, query)
    if ep_lines:
        sections.append("## Endpoints relevantes\n\n" + "\n".join(ep_lines))

    # --- 5. Ensamblar dentro del budget -------------------------------------
    result = _assemble(sections, budget)

    # Pie: punteros a más detalle
    result += (
        "\n\n---\n"
        "_Para más detalle: `.project-ai/repo-map.md`,"
        " `.project-ai/project.json`_"
    )
    return result


# --------------------------------------------------------------------------
# Helpers de carga
# --------------------------------------------------------------------------

def _load_summary(root: Path) -> str:
    """Carga las secciones 1–2 de AGENTS.md, o genera un resumen mínimo."""
    agents = root / "AGENTS.md"
    if agents.exists():
        text = agents.read_text(encoding="utf-8")
        # Tomar hasta ## 3. (secciones 1 y 2 = proyecto + comandos)
        m = re.search(r"^## 3\.", text, re.MULTILINE)
        return text[:m.start()].strip() if m else text[:1200].strip()

    # Fallback: cargar desde project.json
    json_path = root / OUTPUT_DIR / "project.json"
    if json_path.exists():
        try:
            info = ProjectInfo.load(json_path)
            stacks = ", ".join(info.stack_names()) or "desconocido"
            cmds   = ", ".join(info.commands) or "ninguno"
            lines = [
                f"**Stack**: {stacks}",
                f"**Comandos**: {cmds}",
                f"**Módulos**: {len(info.modules)}",
            ]
            if info.endpoints:
                lines.append(f"**Endpoints** ({len(info.endpoints)}):")
                for ep in info.endpoints[:20]:
                    lines.append(
                        f"- `{ep.method} {ep.path}` → `{ep.handler}`"
                    )
                if len(info.endpoints) > 20:
                    lines.append(
                        f"_(y {len(info.endpoints) - 20} más — ver project.json)_"
                    )
            return "\n".join(lines)
        except Exception:
            pass

    return f"Proyecto en `{root.name}` (sin datos — ejecuta `project-ai recon`)."


def _load_repo_map(root: Path) -> str:
    f = root / OUTPUT_DIR / "repo-map.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


# --------------------------------------------------------------------------
# Búsqueda de relevancia
# --------------------------------------------------------------------------

def _tokens(query: str) -> list[str]:
    """Divide la pregunta en tokens útiles (min 3 chars, sin stopwords)."""
    _STOP = {"cómo", "como", "qué", "que", "donde", "cuál", "cual", "el",
             "la", "los", "las", "de", "del", "en", "es", "son", "para",
             "con", "por", "and", "the", "for", "how", "what", "where"}
    return [
        t.lower() for t in re.split(r"[\s/?.,:;]+", query)
        if len(t) >= 3 and t.lower() not in _STOP
    ]


def _search_repo_map(root: Path, query: str) -> list[str]:
    """Devuelve bloques de repo-map.md relevantes para `query`."""
    text = _load_repo_map(root)
    if not text:
        return []
    toks = _tokens(query)
    if not toks:
        return []

    results: list[str] = []
    # El repo-map está dividido por archivo (### path) y símbolo (- kind ...)
    current_file_lines: list[str] = []
    file_score = 0

    def _flush():
        if file_score > 0 and current_file_lines:
            results.append("\n".join(current_file_lines[:20]))

    for line in text.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            _flush()
            current_file_lines = [line]
            file_score = sum(1 for t in toks if t in line.lower())
        else:
            score = sum(1 for t in toks if t in line.lower())
            file_score += score
            current_file_lines.append(line)

    _flush()
    return results[:6]   # max 6 bloques de archivo


def _search_endpoints(root: Path, query: str) -> list[str]:
    """Devuelve endpoints relevantes para `query`.

    Primero intenta coincidir por tokens. Si no hay coincidencias,
    devuelve TODOS los endpoints (el lector los filtra visualmente).
    Así funciona aunque los nombres estén en otro idioma.
    """
    agents = root / "AGENTS.md"
    toks = _tokens(query)

    if not agents.exists():
        json_path = root / OUTPUT_DIR / "project.json"
        if not json_path.exists():
            return []
        try:
            info = ProjectInfo.load(json_path)
        except Exception:
            return []
        if not info.endpoints:
            return []
        all_lines = [
            f"- `{ep.method} {ep.path}` → `{ep.handler}`"
            for ep in info.endpoints
        ]
        if toks:
            matched = [
                ln for ln in all_lines
                if any(t in ln.lower() for t in toks)
            ]
            return matched[:10] if matched else all_lines[:15]
        return all_lines[:15]

    text = agents.read_text(encoding="utf-8")
    all_ep_lines = [
        ln.strip() for ln in text.splitlines()
        if ln.strip().startswith("- `") and "`" in ln
    ]
    if not all_ep_lines:
        return []
    if toks:
        matched = [ln for ln in all_ep_lines if any(t in ln.lower() for t in toks)]
        return matched[:10] if matched else all_ep_lines[:15]
    return all_ep_lines[:15]


# --------------------------------------------------------------------------
# Ensamblado con budget
# --------------------------------------------------------------------------

def _assemble(sections: list[str], budget: int) -> str:
    out = ""
    for sec in sections:
        chunk = ("\n\n" if out else "") + sec
        if len(out) + len(chunk) <= budget:
            out += chunk
        else:
            # Truncar esta sección hasta que quepa
            remaining = budget - len(out) - 2
            if remaining > 100:
                out += "\n\n" + sec[:remaining] + "\n_(truncado)_"
            break
    return out
