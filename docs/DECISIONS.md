# Decisiones de diseño

Registro breve. No reabrir sin un motivo nuevo (p.ej. un proyecto real que lo contradiga).

1. **El usuario ejecuta, no Docker.** La herramienta explora, compara y
   explica; el usuario corre los comandos en su shell/IDE. Docker solo como
   pista o para servicios que el proyecto ya define.
2. **Script determinista antes que LLM.** Detectar stack/versiones/comandos no
   gasta tokens y es reproducible. El LLM entra en triage y en el trabajo diario.
3. **Sin grafo de código ni embeddings.** Navegación bajo demanda con grep +
   LSP (Serena). Continue deprecó su @Codebase por embeddings; los agentes
   actuales exploran con herramientas. Un mapa compacto (repo-map) basta como
   vista aérea.
4. **Evidencia y prioridad en cada dato** (`Fact`). El LLM local debe poder
   distinguir "declarado" de "deducido".
5. **Empate de prioridad → gana el archivo más cercano a la raíz.** Caso real:
   `Dockerfile` raíz (jdk8) frente a `docker/hmdm-docker-0.1.5/Dockerfile` (jdk11).
6. **`jdk` ≠ `jdk_runtime`.** Las imágenes de runtime (tomcat, *-jre) y la
   última etapa de un Dockerfile multi-stage describen la ejecución, no la
   compilación.
7. **`.smarttomcat/` describe la máquina del desarrollador, no el proyecto**
   → `ide.tomcat_local`, no requisito. Se cruza con `java.ee_namespace`.
8. **javax vs jakarta decide Tomcat** (≤9 vs ≥10). Es el error más probable al
   levantar WARs antiguos.
9. **Carpetas de build versionadas se excluyen por marcadores**, no por nombre:
   un `bin/` con scripts propios se conserva.
10. **Solo stdlib** para que funcione igual en los 3 nodos sin instalar nada.
    tree-sitter será opcional.
11. **Orden de adaptadores: `hints` primero**, para que los de stack puedan
    contrastar (maven compara su namespace con el Tomcat del IDE).
12. **Claude fuera del flujo final (alcance 1).** Escalado 100 % local
    N0→N1→N2→N2b→humano; se mide qué nivel resuelve cada caso.
13. **Android: el usuario resuelve la matriz AGP/Gradle/JDK a mano al
    principio**; el adaptador Gradle detecta y avisa, sirve para medir.
14. **Nunca modificar el proyecto analizado** salvo `.project-ai/` y
    `AGENTS.md` (finalize). `.project-ai/` se excluye vía `.git/info/exclude`.
15. **Comandos encontrados en tasks.json/CI/README tienen prioridad sobre los
    genéricos del adaptador** al construir el runbook: reflejan cómo se usa
    realmente el proyecto.
16. **Reglas de triage en TOML**, no YAML: `tomllib` es stdlib (decisión 10).
    Para `--learn` basta un escritor TOML mínimo propio.
17. **cmake.py parsea CMakeLists.txt con regex sobre texto sin comentarios**
    (strips `#...` EOL). No se usa tree-sitter para no romper la decisión 10.
    Los patrones multi-línea se manejan con `re.DOTALL`; la limitación es que
    las macros y variables de CMake no se expanden (p.ej. `${MY_STD}`) → se
    marca HEURISTIC cuando se detecte. Para proyectos reales simples (netclient)
    basta con parsing directo.
18. **conan.py distingue API 2 vs 1 por el import**, no por la versión instalada
    (que no se puede leer sin ejecutar). `from conan import` → 2; `from conans import`
    → 1. En caso dudoso se asume 2 con nota HEURISTIC para no bloquear.
19. **CMakeUserPresets.json con includes ausentes emite aviso pero sigue emitiendo
    comandos con --preset**: el usuario necesita saber tanto que debe hacer `conan
    install` como cuál preset usar luego. Emitir solo la advertencia sin el comando
    configure sería incompleto.
20. **Separador en búsqueda de versión Tomcat en `.smarttomcat/`**: el patrón
    `tomcat[-_/ ]?(\d+...)` ahora permite `/` para capturar `Apache Tomcat/10.1`
    de `catalina.properties`. Los comentarios HTML se eliminan antes para evitar
    capturar versiones de avisos de deprecación.
