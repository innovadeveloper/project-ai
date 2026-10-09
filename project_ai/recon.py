"""
recon.py — Núcleo del flujo de reconocimiento.

Orquesta scanner + adaptadores y persiste el resultado en
<proyecto>/.project-ai/project.json.

    from project_ai.recon import recon
    info = recon("/ruta/al/proyecto")

Criterios:
- Idempotente: ejecutar dos veces sobreescribe el mismo archivo sin efectos secundarios.
- Solo lectura sobre el proyecto (salvo .project-ai/ y .git/info/exclude).
- .project-ai/ se añade a .git/info/exclude (no al .gitignore del proyecto).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .model import ProjectInfo
from .scanner import ProjectScanner
from .adapters import run_adapters

OUTPUT_DIR  = ".project-ai"
OUTPUT_FILE = "project.json"
GIT_EXCLUDE_ENTRY = ".project-ai/"


def recon(
    path: str | Path,
    *,
    only: Iterable[str] | None = None,
    debug: bool = False,
    write: bool = True,
) -> ProjectInfo:
    """Reconoce el proyecto en `path` y devuelve un ProjectInfo.

    Args:
        path:   Ruta al proyecto (directorio raíz).
        only:   Si se indica, solo se ejecutan estos adaptadores.
        debug:  Muestra tracebacks de adaptadores que fallen.
        write:  Si True (defecto), escribe .project-ai/project.json
                y actualiza .git/info/exclude.
    """
    root = Path(path).resolve()
    sc = ProjectScanner(root)
    info = run_adapters(sc, only=list(only) if only else None, debug=debug)

    if write:
        _write_output(root, info)
        _write_repo_map(root, info, sc)
        _add_git_exclude(root)

    return info


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

REPO_MAP_FILE = "repo-map.md"


def _write_repo_map(root: Path, info: ProjectInfo, sc: ProjectScanner) -> Path:
    from .repomap import build_repo_map
    out_dir = root / OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / REPO_MAP_FILE
    out_file.write_text(build_repo_map(info, sc), encoding="utf-8")
    return out_file


def _write_output(root: Path, info: ProjectInfo) -> Path:
    out_dir = root / OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / OUTPUT_FILE
    out_file.write_text(
        json.dumps(info.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_file


def _add_git_exclude(root: Path) -> bool:
    """Añade .project-ai/ a .git/info/exclude del proyecto si es un repo git.

    No toca el .gitignore del proyecto. Devuelve True si añadió la entrada.
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return False

    exclude_file = git_dir / "info" / "exclude"
    try:
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
        if GIT_EXCLUDE_ENTRY not in existing.splitlines():
            with exclude_file.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(f"{GIT_EXCLUDE_ENTRY}\n")
            return True
    except OSError:
        pass
    return False
