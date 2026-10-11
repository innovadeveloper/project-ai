"""
config.py — Configuración de nodos LLM para project-ai.

Lee .project-ai/config.toml si existe; usa valores por defecto si no.
Formato del archivo (TOML):

    [n1]
    url     = "http://localhost:11434"
    model   = "llama3.2:3b"
    timeout = 60
    num_ctx = 4096

    [n2]
    url     = "http://192.168.1.10:11434"
    model   = "qwen2.5-coder:14b"
    timeout = 120
    num_ctx = 8192
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


OUTPUT_DIR = ".project-ai"
CONFIG_FILE = "config.toml"


@dataclass
class NodeConfig:
    """Configuración de un nodo Ollama."""
    url: str     = "http://localhost:11434"
    model: str   = "qwen2.5-coder:7b" # "llama3.2:3b"
    timeout: int = 60
    num_ctx: int = 4096


@dataclass
class Config:
    """Configuración global de nodos LLM."""
    n1:  NodeConfig
    n2:  NodeConfig

    @classmethod
    def default(cls) -> "Config":
        return cls(
            n1=NodeConfig(),
            n2=NodeConfig(model="qwen2.5-coder:14b", timeout=120, num_ctx=8192),
        )

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Carga desde un archivo TOML."""
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

        defaults = cls.default()

        def _node(key: str, default: NodeConfig) -> NodeConfig:
            d = data.get(key, {})
            return NodeConfig(
                url=d.get("url", default.url),
                model=d.get("model", default.model),
                timeout=d.get("timeout", default.timeout),
                num_ctx=d.get("num_ctx", default.num_ctx),
            )

        return cls(n1=_node("n1", defaults.n1), n2=_node("n2", defaults.n2))

    @classmethod
    def from_project(cls, project_root: Path) -> "Config":
        """Carga la config del proyecto o devuelve los valores por defecto."""
        cfg = project_root / OUTPUT_DIR / CONFIG_FILE
        if cfg.exists():
            return cls.load(cfg)
        return cls.default()
