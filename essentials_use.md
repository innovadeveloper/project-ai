# project-ai — Guía de uso esencial

Herramienta de línea de comandos que **analiza un proyecto de software desconocido**
y genera toda la documentación necesaria para levantarlo y trabajar con él mediante
un agente de IA local (Ollama + OpenCode + Serena).

---

## Instalación

Requisito previo: Python ≥ 3.11 y [uv](https://docs.astral.sh/uv/).

```bash
git clone <este-repo>
cd project-ai
uv tool install .
# Verifica:
project-ai --help
```

---

## Flujo completo (de cero a agente funcionando)

```
recon → doctor → runbook → [tú ejecutas] → triage → finalize → setup-agent
```

### Paso 1 — Analizar el proyecto

```bash
project-ai recon /ruta/al/proyecto
```

Genera `.project-ai/project.json` y `.project-ai/repo-map.md`.
Detecta stack, versiones requeridas, endpoints, servicios y comandos.

```bash
# Ver solo el resumen en texto:
project-ai adapters /ruta/al/proyecto

# Ver todo con evidencias (archivos y líneas):
project-ai adapters /ruta/al/proyecto --json

# Solo ciertos adaptadores:
project-ai adapters /ruta/al/proyecto --only hints maven
```

### Paso 2 — Comprobar tu máquina

```bash
project-ai doctor /ruta/al/proyecto
```

Compara lo que el proyecto necesita con lo que tienes instalado.
Genera `.project-ai/env-report.md`. Devuelve exit code 1 si hay ❌.

```bash
# Sin comprobar puertos TCP (más rápido):
project-ai doctor /ruta/al/proyecto --skip-services

# Forzar recetas para un SO concreto:
project-ai doctor /ruta/al/proyecto --os macos
project-ai doctor /ruta/al/proyecto --os linux
```

### Paso 3 — Generar el runbook

```bash
project-ai runbook /ruta/al/proyecto
```

Genera `.project-ai/RUNBOOK.md` con los pasos numerados:
`setup → servicios → deps → configure → build → test → run`.
Cada paso incluye el comando con `tee` para guardar el log.

### Paso 4 — Ejecutar los pasos (tú)

Sigue el RUNBOOK.md en tu terminal. Los logs se guardan automáticamente
en `.project-ai/logs/step-NN.log`.

Si un paso falla, ve al Paso 5. Si todo funciona, salta al Paso 6.

### Paso 5 — Diagnosticar errores

```bash
project-ai triage .project-ai/logs/step-02.log
```

Busca el error en las reglas N0 (instantáneo). Si no coincide,
consulta a Ollama (N1 → N2). Registra el diagnóstico en
`.project-ai/journal.md`.

```bash
# Solo reglas, sin llamadas al LLM:
project-ai triage .project-ai/logs/step-02.log --dry-run
```

### Paso 6 — Marcar como verificado y generar AGENTS.md

```bash
project-ai finalize /ruta/al/proyecto
```

Escanea los logs en busca de señales de éxito, marca los comandos
como `verified` y genera `AGENTS.md` en la raíz del proyecto.
`AGENTS.md` es el archivo que leerá el agente para orientarse.

### Paso 7 — Configurar el agente

```bash
project-ai setup-agent /ruta/al/proyecto
```

Genera `.project-ai/setup-agent.md` con el `opencode.json` listo
para copiar a la raíz del proyecto. Incluye la configuración de
Serena (LSP vía MCP) adaptada al stack detectado.

---

## Consultas al vuelo

```bash
# Genera un paquete de contexto para pegar en cualquier chat LLM:
project-ai context "cómo funciona la autenticación" --path /ruta/al/proyecto

# Ajustar el presupuesto de tokens:
project-ai context "qué hace DeviceService" --path /ruta/al/proyecto --max-tokens 2000
```

---

## Stacks soportados

| Stack | Archivos clave detectados | Qué extrae |
|---|---|---|
| **Maven** (Spring Boot, WAR) | `pom.xml` | JDK, módulos, javax/jakarta, endpoints REST, servicios |
| **CMake** (C++) | `CMakeLists.txt`, `CMakePresets.json` | estándar C++, targets, find_package, presets |
| **Conan** (C++) | `conanfile.py`, `conanfile.txt` | versión Conan, requires, cmake_layout |
| **Python** (FastAPI, Django, Flask) | `pyproject.toml`, `requirements*.txt`, `setup.py` | versión Python, framework, endpoints, servicios |
| **Hints** (transversal) | `Dockerfile`, `docker-compose.yml`, `.vscode/`, CI | comandos, toolchain, builds previos |

### Próximamente

- Gradle / Android / Kotlin
- .NET / C# (`.csproj`, `.sln`)

---

## Referencia rápida de comandos

```
project-ai recon      <ruta> [--only ADAPTER...] [--json] [--no-write] [--debug]
project-ai adapters   <ruta> [--only ADAPTER...] [--json] [--debug]
project-ai doctor     <ruta> [--skip-services] [--os macos|linux] [--no-write]
project-ai runbook    <ruta> [--os macos|linux] [--no-write]
project-ai triage     <log>  [--dry-run] [--no-write]
project-ai finalize   <ruta> [--no-write]
project-ai setup-agent <ruta> [--no-write]
project-ai context    "<pregunta>" --path <ruta> [--max-tokens N]
```

---

## Troubleshooting

### El proyecto no se reconoce ("stack: desconocido")

**Síntomas**: `project-ai adapters .` no muestra ningún stack o dice "desconocido".

**Causas frecuentes y soluciones**:

1. **El proyecto usa un stack no soportado aún** (Gradle, .NET, Go, Rust…).
   - Mira si hay `build.gradle`, `*.csproj`, `go.mod`, `Cargo.toml`.
   - Por ahora, anota a mano el stack en `.project-ai/project.json` o
     espera el adaptador correspondiente.

2. **Los archivos de build están en un subdirectorio inesperado**.
   - Apunta `recon` directamente a ese subdirectorio:
     ```bash
     project-ai recon /ruta/al/proyecto/backend
     ```

3. **El proyecto no tiene archivos de build** (solo scripts sueltos).
   - El adaptador `hints` aún puede extraer comandos de `Makefile`,
     `Dockerfile` o scripts de CI.

4. **El `pom.xml` o `CMakeLists.txt` tienen errores de sintaxis**.
   - Corre `project-ai adapters . --debug` para ver el traceback completo.

---

### doctor muestra ❌ pero creo que tengo lo necesario

1. **JDK incorrecto**: el proyecto puede requerir un rango específico
   (p.ej. `>= 11, <= 17`). Comprueba con `java -version` y usa
   SDKMAN (`sdk use java 17.x`) o Homebrew para cambiar.

2. **Herramienta no en el PATH**: `cmake`, `conan`, `mvn` pueden estar
   instalados pero no accesibles. Comprueba con `which cmake`.

3. **Servicio no escucha**: PostgreSQL/Redis/etc. pueden estar instalados
   pero sin arrancar. Usa `--skip-services` para ignorar puertos.

---

### triage devuelve nivel N3 (sin diagnóstico)

Significa que ninguna regla N0 coincidió y Ollama tampoco pudo ayudar.

1. **Ollama no está corriendo**:
   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   # En otro terminal:
   curl http://localhost:11434/api/tags
   ```

2. **El modelo no está descargado**:
   ```bash
   ollama pull qwen2.5-coder:14b
   ```

3. **El log no tiene el error real** (solo stacktrace sin causa):
   - Sube por el log buscando el primer `ERROR` o `FAILED`.
   - Pasa ese fragmento directamente al modelo con `project-ai context`.

4. **El error es nuevo** (no está en las reglas):
   - El log siempre se guarda. Puedes añadir una regla manual en
     `rules/initial.toml` siguiendo el formato existente.

---

### Los endpoints no aparecen o están incompletos

- **Java**: los endpoints JAX-RS necesitan `@Path` en la clase Y en el método.
  Si la clase no tiene `@Path`, no se detectan. Comprueba con `--debug`.

- **FastAPI con routers en subdirectorios anidados**: si el `include_router`
  está en un archivo distinto al `main.py`, el prefijo puede no detectarse.
  Workaround: busca en `repo-map.md` las rutas detectadas.

- **Django con `re_path`**: se detecta como patrón regex, no como ruta limpia.
  Es normal ver `^api/devices/$` en vez de `/api/devices/`.

- **Flask con `Blueprint`**: los blueprints aún no se resuelven.
  Los endpoints aparecerán sin el prefijo del blueprint.

---

### finalize no marca ningún comando como verificado

`finalize` busca patrones de éxito en `logs/step-*.log`. Si los logs
no existen o no contienen las señales esperadas:

1. Comprueba que los logs están en `.project-ai/logs/`:
   ```bash
   ls .project-ai/logs/
   ```

2. Los patrones reconocidos como éxito son:
   - **build Maven**: `BUILD SUCCESS`
   - **build CMake**: `[100%] Built target` o `cmake --build` sin error
   - **test Maven**: `Tests run: X, Failures: 0, Errors: 0`
   - **test pytest**: `passed`
   - **run Spring Boot**: `Started ... in X.X seconds`
   - **run uvicorn**: `Application startup complete`

3. Si el log tiene éxito pero no coincide con ningún patrón, abre
   un issue con el fragmento de log para añadir el patrón.

---

### project-ai no se puede instalar / ImportError

```bash
# Verificar versión de Python (debe ser >= 3.11):
python3 --version

# Instalar en modo editable para desarrollo:
uv pip install -e .

# Ver errores de importación:
python3 -c "import project_ai; print('OK')"
```

---

## Estructura de `.project-ai/`

```
.project-ai/
├── project.json       ← datos estructurados del proyecto (recon)
├── repo-map.md        ← mapa compacto de clases y métodos (recon)
├── env-report.md      ← estado de la máquina (doctor)
├── RUNBOOK.md         ← pasos para levantar el proyecto (runbook)
├── journal.md         ← historial de diagnósticos (triage)
├── setup-agent.md     ← config OpenCode + Serena (setup-agent)
├── config.toml        ← (opcional) URLs y modelos de tus nodos Ollama
└── logs/
    ├── step-00.log    ← log del paso 0 (setup)
    ├── step-01.log    ← log del paso 1 (servicios)
    └── step-02.log    ← log del paso 2 (deps)…
```

### config.toml opcional

Si tus nodos Ollama no están en `localhost:11434`, crea
`.project-ai/config.toml` en el proyecto analizado:

```toml
[n1]
url = "http://192.168.1.10:11434"
model = "qwen2.5-coder:14b"
timeout = 120
num_ctx = 8192

[n2]
url = "http://192.168.1.11:11434"
model = "qwen3.8:27b"
timeout = 180
num_ctx = 16384
```

---

## Lo que esta herramienta NO hace

- **No ejecuta builds** ni modifica el proyecto analizado.
  Solo escribe en `.project-ai/` y (en `finalize`) en `AGENTS.md`.
- **No usa Docker** para analizar ni construir. Docker solo aparece
  como pista para leer configuración.
- **No inventa datos**. Si no hay evidencia, el dato queda como
  `missing` o `default` con nota explicativa.
- **No reemplaza a un humano** para resolver problemas complejos (N3).
  Escala hasta donde puede y documenta lo que encontró.
