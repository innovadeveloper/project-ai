# project-ai

Referencia rápida de comandos, modelos y configuración de nodos

## ① Flujo universal (todos los stacks)

```
# 1. Reconoce el proyecto → .project-ai/project.json + repo-map.md
project-ai recon <ruta>

# 2. Verifica tu entorno → .project-ai/env-report.md
project-ai doctor <ruta>

# 3. Genera pasos de build → .project-ai/RUNBOOK.md
project-ai runbook <ruta>

# 4. El usuario ejecuta cada paso manualmente (con tee para guardar logs)
mvn clean install 2>&1 | tee .project-ai/logs/step-01.log

# 5. Si algo falla → triage
project-ai triage .project-ai/logs/step-01.log

# 6. Marca lo verificado + genera AGENTS.md
project-ai finalize <ruta>

# 7. OpenCode abre la carpeta; lee AGENTS.md automáticamente
```

## ② Stacks soportados

| Stack | Detecta automáticamente | Solo ese adaptador |
| --- | --- | --- |
| Maven / Spring | JDK, módulos, endpoints, servicios, puertos, application.yml | `--only hints maven` |
| CMake + Conan | C++ std, targets, deps, presets, compile_commands | `--only hints cmake conan` |
| Python | pyproject.toml / requirements, FastAPI / Django / Flask, endpoints | `--only hints python` |
| .NET | .csproj/.sln, TargetFramework, Minimal API + Controllers | `--only hints dotnet` |
| Android / Gradle | AGP, Kotlin, compileSdk, NDK, módulos | `--only hints gradle` |
| JS / TS | Node, PM (npm/yarn/pnpm/bun), NestJS / Angular / React | `--only hints javascript` |
| Flutter / Dart | Dart SDK, plataformas, GoRouter routes, Firebase | `--only hints flutter` |
| Go | go.mod, framework (Gin/Echo/Fiber), endpoints | `--only hints go` |
| Rust | Cargo.toml, workspaces, actix-web / axum / rocket | `--only hints rust` |
| Make | Makefile (sin CMakeLists), CXX, targets, bear hint | `--only hints make` |
| Unity | ProjectVersion.txt, pipeline URP/HDRP/Built-in, Firebase/UGS | `--only hints unity` |
| PlatformIO | platformio.ini, platform/board/framework, lib_deps, monitor | `--only hints platformio` |

Añade `--debug` para ver qué detecta cada adaptador. `--json` vuelca todo con evidencias.

## ③ Comandos adicionales

### Notas de dominio

```
project-ai notes <ruta>          # Crea .project-ai/notes.md (plantilla)
                                  # o muestra su contenido si ya está relleno
```

Edita `.project-ai/notes.md` con contexto del dominio. Se incluye en AGENTS.md §0 y en cada `project-ai context` automáticamente.

### Esquema SQL (PostgreSQL)

```
project-ai schema <ruta>                          # Auto-detecta dump.sql
project-ai schema <ruta> --sql /ruta/dump.sql     # Ruta explícita
project-ai schema <ruta> --sql dump.sql --document            # + docs con Ollama
project-ai schema <ruta> --sql dump.sql --document --force    # Re-documenta todo
```

`--document` escribe `.project-ai/schema/tablas/*.md` y `funciones/*.md`. Es reanudable: salta los `.md` que ya existen.

### Contexto bajo demanda

```
project-ai context "cómo funciona el auth" --path <ruta>
project-ai context "tabla driver" --path <ruta> --max-tokens 5000
```

### Finalizar y configurar agente

```
project-ai finalize <ruta>        # → AGENTS.md en la raíz del proyecto
project-ai setup-agent <ruta>     # → .project-ai/setup-agent.md (opencode.json listo)
```

## ④ Configurar nodos Ollama

Crea `.project-ai/config.toml` en la raíz del proyecto para apuntar a servidores remotos:

```
[n1]                              # N1: triage rápido (reglas + LLM ligero)
url     = "http://192.168.1.10:11434"
model   = "llama3.2:3b"
timeout = 60
num_ctx = 4096

[n2]                              # N2: análisis profundo / --document
url     = "http://192.168.1.20:11434"
model   = "qwen2.5-coder:14b"
timeout = 300
num_ctx = 16384
```

Si no existe el archivo, N1 apunta a `localhost:11434` con `llama3.2:3b` y N2 usa `qwen2.5-coder:14b`. Solo `triage` y `schema --document` llaman a Ollama; el resto es determinista.

## ⑤ Modelos recomendados por tarea

| Tarea / Stack | N1 — rápido | N2 — preciso | Notas |
| --- | --- | --- | --- |
| Triage de errores | `llama3.2:3b` | `qwen2.5-coder:14b` | N2 solo si N1 \< 0.6 confianza |
| Java / Spring | `llama3.2:3b` | `qwen2.5-coder:14b` | qwen entiende anotaciones Spring |
| C++ / CMake | `llama3.2:3b` | `qwen2.5-coder:14b` | templates complejas → N2 |
| Python | `llama3.2:3b` | `qwen2.5-coder:7b` | 7b suficiente para Python |
| Go / Rust | `llama3.2:3b` | `qwen2.5-coder:14b` | compilador estricto → N2 |
| SQL schema docs | — | `qwen2.5-coder:7b` | solo `--document`; 7b suficiente |
| JS / TS / Flutter | `llama3.2:3b` | `qwen2.5-coder:7b` | ecosistemas grandes → 7b |
| Android / Gradle | `llama3.2:3b` | `qwen2.5-coder:14b` | AGP + NDK → N2 |
| Unity C# | `llama3.2:3b` | `qwen2.5-coder:14b` | MonoBehaviour + engine API → N2 |
| PlatformIO / embebido | `llama3.2:3b` | `qwen2.5-coder:7b` | C/C++ simples; 7b suficiente |

Instala: `ollama pull llama3.2:3b` · `ollama pull qwen2.5-coder:7b` · `ollama pull qwen2.5-coder:14b`

## ⑥ OpenCode — proveedores externos

Copia `opencode.json` en la raíz del proyecto (generado por `setup-agent`). Para cambiar proveedor:

#### Ollama remoto

```
{
  "model": "ollama/qwen2.5-coder:14b",
  "provider": {
    "ollama": {
      "type": "ollama",
      "url": "http://192.168.1.10:11434"
    }
  }
}
```

#### Anthropic (Claude)

```
{
  "model": "anthropic/claude-sonnet-4-5",
  "provider": {
    "anthropic": {
      "type": "anthropic",
      "apiKey": "sk-ant-..."
    }
  }
}
```

#### OpenRouter

```
{
  "model": "openrouter/deepseek/deepseek-coder",
  "provider": {
    "openrouter": {
      "type": "openrouter",
      "apiKey": "sk-or-..."
    }
  }
}
```

Ollama para N2 local · Anthropic/OpenRouter cuando no tengas nodo disponible · Mantén `"lsp": true` y el bloque `"mcp": { "serena": ... }` en todos los casos.

## ⑦ Serena MCP — servidor remoto

Si Serena corre en otra máquina (HTTP transport), cambia los args en `opencode.json`:

```
"mcp": {
  "serena": {
    "command": "uvx",
    "args": ["serena", "--project-root", "/ruta/proyecto",
             "--transport", "http", "--host", "192.168.1.30", "--port", "8765"],
    "enabled": true
  }
}
```

El modo por defecto (`stdio`) corre Serena en local. El modo `http` conecta a un servidor Serena ya arrancado en la red.

## ⑧ Instalar herramientas

#### OpenCode

```
# macOS
brew install opencode-ai/tap/opencode

# npm (todas las plataformas)
npm install -g opencode-ai

# Verificar
opencode --version
```

#### Serena + uvx

```
# instalar uv (si no lo tienes)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Serena se instala al vuelo con uvx
uvx serena --help

# LSP: jdtls (Java)
brew install jdtls          # macOS
apt install jdtls           # Ubuntu

# LSP: rust-analyzer
rustup component add rust-analyzer

# LSP: gopls
go install golang.org/x/tools/gopls@latest
```

#### Ollama

```
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Servidor en red (accesible desde otros hosts)
OLLAMA_HOST=0.0.0.0 ollama serve

# Modelos esenciales
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
```

## ⑨ Cobertura de adaptadores

| Adaptador | Tests unitarios | Validado en proyecto real | Proyecto / notas |
| --- | --- | --- | --- |
| `maven` | ✅ | ✅ | `hmdm-server-source-code-service` (WAR/Tomcat), `beex-payment-queue-publisher-api` (Spring Boot 3) |
| `cmake` | ✅ | ✅ | `netclient` (CMake + Conan, C++17) |
| `conan` | ✅ | ✅ | `netclient` (Conan 2, cmake_layout) |
| `python` | ✅ | ✅ | `fmc-server-webapi` (uv + [tool.uv] sin lockfile); `py-libraries` (uv workspace monorepo, 3 miembros) |
| `dotnet` | ✅ | ✅ | `liblogicalaccess-samples-csharp` (net8.0-windows, WinForms) |
| `gradle` | ✅ | ✅ | `app-gps-sib` (Android Gradle 6.1.1, 7 módulos, compileSdk 28) |
| `javascript` | ✅ | ✅ | `ws-servidor-tsir` (Express + tedious/MSSQL + TypeScript) |
| `flutter` | ✅ | ✅ | `beex.mobile.app` (monorepo, pubspec.yaml en subdir, 5 plataformas) |
| `go` | ✅ | ✅ | `smartcard-go` (Go 1.26, go.mod en .gitignore → fix scanner) |
| `rust` | ✅ | — | fixtures actix-web/axum/rocket/workspace |
| `make` | ✅ | — | fixtures Makefile puro, C/C++ |
| `unity` | ✅ | ✅ | `Adventure2DProject` (Unity 6000.2.0f1, URP, aviso .csproj auto-generados) |
| `platformio` | ✅ | ✅ | `audio-tx-esp32-poc` (espressif32 @6.5.0, arduino-app, ESP8266Audio, --baud 115200) |
| `hints` | ✅ | ✅ | transversal en todos los proyectos reales |

**Leyenda:**
- ✅ Tests unitarios = fixtures en `tests/conftest.py` + suite `test_<adaptador>.py`
- ✅ Proyecto real = salida verificada manualmente contra un proyecto en `/Users/kenny/Documents/Projects/`
- — = solo fixtures (no hay proyecto propio de ese stack disponible para validar)

---

project-ai — stdlib Python ≥ 3.11 · `uv run pytest -q` para verificar · Solo escribe en `.project-ai/` y `AGENTS.md`