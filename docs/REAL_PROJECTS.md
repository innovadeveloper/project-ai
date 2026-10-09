# Proyectos reales de validación

Rutas en el MacBook del usuario. Lo que sigue son hallazgos de ejecuciones
reales; los fixtures `NETCLIENT` y `HMDM` de `tests/conftest.py` los imitan.

## netclient — C++ / CMake / Conan 2
Ruta: `/Users/kenny/Documents/Projects/C++Projects/netclient`

Estructura vista: `CMakeLists.txt`, `CMakeUserPresets.json`, `conanfile.py`,
`main.cpp`, `include/`, `src/`, `examples/`, `assets/`, `readme.md`
(minúsculas), `new_module_c++.sh`, `tmp.md`, `.vscode/`, `.cache/` (clangd),
`build/` y `build-android/` **versionados en git** (con CMakeCache,
generators de Conan, Makefiles, compile_commands).

Lo que `hints` ya extrae:
- `.vscode/tasks.json`: `conan install . --build=missing -s build_type=Debug`
  → `cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=build/Debug/generators/...`
  → `cmake --build build`.
- `.vscode/launch.json`: ejecutables `build/sample_test`, `build/event_loop_demo`.
- `readme.md`: flujo para Android (`cmake -S . -B build-android ...`).
- compile_commands en `build-android/`, `build/Debug/`, `build/`.
- Build previo Android: Release, Unix Makefiles, toolchain del NDK.

Ejecución real de `adapters` (2026-10-09):

**Lo que hints detecta bien:**
- Comandos correctos desde `.vscode/tasks.json` y `readme.md`:
  `conan install`, `cmake -B build`, `cmake --build build`, variante Android.
- `hints.executables`: `build/sample_test`, `build/event_loop_demo`.
- `hints.previous_cmake_builds`: caché de build macOS (Ninja, Debug) y
  Android (toolchain de Conan cruzado).
- `hints.compile_commands`: 3 archivos encontrados.
- `ide.run_configs`: vscode-tasks + vscode-launch correctos.

**Lo que falta — `cmake.py` / `conan.py` aún no existen:**

| Dato esperado | Fuente | Valor correcto |
|---|---|---|
| `stack: cmake` | `CMakeLists.txt:1` | `cmake@3.20` (cmake_minimum_required) |
| `cxx_standard` | `CMakeLists.txt:4` | `17` (C++17, REQUIRED) |
| Targets (library) | `CMakeLists.txt:8` | `system_sora_ws` (SHARED) |
| Targets (exe) | `CMakeLists.txt:33,41` | `system_sora_ws_test`, `event_loop_demo` |
| find_package deps | `CMakeLists.txt:15-17` | CURL, eclipse-paho-mqtt-c, Libwebsockets |
| Plataformas | `CMakeLists.txt:23-30` | APPLE, ANDROID (Linux→FATAL_ERROR) |
| `stack: conan` | `conanfile.py:1` | conan 2.x (usa `from conan import ConanFile`) |
| Conan requires | `conanfile.py:9-11` | `libcurl/8.5.0`, `paho-mqtt-c/1.3.16`, `libwebsockets/4.5.8` |
| Conan generators | `conanfile.py:6` | `CMakeToolchain`, `CMakeDeps` |
| Android NDK | `readme.md:16` | `/opt/homebrew/share/android-commandlinetools/ndk/26.1.10909125` |
| Android ABI | `readme.md:21` | `arm64-v8a` / `android-24` |
| Stacks | — | `(ninguno aún)` — correcto hasta que existan los adaptadores |

**Notas de diseño para cmake.py / conan.py:**
- El `CMakeCache.txt` de macOS usa Ninja (generator) pero el de Android usa
  Unix Makefiles + toolchain de Conan — `hints.py` ya los lee correctamente.
- `CMakeUserPresets.json` incluye archivos generados en `build/` (no versionados);
  no leer su contenido para extraer presets, solo detectar que existe.
- Conan 2 se distingue de Conan 1 por `from conan import ConanFile` (vs
  `from conans import ConanFile`).
- La cross-compilación Android sale de `readme.md` y del `CMakeCache.txt` de
  `build-android/` (ANDROID_NDK, ANDROID_ABI, ANDROID_PLATFORM).

Tarea típica que el usuario quiere hacer luego con el modelo local: "crear
un nuevo .cpp que implemente una clase .h del proyecto", "añadir una
dependencia de Conan".

## hmdm — WAR en Tomcat / Maven multi-módulo
Ruta: `/Users/kenny/Documents/Projects/SpringbootProjects/hmdm-server-source-code-service`
(pese al nombre de la carpeta, **no es Spring Boot**: WAR en Tomcat).

Estructura vista: ~1084 archivos; módulos `common/`, `jwt/`, `notification/`,
`plugins/` (con submódulos, p.ej. `plugins/audit`), `server/`;
`.smarttomcat/` (copia de conf de Tomcat local 9.0.109), `context.xml`,
`BUILD.txt`, `INSTALL.txt`, `TROUBLESHOOTING.txt`, `README.md` extenso,
`readme_build.md` (notas del usuario sobre su entorno: openjdk 17.0.14,
Maven 3.9.11), varios `docker/*/docker-compose.yml`, `Dockerfile` raíz
(`tomcat:9-jdk8-openjdk`), `docker/hmdm-docker-0.1.5/Dockerfile`
(`tomcat:9-jdk11-temurin-jammy`), scripts `hmdm_install.sh`,
`step_001_create_image_and_publish.sh`.

Hallazgos de la ejecución real de `adapters` (ejecutada 2026-10-09):
- **82 tests pasando** — scanner + adapters funcionan sobre el proyecto real.
- README trae la receta: `mvn clean install -pl common,jwt,notification,plugins -am -DskipTests`
  y luego `mvn clean package -pl server -am -DskipTests`.
- WAR → `COPY server/target/launcher.war /usr/local/tomcat/webapps/ROOT.war`.
- Postgres 13 (compose), registro privado `registrydev-service.abexa.pe/hmdm`.
- Contenedor `mqtt-connections` (Mosquitto) usado en README pero no definido
  en ningún compose → `hints.undefined_containers`.
- **16 módulos** Maven correctamente detectados con tipos (library/war/aggregator).
- **158 endpoints** JAX-RS extraídos de las clases `*Resource.java`.
- `java.ee_namespace: javax` correcto (50 señales javax, 0 jakarta).
- `jdk: 8` correcto desde `pom.xml:45`; `jdk: 17` de readme correctamente descartado.
- `jdk_ceiling: 16` correcto (lombok 1.18.20 no compila con JDK ≥ 17).
- `tomcat: 9` correcto desde Dockerfile.

**Bug encontrado — falso positivo `ide.tomcat_local: 10.1`**:
- `hints.py:444` busca `tomcat[-_ ]?(\d+\.\d+)` en **todos** los archivos de
  `.smarttomcat/**`. El `web.xml` (línea 198) tiene el comentario HTML
  `<!-- Deprecated. Will be removed in Tomcat 10.1 -->` y la regex lo captura.
- El Tomcat real del usuario es **9.0.109** (declarado en `readme_build.md:4`).
- Consecuencia: el aviso "javax con Tomcat 10.1 → WAR no arrancará" es incorrecto.
- Fix: restringir la búsqueda a `server.xml` (que sí contiene la versión real)
  o filtrar matches dentro de comentarios HTML `<!-- -->`.
- Test mínimo: fixture con `web.xml` que tenga el comentario "Tomcat 10.1" y
  `server.xml` sin versión; verificar que `ide.tomcat_local` no es `10.1`.

## Cómo añadir un proyecto nuevo aquí
Ruta, stack, estructura relevante, salida resumida de `adapters`, qué estuvo
mal y qué test lo cubre.
