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

from ..scanner import ProjectScanner
from ..report import render_text  # noqa: F401 — re-exportado para compatibilidad
from . import REGISTRY, run_adapters


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
