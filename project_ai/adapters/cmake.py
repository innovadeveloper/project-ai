"""
adapters/cmake.py — Proyectos CMake.

Qué descubre (todo con evidencia archivo:línea):
  cmake_minimum_required(VERSION x)     → req cmake (BUILD)
  set(CMAKE_CXX_STANDARD N)             → req cxx_standard (BUILD, máximo entre archivos)
  target_compile_features(... cxx_std_N)→ req cxx_standard (BUILD)
  project(NAME ...)                     → nombre del proyecto
  add_library(n TYPE ...)               → Module kind library/interface-library
  add_executable(n ...)                 → Module kind executable + EntryPoint
  find_package(X [ver] ...)             → fact cmake.find_packages
  FetchContent_Declare(name ...)        → fact cmake.fetchcontent
  enable_testing / include(CTest)       → comando test con ctest
  CMAKE_EXPORT_COMPILE_COMMANDS ON      → omite sugerencia; si falta, la añade
  CMakePresets.json / CMakeUserPresets.json → presets; avisa si include→ archivos ausentes
  Android cross-compilation             → fact cmake.cross_targets

Comandos generados: configure, build, test (si hay tests), run (primer ejecutable).
"""

from __future__ import annotations

import json
import re

from ..model import (Command, EntryPoint, Fact, Module, ProjectInfo,
                     SourcePriority as P, StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, ev, register, req

NAME = "cmake"

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------
_RX_CMAKE_MIN = re.compile(r'cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)', re.I)
_RX_PROJECT   = re.compile(r'\bproject\s*\(\s*(\w[\w.-]*)', re.I)
_RX_CXX_STD   = re.compile(r'\bset\s*\(\s*CMAKE_CXX_STANDARD\s+(\d+)', re.I)
_RX_CXX_FEAT  = re.compile(r'\btarget_compile_features\s*\([^)]*\bcxx_std_(\d+)\b',
                            re.I | re.DOTALL)
_RX_ADD_LIB   = re.compile(
    r'\badd_library\s*\(\s*(\w[\w.-]*)(?:\s+(STATIC|SHARED|INTERFACE|MODULE|OBJECT))?',
    re.I)
_RX_ADD_EXE   = re.compile(r'\badd_executable\s*\(\s*(\w[\w.-]*)', re.I)
_RX_FIND_PKG  = re.compile(r'\bfind_package\s*\(\s*([\w.-]+)(?:\s+([\d.]+))?', re.I)
_RX_EXPORT_CC = re.compile(r'\bset\s*\(\s*CMAKE_EXPORT_COMPILE_COMMANDS\s+ON\b', re.I)
_RX_HAS_TEST  = re.compile(
    r'\b(?:enable_testing|include\s*\(\s*CTest|add_test\s*\(|'
    r'gtest_discover_tests|catch_discover_tests)\b', re.I)
_RX_FETCHCONT = re.compile(r'\bFetchContent_Declare\s*\(\s*(\w+)', re.I)
_RX_STRIP_CMT = re.compile(r'#[^\n]*')  # comentarios CMake (# ... EOL)


def _strip(text: str) -> str:
    return _RX_STRIP_CMT.sub('', text)


def _lineno(text: str, pos: int) -> int:
    return text[:pos].count('\n') + 1


# ---------------------------------------------------------------------------
# Adaptador
# ---------------------------------------------------------------------------

@register
class CMakeAdapter(Adapter):
    name = NAME
    always_run = False

    # ---- detect --------------------------------------------------------

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        roots = sc.glob("CMakeLists.txt") + sc.glob("*/CMakeLists.txt")
        out = []
        for f in roots:
            text = sc.read_text(f) or ""
            if _RX_PROJECT.search(text):
                out.append(StackDetection(
                    adapter=NAME, confidence=0.95, root=".",
                    evidence=[ev(f, None, "CMakeLists.txt con project()")]))
                break  # un solo stack por proyecto
        return out

    # ---- analyze -------------------------------------------------------

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        cmake_files = sc.glob("CMakeLists.txt") + sc.glob("*/CMakeLists.txt")
        if not cmake_files:
            return

        root_file = cmake_files[0]
        root_text = _strip(sc.read_text(root_file) or "")

        self._parse_min_version(sc, info, root_file, root_text)
        self._parse_cxx_standard(sc, info, cmake_files)
        self._parse_targets(sc, info, cmake_files)
        self._parse_find_packages(sc, info, cmake_files)
        self._parse_fetchcontent(sc, info, cmake_files)
        has_tests = self._detect_tests(sc, cmake_files)
        self._parse_presets(sc, info)
        self._suggest_compile_commands(sc, info, cmake_files)
        self._emit_commands(sc, info, has_tests)

    # ---- helpers -------------------------------------------------------

    def _parse_min_version(self, sc: ProjectScanner, info: ProjectInfo,
                           f: str, text: str) -> None:
        m = _RX_CMAKE_MIN.search(text)
        if m:
            line = _lineno(text, m.start())
            # rango "3.15...3.28" → tomamos el mínimo (ya capturado antes de "...")
            req(info, "cmake", m.group(1), P.BUILD, f, line,
                m.group(0).strip(), adapter=NAME)

    def _parse_cxx_standard(self, sc: ProjectScanner, info: ProjectInfo,
                             files: list[str]) -> None:
        best: tuple[int, str, int] | None = None  # (standard_num, file, line)
        for f in files:
            text = _strip(sc.read_text(f) or "")
            for rx in (_RX_CXX_STD, _RX_CXX_FEAT):
                for m in rx.finditer(text):
                    std = int(m.group(1))
                    line = _lineno(text, m.start())
                    if best is None or std > best[0]:
                        best = (std, f, line)
        if best:
            req(info, "cxx_standard", str(best[0]), P.BUILD, best[1], best[2],
                f"C++{best[0]}", adapter=NAME)

    def _parse_targets(self, sc: ProjectScanner, info: ProjectInfo,
                       files: list[str]) -> None:
        for f in files:
            text = _strip(sc.read_text(f) or "")
            for m in _RX_ADD_LIB.finditer(text):
                name = m.group(1)
                lib_type = (m.group(2) or "STATIC").upper()
                kind = "interface-library" if lib_type == "INTERFACE" else "library"
                line = _lineno(text, m.start())
                info.modules.append(Module(
                    name=name, path=".", build_system=NAME, kind=kind))
                info.entry_points.append(EntryPoint(
                    kind=f"cmake-{kind}", symbol=name, file=f, line=line))
            for m in _RX_ADD_EXE.finditer(text):
                name = m.group(1)
                line = _lineno(text, m.start())
                info.modules.append(Module(
                    name=name, path=".", build_system=NAME, kind="executable"))
                info.entry_points.append(EntryPoint(
                    kind="cmake-executable", symbol=name, file=f, line=line))

    def _parse_find_packages(self, sc: ProjectScanner, info: ProjectInfo,
                              files: list[str]) -> None:
        seen: set[str] = set()
        for f in files:
            text = _strip(sc.read_text(f) or "")
            for m in _RX_FIND_PKG.finditer(text):
                pkg = m.group(1)
                if pkg.upper() in ("REQUIRED", "CONFIG", "MODULE", "COMPONENTS",
                                   "HINTS", "PATHS", "NO_DEFAULT_PATH"):
                    continue
                if pkg in seen:
                    continue
                seen.add(pkg)
                version = m.group(2)
                line = _lineno(text, m.start())
                info.add_list_fact("cmake.find_packages",
                                   {"name": pkg, "version": version, "file": f, "line": line},
                                   priority=P.BUILD,
                                   evidence=ev(f, line, m.group(0).strip()))

    def _parse_fetchcontent(self, sc: ProjectScanner, info: ProjectInfo,
                            files: list[str]) -> None:
        for f in files:
            text = _strip(sc.read_text(f) or "")
            for m in _RX_FETCHCONT.finditer(text):
                name = m.group(1)
                line = _lineno(text, m.start())
                info.add_list_fact("cmake.fetchcontent",
                                   {"name": name, "file": f, "line": line},
                                   priority=P.BUILD,
                                   evidence=ev(f, line, f"FetchContent_Declare({name})"))

    def _detect_tests(self, sc: ProjectScanner, files: list[str]) -> bool:
        for f in files:
            if _RX_HAS_TEST.search(_strip(sc.read_text(f) or "")):
                return True
        return False

    def _parse_presets(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        presets_file = None
        for name in ("CMakePresets.json", "CMakeUserPresets.json"):
            f = sc.glob(name)
            if f:
                presets_file = f[0]
                break
        if not presets_file:
            return

        try:
            data = json.loads(sc.read_text(presets_file) or "{}")
        except (json.JSONDecodeError, ValueError):
            return

        # Archivos incluidos (generados por Conan u otras herramientas)
        includes = data.get("include", [])
        missing = [p for p in includes
                   if not sc.glob(p) and not (sc.root / p).exists()]
        existing = [p for p in includes if p not in missing]

        if missing:
            info.warnings.append(
                f"CMakeUserPresets.json incluye archivos no existentes: "
                f"{', '.join(missing)}. Probablemente necesitas ejecutar "
                f"'conan install . --build=missing' primero.")
            info.set_fact("cmake.preset_files_missing", Fact(
                value=missing, priority=P.HEURISTIC, adapter=NAME,
                evidence=[ev(presets_file)],
                note="Ejecuta 'conan install . --build=missing' para generarlos"))

        # Recopilar nombres de configure-presets (de este archivo y de los incluidos)
        all_configure = list(data.get("configurePresets", []))
        for inc_path in existing:
            try:
                inc_data = json.loads(sc.read_text(inc_path) or "{}")
                all_configure.extend(inc_data.get("configurePresets", []))
            except (json.JSONDecodeError, ValueError):
                pass

        if all_configure:
            names = [p.get("name", "") for p in all_configure if p.get("name")]
            info.set_fact("cmake.configure_presets", Fact(
                value=names, priority=P.EXPLICIT, adapter=NAME,
                evidence=[ev(presets_file)],
                note="Presets de configure disponibles"))

    def _suggest_compile_commands(self, sc: ProjectScanner, info: ProjectInfo,
                                  files: list[str]) -> None:
        for f in files:
            if _RX_EXPORT_CC.search(_strip(sc.read_text(f) or "")):
                return  # ya está seteado
        # No está seteado: avisar
        info.set_fact("cmake.missing_export_compile_commands", Fact(
            value=True, priority=P.HEURISTIC, adapter=NAME,
            note="Añade 'set(CMAKE_EXPORT_COMPILE_COMMANDS ON)' al CMakeLists.txt "
                 "raíz para que clangd/Serena funcionen"))

    def _emit_commands(self, sc: ProjectScanner, info: ProjectInfo,
                       has_tests: bool) -> None:
        # Elegir generador según build previo (hints.previous_cmake_builds)
        prev_builds = info.facts.get("hints.previous_cmake_builds")
        generator = None
        if prev_builds and isinstance(prev_builds.value, list) and prev_builds.value:
            generator = prev_builds.value[0].get("CMAKE_GENERATOR")

        # Ver si hay presets disponibles (EXPLICIT > construir comando manual)
        presets = info.facts.get("cmake.configure_presets")
        missing_presets = "cmake.preset_files_missing" in info.facts

        if presets and presets.value and not missing_presets:
            preset_name = presets.value[0]
            configure_cmd = f"cmake --preset {preset_name}"
            build_cmd = f"cmake --build --preset {preset_name}"
            ide_configure = (f"VS Code: CMake Tools → 'CMake: Select Configure Preset' "
                             f"→ {preset_name}")
        elif missing_presets:
            # Presets definidos pero archivos ausentes: sugerir el preset y advertir
            preset_name = "conan-debug"
            configure_cmd = f"cmake --preset {preset_name}"
            build_cmd = f"cmake --build --preset {preset_name}"
            ide_configure = (f"VS Code: CMake Tools → 'CMake: Select Configure Preset' "
                             f"→ {preset_name} (después de conan install)")
        else:
            gen_flag = f" -G \"{generator}\"" if generator and generator != "Ninja" else ""
            configure_cmd = (f"cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug"
                             f" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON{gen_flag}")
            build_cmd = "cmake --build build -j"
            ide_configure = "VS Code: CMake Tools → 'CMake: Configure'"

        info.commands["configure"] = Command(
            name="configure", shell=configure_cmd,
            ide_hint=ide_configure,
            success_hint="-- Build files have been written to",
            fact=Fact(value=configure_cmd, priority=P.BUILD, adapter=NAME))

        info.commands["build"] = Command(
            name="build", shell=build_cmd,
            ide_hint="VS Code: CMake Tools → 'CMake: Build' (Shift+F7)",
            success_hint="Build files have been written / [100%]",
            fact=Fact(value=build_cmd, priority=P.BUILD, adapter=NAME))

        if has_tests:
            build_dir = "build"
            if presets and presets.value and not missing_presets:
                build_dir = "build/Debug"  # conan-debug → binaryDir
            info.commands["test"] = Command(
                name="test",
                shell=f"ctest --test-dir {build_dir} --output-on-failure",
                ide_hint="VS Code: CMake Tools → 'CMake: Run Tests'",
                success_hint="100% tests passed",
                fact=Fact(value="ctest", priority=P.BUILD, adapter=NAME))

        # Primer ejecutable → comando run
        exes = [ep for ep in info.entry_points if ep.kind == "cmake-executable"]
        if exes:
            exe_name = exes[0].symbol
            # Cruza con hints.executables para obtener la ruta real
            hints_exes = info.facts.get("hints.executables")
            run_path = None
            if hints_exes and isinstance(hints_exes.value, list):
                for h in hints_exes.value:
                    if exe_name in h:
                        run_path = h.replace("${workspaceFolder}/", "./")
                        break
            if run_path is None:
                run_path = f"./build/{exe_name}"
            info.commands["run"] = Command(
                name="run", shell=run_path,
                fact=Fact(value=run_path, priority=P.HEURISTIC, adapter=NAME))
