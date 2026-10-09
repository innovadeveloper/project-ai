"""
adapters/conan.py — Proyectos Conan (gestor de dependencias C/C++).

Qué descubre:
  conanfile.py / conanfile.txt → stack conan (versión 1 o 2)
  Conan 2: from conan import ConanFile | usa cmake_layout / CMakeToolchain
  Conan 1: from conans import ConanFile | usa generadores cmake / cmake_find_package
  requires / tool_requires → fact conan.requires / conan.tool_requires
  generators → fact conan.generators
  cmake_layout → nota sobre estructura de salida (build/<BuildType>/generators/)
  Perfiles en profiles/ o .conan/profiles → fact conan.profiles
  Comando deps: el que aparezca en tasks.json/README (prioridad EXPLICIT/docs)
    o 'conan install . --build=missing -s build_type=Debug' (fallback)
"""

from __future__ import annotations

import re

from ..model import (Command, Fact, ProjectInfo, SourcePriority as P,
                     StackDetection)
from ..scanner import ProjectScanner
from .base import Adapter, ev, register, req

NAME = "conan"

# ---------------------------------------------------------------------------
# Detección de versión API
# ---------------------------------------------------------------------------
_RX_CONAN2_IMPORT = re.compile(r'from\s+conan\s+import\s+ConanFile', re.I)
_RX_CONAN2_TOOLS  = re.compile(r'from\s+conan\.tools', re.I)
_RX_CONAN1_IMPORT = re.compile(r'from\s+conans\s+import', re.I)
_RX_CONAN1_GEN    = re.compile(r'"cmake(?:_find_package)?(?:_multi)?"', re.I)

# ---------------------------------------------------------------------------
# Parsing de conanfile.py
# ---------------------------------------------------------------------------
_RX_REQUIRES_CALL = re.compile(
    r'\bself\.(?:requires|tool_requires)\s*\(\s*["\']([^"\']+)["\']\s*\)', re.I)
_RX_REQUIRES_ATTR = re.compile(
    r'^\s*requires\s*=\s*(.+)', re.MULTILINE)
_RX_GEN_ATTR      = re.compile(
    r'\bgenerators\s*=\s*[\(\[]?([^\n\)\]]+)', re.I)
_RX_CMAKE_LAYOUT  = re.compile(r'\bcmake_layout\s*\(', re.I)
_RX_PKG_REF       = re.compile(r'["\']([A-Za-z0-9_.-]+)/([A-Za-z0-9_.\-+]+)["\']')

# ---------------------------------------------------------------------------
# Parsing de conanfile.txt (formato INI)
# ---------------------------------------------------------------------------
_RX_TXT_SECTION   = re.compile(r'^\[(\w+)\]')
_RX_TXT_ENTRY     = re.compile(r'^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.\-+]+)')


def _parse_pkg_ref(ref: str) -> tuple[str, str] | None:
    m = _RX_PKG_REF.search(f'"{ref}"')
    if m:
        return m.group(1), m.group(2)
    parts = ref.strip().split("/")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None


# ---------------------------------------------------------------------------
# Adaptador
# ---------------------------------------------------------------------------

@register
class ConanAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        py_files = sc.glob("conanfile.py")
        txt_files = sc.glob("conanfile.txt")
        if not (py_files or txt_files):
            return []
        f = (py_files or txt_files)[0]
        return [StackDetection(adapter=NAME, confidence=0.95, root=".",
                               evidence=[ev(f)])]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        py_files  = sc.glob("conanfile.py")
        txt_files = sc.glob("conanfile.txt")

        if py_files:
            self._analyze_py(sc, info, py_files[0])
        elif txt_files:
            self._analyze_txt(sc, info, txt_files[0])

        self._detect_profiles(sc, info)
        self._emit_command(sc, info)

    # ---- conanfile.py --------------------------------------------------

    def _analyze_py(self, sc: ProjectScanner, info: ProjectInfo, f: str) -> None:
        text = sc.read_text(f) or ""

        # Versión de la API
        if _RX_CONAN2_IMPORT.search(text) or _RX_CONAN2_TOOLS.search(text):
            api_version = "2"
        elif _RX_CONAN1_IMPORT.search(text) or _RX_CONAN1_GEN.search(text):
            api_version = "1"
        else:
            api_version = "2"   # HEURISTIC: dudoso → marcar

        req(info, "conan", api_version, P.BUILD, f, None,
            f"conanfile.py (API Conan {api_version})", adapter=NAME)

        # Requires por self.requires(...) en methods
        for i, line in enumerate(sc.read_lines(f), start=1):
            m = _RX_REQUIRES_CALL.search(line)
            if m:
                ref = m.group(1)
                parsed = _parse_pkg_ref(ref)
                if parsed:
                    pkg, ver = parsed
                    info.add_list_fact(
                        "conan.requires",
                        {"name": pkg, "version": ver, "ref": ref},
                        priority=P.BUILD, evidence=[ev(f, i, ref)])

        # Requires como atributo de clase: requires = ("fmt/10.2", "boost/1.82")
        for m in _RX_REQUIRES_ATTR.finditer(text):
            for ref_m in _RX_PKG_REF.finditer(m.group(1)):
                pkg, ver = ref_m.group(1), ref_m.group(2)
                already = any(r["name"] == pkg
                              for r in (info.facts.get("conan.requires") or
                                        Fact(value=[])).value)
                if not already:
                    info.add_list_fact(
                        "conan.requires",
                        {"name": pkg, "version": ver, "ref": f"{pkg}/{ver}"},
                        priority=P.BUILD, evidence=[ev(f)])

        # Generadores
        gen_m = _RX_GEN_ATTR.search(text)
        if gen_m:
            gens = re.findall(r'"([^"]+)"', gen_m.group(1))
            if not gens:
                gens = re.findall(r"'([^']+)'", gen_m.group(1))
            if gens:
                info.set_fact("conan.generators", Fact(
                    value=gens, priority=P.BUILD, adapter=NAME,
                    evidence=[ev(f)]))

        # cmake_layout → outputs en build/<BuildType>/generators/
        if _RX_CMAKE_LAYOUT.search(text):
            info.set_fact("conan.cmake_layout", Fact(
                value=True, priority=P.BUILD, adapter=NAME,
                evidence=[ev(f)],
                note="Genera archivos en build/<BuildType>/generators/; "
                     "usa '--preset conan-debug' con cmake después"))

    # ---- conanfile.txt -------------------------------------------------

    def _analyze_txt(self, sc: ProjectScanner, info: ProjectInfo, f: str) -> None:
        req(info, "conan", "2", P.HEURISTIC, f, None, "conanfile.txt", adapter=NAME,
            note="conanfile.txt compatible con Conan 1 y 2; versión no confirmada")

        section = None
        for i, line in enumerate(sc.read_lines(f), start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            sec_m = _RX_TXT_SECTION.match(line)
            if sec_m:
                section = sec_m.group(1).lower()
                continue
            if section == "requires":
                entry = _RX_TXT_ENTRY.match(line)
                if entry:
                    pkg, ver = entry.group(1), entry.group(2)
                    info.add_list_fact(
                        "conan.requires",
                        {"name": pkg, "version": ver, "ref": f"{pkg}/{ver}"},
                        priority=P.BUILD, evidence=[ev(f, i, line)])
            elif section == "generators":
                gen = line.strip()
                if gen:
                    fact = info.facts.get("conan.generators")
                    if fact is None:
                        info.set_fact("conan.generators", Fact(
                            value=[gen], priority=P.BUILD, adapter=NAME,
                            evidence=[ev(f, i, gen)]))
                    elif gen not in fact.value:
                        fact.value.append(gen)

        # cmake_layout en [layout]
        lines_all = sc.read_text(f) or ""
        if re.search(r'^\[layout\].*cmake_layout', lines_all, re.I | re.MULTILINE | re.DOTALL):
            info.set_fact("conan.cmake_layout", Fact(
                value=True, priority=P.BUILD, adapter=NAME,
                evidence=[ev(f)],
                note="Genera archivos en build/<BuildType>/generators/"))

    # ---- perfiles ------------------------------------------------------

    def _detect_profiles(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        profiles = (sc.glob("profiles/*") + sc.glob(".conan/profiles/*") +
                    sc.glob(".conan2/profiles/*"))
        names = [p.rsplit("/", 1)[-1] for p in profiles
                 if not p.endswith((".md", ".txt", ".yml", ".yaml"))]
        if names:
            info.set_fact("conan.profiles", Fact(
                value=names, priority=P.EXPLICIT, adapter=NAME,
                evidence=[ev(profiles[0])],
                note="Perfiles en el repo; el usuario también puede tener "
                     "perfiles globales (~/.conan2/profiles/)"))

    # ---- comando deps --------------------------------------------------

    def _emit_command(self, sc: ProjectScanner, info: ProjectInfo) -> None:
        # Buscar si hints ya capturó un 'conan install' de tasks.json/README
        hints_cmds = info.facts.get("hints.commands")
        if hints_cmds and isinstance(hints_cmds.value, list):
            for item in hints_cmds.value:
                if "conan install" in item.get("cmd", ""):
                    # Ya existe; solo emitir el comando propuesto con esa fuente
                    info.commands["deps"] = Command(
                        name="deps", shell=item["cmd"],
                        ide_hint="VS Code: Terminal → ejecutar conan install",
                        success_hint="Install finished",
                        fact=Fact(value=item["cmd"], priority=P.HEURISTIC,
                                  adapter=NAME))
                    return

        # Fallback: generar comando estándar
        has_cmake_layout = bool(info.facts.get("conan.cmake_layout"))
        cmd = "conan install . --build=missing -s build_type=Debug"
        info.commands["deps"] = Command(
            name="deps", shell=cmd,
            ide_hint="VS Code: Terminal → ejecutar conan install",
            success_hint="Install finished",
            fact=Fact(value=cmd, priority=P.HEURISTIC, adapter=NAME,
                      note="Genera el toolchain en build/Debug/generators/" if has_cmake_layout
                           else None))
