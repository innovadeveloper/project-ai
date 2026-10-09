---
description: Retoma el trabajo en el siguiente ítem del ROADMAP
---
1. Lee `CLAUDE.md` (sección "Estado actual" y "Siguiente tarea") y la sección
   correspondiente de `docs/ROADMAP.md`. Lee `docs/ADAPTER_GUIDE.md` si la tarea
   es un adaptador.
2. Ejecuta `uv run pytest -q` para confirmar que se parte de verde.
3. Propón un plan corto (archivos a crear/modificar, fixtures, tests) y espera
   mi confirmación antes de escribir código.
4. Implementa: fixture realista → tests que fallan → código → tests en verde →
   `uv run python -m pyflakes project_ai tests`.
5. Muestra la salida de `uv run python -m project_ai.adapters` sobre el fixture
   nuevo (créalo en un directorio temporal) para que la revise.
6. Actualiza CLAUDE.md (Estado actual / Siguiente tarea), marca ✅ en el
   ROADMAP y añade a `docs/DECISIONS.md` cualquier decisión nueva.
7. Dime qué comando ejecutar sobre mis proyectos reales para validarlo.

Indicaciones extra: $ARGUMENTS
