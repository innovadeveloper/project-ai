---
description: Crea un adaptador nuevo siguiendo la guía (uso /nuevo-adaptador <stack>)
argument-hint: <stack> (p.ej. cmake, conan, gradle, python, dotnet)
---
Vamos a crear el adaptador **$ARGUMENTS**.

1. Lee `docs/ADAPTER_GUIDE.md`, `project_ai/adapters/base.py` y, como
   referencia, `project_ai/adapters/maven.py`.
2. Busca en `docs/ROADMAP.md` la especificación de "$ARGUMENTS" y lista los
   criterios de aceptación.
3. Revisa `docs/REAL_PROJECTS.md`: si hay un proyecto real de este stack, el
   fixture debe imitar su estructura (incluidas trampas: carpetas generadas,
   presets incluidos que no existen, comandos en tasks.json/README).
4. Propón: nombre del fixture en `tests/conftest.py`, casos de
   `tests/test_$ARGUMENTS.py`, facts nuevos (con prefijo `$ARGUMENTS.`),
   claves de requisito que usarás (estándar o nuevas → añadirlas a
   `base.REQUIREMENT_KEYS` y a `docs/COMMANDS.md` §4). Espera mi OK.
5. Implementa con TDD, regístralo en `adapters/__init__.py` después de `hints`,
   y deja `uv run pytest -q` y pyflakes en verde.
6. Actualiza CLAUDE.md, ROADMAP y DECISIONS.
