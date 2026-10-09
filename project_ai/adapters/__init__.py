"""Adaptadores de project-ai. Importar un módulo aquí lo registra.

El ORDEN importa: 'hints' va primero porque los adaptadores de stack pueden
contrastar sus hallazgos (p.ej. maven compara javax/jakarta con el Tomcat del IDE).
"""
from .base import REGISTRY, Adapter, all_adapters, register, run_adapters
from . import hints  # señales transversales (siempre)
from . import maven  # Maven
from . import cmake  # CMake
from . import conan  # Conan

__all__ = ["REGISTRY", "Adapter", "all_adapters", "register", "run_adapters",
           "hints", "maven", "cmake", "conan"]
