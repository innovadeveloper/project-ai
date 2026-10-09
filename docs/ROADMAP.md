# Roadmap

Orden pensado para dar valor cuanto antes con los proyectos reales del usuario
(netclient = C++/CMake/Conan, hmdm = WAR/Tomcat/Maven). Cada ítem tiene
criterios de aceptación; no se marca hecho sin tests.

Leyenda: ✅ hecho · 🔜 siguiente · ⏳ pendiente

---

## Fase A — Base y Java/Maven ✅

- ✅ `model.py` — Fact, prioridades, fusión, serialización (round-trip).
- ✅ `scanner.py` — git/walk, carpetas generadas (aunque estén versionadas),
  builds previos, key_files por categoría (build, toolchain, container, ci, ide,
  config, scripts, docs).
- ✅ `adapters/base.py` — contrato, registro, `run_adapters` tolerante a fallos.
- ✅ `adapters/hints.py` — ver docstring.
- ✅ `adapters/maven.py` — ver docstring.

Pendientes menores de Maven/Spring (hacer junto con Fase D o cuando un proyecto
real lo pida):
- ⏳ Configuración Spring: leer `application*.yml|properties` → `server.port`,
  `server.servlet.context-path`, perfiles (`spring.profiles.active`),
  placeholders sin default `${DB_PASSWORD}` → fact `config.required_env`
  (lo usará runbook para generar `.env.example`).
- ⏳ Constantes en rutas JAX-RS/Spring: resolver `static final String X = "..."`
  en el mismo archivo o clase `Constants` (hoy sale `{Constants.API}`).
- ⏳ Techo de JDK ampliable: tabla en `maven.py` (lombok, source<=7). Añadir
  casos reales cuando aparezcan (plugins antiguos que fallan con JDK modernos).

## Fase B — C++ ✅

### `adapters/cmake.py` ✅
Detectar:
- `CMakeLists.txt` raíz (la que tiene `project()`); subdirectorios vía
  `add_subdirectory()`; ignorar los de `_deps`/third_party si están vendorizados
  (marcarlos como `vendored`).
- `cmake_minimum_required(VERSION x[...y])` → req `cmake` (BUILD). Rango
  `3.15...3.28` → mínimo 3.15.
- `project(NAME VERSION x LANGUAGES CXX C)`.
- Estándar: `set(CMAKE_CXX_STANDARD 17)`, `target_compile_features(... cxx_std_20)`,
  `CXX_STANDARD` en properties → req `cxx_standard` (máximo).
- Targets: `add_executable(n ...)` → Module kind `executable` + EntryPoint;
  `add_library(n STATIC|SHARED|INTERFACE ...)` → kind `library`;
  `target_link_libraries(a PRIVATE b)` → depends_on.
- Tests: `enable_testing()`, `add_test()`, `include(CTest)`, `gtest_discover_tests`,
  `catch_discover_tests` → comando `test` con `ctest --test-dir <build>`.
- Dependencias: `find_package(X [version] REQUIRED)` → fact
  `cmake.find_packages`; `FetchContent_Declare` (con URL/tag) → fact
  `cmake.fetchcontent` (necesita red al configurar).
- `CMakePresets.json` / `CMakeUserPresets.json`: presets de configure/build/test
  (JSON, `include` puede apuntar a `build/.../generators/CMakePresets.json`
  generado por Conan → si el archivo incluido no existe: aviso "ejecuta
  conan install primero").
- Toolchains: `CMAKE_TOOLCHAIN_FILE` en presets/cache; Android NDK
  (`android.toolchain.cmake`, `ANDROID_ABI`) → fact `cmake.cross_targets`.
- `compile_commands`: si `CMAKE_EXPORT_COMPILE_COMMANDS` no está, sugerir
  `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` (para clangd/Serena).
- Generador previo (de `hints.previous_cmake_builds`) → preferir el mismo.
Comandos: `configure` (preset si existe; si no `cmake -S . -B build
-DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON`), `build`
(`cmake --build build -j`), `test` (ctest), `run` (ruta del ejecutable principal;
cruzar con `hints.executables` de launch.json).
IDE hints: CLion (abrir carpeta / seleccionar preset), VS Code (CMake Tools:
"CMake: Select Configure Preset").

### `adapters/conan.py` ✅
- `conanfile.py` vs `conanfile.txt`; Conan 2 si `from conan import ConanFile`
  o `cmake_layout`/`CMakeToolchain`; Conan 1 si `from conans import` o
  generadores `cmake`/`cmake_find_package` → req `conan` (`2` o `1`) BUILD.
- `requires` / `tool_requires` / `[requires]` → fact `conan.requires`
  (`fmt/10.2.1`, …); `settings`, `options`, `default_options`.
- Layout: `cmake_layout` → carpeta `build/<BuildType>/generators`; esto explica
  los presets `conan-debug`/`conan-release`.
- Perfiles en el repo (`profiles/`, `.conan/profiles`) → fact; el usuario
  necesita `conan profile detect` si no tiene perfil por defecto.
- Remotes privados (`conan remote add` en docs/CI) → fact + aviso credenciales.
Comandos: `deps` = `conan install . --build=missing -s build_type=Debug`
(o el que aparezca en tasks.json/README, que tiene prioridad), luego
`configure` con preset `conan-debug`.
Criterio: con el fixture de netclient, salen `cmake`, `conan=2`, `cxx_standard`,
ejecutables `sample_test` y `event_loop_demo`, y comandos
deps → configure → build que coinciden con `.vscode/tasks.json`.

### `adapters/make.py` (pequeño) — 🔜 siguiente si se necesita
Solo si hay `Makefile` **no generado** y no hay CMakeLists: targets (`all`,
`test`, `install`), variables `CXX`, `CXXFLAGS -std=`. Sugerir `bear -- make`
para compile_commands.

## Fase C — Núcleo del flujo ⏳

### `recon.py` + `cli.py`
- `project-ai recon <ruta> [--only ...] [--json]` → escribe
  `<ruta>/.project-ai/project.json` y muestra el resumen (reusar
  `render_text` de `adapters/__main__.py`, moverlo a `report.py`).
- Añade `.project-ai/` al `.git/info/exclude` del proyecto (no tocar su
  `.gitignore`).
- `pyproject.toml`: `[project.scripts] project-ai = "project_ai.cli:main"`.
Criterio: correr dos veces es idempotente; `--json` == `project.json`.

### `repomap.py`
- Mapa compacto por módulo: archivos y símbolos (clases, métodos públicos,
  funciones libres, structs) con firmas, sin cuerpos. Objetivo 2–4k tokens;
  si se excede, priorizar archivos con entry points/endpoints y los más
  referenciados (conteo de includes/imports).
- Implementación: regex por lenguaje (Java/Kotlin/C++/Python/C#); tree-sitter
  opcional si está instalado (`py-tree-sitter` + gramáticas), con fallback.
Criterio: en hmdm el mapa cabe en 4k tokens y lista los resources REST.

### `doctor.py`
- Comprueba cada clave de `requirements` con comandos de versión (tabla en
  `docs/COMMANDS.md` → "Comprobaciones de doctor"). Timeout 10 s por comando.
- Lista JDKs instalados: macOS `/usr/libexec/java_home -V`, SDKMAN
  `~/.sdkman/candidates/java/*`, Linux `/usr/lib/jvm/*`.
- Tomcat: `$CATALINA_HOME`/`$CATALINA_BASE`, `version.sh`; Homebrew
  (`/opt/homebrew/opt/tomcat@9`). Cruza con `java.ee_namespace`.
- Servicios: conexión TCP a puertos por defecto (postgres 5432, mysql 3306,
  redis 6379, mqtt 1883, kafka 9092, rabbitmq 5672) — sin credenciales.
- Respeta `jdk` (mínimo) y `jdk_ceiling` (máximo): recomienda una versión
  instalada dentro del rango o el comando SDKMAN/brew/apt para instalarla.
- Salida `env-report.md` + código de salida ≠ 0 si hay ❌.

### `runbook.py`
- Fuentes de comandos por prioridad: verificados (journal) > IDE tasks > CI >
  adaptador > docs. Deduplicar por kind; mantener orden
  deps → configure → generate → build → test → run.
- Cada paso: `tee` a `logs/step-NN.log`, IDE hint, "éxito si", "si falla".
- Paso 0: arreglos de doctor (instalar JDK, levantar Postgres…).
- Servicios: si hay compose en el repo que define el servicio, proponerlo;
  si no, instrucciones locales (brew/apt) — el usuario decide.

### `triage.py` + `rules/*.toml` + `llm.py` + `config.py`
- Recorta log: primer `ERROR`/`FAILED`/`error:` + 40 líneas, quitando ruido
  de descargas.
- N0: reglas TOML (formato abajo; TOML porque `tomllib` es stdlib y YAML no).
  Coincidencia → causa + arreglo al instante.
- N1/N2/N2b: `llm.py` llama a Ollama `/api/chat` (urllib, stream off,
  `options.num_ctx` desde config). Prompt de sistema fijo en español que exige
  respuesta JSON `{causa, confianza, comando, explicacion}`.
- Política: N1 hasta 2 intentos por error distinto; si confianza < 0.6 o el
  usuario reporta que no funcionó → N2; luego N2b; luego N3 (humano).
- `journal.md` registra nivel que resolvió → métrica de alcance.
- `--learn`: convierte la resolución en regla candidata (el usuario confirma).
Formato de regla:
```toml
[[rule]]
id = "jdk-class-version"
stack = ["maven", "gradle"]
match = 'Unsupported class file major version (\d+)|invalid target release: (\S+)'
cause = "El JDK activo no coincide con el que exige el proyecto"
fix = "Usa el JDK de env-report.md (sdk use java <versión>) y repite el paso"
refs = ["requirements.jdk", "facts.jdk_ceiling"]
```
Ejemplos ya escritos (sin motor todavía): `rules/initial.toml`.
Reglas iniciales mínimas (escribirlas con tests): JDK incorrecto, lombok/JDK,
`javax` en Tomcat 10, `SDK location not found` (Android), Conan
`Missing prebuilt package` (→ `--build=missing`), `Could NOT find X`
(find_package), CMake `CMAKE_CXX_COMPILER not set`, puerto ocupado
(`Address already in use`), Postgres `Connection refused`, Maven
`401 Unauthorized` / `Could not resolve dependencies` en repo privado,
`PKIX path building failed` (certificados corporativos).

### `finalize.py`
- Marca comandos que tienen log con éxito como `verified` en project.json.
- Genera `AGENTS.md` con la plantilla de ARCHITECTURE.md (≤ 200 líneas).
- Opcional: `CLAUDE.md` del proyecto con una línea `@AGENTS.md`.

## Fase D — Gradle / Android / Kotlin ⏳
`adapters/gradle.py`:
- settings.gradle(.kts): `include(...)` módulos; wrapper → gradle EXPLICIT.
- `java { toolchain { languageVersion = JavaLanguageVersion.of(17) } }`,
  `sourceCompatibility`, `jvmTarget`, `kotlinOptions` → jdk.
- `libs.versions.toml` (version catalog) → versiones AGP, Kotlin, Spring Boot.
- Plugins: `com.android.application|library` (Android: compileSdk, minSdk,
  targetSdk, namespace, NDK `externalNativeBuild` → enlaza con cmake.py),
  `org.springframework.boot`, `war`, `application` (mainClass).
- Matriz AGP ↔ Gradle ↔ JDK (tabla pequeña y explícita, con fuente) →
  warnings. **El usuario resolverá Android a mano al principio**; el
  adaptador sirve para medir el alcance.
- Endpoints Spring en Kotlin (`@GetMapping` en `fun`).

## Fase E — Python y C# ⏳
- `python.py`: pyproject (PEP 621/poetry/uv/hatch), requirements*.txt,
  setup.py, `.python-version`, `requires-python`; framework (FastAPI, Django,
  Flask) → entry points y endpoints (`@app.get`, `urls.py`); comandos con uv
  si hay `uv.lock`, poetry si `poetry.lock`, si no `python -m venv` + pip.
- `dotnet.py`: `.sln`, `.csproj` (`TargetFramework` net8.0 → dotnet 8),
  `global.json` (ya en hints), ASP.NET (`Program.cs`, `MapGet`, controllers
  `[HttpGet]`), comandos `dotnet restore/build/test/run`, `launchSettings.json`
  (puertos, perfiles).

## Fase F — Integración con agentes locales ⏳
- Plantilla de config de **OpenCode** apuntando a los nodos (docs/NODES.md).
- Configuración de **Serena** por stack (clangd necesita compile_commands;
  jdtls necesita importar Maven/Gradle).
- `project-ai context "<pregunta>"`: imprime un paquete de contexto mínimo
  (resumen + módulos relevantes por grep de nombres) para pegar en cualquier
  chat local.

## Fase G — Medir el alcance (sin Claude) ⏳
- `docs/EVAL.md`: 10 tareas reales por stack (consulta, edición pequeña, nueva
  clase/archivo, nueva dependencia, arreglar build roto).
- Registrar por tarea: nivel que resolvió (N0/N1/N2/N2b/N3), tiempo, intentos.
- Objetivo: decidir con datos qué casos requieren humano.
