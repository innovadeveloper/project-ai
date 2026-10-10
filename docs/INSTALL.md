# Instalación y uso de project-ai

Herramienta de línea de comandos (Python ≥ 3.11, solo stdlib).
Reconoce proyectos de software desconocidos y genera contexto para
agentes locales (Ollama).

---

## Requisitos previos

| Herramienta | Versión mínima | Para qué la usa |
|---|---|---|
| Python | 3.11 | ejecutar la herramienta |
| Git | cualquiera | listar archivos del proyecto (fallback: walk) |
| Ollama | 0.1+ | pasos 5 triage (opcional si usas solo recon/doctor) |

---

## Instalación

### Opción A — con `uv` (recomendada, todos los OS)

```bash
# Instalar uv si no lo tienes
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell):
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Clonar e instalar
git clone https://github.com/tu-usuario/project-ai.git
cd project-ai
uv sync
```

Después de `uv sync`, el comando `project-ai` queda disponible en el entorno virtual de uv.
Para invocarlo sin activar el entorno:

```bash
uv run project-ai recon /ruta/al/proyecto
```

### Opción B — con `pip` + virtualenv

```bash
git clone https://github.com/tu-usuario/project-ai.git
cd project-ai
python3 -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -e .
project-ai --help
```

---

## Flujo completo paso a paso

```
proyecto/
└── (archivos del proyecto desconocido)
```

```bash
# 1. Reconocer el proyecto (escribe .project-ai/project.json y repo-map.md)
project-ai recon /ruta/proyecto

# 2. Diagnosticar el entorno (compara requisitos con tu máquina)
project-ai doctor /ruta/proyecto

# 3. Generar el runbook de comandos
project-ai runbook /ruta/proyecto

# 4. Ejecutar los pasos del runbook (tú los ejecutas, guardando logs con tee)
# Ejemplo:
mvn dependency:go-offline 2>&1 | tee .project-ai/logs/step-01.log
mvn package -DskipTests  2>&1 | tee .project-ai/logs/step-02.log

# 5. Triagear un error
project-ai triage .project-ai/logs/step-02.log

# 6. Finalizar (marca lo verificado, genera AGENTS.md)
project-ai finalize /ruta/proyecto
```

El archivo `AGENTS.md` generado en la raíz del proyecto contiene el contexto
compacto para usar con agentes locales (OpenCode + Ollama).

---

## Notas por sistema operativo

### macOS

- Python 3.11+ viene en macOS 13+. Para versiones anteriores: `brew install python@3.12`.
- `uv` se instala en `~/.cargo/bin` (ya incluido en PATH por el instalador).
- Android SDK se busca en `~/Library/Android/sdk` (estándar de Android Studio).
- Para compilar proyectos C++: Xcode Command Line Tools (`xcode-select --install`).

```bash
# Instalar herramientas de desarrollo
xcode-select --install
brew install cmake ninja conan   # para proyectos C++
brew install openjdk@21          # para Maven/Gradle
```

### Linux (Debian / Ubuntu)

```bash
# Python 3.11+
sudo apt install python3.11 python3.11-venv python3.11-pip

# Herramientas de compilación comunes
sudo apt install build-essential cmake ninja-build
sudo apt install default-jdk-headless   # OpenJDK

# Android SDK: usar sdkmanager de cmdline-tools
# https://developer.android.com/studio/command-line/sdkmanager
export ANDROID_HOME="$HOME/Android/Sdk"
```

```bash
# Fedora / RHEL
sudo dnf install python3.11 cmake ninja-build java-21-openjdk
```

### Windows

**PowerShell (recomendado)**:

```powershell
# Instalar uv
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Reiniciar terminal para que $PATH incluya uv

# Clonar y usar
git clone https://github.com/tu-usuario/project-ai.git
cd project-ai
uv sync
uv run project-ai recon C:\ruta\proyecto
```

**Notas importantes en Windows**:
- Usa rutas absolutas con backslash o forward-slash: `C:/Users/kenny/proyecto`
- El comando `tee` no existe en cmd.exe; en PowerShell usa:
  ```powershell
  mvn package | Tee-Object -FilePath .project-ai\logs\step-01.log
  ```
- `doctor.py` detecta Android SDK desde `%LOCALAPPDATA%\Android\Sdk`
  (variable `ANDROID_HOME` o `ANDROID_SDK_ROOT`).
- Git para Windows incluye `git.exe` en PATH; la herramienta lo usa automáticamente.
- Si usas WSL2, ejecuta `project-ai` desde dentro de WSL (rutas `/mnt/c/...`).

---

## Verificar la instalación

```bash
uv run project-ai --help
uv run pytest -q   # 795 tests deben pasar
```

---

## Integración con Ollama (triage N1/N2)

Ollama debe estar corriendo localmente:

```bash
ollama serve                  # en una terminal separada
ollama pull llama3.2:3b       # modelo N1 (rápido, para diagnóstico inicial)
ollama pull qwen2.5-coder:14b # modelo N2 (más preciso, para errores complejos)
```

La configuración de nodos está en `.project-ai/config.toml` (se crea
automáticamente con valores por defecto). Ver `docs/NODES.md` para ajustar
los modelos por nodo.

---

## Comandos de referencia rápida

```bash
# Ver qué archivos detecta el scanner
uv run python -m project_ai.scanner /ruta/proyecto

# Ver qué descubre el reconocimiento (modo texto)
uv run python -m project_ai.adapters /ruta/proyecto

# Mismo, solo stack Maven con debug
uv run python -m project_ai.adapters /ruta/proyecto --only hints maven --debug

# Salida JSON completa (con evidencias)
uv run python -m project_ai.adapters /ruta/proyecto --json

# Obtener contexto para preguntar a un agente
uv run project-ai context "cómo arranco el servidor" --path /ruta/proyecto

# Generar config para OpenCode + Serena MCP
uv run project-ai setup-agent /ruta/proyecto
```
