# project-ai — contexto para Claude Code

> Lee este archivo completo al empezar. Los detalles están en `docs/`; léelos
> **solo cuando la tarea lo requiera** (ahorra contexto).

## Qué es este proyecto

Herramienta en Python (solo stdlib, Python >= 3.11) que **reconoce proyectos de
software desconocidos** (Spring Boot, WAR en Tomcat, C++ con CMake/Conan; luego
Gradle/Android, Python y C#) y prepara todo para que **un humano los levante
siguiendo instrucciones** y para que **un agente con modelos locales (Ollama)**
trabaje después sobre ellos sin explorar a ciegas.

Objetivo del "alcance 1": **prescindir de Claude/cloud**. Todo el flujo debe
funcionar con reglas deterministas + modelos locales en 3 nodos propios
(ver `docs/NODES.md`). Claude Code se usa solo para **construir esta
herramienta**, no forma parte del flujo final.

## Flujo final (ver `docs/ARCHITECTURE.md`)

```
1 recon     descubre qué es el proyecto              (script, sin LLM)  → project.json, repo-map.md
2 doctor    compara requisitos con TU máquina        (script, sin LLM)  → env-report.md
3 runbook   pasos ordenados: comando + IDE + éxito    (script)           → RUNBOOK.md
4 el USUARIO ejecuta en su shell/IDE y guarda logs con tee               → .project-ai/logs/
5 triage    error → reglas → LLM local N1 → N2 → humano                   → diagnóstico / escalation.md
6 finalize  marca lo verificado y genera AGENTS.md                        → AGENTS.md
7 trabajo diario: OpenCode/agente + Ollama + Serena (LSP) leyendo AGENTS.md
```

Principios innegociables:
- **Sin Docker para explorar ni construir.** El usuario ejecuta los comandos.
  Docker solo puede aparecer como *pista* (leer Dockerfiles/compose) o para
  servicios (Postgres…) si el proyecto ya lo usa.
- **Solo lectura sobre el proyecto analizado.** Lo único que se escribe es
  `.project-ai/` y, en finalize, `AGENTS.md`.
- **Evidencia siempre**: cada dato es un `Fact` con archivo:línea, prioridad de
  fuente y estado. Nunca inventar un valor; si no hay evidencia → `missing`.
- **Sin grafos ni embeddings**: navegación bajo demanda (grep + LSP/Serena).

## Estado actual (actualízalo al terminar cada tarea)

Hecho y con tests (460 pasando):
- `project_ai/model.py` — Fact/Evidence/SourcePriority/Status, ProjectInfo con
  fusión por prioridad (empate → gana el archivo más cercano a la raíz).
- `project_ai/scanner.py` — listado git/walk, excluye carpetas generadas aunque
  estén versionadas, anota builds previos (CMakeCache, compile_commands).
- `project_ai/adapters/base.py` — contrato Adapter, registro, helpers,
  normalización de versiones, clasificación de comandos.
- `project_ai/adapters/hints.py` — toolchain files, Dockerfile, compose, CI,
  IDE (.vscode, IntelliJ, Smart Tomcat), docs, builds previos.
  Fix: comentarios HTML en `.smarttomcat/` ya no producen falsos positivos de versión Tomcat.
- `project_ai/adapters/maven.py` — módulos, JDK, Spring Boot vs WAR, javax vs
  jakarta + compatibilidad Tomcat, techo de JDK, servicios, endpoints, comandos.
- `project_ai/adapters/cmake.py` — cmake_minimum_required, C++ standard, targets
  (library/executable), find_package, FetchContent, presets (con aviso si archivos
  de Conan no generados aún), sugerencia CMAKE_EXPORT_COMPILE_COMMANDS, comandos
  configure/build/test/run.
- `project_ai/adapters/conan.py` — Conan 2 vs 1, requires (conanfile.py y .txt),
  generators, cmake_layout, perfiles en repo, comando deps.
- `project_ai/report.py` — `render_text(info)` extraído de `adapters/__main__.py`.
- `project_ai/recon.py` — `recon(path, *, only, debug, write)` → `ProjectInfo`;
  escribe `.project-ai/project.json` y `.project-ai/repo-map.md`;
  añade `.project-ai/` a `.git/info/exclude`.
- `project_ai/doctor.py` — `doctor(path, *, info, skip_services, os_hint, write)`
  → `DoctorReport`; verifica jdk (con ceiling), maven, cmake, conan, ninja, clang,
  gcc, python, node, tomcat, android; sonda puertos TCP; genera `env-report.md`.
  Exit code 1 si hay ❌. Fallback a recon si project.json está corrupto.
- `project_ai/repomap.py` — `build_repo_map(info, sc, *, max_tokens=4000)` → str;
  parsea Java (JAX-RS + Spring MVC, brace-depth counting, anotaciones HTTP),
  C++ (clases, structs, funciones libres) y Python (clases, métodos, funciones);
  prioriza controllers/resources > entry_points > más importados; trunca con aviso.
- `project_ai/runbook.py` — `runbook(path, *, info, doctor_report, os_hint, write)`
  → `RunbookResult`; pasos ordenados deps→configure→build→test→run, cada uno con
  tee a `.project-ai/logs/step-NN.log`; paso 0 de setup si doctor detecta fallos;
  pasos de servicios con docker compose o instrucciones locales (brew/apt).
- `project_ai/config.py` — `NodeConfig` + `Config`; carga `.project-ai/config.toml`
  o usa defaults (n1=llama3.2:3b local, n2=qwen2.5-coder:14b con más ctx).
- `project_ai/llm.py` — `chat(msg, *, node)` → `LLMResponse`; llama a Ollama
  `/api/chat` con `urllib` (sin dependencias externas); extrae JSON del modelo
  aunque envuelva la respuesta en bloques markdown; lanza `LLMError` si falla.
- `project_ai/triage.py` — `triage(log_path, *, info, config, dry_run, write)` →
  `TriageResult`; recorta log (primer ERROR + 40 líneas, sin ruido de descargas);
  N0 (reglas TOML), N1/N2 (Ollama, escalada por confianza < 0.6), N3 (humano);
  registra en `.project-ai/journal.md`.
- `project_ai/cli.py` — subcomandos `recon`, `adapters`, `doctor`, `runbook` y
  `triage` (con `--dry-run` / `--no-write`); `app = main`.
- `pyproject.toml` — solo stdlib + pytest/pyflakes dev; entry point `project_ai.cli:main`.
- CLI provisional mantenida: `python -m project_ai.scanner` y `python -m project_ai.adapters`.
- `rules/initial.toml` — 13 reglas N0 de triage (aún sin motor; validadas por
  `tests/test_rules.py`: cada `example` debe coincidir con su `match`).

- `project_ai/finalize.py` — `finalize(path, *, info, write)` → `FinalizeResult`;
  escanea `logs/step-*.log` para detectar éxito por kind (BUILD SUCCESS, Tests
  run Failures: 0, [100%] Built target…); marca comandos como `verified` en
  project.json; lee journal.md para extraer trampas conocidas; genera `AGENTS.md`
  (≤ 200 líneas) en la raíz del proyecto con stack, comandos, entorno, mapa,
  trampas y punteros de navegación.
- `project_ai/context.py` — `context(path, query, *, max_tokens=3000)` → str;
  carga AGENTS.md §1–§2 o fallback de project.json, busca en repo-map.md y
  endpoints por tokens de la pregunta, ensambla dentro del presupuesto de tokens.
- `project_ai/setup_agent.py` — `setup_agent(path, *, info, config, write)` → str;
  genera `.project-ai/setup-agent.md` con config OpenCode JSON, config Serena MCP
  por stack (clangd para cmake, jdtls para maven/gradle), verificaciones curl y
  ejemplo de `project-ai context`.
- `project_ai/adapters/python.py` — detecta pyproject.toml (PEP 621, Poetry, uv,
  hatch), requirements*.txt, setup.py, .python-version; frameworks FastAPI/Django/Flask
  → endpoints y servicios; gestor de paquetes → comandos deps/run/test; endpoints
  FastAPI con prefijos de include_router, Flask @route con methods=[], Django urls.py.
- `project_ai/cli.py` — subcomandos `recon`, `adapters`, `doctor`, `runbook`,
  `triage`, `finalize`, `context` y `setup-agent`; `app = main`.
- **Bug corregido**: `cmake.py` y `conan.py` pasaban `evidence=[ev(...)]` a
  `add_list_fact` (que espera `Evidence | None`); la lista quedaba como lista
  anidada en el JSON impidiendo `ProjectInfo.load()` → corregido a `evidence=ev(...)`.

**Fases C, E (Python) y F completas.** Siguiente: `dotnet.py` (Fase E resto) o Fase G (evaluación).
Ver ROADMAP.

## Cómo trabajar en este repo

```bash
uv run pytest -q                                   # siempre antes y después de cambiar algo
uv run python -m pyflakes project_ai tests         # lint (instalar: uv add --dev pyflakes)
uv run python -m project_ai.scanner  <ruta>        # qué archivos ve
uv run python -m project_ai.adapters <ruta>        # qué descubre (texto)
uv run python -m project_ai.adapters <ruta> --json # todo, con evidencias
uv run python -m project_ai.adapters <ruta> --only hints maven --debug
```
Referencia completa de comandos (actuales y planificados): `docs/COMMANDS.md`.

Proyectos reales del usuario para validar (macOS):
- C++ / CMake / Conan: `/Users/kenny/Documents/Projects/C++Projects/netclient`
- WAR / Tomcat / Maven: `/Users/kenny/Documents/Projects/SpringbootProjects/hmdm-server-source-code-service`
Hallazgos ya conocidos de ambos: `docs/REAL_PROJECTS.md`.

## Reglas para Claude Code en este repo

1. **Tests primero con fixtures realistas.** Cada adaptador nuevo trae fixtures
   en `tests/conftest.py` que imitan estructuras reales (ver los de netclient,
   hmdm y spring-api). Cada bug encontrado en un proyecto real → un test.
2. **Solo stdlib.** Nada de PyYAML, lxml, tree-sitter… salvo que se discuta
   antes (tree-sitter será opcional en `repomap.py`, con fallback a regex).
3. **Un adaptador nunca ejecuta comandos ni modifica el proyecto.** Solo lee.
   (`doctor` sí ejecuta comandos de *versión* en la máquina, nunca builds.)
4. Sigue `docs/ADAPTER_GUIDE.md`: claves de requisitos estándar, prioridades,
   `add_cmd_hint`, `add_service`, `set_fact`, `add_list_fact`.
5. Comentarios y mensajes al usuario en **español**; identificadores en inglés.
6. No rompas el orden de registro en `adapters/__init__.py` (hints primero).
7. Al terminar una tarea: actualiza "Estado actual" aquí y marca el ROADMAP.
8. Decisiones de diseño nuevas → añádelas a `docs/DECISIONS.md` (1 párrafo).
9. Si una heurística es dudosa, márcala `HEURISTIC` y explícala en `note`;
   es preferible un aviso que un dato falso.

## Mapa de documentación

| Archivo | Cuándo leerlo |
|---|---|
| `docs/ARCHITECTURE.md` | flujo completo, archivos de salida y su contenido, modelo de datos |
| `docs/ROADMAP.md` | qué falta, en qué orden, criterios de aceptación de cada pieza |
| `docs/COMMANDS.md` | todos los comandos: herramienta, toolchains por stack, Ollama por nodo |
| `docs/NODES.md` | 3 nodos (RTX 5070, M1 Max, M2 Pro), modelos, escalado N0–N3 |
| `docs/ADAPTER_GUIDE.md` | cómo escribir un adaptador nuevo (checklist) |
| `docs/DECISIONS.md` | por qué se decidió cada cosa (no reabrir sin motivo) |
| `docs/REAL_PROJECTS.md` | salidas reales de netclient/hmdm y lo que enseñaron |

Slash commands del proyecto (`.claude/commands/`): `/siguiente-paso`,
`/nuevo-adaptador <stack>`, `/probar-real <ruta>`.
