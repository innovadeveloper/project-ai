"""
Ejecuta los adaptadores sobre un proyecto y muestra lo descubierto.
Es una herramienta de prueba hasta que exista `recon` (que además guardará
.project-ai/project.json). No escribe nada en el proyecto.

    python -m project_ai.adapters ./mi-proyecto
    python -m project_ai.adapters ./mi-proyecto --only hints
    python -m project_ai.adapters ./mi-proyecto --json
    python -m project_ai.adapters ./mi-proyecto --debug     (traceback si algo falla)
"""

from __future__ import annotations

import argparse
import json
import sys

from ..model import ProjectInfo
from ..scanner import ProjectScanner
from . import REGISTRY, run_adapters
from .base import CMD_KIND_ORDER


def render_text(info: ProjectInfo, max_items: int = 15) -> str:
    out: list[str] = [f"Proyecto: {info.root}"]

    out.append("\nStacks: " + (", ".join(
        f"{s.adapter}@{s.root} ({s.confidence:.2f})" for s in info.stacks) or "(ninguno aún)"))

    out.append("\nRequisitos:")
    if not info.requirements:
        out.append("  (ninguno)")
    for k, f in sorted(info.requirements.items()):
        out.append(f"  {k:<14} {f.value:<8} [{f.priority.name}/{f.status.value}]  ← {f.source}"
                   + (f"  ({f.note})" if f.note else ""))
        if len(f.evidence) > 1:
            out.append(f"  {'':<14} +{len(f.evidence) - 1} evidencia(s) más")
        for a in f.alternatives[:3]:
            out.append(f"  {'':<14} descartado: {a['value']} [{a['priority']}] ← {a['source']}")

    if info.services:
        out.append("\nServicios de runtime:")
        for s in info.services:
            out.append(f"  {s.kind:<14} {s.fact.value:<8} [{s.fact.priority.name}]  ← "
                       f"{s.fact.source}" + (f"  (+{len(s.fact.evidence) - 1})"
                                             if len(s.fact.evidence) > 1 else ""))

    cmds = info.facts.get("hints.commands")
    if cmds and cmds.value:
        prio = {"EXPLICIT": 0, "CI": 1, "BUILD": 2, "HEURISTIC": 3, "DEFAULT": 4}
        items = sorted(cmds.value, key=lambda c: (
            CMD_KIND_ORDER.index(c["kind"]), prio.get(c["priority"], 9),
            -len(c["sources"])))
        out.append(f"\nComandos vistos ({len(items)}), en orden típico de ejecución:")
        for c in items[:max_items]:
            more = f" (+{len(c['sources']) - 1})" if len(c["sources"]) > 1 else ""
            out.append(f"  {c['kind']:<9} [{c['origin']:<6}] {c['cmd'][:100]}"
                       f"   ← {c['sources'][0]}{more}")
        if len(items) > max_items:
            out.append(f"  ... +{len(items) - max_items} más (--json para ver todos)")

    others = {k: v for k, v in info.facts.items() if k != "hints.commands"}
    if others:
        out.append("\nOtros hechos:")
        for k, f in sorted(others.items()):
            val = f.value
            if isinstance(val, list):
                shown = [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                         for v in val[:4]]
                val = "; ".join(shown) + (f" (+{len(f.value) - 4})" if len(f.value) > 4 else "")
            src = f"  ← {f.source}" if f.evidence else ""
            out.append(f"  {k}: {str(val)[:160]}{src}")

    if info.warnings:
        out.append("\n⚠ Avisos:")
        out += [f"  - {w}" for w in info.warnings]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m project_ai.adapters",
                                 description="Ejecuta los adaptadores (solo lectura).")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--only", nargs="+", choices=sorted(REGISTRY), help="solo estos adaptadores")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args(argv)

    sc = ProjectScanner(a.path, use_git=not a.no_git)
    info = run_adapters(sc, only=a.only, debug=a.debug)
    if a.json:
        print(json.dumps(info.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_text(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
