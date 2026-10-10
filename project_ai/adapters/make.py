"""
adapters/make.py — Proyectos con Makefile puro (no generado por CMake).

Solo se activa cuando hay un Makefile en la raíz Y no hay CMakeLists.txt
(CMake tiene prioridad; sus Makefiles son generados y no aportan info útil).

Qué descubre:
  Lenguaje/std  CC/CXX + CFLAGS/CXXFLAGS -std=cXX|c1X → req cxx_standard/c_standard
  Compilador    CXX=clang++ | CC=clang → fact make.compiler (g++/gcc/clang++/clang)
  Targets       all, test, install, clean → comandos build/test/install
  TARGET var    nombre del ejecutable/biblioteca principal → module name + kind
                (libXXX.so/.a → library; el resto → executable)

Prioridades:
  CXXFLAGS -std=c++17 / CFLAGS -std=c11 → BUILD
  CXX/CC var                             → BUILD (HEURISTIC: puede ser sobreescrita)
"""
from __future__ import annotations

import re
from pathlib import Path

from ..model import Command, Module, Fact, ProjectInfo, SourcePriority as P, StackDetection
from ..scanner import ProjectScanner
from .base import Adapter, ev, register, req

NAME = "make"

# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------

# Variable assignment: VAR = value o VAR := value o VAR ?= value
_RX_VAR = re.compile(r'^(\w+)\s*[:?]?=\s*(.+)', re.MULTILINE)

# Targets: nombre: dependencias (línea que no comienza con tab)
_RX_TARGET = re.compile(r'^([\w][.\w-]*)\s*:', re.MULTILINE)

# Estándar C++: -std=c++17, -std=gnu++20 ...
_RX_CXX_STD = re.compile(r'-std=(?:gnu\+\+|c\+\+)(\d+)')

# Estándar C: -std=c11, -std=gnu11 ...
_RX_C_STD = re.compile(r'-std=(?:gnu|c)(\d+)')

# Nombre de biblioteca (TARGET = libXXX.so / libXXX.a)
_RX_LIB_TARGET = re.compile(r'^lib\w+\.(?:so|a)(?:\.\d+)*$')

# Targets de infraestructura (no son comandos útiles)
_INFRA_TARGETS = {
    ".PHONY", ".DEFAULT", ".SUFFIXES", ".PRECIOUS",
    "clean", "distclean",
}

_KNOWN_TARGETS = {"all", "test", "check", "build", "run", "install"}


def _parse_makefile(text: str) -> dict:
    out: dict = {
        "vars": {},        # VAR → valor raw
        "targets": [],     # lista de nombres de target
    }
    for m in _RX_VAR.finditer(text):
        out["vars"][m.group(1)] = m.group(2).strip()
    for m in _RX_TARGET.finditer(text):
        name = m.group(1)
        if name not in _INFRA_TARGETS:
            out["targets"].append(name)
    return out


def _cxx_std_year_to_ver(year_str: str) -> str:
    """'17' → '17', '11' → '11', '0x' → '11', '1y' → '14', '1z' → '17'."""
    mapping = {"0x": "11", "1y": "14", "1z": "17", "2a": "20"}
    return mapping.get(year_str, year_str)


def _c_std_year_to_ver(year_str: str) -> str:
    mapping = {"89": "90", "9x": "99", "0x": "11", "1x": "17"}
    return mapping.get(year_str, year_str)


# --------------------------------------------------------------------------
# Adaptador
# --------------------------------------------------------------------------

@register
class MakeAdapter(Adapter):
    """Proyectos con Makefile puro (sin CMakeLists.txt)."""

    name = NAME

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        has_makefile = "Makefile" in sc.files
        has_cmake    = any(f == "CMakeLists.txt" for f in sc.files)
        if has_makefile and not has_cmake:
            return [StackDetection(adapter=NAME, confidence=0.75,
                                   evidence=[ev("Makefile", None)])]
        return []

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)
        make_rel = "Makefile"
        try:
            text = (root / make_rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        parsed = _parse_makefile(text)
        vars_ = parsed["vars"]
        targets = parsed["targets"]

        # ----------------------------------------------------------------
        # Estándar C++ / C
        # ----------------------------------------------------------------
        cxxflags = vars_.get("CXXFLAGS", "")
        cflags   = vars_.get("CFLAGS", "")
        all_flags = cxxflags + " " + cflags

        cxx_m = _RX_CXX_STD.search(all_flags)
        if cxx_m:
            std = _cxx_std_year_to_ver(cxx_m.group(1))
            req(info, "cxx_standard", std, P.BUILD,
                make_rel, None, f"-std=c++{cxx_m.group(1)}", adapter=NAME)

        c_m = _RX_C_STD.search(cflags)
        if c_m and not cxx_m:   # solo si no hay C++ (evita ruido)
            std = _c_std_year_to_ver(c_m.group(1))
            req(info, "c_standard", std, P.BUILD,
                make_rel, None, f"-std=c{c_m.group(1)}", adapter=NAME)

        # ----------------------------------------------------------------
        # Compilador (HEURISTIC)
        # ----------------------------------------------------------------
        cxx_var = vars_.get("CXX", "")
        cc_var  = vars_.get("CC", "")
        compiler = cxx_var or cc_var
        if compiler:
            info.set_fact("make.compiler", Fact(
                value=compiler, priority=P.BUILD,
                evidence=[ev(make_rel, None)],
                note="HEURISTIC: CXX/CC pueden ser sobreescritas en tiempo de invocación",
                adapter=NAME,
            ))

        # ----------------------------------------------------------------
        # Módulo (nombre y kind)
        # ----------------------------------------------------------------
        target_var = vars_.get("TARGET", "")
        if not target_var:
            # Intentar inferir del primer target que no sea "all"
            real_targets = [t for t in targets
                            if t not in {"all", "test", "check"} and not t.startswith(".")]
            target_var = real_targets[0] if real_targets else Path(sc.root).name

        kind = "library" if _RX_LIB_TARGET.match(target_var) else "executable"
        info.modules.append(Module(
            name=target_var,
            path=".",
            build_system=NAME,
            kind=kind,
        ))

        # ----------------------------------------------------------------
        # Comandos
        # ----------------------------------------------------------------
        # build → make (o make all si existe target all)
        build_shell = "make all" if "all" in targets else "make"
        info.add_command(Command(
            name="build", shell=build_shell,
            success_hint="",
        ))

        # test → make test / make check
        if "test" in targets:
            info.add_command(Command(name="test", shell="make test", success_hint=""))
        elif "check" in targets:
            info.add_command(Command(name="test", shell="make check", success_hint=""))

        # install → make install (opcional)
        if "install" in targets:
            info.add_command(Command(name="install", shell="make install", success_hint=""))

        # Sugerencia bear para compile_commands (útil para clangd)
        info.set_fact("make.bear_hint", Fact(
            value="bear -- make",
            priority=P.HEURISTIC,
            evidence=[ev(make_rel, None)],
            note="Ejecuta 'bear -- make' para generar compile_commands.json (necesario para clangd/LSP)",
            adapter=NAME,
        ))
