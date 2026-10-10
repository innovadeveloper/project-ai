"""Adaptadores de project-ai. Importar un módulo aquí lo registra.

El ORDEN importa: 'hints' va primero porque los adaptadores de stack pueden
contrastar sus hallazgos (p.ej. maven compara javax/jakarta con el Tomcat del IDE).
"""
from .base import REGISTRY, Adapter, all_adapters, register, run_adapters
from . import hints   # señales transversales (siempre)
from . import maven   # Maven
from . import cmake   # CMake
from . import conan   # Conan
from . import python  # Python
from . import dotnet      # .NET / ASP.NET Core
from . import gradle      # Gradle / Android / Kotlin
from . import javascript  # JavaScript / TypeScript / HTML
from . import flutter     # Flutter / Dart
from . import go          # Go (módulos go.mod)
from . import rust        # Rust (Cargo.toml)
from . import make        # Make (Makefile puro, sin CMakeLists)
from . import unity       # Unity (C#, juegos/simulaciones)
from . import platformio  # PlatformIO (C/C++ embebido: Arduino, ESP-IDF, Zephyr)

__all__ = ["REGISTRY", "Adapter", "all_adapters", "register", "run_adapters",
           "hints", "maven", "cmake", "conan", "python", "dotnet", "gradle",
           "javascript", "flutter", "go", "rust", "make", "unity", "platformio"]
