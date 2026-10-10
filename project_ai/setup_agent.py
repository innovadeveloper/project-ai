"""
setup_agent.py — Genera instrucciones de configuración para OpenCode + Serena.

Escribe .project-ai/setup-agent.md con:
  1. Un único opencode.json combinado: modelo + proveedor Ollama + lsp:true + MCP Serena.
  2. Prerrequisitos y notas por stack (compile_commands para C++, jdtls para Java).
  3. Verificaciones rápidas (curl a los nodos).
  4. Ejemplo de project-ai context.

El archivo es copy-paste ready: el usuario copia opencode.json a la raíz del proyecto.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import ProjectInfo

OUTPUT_DIR = ".project-ai"
SETUP_FILE = "setup-agent.md"


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
    n1_url   = config.n1.url
    n1_model = config.n1.model
    n2_url   = config.n2.url
    n2_model = config.n2.model

    lines: list[str] = [
        "# Configuración del agente",
        "",
        f"> Proyecto: `{root.name}`  ",
        f"> Stack detectado: {', '.join(stacks) or 'desconocido'}",
        "",
    ]

    # ---- 1. opencode.json combinado ----------------------------------------
    mcp_args = _serena_args(root, stacks)
    opencode_cfg = _opencode_config(root, n1_url, n1_model, mcp_args)

    lines += [
        "## 1. opencode.json",
        "",
        "Copia este archivo en la **raíz del proyecto** y abre OpenCode ahí.",
        "Incluye el modelo, el proveedor Ollama y Serena (MCP + LSP) en un solo bloque.",
        "",
        "```json",
        json.dumps(opencode_cfg, indent=2, ensure_ascii=False),
        "```",
        "",
        f"> Para usar el nodo N2 cambia `model` a `ollama/{n2_model}` y `url` a `{n2_url}`.",
        "",
    ]

    # ---- 2. Prerrequisitos por stack ----------------------------------------
    lines += [
        "## 2. Prerrequisitos",
        "",
    ]

    if "cmake" in stacks:
        build_dir = _find_build_dir(root)
        lines += [
            "### C++ — compile_commands.json",
            "",
            "Serena usa clangd, que necesita `compile_commands.json` para indexar el proyecto.",
            "Genera con:",
            "",
            "```bash",
            "conan install . --build=missing -s build_type=Debug",
            "cmake --preset conan-debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "```",
            "",
            f"> El archivo quedará en `{build_dir}/compile_commands.json`.",
            "",
        ]

    if "maven" in stacks or "gradle" in stacks:
        bs = "Gradle" if "gradle" in stacks else "Maven"
        lines += [
            f"### Java — jdtls ({bs})",
            "",
            f"jdtls importará el proyecto {bs} automáticamente al arrancar Serena.",
            "Instala si no lo tienes:",
            "",
            "```bash",
            "brew install jdtls          # macOS",
            "sudo apt install jdtls      # Ubuntu/Debian",
            "```",
            "",
        ]

    if "rust" in stacks:
        lines += [
            "### Rust — rust-analyzer",
            "",
            "Serena usa rust-analyzer para navegar el código Rust.",
            "Instala si no lo tienes:",
            "",
            "```bash",
            "rustup component add rust-analyzer   # recomendado (misma toolchain)",
            "# o bien:",
            "brew install rust-analyzer            # macOS",
            "sudo apt install rust-analyzer        # Ubuntu/Debian",
            "```",
            "",
            "> rust-analyzer necesita que `cargo check` funcione. Ejecuta `cargo fetch` primero.",
            "",
        ]

    if "go" in stacks:
        lines += [
            "### Go — gopls",
            "",
            "Serena usa gopls para navegar el código Go.",
            "Instala si no lo tienes:",
            "",
            "```bash",
            "go install golang.org/x/tools/gopls@latest",
            "```",
            "",
            "> gopls necesita que los módulos estén descargados. Ejecuta `go mod download` primero.",
            "",
        ]

    if not any(s in stacks for s in ("cmake", "maven", "gradle", "rust", "go")):
        lines += [
            "### Stack genérico",
            "",
            "Serena arrancará sin LSP específico. Para mejor soporte instala el LSP",
            "de tu lenguaje y añade `--lsp-binary <nombre>` a los args de Serena.",
            "",
        ]

    # ---- 3. Verificaciones --------------------------------------------------
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
        "# Modelos cargados",
        f"curl -s {n1_url}/api/ps",
        "```",
        "",
        "Si los nodos no responden: `OLLAMA_HOST=0.0.0.0 ollama serve`.",
        "",
    ]

    # ---- 4. project-ai context ---------------------------------------------
    lines += [
        "## 4. Contexto bajo demanda",
        "",
        "```bash",
        "# Genera un paquete de contexto para pegar en cualquier chat:",
        f'project-ai context "cómo funciona el auth" --path {root}',
        "```",
        "",
    ]

    # ---- 5. Schema SQL (solo si existe) ------------------------------------
    if (root / OUTPUT_DIR / "schema-map.md").exists():
        lines += [
            "## 5. Schema SQL",
            "",
            "El proyecto tiene un esquema SQL documentado en `.project-ai/schema-map.md`.",
            "Para documentar cada tabla y función con Ollama:",
            "",
            "```bash",
            f"project-ai schema {root} --document",
            "```",
            "",
            "Los documentos se guardan en `.project-ai/schema/tablas/` y"
            " `.project-ai/schema/funciones/`.",
            "Inclúyelos como contexto adicional en tu chat con OpenCode.",
            "",
        ]

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Constructores de config
# --------------------------------------------------------------------------

def _opencode_config(root: Path, n1_url: str, n1_model: str,
                     mcp_args: list[str]) -> dict:
    """Config combinada: modelo + Ollama + lsp:true + Serena MCP."""
    return {
        "$schema": "https://opencode.ai/config.schema.json",
        "model": f"ollama/{n1_model}",
        "provider": {
            "ollama": {
                "type": "ollama",
                "url": n1_url,
            }
        },
        "lsp": True,
        "mcp": {
            "serena": {
                "command": "uvx",
                "args": mcp_args,
                "enabled": True,
            }
        },
    }


def _serena_args(root: Path, stacks: list[str]) -> list[str]:
    """Devuelve los args de uvx serena según el stack detectado."""
    if "cmake" in stacks:
        return _serena_cmake_args(root)
    if "maven" in stacks or "gradle" in stacks:
        return _serena_jvm_args(root)
    if "rust" in stacks:
        return _serena_rust_args(root)
    if "go" in stacks:
        return _serena_go_args(root)
    return _serena_generic_args(root)


def _serena_cmake_args(root: Path) -> list[str]:
    build_dir = _find_build_dir(root)
    return [
        "serena",
        "--project-root", str(root),
        "--lsp-binary", "clangd",
        "--lsp-args", f"--compile-commands-dir={build_dir}",
    ]


def _serena_jvm_args(root: Path) -> list[str]:
    return [
        "serena",
        "--project-root", str(root),
        "--lsp-binary", "jdtls",
    ]


def _serena_rust_args(root: Path) -> list[str]:
    return [
        "serena",
        "--project-root", str(root),
        "--lsp-binary", "rust-analyzer",
    ]


def _serena_go_args(root: Path) -> list[str]:
    return [
        "serena",
        "--project-root", str(root),
        "--lsp-binary", "gopls",
    ]


def _serena_generic_args(root: Path) -> list[str]:
    return ["serena", "--project-root", str(root)]


def _find_build_dir(root: Path) -> str:
    """Busca el directorio de build con compile_commands.json."""
    candidates = [
        root / "build" / "Debug",
        root / "build",
        root / "build" / "Release",
    ]
    for d in candidates:
        if (d / "compile_commands.json").exists():
            return str(d)
    return str(root / "build" / "Debug")
