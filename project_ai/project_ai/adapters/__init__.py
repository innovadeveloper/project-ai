"""Adaptadores de project-ai. Importar un módulo aquí lo registra."""
from .base import REGISTRY, Adapter, all_adapters, register, run_adapters
from . import hints  # registro del adaptador transversal

__all__ = ["REGISTRY", "Adapter", "all_adapters", "register", "run_adapters", "hints"]
