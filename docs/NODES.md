# Nodos de inferencia local

Tres máquinas. Objetivo: equilibrio calidad / velocidad / consumo. Claude no
participa en el flujo final (alcance 1).

> Los tags de modelos cambian a menudo: confirmar en https://ollama.com/library
> antes de descargar. Recomendaciones vigentes a oct-2026.

## Resumen de roles

| Nodo | Hardware | Rol | Modelo principal |
|---|---|---|---|
| **UBUNTU-RTX** | Ryzen 9 7900X, 64 GB RAM, RTX 5070 12 GB | **N1**: agente diario y triage rápido; builds pesados | `qwen3.6:35b-a3b` (MoE, Q4, expertos en RAM) |
| **MAC-M1MAX** | M1 Max 32-core GPU, 64 GB unificada | **N2/N2b**: diagnóstico difícil, planificación, revisión; contexto largo | `qwen3.8:27b` (denso Q6/Q8) + `glm-4.7-flash` |
| **MAC-M2PRO** | M2 Pro, 32 GB | cliente de los otros dos; offline con modelo propio | `qwen3.6:35b-a3b` (Q4, ctx ~32k) |

Por qué:
- La GPU NVIDIA procesa prompts (prefill) mucho más rápido que Apple Silicon;
  un agente reenvía 20–60k tokens por turno → N1 en la RTX.
- 12 GB de VRAM no alojan un denso de 27B con contexto; la M1 Max sí (lento
  pero más capaz) → N2 ahí, usado pocas veces.
- Modelos 70B antiguos: peores que los 27–35B actuales y lentos → descartados.
- Modelos de 7–14B: útiles para autocompletado, no como agentes.

## Escalado (lo implementa `triage.py`)

```
N0  reglas TOML                                  (sin modelo)
N1  UBUNTU-RTX  qwen3.6:35b-a3b                  rápido, la mayoría
N2  MAC-M1MAX   qwen3.8:27b (thinking on)        difícil
N2b MAC-M1MAX   glm-4.7-flash                    otra familia, otros puntos ciegos
N3  humano + documentación oficial
```

## Configuración global (`~/.project-ai/config.toml`) — formato previsto

```toml
[nodes.rtx]
url = "http://ubuntu-rtx.local:11434"
model = "qwen3.6:35b-a3b"
num_ctx = 65536
role = "n1"

[nodes.m1max]
url = "http://m1max.local:11434"
model = "qwen3.8:27b"
num_ctx = 65536
role = "n2"

[nodes.m1max_alt]
url = "http://m1max.local:11434"
model = "glm-4.7-flash"
num_ctx = 32768
role = "n2b"

[triage]
order = ["n0", "n1", "n2", "n2b"]
timeout_s = 300
```
Si un nodo no responde, `triage` salta al siguiente y lo anota en el journal.

## Instalación por nodo

### Común (los tres)
```bash
# Ollama: https://ollama.com/download  (macOS app o script Linux)
ollama --version
# herramientas de soporte
#   macOS: brew install git ripgrep uv
#   Ubuntu: sudo apt install git ripgrep && curl -LsSf https://astral.sh/uv/install.sh | sh
```

### UBUNTU-RTX (N1)
```bash
nvidia-smi                                   # driver con soporte Blackwell (RTX 50xx)
sudo systemctl edit ollama                   # añadir variables:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0"
# Environment="OLLAMA_CONTEXT_LENGTH=65536"
# Environment="OLLAMA_FLASH_ATTENTION=1"
# Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
# Environment="OLLAMA_KEEP_ALIVE=15m"
sudo systemctl restart ollama
ollama pull qwen3.6:35b-a3b                  # confirmar tag (variante coding si existe)
ollama pull gpt-oss:20b                      # alternativa rápida para comparar
ollama ps                                    # ver % GPU/CPU del modelo cargado
sudo nvidia-smi -pl 200                      # limitar potencia (~250 W de serie): menos calor/consumo
```
Notas:
- El MoE deja parte de los expertos en RAM: compite por CPU con compilaciones
  C++. Mientras el agente trabaja, compilar con `-j12` en vez de `-j24`.
- Alternativa más rápida si Ollama se queda corto: `llama-server` (llama.cpp)
  con `--n-cpu-moe N` ajustado a la VRAM; expone API compatible OpenAI.

### MAC-M1MAX (N2)
```bash
launchctl setenv OLLAMA_HOST 0.0.0.0
launchctl setenv OLLAMA_CONTEXT_LENGTH 65536
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
launchctl setenv OLLAMA_KEEP_ALIVE 10m
# reiniciar la app Ollama tras cambiar variables
sudo sysctl iogpu.wired_limit_mb=56000      # más memoria para la GPU (no persiste al reiniciar)
ollama pull qwen3.8:27b                      # elegir cuantización q6/q8 si está disponible
ollama pull glm-4.7-flash
```
Notas: batería → limitar carga al 80 % (ajuste de macOS o AlDente); no usar
como servidor 24/7. Despertarlo solo para N2.

### MAC-M2PRO (cliente / offline)
```bash
# Normalmente no sirve modelos: apunta a rtx/m1max en config.toml.
ollama pull qwen3.6:35b-a3b                  # solo para trabajar sin red
# con OLLAMA_CONTEXT_LENGTH=32768 para no quedarse sin memoria
```

## Comprobaciones rápidas
```bash
curl -s http://ubuntu-rtx.local:11434/api/tags | head
curl -s http://ubuntu-rtx.local:11434/api/chat -d '{
  "model":"qwen3.6:35b-a3b","stream":false,
  "messages":[{"role":"user","content":"di OK"}]}'
ollama ps            # en el nodo: modelo cargado, contexto, % GPU
```

## Agente diario (Fase F)
- OpenCode o Claude Code contra Ollama: `ollama launch opencode` /
  `ollama launch claude` (elige modelo y nodo).
- Serena (MCP) para navegación por símbolos: necesita `compile_commands.json`
  (C++) o proyecto Maven/Gradle importable (Java). `finalize` dejará
  instrucciones en AGENTS.md.
- Modo de aprobación de comandos activado: el agente propone, el usuario ejecuta.

## Energía
- `OLLAMA_KEEP_ALIVE` descarga modelos inactivos → GPU en reposo.
- RTX con power limit ~200 W pierde poco rendimiento en inferencia.
- Si un nodo debe estar siempre encendido, que sea UBUNTU-RTX.
