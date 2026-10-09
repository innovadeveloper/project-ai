# Referencia de comandos

Tres grupos: (1) la herramienta `project-ai`, (2) desarrollo de este repo,
(3) toolchains que `doctor`/`runbook` recomiendan al usuario por stack.
Los comandos de modelos/Ollama por nodo están en `docs/NODES.md`.

Convención: ✅ existe hoy · ⏳ planificado (Fase indicada en ROADMAP).

---

## 1. Herramienta `project-ai`

### ✅ `python -m project_ai.scanner <ruta> [opciones]`
Lista y resume los archivos fuente. Solo lectura.
| Opción | Efecto |
|---|---|
| `--json` | resumen en JSON (key_files, generated_dirs, build_artifacts…) |
| `--no-git` | recorrer disco aunque sea repo git |
| `--grep REGEX` | buscar una regex en todos los archivos fuente y salir |
| `--show-generated` | listar todas las carpetas excluidas por generadas |
Ejemplo: `uv run python -m project_ai.scanner ~/Projects/netclient`

### ✅ `python -m project_ai.adapters <ruta> [opciones]`
Ejecuta los adaptadores y muestra lo descubierto. Provisional hasta `recon`;
no escribe nada.
| Opción | Efecto |
|---|---|
| `--only hints maven ...` | solo esos adaptadores |
| `--json` | ProjectInfo completo con evidencias |
| `--debug` | traceback si un adaptador falla (si no, solo un aviso) |
| `--no-git` | igual que en scanner |

### ⏳ `project-ai recon <ruta>` (Fase C)
Escribe `<ruta>/.project-ai/project.json` (+ `repo-map.md`). Opciones:
`--only`, `--json` (a stdout), `--no-git`, `--quiet`.

### ⏳ `project-ai doctor <ruta>` (Fase C)
Compara requisitos con la máquina. Escribe `env-report.md`. Exit code 1 si hay ❌.
Opciones: `--os macos|ubuntu` (forzar recetas), `--skip-services`.

### ⏳ `project-ai runbook <ruta>` (Fase C)
Genera `RUNBOOK.md`. Opciones: `--ide intellij|vscode|clion|android-studio`
(qué pista de IDE mostrar), `--with-llm` (redactar con N1).

### ⏳ `project-ai triage <ruta> <step-NN | archivo.log>` (Fase C)
Diagnostica un fallo: N0 reglas → N1 → N2 → N2b → humano.
| Opción | Efecto |
|---|---|
| `--level n0|n1|n2|n2b` | empezar en un nivel concreto |
| `--max-level n1` | no escalar más allá |
| `--failed` | "probé la sugerencia y no funcionó" → escala |
| `--learn` | guarda la última resolución como regla candidata |
| `--dry-run` | muestra el paquete que se enviaría al modelo, sin llamarlo |

### ⏳ `project-ai finalize <ruta>` (Fase C)
Marca lo verificado y genera `AGENTS.md`. `--claude-md` crea además
`CLAUDE.md` con `@AGENTS.md`.

### ⏳ `project-ai context <ruta> "<pregunta>"` (Fase F)
Paquete de contexto mínimo para pegar en un chat local.

### ⏳ `project-ai nodes [check]` (Fase C, con `llm.py`)
Lista nodos de `~/.project-ai/config.toml`, comprueba que responden
(`/api/tags`) y qué modelos tienen cargados.

---

## 2. Desarrollo de este repo

```bash
uv sync                                   # instala entorno (pytest como dev)
uv add --dev pytest pyflakes              # si faltan
uv run pytest -q                          # todos los tests
uv run pytest -q tests/test_maven.py -k endpoints
uv run python -m pyflakes project_ai tests
```
Flujo para validar con un proyecto real:
```bash
uv run python -m project_ai.scanner  <ruta> > /tmp/scan.txt
uv run python -m project_ai.adapters <ruta> > /tmp/adapters.txt
uv run python -m project_ai.adapters <ruta> --json > /tmp/info.json
```
Si algo sale mal: copiar el caso mínimo a `tests/conftest.py` como fixture,
escribir el test que falla y luego arreglar.

---

## 3. Toolchains por stack (lo que doctor/runbook recomendarán)

### 3.1 Java / Maven / Spring Boot
```bash
# JDKs (SDKMAN, macOS y Ubuntu)
curl -s "https://get.sdkman.io" | bash
sdk list java
sdk install java 8.0.392-tem     # ejemplo; usar la versión de env-report
sdk use java 17.0.12-tem          # solo esta terminal
sdk default java 21.0.4-tem
/usr/libexec/java_home -V         # macOS: JDKs instalados
# Maven
sdk install maven 3.9.6           # o: brew install maven / apt install maven
mvn -v
# Build
./mvnw -DskipTests package        # usar wrapper si existe
mvn -pl server -am -DskipTests package
mvn test ; mvn -Dtest=Clase#metodo test
mvn dependency:tree -Dincludes=grupo:artefacto
mvn help:effective-pom            # ver propiedades resueltas
./mvnw spring-boot:run -Dspring-boot.run.profiles=dev
java -jar target/app.jar --server.port=8081
```
IntelliJ: Maven tool window → Reload; Lifecycle → package; Run sobre la clase
`@SpringBootApplication`; Project Structure → SDK para elegir JDK.

### 3.2 WAR en Tomcat
```bash
# Instalar Tomcat 9 (javax.*) o 10.1+ (jakarta.*) — ver java.ee_namespace
brew install tomcat@9                         # macOS
sudo apt install tomcat9                      # Ubuntu (servicio del sistema)
# o descargar el zip de tomcat.apache.org y descomprimir en ~/opt
export CATALINA_HOME=~/opt/apache-tomcat-9.0.x
"$CATALINA_HOME/bin/version.sh"
cp server/target/launcher.war "$CATALINA_HOME/webapps/ROOT.war"
"$CATALINA_HOME/bin/catalina.sh" run          # primer plano, logs en consola
tail -f "$CATALINA_HOME/logs/catalina.out"
```
IntelliJ Ultimate: Run Configuration → Tomcat Server → Local (deployment: el
WAR o el artefacto exploded, contexto `/`). Community: plugin Smart Tomcat
(apunta a la carpeta de Tomcat; `.smarttomcat/` del repo es copia de esa conf).

### 3.3 C++ / CMake / Conan
```bash
# Herramientas
brew install cmake ninja conan llvm           # macOS
sudo apt install build-essential cmake ninja-build clang clangd pipx && pipx install conan
cmake --version ; conan --version ; clang++ --version
conan profile detect --force                  # perfil por defecto (Conan 2)
# Flujo Conan 2 + presets
conan install . --build=missing -s build_type=Debug
cmake --preset conan-debug                    # o: cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=build/Debug/generators/conan_toolchain.cmake
cmake --build --preset conan-debug -j
ctest --preset conan-debug --output-on-failure
# Sin presets
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build -j
# compile_commands para clangd/Serena
ln -sf build/compile_commands.json .           # o configurar clangd --compile-commands-dir
bear -- make                                   # proyectos solo-Make
```
VS Code: extensión CMake Tools → "CMake: Select Configure Preset"; clangd.
CLion: abrir carpeta → elegir preset de Conan.

### 3.4 Gradle / Android / Kotlin (Fase D)
```bash
./gradlew --version ; ./gradlew tasks
./gradlew build -x test ; ./gradlew test
./gradlew :app:assembleDebug                  # Android → app/build/outputs/apk/debug/
./gradlew bootRun                             # Spring Boot con Gradle
echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties   # macOS
```
Android Studio: Settings → Build Tools → Gradle → Gradle JDK.

### 3.5 Python (Fase E)
```bash
uv sync ; uv run pytest ; uv run python -m <paquete>
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

### 3.6 C# / .NET (Fase E)
```bash
dotnet --list-sdks ; dotnet restore ; dotnet build ; dotnet test
dotnet run --project src/Api --launch-profile http
```

---

## 4. Comprobaciones de `doctor` (especificación)

| Clave | Comando | Parseo |
|---|---|---|
| jdk | `java -version` (stderr) | `version "1.8.0_392"` → 8; `"17.0.12"` → 17 |
| jdk (instalados) | `/usr/libexec/java_home -V`, `ls ~/.sdkman/candidates/java` | lista |
| maven | `mvn -v` | `Apache Maven (\S+)` |
| gradle | `./gradlew --version` o `gradle --version` | `Gradle (\S+)` |
| tomcat | `$CATALINA_HOME/bin/version.sh` | `Server number:\s+(\S+)` |
| cmake | `cmake --version` | `cmake version (\S+)` |
| conan | `conan --version` | `Conan version (\S+)` |
| ninja | `ninja --version` | número |
| gcc / clang | `g++ --version` / `clang++ --version` | primera línea |
| python | `python3 --version` | `Python (\S+)` |
| node | `node -v` | `v(\S+)` |
| dotnet | `dotnet --list-sdks` | lista |
| android | `$ANDROID_HOME`, `local.properties` | existe |
| servicios | TCP connect a localhost:puerto (1 s) | abierto/cerrado |
Nunca ejecutar builds ni instalar nada desde doctor: solo proponer el comando.
