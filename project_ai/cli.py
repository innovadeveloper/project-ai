"""
cli.py — Punto de entrada del comando `project-ai`.

Uso:
    project-ai recon <ruta> [--json] [--only ADAPTER ...] [--no-write] [--debug]
    project-ai adapters <ruta> [--json] [--only ADAPTER ...] [--debug]  (alias)

Instalación (uv sync después de crear pyproject.toml):
    project-ai recon .
"""

from __future__ import annotations

import argparse
import json
import sys

from .adapters import REGISTRY
from .recon import OUTPUT_DIR, OUTPUT_FILE, recon
from .report import render_text


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="project-ai",
        description="Reconoce proyectos de software y prepara el contexto para agentes locales.",
    )
    sub = ap.add_subparsers(dest="cmd")

    # ---- recon (comando principal) --------------------------------------
    p_recon = sub.add_parser(
        "recon",
        help="Analiza el proyecto y escribe .project-ai/project.json",
    )
    p_recon.add_argument("path", nargs="?", default=".",
                         help="Ruta al proyecto (por defecto: directorio actual)")
    p_recon.add_argument("--json", action="store_true",
                         help="Imprime la salida en JSON (idéntico a project.json)")
    p_recon.add_argument("--only", nargs="+", choices=sorted(REGISTRY),
                         metavar="ADAPTER",
                         help="Ejecutar solo estos adaptadores")
    p_recon.add_argument("--no-write", action="store_true",
                         help="No escribir .project-ai/project.json")
    p_recon.add_argument("--debug", action="store_true",
                         help="Mostrar traceback si un adaptador falla")

    # ---- adapters (alias hacia atrás para compatibilidad) ---------------
    p_ad = sub.add_parser(
        "adapters",
        help="Alias de recon sin escritura (diagnóstico rápido)",
    )
    p_ad.add_argument("path", nargs="?", default=".")
    p_ad.add_argument("--json", action="store_true")
    p_ad.add_argument("--only", nargs="+", choices=sorted(REGISTRY), metavar="ADAPTER")
    p_ad.add_argument("--debug", action="store_true")

    # ---- finalize -----------------------------------------------------------
    p_fin = sub.add_parser(
        "finalize",
        help="Marca comandos verificados y genera AGENTS.md en la raíz del proyecto",
    )
    p_fin.add_argument("path", nargs="?", default=".",
                       help="Ruta al proyecto (por defecto: directorio actual)")
    p_fin.add_argument("--no-write", action="store_true",
                       help="No escribe AGENTS.md ni actualiza project.json")

    # ---- triage -------------------------------------------------------------
    p_tri = sub.add_parser(
        "triage",
        help="Diagnostica un log de error: reglas N0 → Ollama N1/N2 → N3 humano",
    )
    p_tri.add_argument("log", help="Ruta al archivo de log")
    p_tri.add_argument("--dry-run", action="store_true",
                       help="Solo aplica reglas N0, sin llamadas LLM")
    p_tri.add_argument("--no-write", action="store_true",
                       help="No escribe en .project-ai/journal.md")

    # ---- runbook ------------------------------------------------------------
    p_run = sub.add_parser(
        "runbook",
        help="Genera .project-ai/RUNBOOK.md con los pasos de build/test/run",
    )
    p_run.add_argument("path", nargs="?", default=".",
                       help="Ruta al proyecto (por defecto: directorio actual)")
    p_run.add_argument("--no-write", action="store_true",
                       help="No escribir .project-ai/RUNBOOK.md")
    p_run.add_argument("--os", choices=["macos", "linux"], dest="os_hint",
                       help="Forzar recetas de instalación para este SO")

    # ---- doctor -------------------------------------------------------------
    p_doc = sub.add_parser(
        "doctor",
        help="Comprueba que la máquina tiene los requisitos del proyecto",
    )
    p_doc.add_argument("path", nargs="?", default=".",
                       help="Ruta al proyecto (por defecto: directorio actual)")
    p_doc.add_argument("--no-write", action="store_true",
                       help="No escribir .project-ai/env-report.md")
    p_doc.add_argument("--skip-services", action="store_true",
                       help="Omitir las comprobaciones de puertos TCP")
    p_doc.add_argument("--os", choices=["macos", "linux"], dest="os_hint",
                       help="Forzar recetas de instalación para este SO")

    # ---- context ------------------------------------------------------------
    p_ctx = sub.add_parser(
        "context",
        help="Genera un paquete de contexto para pegar en un chat LLM local",
    )
    p_ctx.add_argument("query", help="Pregunta o tema a buscar")
    p_ctx.add_argument("--path", default=".",
                       help="Ruta al proyecto (por defecto: directorio actual)")
    p_ctx.add_argument("--max-tokens", type=int, default=3000,
                       help="Presupuesto máximo de tokens (por defecto: 3000)")

    # ---- setup-agent --------------------------------------------------------
    p_sa = sub.add_parser(
        "setup-agent",
        help="Genera instrucciones de configuración para OpenCode y Serena",
    )
    p_sa.add_argument("path", nargs="?", default=".",
                      help="Ruta al proyecto (por defecto: directorio actual)")
    p_sa.add_argument("--no-write", action="store_true",
                      help="No escribir .project-ai/setup-agent.md")

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = _build_parser()
    a = ap.parse_args(argv)

    if a.cmd is None:
        ap.print_help()
        return 0

    if a.cmd == "finalize":
        from .finalize import finalize as _finalize
        write_fin = not getattr(a, "no_write", False)
        result = _finalize(a.path, write=write_fin)
        v = ", ".join(result.verified) if result.verified else "(ninguno)"
        print(f"Verificados: {v}")
        print(f"\n{result.agents_md}")
        if write_fin:
            print(f"\n→ Escrito en {a.path}/AGENTS.md")
        return 0 if result.verified else 1

    if a.cmd == "triage":
        from .triage import triage as _triage
        result = _triage(
            a.log,
            dry_run=getattr(a, "dry_run", False),
            write=not getattr(a, "no_write", False),
        )
        print(f"Nivel:   {result.level}")
        print(f"Causa:   {result.cause}")
        print(f"Arreglo: {result.fix}")
        if result.command:
            print(f"Comando: {result.command}")
        if result.explanation:
            print(f"Detalle: {result.explanation}")
        return 0 if result.level != "N3" else 1

    if a.cmd == "runbook":
        from .runbook import runbook as _runbook
        write_rb = not getattr(a, "no_write", False)
        result = _runbook(
            a.path,
            os_hint=getattr(a, "os_hint", None),
            write=write_rb,
        )
        print(result.to_md())
        if write_rb:
            print(f"\n→ Escrito en {a.path}/.project-ai/RUNBOOK.md")
        return 0 if result.ok else 1

    if a.cmd == "doctor":
        from .doctor import doctor as _doctor
        write_doc = not getattr(a, "no_write", False)
        report = _doctor(
            a.path,
            skip_services=getattr(a, "skip_services", False),
            os_hint=getattr(a, "os_hint", None),
            write=write_doc,
        )
        print(report.to_md())
        if write_doc:
            print(f"\n→ Escrito en {a.path}/.project-ai/env-report.md")
        return 0 if report.ok else 1

    if a.cmd == "context":
        from .context import context as _context
        result = _context(
            a.path,
            a.query,
            max_tokens=a.max_tokens,
        )
        print(result)
        return 0

    if a.cmd == "setup-agent":
        from .setup_agent import setup_agent as _setup_agent
        write_sa = not getattr(a, "no_write", False)
        result = _setup_agent(a.path, write=write_sa)
        print(result)
        if write_sa:
            print(f"\n→ Escrito en {a.path}/.project-ai/setup-agent.md")
        return 0

    write = (a.cmd == "recon") and not getattr(a, "no_write", False)

    info = recon(a.path, only=a.only, debug=a.debug, write=write)

    if a.json:
        print(json.dumps(info.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_text(info))
        if write:
            out_path = f"{a.path}/{OUTPUT_DIR}/{OUTPUT_FILE}"
            print(f"\n→ Escrito en {out_path}")

    return 1 if (info.warnings and not a.json) else 0


# Alias para compatibilidad con el entry_point anterior (project_ai.cli:app)
app = main


if __name__ == "__main__":
    sys.exit(main())
