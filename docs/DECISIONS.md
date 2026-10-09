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
21. **`recon()` siempre sobreescribe `project.json`** (no diff incremental):
    la serialización es rápida, el archivo es pequeño, y comparar diffs del
    modelo sería complejidad innecesaria. "Idempotente" = dos pasadas no rompen
    nada ni duplican entradas (especialmente en `.git/info/exclude`).
22. **`app = main` en cli.py** para compatibilidad hacia atrás con el
    entry_point previo (`project_ai.cli:app`), que queda funcional hasta que
    el usuario ejecute `uv sync` con el nuevo pyproject.toml.
23. **CLI devuelve exit code 1 si hay warnings** (en modo texto): permite que
    scripts de CI detecten proyectos con advertencias sin parsear la salida.
    En modo `--json` siempre devuelve 0 para no romper pipelines que parsean JSON.
24. **doctor.py recibe ProjectInfo opcional**: permite testearlo con fixtures sin
    ejecutar el scanner completo. Si no se pasa, intenta cargar project.json del disco
    y, si falla o no existe, corre recon. El fallback por excepción también cubre
    project.json con formato antiguo (bug de serialización de sesiones previas).
25. **doctor siempre re-ejecuta recon si el JSON está corrupto**: ProjectInfo.load()
    puede fallar si el archivo fue generado con una versión anterior que serializó
    Evidence como listas anidadas. El fallback escribe un JSON nuevo (`write=True`)
    para que la siguiente llamada sea rápida.
32. **finalize.py detecta éxito escaneando TODOS los logs a la vez**: en vez de
    asignar cada log a un comando específico (lo que requiere parsear el RUNBOOK),
    concatena todos los `step-*.log` y busca patrones de éxito por kind. Esto es
    conservador: si BUILD SUCCESS aparece en cualquier log, se marca el comando
    `build` como verified. La imprecisión es aceptable porque finalize solo se
    ejecuta cuando el usuario declara que el proyecto funciona.
30. **triage.py importa `chat` lazily dentro de `_escalate_llm`**: evita que
    un `ImportError` de `llm.py` rompa el path N0 (solo reglas). También permite
    mockear con `patch("project_ai.llm.chat")` sin necesidad de inyectar el
    módulo, porque el mock reemplaza el símbolo en `llm` antes de que se importe.
31. **config.py define n1 y n2 como los únicos nodos configurables**; n2b se
    omite por ahora (en la práctica apunta al mismo host que n2 con modelo más
    grande). Se añade cuando un proyecto real demuestre que necesitar 3 intentos.
28. **runbook.py acepta DoctorReport opcional pero no lo carga del disco
    automáticamente**: el CLI ejecuta `recon` + `doctor` + `runbook` como pasos
    separados. El runbook lee el `ProjectInfo` de `project.json` (o lo genera si
    no existe), pero no parsea `env-report.md` — el usuario que quiere integrar
    doctor en el runbook lo hace pasando el objeto programáticamente. Esto evita
    acoplar el formato de salida de doctor al parser de runbook.
29. **Orden canónico de pasos en runbook**: `deps → configure → generate → build
    → test → run`. Los comandos con nombre fuera de este orden (p.ej. `build_app`
    de Maven) se añaden al final para no ocultar su existencia. El paso `setup`
    (doctor) es siempre el número 0; el paso `service` va justo después; los
    ejecutables se numeran a continuación.
26. **repomap.py usa brace-depth counting por línea para Java**: el parser de Java
    mantiene un contador de profundidad de llaves procesando línea a línea, pero
    llama a `_strip_string_literals` solo sobre la línea individual (no sobre el
    texto completo) para no destruir el contenido de las anotaciones `@Path` antes
    de extraerlo. Los varargs Java (`String... args`) se limpian con `replace("...", "")`
    **antes** de `split(".")[-1]` para evitar que `"String..."` se parta en
    `["String","",""]` dejando el tipo vacío.
27. **repomap.py prioriza archivos REST/controller sobre servicios**: la puntuación
    es `2` para archivos con `resource|controller|rest|api` en el nombre, `1` para
    archivos que coinciden con un entry point o endpoint declarado en ProjectInfo, y
    `0` para el resto. Los empates se rompen por conteo de imports recibidos.
    El recorte por token budget respeta este orden para que el LLM local siempre
    vea los puntos de entrada HTTP primero.
33. **`context.py` usa tokens mínimos de 3 chars y una stoplist bilingüe**: las
    preguntas en español e inglés deben funcionar igual de bien. El límite de 3
    caracteres elimina artículos y preposiciones sin stoplist exhaustiva; la stoplist
    cubre los casos de alta frecuencia que sobrevivirían ese filtro ("cómo", "para", "the").
34. **`setup_agent.py` genera un `.md` copy-paste ready**, no ejecuta comandos: el
    usuario copia los bloques JSON que necesita. Esto sigue el principio "solo lectura
    sobre el proyecto analizado" — el agente nunca toca `~/.config/opencode` ni el
    archivo MCP del sistema.
35. **Bug: `add_list_fact` esperaba `Evidence | None` pero cmake/conan pasaban
    `list[Evidence]`**: la evidencia quedaba serializada como `[[{...}]]` en el JSON,
    rompiendo `ProjectInfo.load()`. Corregido quitando los corchetes en los sitios de
    llamada (no en la firma, que ya era correcta).
20. **Separador en búsqueda de versión Tomcat en `.smarttomcat/`**: el patrón
    `tomcat[-_/ ]?(\d+...)` ahora permite `/` para capturar `Apache Tomcat/10.1`
    de `catalina.properties`. Los comentarios HTML se eliminan antes para evitar
    capturar versiones de avisos de deprecación.
