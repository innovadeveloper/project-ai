"""
setup_agent.py — Genera instrucciones de configuración para OpenCode + Serena.

Escribe .project-ai/setup-agent.md con:
  1. Configuración de OpenCode (JSON template para el proyecto).
  2. Configuración de Serena por stack:
       cmake  → clangd + --compile-commands-dir
       maven  → jdtls
       gradle → jdtls
  3. Verificaciones rápidas (curl a los nodos, ollama ps).

El archivo es copy-paste ready: el usuario copia los bloques que necesita.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import ProjectInfo

OUTPUT_DIR   = ".project-ai"
SETUP_FILE   = "setup-agent.md"


def setup_agent(
    path: str | Path,
    *,
    info: ProjectInfo | None = None,
    config=None,
    write: bool = True,
) -> str:
    """Genera las instrucciones de integración con OpenCode y Serena.

    Args:
        path:   Raíz del proyecto.
        info:   ProjectInfo ya cargado; si None se carga de project.json.
        config: Config de nodos (project_ai.config.Config); si None, defaults.
        write:  Si True, escribe .project-ai/setup-agent.md.
    """
    root = Path(path).resolve()

    if info is None:
        json_path = root / OUTPUT_DIR / "project.json"
        if json_path.exists():
            try:
                info = ProjectInfo.load(json_path)
            except Exception:
                pass

    if config is None:
        from .config import Config
        config = Config.from_project(root)

    stacks = info.stack_names() if info else []
    md = _generate(root, stacks, config)

    if write:
        out = root / OUTPUT_DIR / SETUP_FILE
        out.parent.mkdir(exist_ok=True)
        out.write_text(md, encoding="utf-8")

    return md


# --------------------------------------------------------------------------
# Generación del documento
# --------------------------------------------------------------------------

def _generate(root: Path, stacks: list[str], config) -> str:
    n1_url  = config.n1.url
    n1_model = config.n1.model
    n2_url  = config.n2.url
    n2_model = config.n2.model

    lines: list[str] = [
        "# Configuración del agente",
        "",
        f"> Proyecto: `{root.name}`  ",
        f"> Stack detectado: {', '.join(stacks) or 'desconocido'}",
        "",
    ]

    # ---- 1. OpenCode -------------------------------------------------------
    lines += [
        "## 1. OpenCode",
        "",
        "Copia `opencode.json` en la **raíz del proyecto** y abre OpenCode ahí.",
        "",
        "```json",
    ]
    opencode_cfg = _opencode_config(root, n1_url, n1_model)
    lines.append(json.dumps(opencode_cfg, indent=2, ensure_ascii=False))
    lines += [
        "```",
        "",
        "> Cambia `model` y `url` si quieres usar el nodo N2 "
        f"(`{n2_url}` / `{n2_model}`).",
        "",
    ]

    # ---- 2. Serena (MCP) ---------------------------------------------------
    lines += [
        "## 2. Serena (LSP vía MCP)",
        "",
        "Añade este bloque a la config MCP de tu agente "
        "(Claude Desktop, OpenCode, etc.).",
        "",
    ]

    if "cmake" in stacks:
        lines += _serena_cmake(root)
    if "maven" in stacks or "gradle" in stacks:
        lines += _serena_jvm(root, stacks)
    if not any(s in stacks for s in ("cmake", "maven", "gradle")):
        lines += _serena_generic(root)

    # ---- 3. Verificaciones -------------------------------------------------
    lines += [
        "## 3. Verificaciones rápidas",
        "",
        "```bash",
        f"# N1 — {n1_url}",
        f"curl -s {n1_url}/api/tags | python3 -m json.tool | head -20",
        "",
        f"# N2 — {n2_url}",
        f"curl -s {n2_url}/api/tags | python3 -m json.tool | head -20",
        "",
        "# Ver modelos cargados en el nodo activo",
        f"curl -s {n1_url}/api/ps",
        "```",
        "",
        "Si los nodos no responden, comprueba que Ollama esté corriendo "
        "y que `OLLAMA_HOST=0.0.0.0` esté configurado.",
        "",
    ]

    # ---- 4. project-ai context --------------------------------------------
    lines += [
        "## 4. Contexto bajo demanda",
        "",
        "```bash",
        "# Genera un paquete de contexto para cualquier pregunta:",
        f'project-ai context "cómo funciona el auth" --path {root}',
        "",
        "# Pega la salida directamente en tu chat con el modelo.",
        "```",
        "",
    ]

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Helpers de secciones
# --------------------------------------------------------------------------

def _opencode_config(root: Path, n1_url: str, n1_model: str) -> dict:
    return {
        "$schema": "https://opencode.ai/config.schema.json",
        "model": f"ollama/{n1_model}",
        "provider": {
            "ollama": {
                "type": "ollama",
                "url": n1_url,
            }
        },
        "keybinds": {
            "leader": "ctrl+a",
        },
    }


def _serena_cmake(root: Path) -> list[str]:
    """Instrucciones de Serena para C++ / clangd."""
    build_dir = _find_build_dir(root)
    compile_cmds = f"{build_dir}/compile_commands.json"
    return [
        "### C++ — clangd",
        "",
        "```json",
        json.dumps({
            "mcpServers": {
                "serena": {
                    "command": "uvx",
                    "args": [
                        "serena",
                        "--project-root", str(root),
                        "--lsp-binary", "clangd",
                        "--lsp-args", f"--compile-commands-dir={build_dir}",
                    ],
                }
            }
        }, indent=2),
        "```",
        "",
        f"> `compile_commands.json` debe existir en `{compile_cmds}`.  ",
        "> Genera con: `cmake --preset conan-debug "
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`",
        "",
    ]


def _serena_jvm(root: Path, stacks: list[str]) -> list[str]:
    """Instrucciones de Serena para Java / jdtls."""
    bs = "Gradle" if "gradle" in stacks else "Maven"
    return [
        f"### Java — jdtls ({bs})",
        "",
        "```json",
        json.dumps({
            "mcpServers": {
                "serena": {
                    "command": "uvx",
                    "args": [
                        "serena",
                        "--project-root", str(root),
                        "--lsp-binary", "jdtls",
                    ],
                }
            }
        }, indent=2),
        "```",
        "",
        f"> jdtls importará el proyecto {bs} automáticamente al arrancar.  ",
        "> Asegúrate de tener jdtls instalado: `brew install jdtls` (macOS) o "
        "`sudo apt install jdtls` (Ubuntu).",
        "",
    ]


def _serena_generic(root: Path) -> list[str]:
    return [
        "### Configuración genérica",
        "",
        "```json",
        json.dumps({
            "mcpServers": {
                "serena": {
                    "command": "uvx",
                    "args": ["serena", "--project-root", str(root)],
                }
            }
        }, indent=2),
        "```",
        "",
    ]


def _find_build_dir(root: Path) -> str:
    """Busca un directorio de build existente con compile_commands.json."""
    candidates = [
        root / "build" / "Debug",
        root / "build",
        root / "build" / "Release",
    ]
    for d in candidates:
        if (d / "compile_commands.json").exists():
            return str(d)
    return str(root / "build" / "Debug")
