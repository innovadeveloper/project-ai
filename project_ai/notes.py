"""
notes.py — Notas de dominio del proyecto para el agente.

El archivo .project-ai/notes.md es escrito por el usuario (o generado como
plantilla vacía en finalize) y se incluye en AGENTS.md §0 y en cada paquete
de contexto que genera context.py.

Formato del archivo: Markdown libre. Las secciones recomendadas están en la
plantilla, pero el usuario puede añadir o quitar lo que quiera.
"""
from __future__ import annotations

import re
from pathlib import Path

OUTPUT_DIR = ".project-ai"
NOTES_FILE = "notes.md"


# --------------------------------------------------------------------------
# Plantilla
# --------------------------------------------------------------------------

_TEMPLATE = """\
# Notas del proyecto

> Edita este archivo con el contexto de dominio que el agente necesita.
> Se incluirá en AGENTS.md y en cada `project-ai context`.

## ¿Qué hace este proyecto?

<!-- Describe el propósito principal en 2-3 frases -->

## Entidades clave

<!-- Lista las entidades principales del dominio, ej:
- **Device** — representa un dispositivo MDM registrado
- **Fleet** — agrupación de dispositivos
-->

## Reglas de negocio

<!-- Restricciones o lógica importante que no está en el código, ej:
- Solo los admins pueden reasignar dispositivos
- Los perfiles se aplican en cascada (grupo → device)
-->

## Notas para el agente

<!-- Lo que NO está en el código pero es relevante para trabajar en él, ej:
- El módulo `server/` es el único deployable; `common/` es librería interna
- Las migraciones se aplican manualmente (no hay flyway)
- El entorno de staging usa perfil `application-staging.yml`
-->
"""


# --------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------

def notes_path(project_root: str | Path) -> Path:
    """Devuelve la ruta canónica de notes.md para un proyecto."""
    return Path(project_root).resolve() / OUTPUT_DIR / NOTES_FILE


def load_notes(project_root: str | Path) -> str | None:
    """Lee el contenido de notes.md, o None si no existe o está vacío.

    Filtra las líneas de comentario HTML (<!-- ... -->) al comprobar si
    el archivo tiene contenido real, pero devuelve el texto original íntegro
    para que el agente lo lea con todo el contexto.
    """
    p = notes_path(project_root)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return None
    # Comprobar si hay contenido real más allá de la plantilla vacía.
    # Primero elimina bloques HTML multilinea (<!-- ... -->) para que las
    # líneas de ejemplo dentro de ellos no cuenten como contenido real.
    stripped = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    real_lines = [
        ln for ln in stripped.splitlines()
        if ln.strip()
        and not ln.strip().startswith("#")
        and not ln.strip().startswith(">")
    ]
    return text if real_lines else None


def ensure_notes_template(project_root: str | Path) -> bool:
    """Crea notes.md con la plantilla si no existe.

    Returns True si se creó el archivo, False si ya existía.
    """
    p = notes_path(project_root)
    if p.exists():
        return False
    p.parent.mkdir(exist_ok=True)
    p.write_text(_TEMPLATE, encoding="utf-8")
    return True
