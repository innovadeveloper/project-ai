# 1. Crear y entrar al proyecto
cd ~/Documents/Projects/PythonProjects
mkdir project-ai && cd project-ai

# 2. Estructura mínima
mkdir -p project_ai/adapters rules tests

# 3. Crear pyproject.toml (con hatchling, entrypoint project-ai → project_ai.cli:app)

# 4. Crear README.md (requerido por readme = "README.md" en pyproject)

# 5. Instalar como herramienta global
uv tool install . --force

# 6. (Opcional) Reinstalar limpio si ya existía
uv tool uninstall project-ai && uv tool install .

# 7. Verificar
uv tool list
project-ai --help


---

# Corre un módulo dentro del entorno virtual del proyecto (crea .venv en la primera ejecución)
uv run python -m project_ai.scanner /ruta/al/proyecto/objetivo

---
### Example output

Proyecto: /Users/kenny/Documents/Projects/C++Projects/netclient
Archivos: 370  (listado vía git)
Lenguajes: CMake 168, JSON 52, Shell 23, C++ 11, C/C++ header 5, TypeScript 4, YAML 3, Python 1
Raíz: .DS_Store .cache/ .gitignore .vscode/ CMakeLists.txt CMakeUserPresets.json assets/ build-android/ build/ conanfile.py examples/ include/ main.cpp new_module_c++.sh readme.md src/ tmp.md

Archivos señal:
  [build] CMakeLists.txt, CMakeUserPresets.json, conanfile.py,
          build-android/Makefile, build/Debug/Makefile,
          build/Debug/generators/CMakePresets.json,
          build-android/build/Release/generators/CMakePresets.json,
          build/android/build/Release/generators/CMakePresets.json  (+1 más)


----
### Tree Setup

.
├── README.md
├── pyproject.toml
├── uv.lock
├── project_ai/
│   ├── __init__.py
│   ├── model.py
│   ├── scanner.py
│   └── adapters/
├── rules/
└── tests/










