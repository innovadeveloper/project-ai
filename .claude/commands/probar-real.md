---
description: Ejecuta scanner y adaptadores sobre un proyecto real y analiza discrepancias
argument-hint: <ruta del proyecto>
---
Proyecto a analizar: $ARGUMENTS

1. Ejecuta (solo lectura, no modifiques nada en esa ruta):
   - `uv run python -m project_ai.scanner "$ARGUMENTS"`
   - `uv run python -m project_ai.adapters "$ARGUMENTS"`
   - `uv run python -m project_ai.adapters "$ARGUMENTS" --json > /tmp/project-ai-info.json`
2. Para verificar dudas puedes leer archivos del proyecto (pom.xml,
   CMakeLists.txt, conanfile.py, Dockerfile, README…), sin escribir en él.
3. Informa en una tabla: dato descubierto · ¿correcto? · evidencia · qué
   debería salir. Señala falsos positivos, datos que faltan y avisos dudosos.
4. Por cada error, propón el caso mínimo para `tests/conftest.py` y el test
   que lo cubriría. Espera mi OK antes de cambiar código.
5. Añade un resumen de lo aprendido a `docs/REAL_PROJECTS.md`.
