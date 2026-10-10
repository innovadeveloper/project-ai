"""
scanner.py — Indexador de archivos del proyecto (sin LLM, sin ejecutar nada).

Responsabilidad única: saber QUÉ archivos fuente tiene el proyecto y dar a los
adaptadores utilidades rápidas para buscarlos y leerlos. Nunca modifica nada.

Cómo lista:
- Si la carpeta es un repo git, usa `git ls-files` (tracked + untracked no
  ignorados). Si no, recorre el disco.
- En ambos casos aplica el mismo filtro:
    * HARD: carpetas que nunca interesan (node_modules, .gradle, CMakeFiles,
      .cache, ...) y basura (.DS_Store).
    * SOFT: carpetas con nombre "de build" (build, build-*, out, target, bin,
      obj, Debug, cmake-build-*, ...) se excluyen SOLO si parecen generadas:
      contienen marcadores (CMakeCache.txt, conan_toolchain.cmake, build.ninja),
      muchos binarios (.class, .o, .so...), o están junto a su archivo de build
      (target/ junto a pom.xml, build/ junto a build.gradle, bin|obj junto a
      .csproj). Así un `bin/` con scripts propios NO se pierde.
- Antes de excluir carpetas generadas, anota "builds previos" útiles:
  CMakeCache.txt (qué compilador/generador se usó) y compile_commands.json
  (lo que necesita clangd).

Uso como librería (lo que harán los adaptadores):
    sc = ProjectScanner("./mi-proyecto")
    sc.find_name("pom.xml")              -> ["pom.xml", "api/pom.xml"]
    sc.glob("**/CMakeLists.txt")          ('*' no cruza carpetas, '**' sí)
    sc.read_text("pom.xml")
    sc.grep(r"@SpringBootApplication", exts={".java", ".kt"})

Uso por consola:
    python -m project_ai.scanner ./mi-proyecto
    python -m project_ai.scanner ./mi-proyecto --json
    python -m project_ai.scanner ./mi-proyecto --grep "REGEX"
    python -m project_ai.scanner ./mi-proyecto --show-generated
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

# --------------------------------------------------------------------------
# Reglas de filtrado
# --------------------------------------------------------------------------

# Nunca interesan (y pueden ser enormes). Se podan también al recorrer disco.
HARD_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".vs", ".fleet", ".gradle", ".kotlin", ".cxx",
    ".externalNativeBuild", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".conan", ".conan2",
    "CMakeFiles", "_deps", ".cache", ".project-ai",
}
HARD_IGNORED_DIR_PATTERNS = ("*.egg-info",)
IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# Nombres "sospechosos": se excluyen solo si parecen generados.
SOFT_BUILD_DIR_NAMES = {
    "build", "builds", "out", "target", "bin", "obj", "dist",
    "Debug", "Release", "RelWithDebInfo", "MinSizeRel", "x64", "x86",
}
SOFT_BUILD_DIR_PATTERNS = ("build-*", "build_*", "cmake-build-*", "out-*", "out_*")

GENERATED_MARKER_NAMES = {
    "CMakeCache.txt", "cmake_install.cmake", "CTestTestfile.cmake",
    "conan_toolchain.cmake", "conanbuildinfo.cmake", "conanbuildinfo.txt",
    "conaninfo.txt", "conanbuild.sh", "conanrun.sh", "conanbuild.bat",
    "build.ninja", ".ninja_log", ".ninja_deps",
}
GENERATED_MARKER_EXTS = {
    ".class", ".o", ".obj", ".a", ".so", ".dylib", ".dll", ".lib", ".exe",
    ".jar", ".war", ".ear", ".apk", ".aab", ".dex", ".pyc", ".pdb", ".ilk",
}
GENERATED_BINARY_RATIO = 0.3
# carpeta -> archivos hermanos que delatan que es salida de build
SIBLING_RULES = {
    "target": ("pom.xml",),
    "build": ("build.gradle", "build.gradle.kts"),
    "bin": ("*.csproj", "*.fsproj", "*.vbproj"),
    "obj": ("*.csproj", "*.fsproj", "*.vbproj"),
}

# --------------------------------------------------------------------------
# Archivos señal (glob relativos a la raíz, sin distinguir mayúsculas)
# --------------------------------------------------------------------------

KEY_FILE_PATTERNS: dict[str, list[str]] = {
    "build": [
        "**/pom.xml", "**/build.gradle", "**/build.gradle.kts",
        "**/settings.gradle", "**/settings.gradle.kts", "gradlew",
        "**/gradle/wrapper/gradle-wrapper.properties", "**/gradle/libs.versions.toml",
        ".mvn/wrapper/maven-wrapper.properties", "mvnw",
        "**/CMakeLists.txt", "CMakePresets.json", "CMakeUserPresets.json",
        "**/conanfile.py", "**/conanfile.txt", "**/Makefile", "**/meson.build",
        "**/pyproject.toml", "**/setup.py", "**/requirements*.txt",
        "**/*.csproj", "**/*.sln", "global.json", "**/package.json",
        "**/go.mod", "**/Cargo.toml",
    ],
    "toolchain": [
        ".tool-versions", "mise.toml", ".mise.toml", ".sdkmanrc", ".java-version",
        ".python-version", ".nvmrc", ".node-version", "rust-toolchain*",
        "**/gradle.properties", "**/local.properties",
    ],
    "container": [
        "**/Dockerfile", "**/Dockerfile.*", "**/*.Dockerfile",
        "**/docker-compose*.yml", "**/docker-compose*.yaml",
        "**/compose*.yml", "**/compose*.yaml",
        ".devcontainer/devcontainer.json", ".devcontainer.json",
    ],
    "ci": [
        ".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml",
        "Jenkinsfile", "azure-pipelines.yml", ".circleci/config.yml",
        "bitbucket-pipelines.yml", ".travis.yml",
    ],
    "ide": [
        ".vscode/launch.json", ".vscode/tasks.json",
        ".idea/runConfigurations/*.xml", ".run/*.xml", ".smarttomcat/**",
    ],
    "config": [
        "**/application*.yml", "**/application*.yaml", "**/application*.properties",
        "**/bootstrap*.yml", "**/AndroidManifest.xml",
        "**/.env.example", "**/.env.sample", "**/.env.template",
        "**/WEB-INF/web.xml", "context.xml", "**/META-INF/context.xml",
    ],
    "scripts": ["*.sh", "*.bat", "*.ps1", "*.cmd", "scripts/*", "install/*.sh"],
    "docs": [
        "**/README*", "BUILD*", "INSTALL*", "CONTRIBUTING*", "TROUBLESHOOT*",
        "HACKING*", "DEVELOP*", "SETUP*", "*.md", "docs/*.md",
    ],
}
# Nombres que matchean patrones de docs pero no lo son.
NOT_DOCS = {"cmakelists.txt", "license", "license.txt", "license.md", "notice",
            "notice.txt", "agents.md", "claude.md"}

EXT_LANG = {
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".groovy": "Groovy",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".hxx": "C++", ".h": "C/C++ header", ".c": "C", ".ipp": "C++", ".inl": "C++",
    ".py": "Python", ".cs": "C#", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".swift": "Swift",
    ".m": "Objective-C", ".mm": "Objective-C++", ".cmake": "CMake",
    ".xml": "XML", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".properties": "Properties", ".sql": "SQL", ".sh": "Shell",
}

DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024  # no leer archivos > 2 MB


@dataclass
class GrepHit:
    file: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.text}"


# Manifiestos que los adaptadores necesitan aunque estén en .gitignore.
# Solo se añaden si existen en el directorio raíz del proyecto.
_MANIFEST_NAMES = frozenset({
    "go.mod", "go.sum",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "Cargo.toml", "Cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "CMakeLists.txt", "conanfile.py", "conanfile.txt",
    "pubspec.yaml",
    "Makefile",
    "*.csproj", "*.sln",
    "global.json",
})


def _inject_ignored_manifests(root: Path, files: list[str]) -> None:
    """Añade manifiestos clave que existen en disco pero no están en `files`.

    Solo inyecta archivos en la raíz del proyecto (depth 0) o en subdirectorios
    inmediatos (depth 1) para no escanear el árbol completo.
    """
    existing = set(files)
    # Exactos en la raíz
    exact = {
        "go.mod", "go.sum",
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
        "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
        "Cargo.toml", "Cargo.lock",
        "pom.xml", "build.gradle", "build.gradle.kts",
        "settings.gradle", "settings.gradle.kts",
        "CMakeLists.txt", "conanfile.py", "conanfile.txt",
        "pubspec.yaml", "Makefile", "global.json",
    }
    for name in exact:
        if name not in existing and (root / name).is_file():
            files.append(name)
    # .csproj y .sln en la raíz (extensión variable)
    for p in root.iterdir():
        if p.suffix in (".csproj", ".sln") and p.name not in existing:
            files.append(p.name)


class ProjectScanner:
    """Índice en memoria de los archivos fuente de un proyecto."""

    def __init__(self, root: str | os.PathLike, *,
                 use_git: bool = True,
                 max_file_bytes: int = DEFAULT_MAX_FILE_BYTES):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"No es una carpeta: {self.root}")
        self.max_file_bytes = max_file_bytes
        self.listing_method = "walk"
        self._text_cache: dict[str, str | None] = {}

        raw = self._list_with_git() if use_git else None
        if raw is not None:
            self.listing_method = "git"
        else:
            raw = list(self._walk())

        # builds previos: se anotan ANTES de filtrar
        self.build_artifacts: dict[str, list[str]] = {
            "cmake_cache": sorted(f for f in raw if f.endswith("CMakeCache.txt")),
            "compile_commands": sorted(f for f in raw
                                       if f.endswith("compile_commands.json")),
        }
        self.files, self.generated_dirs = _filter_files(raw)

        # Manifiestos clave que pueden estar en .gitignore pero deben ser
        # visibles para los adaptadores (go.mod, package-lock.json, etc.)
        if self.listing_method == "git":
            _inject_ignored_manifests(self.root, self.files)

        self.files.sort()

        self._by_name: dict[str, list[str]] = {}
        for f in self.files:
            self._by_name.setdefault(PurePosixPath(f).name, []).append(f)

    # ------------------------------------------------------------------ listado

    def _list_with_git(self) -> list[str] | None:
        try:
            top = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=10)
            if top.returncode != 0:
                return None
            out = subprocess.run(
                ["git", "-C", str(self.root), "ls-files", "-z",
                 "--cached", "--others", "--exclude-standard"],
                capture_output=True, timeout=60)
            if out.returncode != 0:
                return None
        except (OSError, subprocess.TimeoutExpired):
            return None
        files = []
        for rawp in out.stdout.split(b"\0"):
            if not rawp:
                continue
            rel = rawp.decode("utf-8", errors="replace")
            if (self.root / rel).is_file():   # el índice puede tener borrados
                files.append(rel)
        return files

    def _walk(self) -> Iterator[str]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not _is_hard_ignored(d)]
            for fn in filenames:
                yield (Path(dirpath) / fn).relative_to(self.root).as_posix()

    # ------------------------------------------------------------------ búsqueda

    def exists(self, rel: str) -> bool:
        return rel in self._by_name.get(PurePosixPath(rel).name, ())

    def find_name(self, *names: str) -> list[str]:
        """Archivos cuyo nombre (sin carpeta) coincide. Acepta comodines."""
        out: list[str] = []
        for n in names:
            if any(c in n for c in "*?["):
                out += [f for f in self.files
                        if fnmatch.fnmatchcase(PurePosixPath(f).name, n)]
            else:
                out += self._by_name.get(n, [])
        return sorted(set(out), key=_depth_then_name)

    def glob(self, pattern: str, *, icase: bool = False) -> list[str]:
        """Glob sobre rutas relativas. '*' no cruza carpetas, '**' sí.
        Ej: '**/CMakeLists.txt', 'api/**/*.java', '.github/workflows/*.yml'"""
        rx = _glob_to_regex(pattern, icase)
        return sorted((f for f in self.files if rx.fullmatch(f)), key=_depth_then_name)

    def by_ext(self, *exts: str) -> list[str]:
        exts_l = {e.lower() for e in exts}
        return [f for f in self.files if PurePosixPath(f).suffix.lower() in exts_l]

    def under(self, folder: str) -> list[str]:
        folder = folder.rstrip("/") + "/"
        return [f for f in self.files if f.startswith(folder)]

    def siblings(self, rel: str) -> list[str]:
        """Archivos en la misma carpeta que `rel` (incluido)."""
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        return [f for f in self.files
                if (f.rsplit("/", 1)[0] if "/" in f else "") == parent]

    # ------------------------------------------------------------------ lectura

    def abspath(self, rel: str) -> Path:
        return self.root / rel

    def read_text(self, rel: str) -> str | None:
        """Lee un archivo como texto. None si es binario, enorme o ilegible."""
        if rel in self._text_cache:
            return self._text_cache[rel]
        p = self.root / rel
        text: str | None = None
        try:
            if p.stat().st_size <= self.max_file_bytes:
                data = p.read_bytes()
                if b"\0" not in data[:8192]:
                    for enc in ("utf-8", "utf-8-sig", "latin-1"):
                        try:
                            text = data.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
        except OSError:
            text = None
        self._text_cache[rel] = text
        return text

    def read_lines(self, rel: str) -> list[str]:
        t = self.read_text(rel)
        return t.splitlines() if t is not None else []

    def grep(self, pattern: str | re.Pattern, *,
             files: Iterable[str] | None = None,
             exts: Iterable[str] | None = None,
             flags: int = 0,
             max_hits: int = 500) -> list[GrepHit]:
        """Busca una regex línea a línea. Limita resultados para no inundar."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        if files is None:
            files = self.by_ext(*exts) if exts else self.files
        hits: list[GrepHit] = []
        for f in files:
            for i, line in enumerate(self.read_lines(f), start=1):
                if rx.search(line):
                    hits.append(GrepHit(f, i, line.strip()[:240]))
                    if len(hits) >= max_hits:
                        return hits
        return hits

    # ------------------------------------------------------------------ resumen

    def key_files(self) -> dict[str, list[str]]:
        """Archivos señal agrupados por categoría."""
        out: dict[str, list[str]] = {}
        for cat, pats in KEY_FILE_PATTERNS.items():
            found: set[str] = set()
            for p in pats:
                found.update(self.glob(p, icase=True))
            if cat == "docs":
                found = {f for f in found
                         if PurePosixPath(f).name.lower() not in NOT_DOCS}
            if found:
                out[cat] = sorted(found, key=_depth_then_name)
        return out

    def language_stats(self, top: int = 10) -> list[tuple[str, int]]:
        c: Counter[str] = Counter()
        for f in self.files:
            lang = EXT_LANG.get(PurePosixPath(f).suffix.lower())
            if lang:
                c[lang] += 1
        return c.most_common(top)

    def summary(self) -> dict:
        return {
            "root": str(self.root),
            "listing_method": self.listing_method,
            "total_files": len(self.files),
            "languages": dict(self.language_stats()),
            "key_files": self.key_files(),
            "top_level": sorted({f.split("/", 1)[0] + ("/" if "/" in f else "")
                                 for f in self.files}),
            "generated_dirs": self.generated_dirs,
            "build_artifacts": {k: v for k, v in self.build_artifacts.items() if v},
        }


# ---------------------------------------------------------------------- filtro

def _is_hard_ignored(dirname: str) -> bool:
    return dirname in HARD_IGNORED_DIRS or any(
        fnmatch.fnmatchcase(dirname, p) for p in HARD_IGNORED_DIR_PATTERNS)


def _is_soft(dirname: str) -> bool:
    return dirname in SOFT_BUILD_DIR_NAMES or any(
        fnmatch.fnmatchcase(dirname, p) for p in SOFT_BUILD_DIR_PATTERNS)


def _filter_files(raw: list[str]) -> tuple[list[str], list[str]]:
    """Devuelve (archivos fuente, carpetas generadas excluidas)."""
    stage1: list[str] = []
    for f in raw:
        parts = f.split("/")
        if parts[-1] in IGNORED_FILE_NAMES:
            continue
        dirs = parts[:-1]
        if any(_is_hard_ignored(d) for d in dirs):
            continue
        # de .idea solo interesan las run configurations compartidas
        if dirs and dirs[0] == ".idea" and not (len(dirs) > 1 and
                                                dirs[1] == "runConfigurations"):
            continue
        stage1.append(f)

    candidates: set[str] = set()
    for f in stage1:
        dirs = f.split("/")[:-1]
        for i, d in enumerate(dirs):
            if _is_soft(d):
                candidates.add("/".join(dirs[: i + 1]))

    generated: list[str] = []
    for c in sorted(candidates, key=_depth_then_name):
        if any(c.startswith(g + "/") for g in generated):
            continue
        if _looks_generated(c, stage1):
            generated.append(c)

    if generated:
        prefixes = tuple(g + "/" for g in generated)
        kept = [f for f in stage1 if not f.startswith(prefixes)]
    else:
        kept = stage1
    return kept, generated


def _looks_generated(d: str, files: list[str]) -> bool:
    prefix = d + "/"
    under = [f for f in files if f.startswith(prefix)]
    if not under:
        return False
    names = {f.rsplit("/", 1)[-1] for f in under}
    if names & GENERATED_MARKER_NAMES:
        return True
    n_bin = sum(1 for f in under
                if PurePosixPath(f).suffix.lower() in GENERATED_MARKER_EXTS)
    if n_bin / len(under) >= GENERATED_BINARY_RATIO:
        return True
    base = d.rsplit("/", 1)[-1]
    pats = SIBLING_RULES.get(base)
    if pats:
        parent = d.rsplit("/", 1)[0] + "/" if "/" in d else ""
        sib_names = [f[len(parent):] for f in files
                     if f.startswith(parent) and "/" not in f[len(parent):]]
        if any(fnmatch.fnmatchcase(n, p) for n in sib_names for p in pats):
            return True
    return False


# ---------------------------------------------------------------------- utils

def _depth_then_name(p: str) -> tuple[int, str]:
    return (p.count("/"), p)


_GLOB_CACHE: dict[tuple[str, bool], re.Pattern] = {}


def _glob_to_regex(pattern: str, icase: bool = False) -> re.Pattern:
    """Traduce un glob con soporte de '**' a regex (cualquier versión de Python)."""
    key = (pattern, icase)
    if key in _GLOB_CACHE:
        return _GLOB_CACHE[key]
    i, out = 0, []
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append(r"(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(r".*")
            i += 2
        elif c == "*":
            out.append(r"[^/]*")
            i += 1
        elif c == "?":
            out.append(r"[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                out.append("[" + pattern[i + 1:j].replace("\\", "\\\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    rx = re.compile("".join(out), re.IGNORECASE if icase else 0)
    _GLOB_CACHE[key] = rx
    return rx


# ---------------------------------------------------------------------- CLI

def _print_human(s: dict, show_generated: bool) -> None:
    print(f"Proyecto: {s['root']}")
    print(f"Archivos fuente: {s['total_files']}  (listado vía {s['listing_method']})")
    if s["languages"]:
        print("Lenguajes: " + ", ".join(f"{k} {v}" for k, v in s["languages"].items()))
    top = s["top_level"]
    print(f"Raíz: {' '.join(top[:25])}" + (" ..." if len(top) > 25 else ""))

    gen = s["generated_dirs"]
    if gen:
        warn = "  ⚠ versionadas o no ignoradas en git" if s["listing_method"] == "git" else ""
        shown = gen if show_generated else gen[:6]
        more = f" (+{len(gen) - 6} más, --show-generated)" if len(gen) > len(shown) else ""
        print(f"Excluidas por generadas: {', '.join(d + '/' for d in shown)}{more}{warn}")
    ba = s["build_artifacts"]
    if ba:
        print("Builds previos detectados:")
        for k, v in ba.items():
            print(f"  {k}: " + ", ".join(v[:4]) + (f" (+{len(v) - 4})" if len(v) > 4 else ""))

    print("\nArchivos señal:")
    if not s["key_files"]:
        print("  (ninguno detectado)")
    for cat, files in s["key_files"].items():
        shown = files[:8]
        more = f"  (+{len(files) - 8} más)" if len(files) > 8 else ""
        print(f"  [{cat}] " + ", ".join(shown) + more)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m project_ai.scanner",
        description="Lista y resume los archivos relevantes de un proyecto.")
    ap.add_argument("path", nargs="?", default=".", help="carpeta del proyecto")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    ap.add_argument("--no-git", action="store_true", help="no usar git ls-files")
    ap.add_argument("--grep", metavar="REGEX", help="buscar una regex y salir")
    ap.add_argument("--show-generated", action="store_true",
                    help="listar todas las carpetas excluidas por generadas")
    args = ap.parse_args(argv)

    try:
        sc = ProjectScanner(args.path, use_git=not args.no_git)
    except NotADirectoryError as e:
        print(e, file=sys.stderr)
        return 2

    if args.grep:
        for h in sc.grep(args.grep):
            print(h)
        return 0

    s = sc.summary()
    if args.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        _print_human(s, args.show_generated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
