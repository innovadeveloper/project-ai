"""
report.py — Renderizado de ProjectInfo en texto legible o JSON.

Usado por cli.py (project-ai recon) y por adapters/__main__.py (python -m project_ai.adapters).
"""

from __future__ import annotations

import json

from .model import ProjectInfo
from .adapters.base import CMD_KIND_ORDER


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

    if info.modules:
        out.append(f"\nMódulos ({len(info.modules)}):")
        for m in info.modules[:max_items]:
            deps = f"  → {', '.join(m.depends_on)}" if m.depends_on else ""
            out.append(f"  {m.name:<28} {m.kind or '':<16} {m.path}{deps}")
        if len(info.modules) > max_items:
            out.append(f"  ... +{len(info.modules) - max_items} más")

    if info.entry_points:
        out.append(f"\nEntry points ({len(info.entry_points)}):")
        for e in info.entry_points[:10]:
            loc = f"{e.file}:{e.line}" if e.line else e.file
            out.append(f"  {e.kind:<20} {e.symbol:<40} {loc}")

    if info.endpoints:
        out.append(f"\nEndpoints ({len(info.endpoints)}), muestra:")
        for e in info.endpoints[:10]:
            out.append(f"  {e.method:<6} {e.path:<45} {e.handler}  ({e.file}:{e.line})")

    if info.commands:
        out.append("\nComandos propuestos:")
        for c in info.commands.values():
            cwd = f"(en {c.cwd}) " if c.cwd not in (".", "") else ""
            out.append(f"  {c.name:<10} {cwd}{c.shell}")
            if c.ide_hint:
                out.append(f"  {'':<10} IDE: {c.ide_hint}")
            if c.success_hint:
                out.append(f"  {'':<10} OK si: {c.success_hint}")

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
            if f.note and k in ("jdk_ceiling", "java.ee_namespace", "maven.repositories",
                                "maven.notable_plugins", "ide.tomcat_local"):
                out.append(f"      ↳ {f.note}")

    if info.warnings:
        out.append("\n⚠ Avisos:")
        out += [f"  - {w}" for w in info.warnings]
    return "\n".join(out)
