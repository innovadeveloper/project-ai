"""
repomap.py — Mapa compacto de símbolos por módulo para agentes locales.

Extrae clases, interfaces, structs, métodos públicos y funciones libres con
sus firmas (sin cuerpos). Si el resultado supera max_tokens, prioriza los
archivos con entry points/endpoints y los más referenciados por imports.

Solo stdlib, sin tree-sitter (opcional en el futuro).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import ProjectInfo
from .scanner import ProjectScanner

# Aproximación conservadora: 1 token ≈ 4 caracteres
CHARS_PER_TOKEN = 4

# Extensiones por lenguaje
_LANG_EXT: dict[str, str] = {
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp",
    ".h": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".py": "python",
    ".cs": "csharp",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".dart": "dart",
}


# --------------------------------------------------------------------------
# Modelo de datos
# --------------------------------------------------------------------------

@dataclass
class Symbol:
    kind: str          # class | interface | enum | record | struct | method | function
    name: str
    signature: str     # nombre + parámetros simplificados
    visibility: str = "public"    # public | protected | private | package
    http_method: str | None = None   # GET POST PUT DELETE PATCH
    http_path: str | None = None     # ruta HTTP completa
    is_static: bool = False
    line: int | None = None


@dataclass
class FileMap:
    path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)

    @property
    def has_symbols(self) -> bool:
        return bool(self.symbols)

    def render(self) -> str:
        if not self.symbols:
            return ""
        lines = [f"## {self.path}"]
        for sym in self.symbols:
            lines.append(_render_symbol(sym))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------

def build_repo_map(
    info: ProjectInfo,
    sc: ProjectScanner,
    *,
    max_tokens: int = 4000,
) -> str:
    """Genera el mapa de símbolos en Markdown. Trunca si supera max_tokens."""
    max_chars = max_tokens * CHARS_PER_TOKEN

    all_files = [f for f in sc.files if _detect_lang(f) is not None]
    priority_files = _prioritize(all_files, info, sc)

    header = "# Mapa de símbolos\n\n"
    parts: list[str] = [header]
    total_chars = len(header)
    included = 0
    total = len(priority_files)

    for fpath in priority_files:
        lang = _detect_lang(fpath)
        text = sc.read_text(fpath)
        if not text:
            continue
        fm = _parse_file(fpath, lang, text)
        if not fm.has_symbols:
            continue
        rendered = fm.render() + "\n\n"
        if total_chars + len(rendered) > max_chars and included > 0:
            remaining = total - included
            parts.append(
                f"_[{remaining} archivos omitidos — límite de {max_tokens} tokens]_\n"
            )
            break
        parts.append(rendered)
        total_chars += len(rendered)
        included += 1

    return "".join(parts)


# --------------------------------------------------------------------------
# Priorización
# --------------------------------------------------------------------------

def _prioritize(
    files: list[str],
    info: ProjectInfo,
    sc: ProjectScanner,
) -> list[str]:
    """Ordena archivos por relevancia para los agentes."""
    # Archivos con entry points o endpoints
    priority_set: set[str] = set()
    for ep in info.entry_points:
        priority_set.add(ep.file)
    for ep in info.endpoints:
        priority_set.add(ep.file)

    # Conteo de referencias (imports/includes)
    ref_counts = _count_references(sc)

    def score(fpath: str) -> tuple[int, int]:
        fname = Path(fpath).name
        stem = Path(fpath).stem
        in_priority = fpath in priority_set or stem in priority_set
        # Archivos REST/controller tienen alta prioridad en Java
        is_rest = any(p in fpath.lower() for p in (
            "resource", "controller", "endpoint", "handler", "rest", "api"))
        refs = ref_counts.get(fname, 0) + ref_counts.get(stem, 0)
        return (
            -(2 if in_priority else 1 if is_rest else 0),  # negativo: más = mejor
            -refs,
        )

    return sorted(files, key=score)


def _count_references(sc: ProjectScanner) -> dict[str, int]:
    """Cuenta cuántas veces se importa/incluye cada archivo."""
    counts: dict[str, int] = {}
    for fpath in sc.files:
        text = sc.read_text(fpath)
        if not text:
            continue
        # Java/Kotlin: import com.acme.foo.ClassName
        for m in re.finditer(r'\bimport\s+[\w.]+\.(\w+)\s*[;\n]', text):
            k = m.group(1)
            counts[k] = counts.get(k, 0) + 1
        # C/C++: #include "header.h"
        for m in re.finditer(r'#include\s+"([^"]+)"', text):
            k = Path(m.group(1)).name
            counts[k] = counts.get(k, 0) + 1
        # TypeScript/JS: import ... from './module'
        for m in re.finditer(r'\bfrom\s+[\'"]([^\'"]+)[\'"]', text):
            k = Path(m.group(1)).stem.lstrip("./")
            if k:
                counts[k] = counts.get(k, 0) + 1
        # Dart: import 'package:app/module.dart'
        for m in re.finditer(r"\bimport\s+'[^']*?([^/]+)\.dart'", text):
            k = m.group(1)
            counts[k] = counts.get(k, 0) + 1
    return counts


# --------------------------------------------------------------------------
# Dispatch de parsers
# --------------------------------------------------------------------------

def _detect_lang(fpath: str) -> str | None:
    return _LANG_EXT.get(Path(fpath).suffix.lower())


def _parse_file(fpath: str, lang: str, text: str) -> FileMap:
    if lang == "java":
        return _parse_java(fpath, text)
    if lang == "kotlin":
        return _parse_kotlin(fpath, text)
    if lang == "cpp":
        return _parse_cpp(fpath, text)
    if lang == "python":
        return _parse_python(fpath, text)
    if lang in ("typescript", "javascript"):
        return _parse_typescript(fpath, text)
    if lang == "dart":
        return _parse_dart(fpath, text)
    return FileMap(path=fpath, language=lang)


# --------------------------------------------------------------------------
# Parser Java
# --------------------------------------------------------------------------

def _parse_java(rel_path: str, text: str) -> FileMap:
    fm = FileMap(path=rel_path, language="java")
    # Preservar strings para extraer paths de anotaciones; quitar solo comentarios
    t = _strip_java_comments(text)
    t = _normalize_annotations(t)

    class_name: str | None = None
    class_http_base: str | None = None
    pending_anns: list[str] = []
    depth = 0
    class_open_depth: int | None = None

    for lineno, raw_line in enumerate(t.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        # Depth counting: quitar strings DE LA LÍNEA para no confundir {} en strings
        depth_before = depth
        depth += _strip_string_literals(line).count("{") - \
                 _strip_string_literals(line).count("}")

        if line.startswith("@"):
            pending_anns.append(line)
            continue

        # Primera clase/interface/enum del archivo
        if class_name is None:
            cm = re.search(r'\b(class|interface|enum|record)\s+(\w+)', line)
            if cm:
                class_name = cm.group(2)
                class_http_base = _java_http_base(pending_anns)
                fm.symbols.append(Symbol(
                    kind=cm.group(1),
                    name=class_name,
                    signature=class_name,
                    visibility=_java_vis(line),
                    http_path=class_http_base,
                ))
                pending_anns.clear()
                class_open_depth = depth  # profundidad tras abrir la llave
                continue

        # Métodos: solo en el cuerpo directo de la clase (depth_before == class_open_depth)
        if class_open_depth is not None and depth_before == class_open_depth:
            mm = _java_method_match(line)
            if mm is not None:
                name, params, vis = mm
                if name != class_name and vis in ("public", "protected"):
                    h_method, h_path = _java_http_info(pending_anns, class_http_base)
                    fm.symbols.append(Symbol(
                        kind="method",
                        name=name,
                        signature=f"{name}({params})",
                        visibility=vis,
                        http_method=h_method,
                        http_path=h_path,
                        is_static="static" in line,
                        line=lineno,
                    ))

        pending_anns.clear()

    return fm


# Sin $ al final: el body puede estar en la misma línea ("{ return null; }")
_RX_JAVA_METHOD = re.compile(
    r'^[ \t]*'
    r'(?:(?:public|protected|private)\s+)?'
    r'(?:(?:static|final|abstract|synchronized|default|native|override)\s+)*'
    r'(?:<[^>]+>\s+)?'
    r'(?!(?:class|interface|enum|record|if|for|while|switch|return|throw|import|package|new)\b)'
    r'(?:[\w<>\[\].,?]+ )+?'   # tipo de retorno (1+ palabras seguidas de espacio)
    r'(\w+)\s*'                # nombre del método
    r'\(([^)]*)\)'             # parámetros
)


def _java_method_match(line: str) -> tuple[str, str, str] | None:
    m = _RX_JAVA_METHOD.match(line)
    if not m:
        return None
    name = m.group(1)
    # Filtrar palabras que nunca son nombres de métodos
    if name in {"class", "interface", "enum", "if", "for", "while", "return",
                "switch", "new", "throw", "import", "package", "extends", "implements"}:
        return None
    params = _simplify_params(m.group(2))
    vis = _java_vis(line)
    return name, params, vis


def _java_vis(line: str) -> str:
    if "public" in line:
        return "public"
    if "protected" in line:
        return "protected"
    if "private" in line:
        return "private"
    return "package"


def _java_http_base(anns: list[str]) -> str | None:
    for ann in anns:
        # JAX-RS @Path("/foo")
        m = re.search(r'@Path\s*\(\s*"([^"]+)"\s*\)', ann)
        if m:
            return m.group(1)
        # Spring @RequestMapping("/foo") o @RequestMapping(value="/foo")
        m = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"', ann)
        if m:
            return m.group(1)
    return None


def _java_http_info(anns: list[str], base: str | None) -> tuple[str | None, str | None]:
    http_method: str | None = None
    sub_path: str | None = None
    for ann in anns:
        # JAX-RS @GET @POST @PUT @DELETE @PATCH
        jax = re.match(r'@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', ann)
        if jax:
            http_method = jax.group(1)
        # JAX-RS @Path("/{id}")
        path_m = re.search(r'@Path\s*\(\s*"([^"]+)"\s*\)', ann)
        if path_m:
            sub_path = path_m.group(1)
        # Spring @GetMapping @PostMapping etc. (opcionalmente con path)
        spring = re.match(r'@(Get|Post|Put|Delete|Patch)Mapping(?:\s*\(\s*(?:"([^"]+)"|value\s*=\s*"([^"]+)"|path\s*=\s*"([^"]+)")\s*\))?', ann)
        if spring:
            http_method = spring.group(1).upper()
            sub_path = spring.group(2) or spring.group(3) or spring.group(4) or sub_path

    if http_method is None:
        return None, None

    if sub_path:
        full = (base or "").rstrip("/") + "/" + sub_path.lstrip("/")
    else:
        full = base

    return http_method, full


# --------------------------------------------------------------------------
# Parser C++
# --------------------------------------------------------------------------

def _parse_cpp(rel_path: str, text: str) -> FileMap:
    fm = FileMap(path=rel_path, language="cpp")
    t = _strip_cpp_comments(text)
    t = _strip_string_literals(t)

    # Clases y structs
    for m in re.finditer(
        r'\b(class|struct)\s+(\w+)\s*(?:final\s*)?(?::[^{;]+)?\s*\{',
        t
    ):
        kind = m.group(1)
        name = m.group(2)
        # Filtrar forward-declarations y palabras clave internas
        if name in {"", "override", "final"}:
            continue
        fm.symbols.append(Symbol(kind=kind, name=name, signature=name))

    # Funciones / métodos con declaración
    # Buscamos líneas que parecen declaraciones de función: tipo nombre(params) const? ;|{
    for m in re.finditer(
        r'^[ \t]*'
        r'(?:(?:virtual|static|inline|explicit|constexpr)\s+)*'
        r'(?:[\w:*&<>\[\] ]+?\s+)'       # tipo de retorno
        r'(?:\w+::)*'                     # namespace/clase opcional
        r'(\w+)\s*'                       # nombre
        r'\(([^)]*)\)\s*'                 # parámetros
        r'(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:= 0\s*)?'
        r'[;{]',
        t, re.MULTILINE
    ):
        name = m.group(1)
        if name in {"if", "for", "while", "switch", "return", "catch",
                    "namespace", "class", "struct", "enum", "union",
                    "sizeof", "alignof", "decltype"}:
            continue
        params = _simplify_params(m.group(2))
        fm.symbols.append(Symbol(kind="function", name=name, signature=f"{name}({params})"))

    # Deduplicar (misma signature puede aparecer en header y .cpp)
    seen: set[str] = set()
    unique: list[Symbol] = []
    for s in fm.symbols:
        key = (s.kind, s.signature)
        if key not in seen:
            seen.add(key)
            unique.append(s)
    fm.symbols = unique

    return fm


# --------------------------------------------------------------------------
# Parser Python
# --------------------------------------------------------------------------

def _parse_python(rel_path: str, text: str) -> FileMap:
    fm = FileMap(path=rel_path, language="python")
    current_class: str | None = None

    for m in re.finditer(
        r'^([ \t]*)(class|def|async def)\s+(\w+)\s*(?:\(([^)]*)\))?',
        text, re.MULTILINE
    ):
        indent = len(m.group(1))
        keyword = m.group(2)
        name = m.group(3)
        params_raw = m.group(4) or ""

        if keyword == "class":
            current_class = name
            fm.symbols.append(Symbol(kind="class", name=name, signature=name))
            continue

        # Funciones / métodos
        if name.startswith("_") and not name.startswith("__"):
            continue  # privados/protegidos → omitir
        params = _simplify_python_params(params_raw)
        vis = "public" if not name.startswith("_") else "protected"
        fm.symbols.append(Symbol(
            kind="method" if (indent > 0 and current_class) else "function",
            name=name,
            signature=f"{name}({params})",
            visibility=vis,
        ))

    return fm


# --------------------------------------------------------------------------
# Helpers de limpieza de texto
# --------------------------------------------------------------------------

def _strip_java_comments(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _strip_cpp_comments(text: str) -> str:
    # igual que Java
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _strip_string_literals(text: str) -> str:
    """Reemplaza strings y chars con marcadores vacíos para no confundir conteo de llaves."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    text = re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)
    text = re.sub(r'`[^`]*`', '``', text)  # template literals TS/Kotlin (no anidados)
    return text


def _normalize_annotations(text: str) -> str:
    """Colapsa anotaciones multilínea (paréntesis sin cerrar) en una sola línea."""
    result: list[str] = []
    buffer = ""
    parens = 0
    in_ann = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@") and not in_ann:
            in_ann = True
            buffer = stripped
            parens = stripped.count("(") - stripped.count(")")
            if parens <= 0:
                result.append(buffer)
                buffer = ""
                in_ann = False
        elif in_ann:
            buffer += " " + stripped
            parens += stripped.count("(") - stripped.count(")")
            if parens <= 0:
                result.append(buffer)
                buffer = ""
                in_ann = False
        else:
            result.append(line)

    if buffer:
        result.append(buffer)
    return "\n".join(result)


# --------------------------------------------------------------------------
# Helpers de parámetros
# --------------------------------------------------------------------------

def _simplify_params(params: str) -> str:
    """Reduce "String userId, int limit" → "String, int" (tipos sin nombres ni paquetes)."""
    if not params.strip():
        return ""
    parts: list[str] = []
    for p in params.split(","):
        p = p.strip()
        if not p:
            continue
        # Quitar anotaciones @X o @X(...)
        p = re.sub(r'@\w+(?:\s*\([^)]*\))?\s*', '', p).strip()
        # Quitar modificadores final
        p = re.sub(r'\bfinal\b\s*', '', p).strip()
        tokens = p.split()
        if len(tokens) >= 2:
            # tokens[-2] = tipo, tokens[-1] = nombre → tomar tipo
            raw_type = tokens[-2].replace("...", "")  # quitar varargs antes de split
            t = raw_type.split(".")[-1]               # quitar paquete
        elif tokens:
            t = tokens[0].replace("...", "").split(".")[-1]
        else:
            continue
        # Truncar generics largos
        t = re.sub(r'<.*', '', t)
        if t:
            parts.append(t)
    return ", ".join(parts)


def _simplify_ts_kotlin_params(params: str) -> str:
    """Simplifica parámetros estilo 'name: Type' (TS/Kotlin) → solo tipos."""
    if not params.strip():
        return ""
    parts: list[str] = []
    for p in params.split(","):
        p = p.strip()
        if not p:
            continue
        p = re.split(r'\s*=\s*', p)[0].strip()  # quitar valor por defecto
        p = re.sub(r'@\w+(?:\s*\([^)]*\))?\s*', '', p).strip()  # quitar decoradores
        if ":" in p:
            type_part = p.split(":", 1)[1].strip()
            type_part = re.sub(r'<[^>]*>', '', type_part).rstrip("?").strip()
            type_part = type_part.split(".")[-1]
            if type_part:
                parts.append(type_part)
        elif p:
            parts.append(p.split(".")[-1])
    return ", ".join(parts)


def _simplify_python_params(params: str) -> str:
    """Reduce params Python: elimina self/cls y tipos de anotación."""
    if not params.strip():
        return ""
    parts: list[str] = []
    for p in params.split(","):
        p = p.strip()
        if not p or p in ("self", "cls", "*", "**kwargs", "*args"):
            continue
        # Quitar tipo de anotación: "name: str = None" → "name"
        name = p.split(":")[0].split("=")[0].strip()
        if name.startswith("*"):
            name = name.lstrip("*")
        if name:
            parts.append(name)
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Parser TypeScript / JavaScript
# --------------------------------------------------------------------------

_RX_TS_METHOD = re.compile(
    r'^[ \t]*'
    r'(?:(?:public|private|protected|static|async|abstract|override|readonly)\s+)*'
    r'(?:get\s+|set\s+)?'
    r'(\w+)\s*'
    r'\(((?:[^)(]|\([^)]*\))*)\)'   # params con 1 nivel de anidamiento
    r'(?:\s*:\s*[\w<>\[\]|& ,?.]+)?'
    r'\s*[{;]',
)

_TS_SKIP = frozenset({
    "if", "for", "while", "switch", "return", "catch", "class", "interface",
    "import", "export", "new", "typeof", "instanceof", "constructor",
    "describe", "it", "test", "expect", "beforeEach", "afterEach",
})


def _ts_method_match(line: str) -> tuple[str, str, str] | None:
    m = _RX_TS_METHOD.match(line)
    if not m:
        return None
    name = m.group(1)
    if name in _TS_SKIP:
        return None
    params = _simplify_ts_kotlin_params(m.group(2))
    vis_m = re.search(r'\b(public|private|protected)\b', line)
    vis = vis_m.group(1) if vis_m else "default"
    return name, params, vis


def _ts_http_base(anns: list[str]) -> str | None:
    for ann in anns:
        m = re.search(r'@Controller\s*\(\s*[\'"]([^\'"]+)[\'"]', ann)
        if m:
            return "/" + m.group(1).lstrip("/")
    return None


def _ts_http_info(anns: list[str], base: str | None) -> tuple[str | None, str | None]:
    for ann in anns:
        m = re.match(
            r'@(Get|Post|Put|Delete|Patch|All)\s*(?:\(\s*[\'"]([^\'"]*)[\'"])?',
            ann, re.IGNORECASE,
        )
        if m:
            verb = "GET" if m.group(1).upper() == "ALL" else m.group(1).upper()
            sub = m.group(2) or ""
            if base and sub:
                path: str | None = base.rstrip("/") + "/" + sub.lstrip("/")
            elif base:
                path = base
            elif sub:
                path = "/" + sub.lstrip("/")
            else:
                path = None
            return verb, path
    return None, None


def _parse_typescript(rel_path: str, text: str) -> FileMap:
    lang = "typescript" if Path(rel_path).suffix.lower() in (".ts", ".tsx") else "javascript"
    fm = FileMap(path=rel_path, language=lang)
    t = _strip_cpp_comments(text)
    t = _normalize_annotations(t)

    class_name: str | None = None
    class_http_base: str | None = None
    pending_anns: list[str] = []
    depth = 0
    class_open_depth: int | None = None

    for lineno, raw_line in enumerate(t.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        depth_before = depth
        depth += _strip_string_literals(line).count("{") - \
                 _strip_string_literals(line).count("}")

        if line.startswith("@"):
            pending_anns.append(line)
            continue

        # Clase / interfaz (solo la primera del archivo)
        if class_name is None:
            cm = re.search(r'\b(class|interface)\s+(\w+)', line)
            if cm:
                class_name = cm.group(2)
                class_http_base = _ts_http_base(pending_anns)
                fm.symbols.append(Symbol(
                    kind=cm.group(1),
                    name=class_name,
                    signature=class_name,
                    visibility="public",
                    http_path=class_http_base,
                    line=lineno,
                ))
                pending_anns.clear()
                class_open_depth = depth
                continue

        # Funciones exportadas a nivel de módulo
        if class_name is None:
            fn_m = re.match(
                r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
                line,
            )
            if fn_m:
                fm.symbols.append(Symbol(
                    kind="function", name=fn_m.group(1),
                    signature=f"{fn_m.group(1)}({_simplify_ts_kotlin_params(fn_m.group(2))})",
                    visibility="public", line=lineno,
                ))
                pending_anns.clear()
                continue
            arr_m = re.match(
                r'export\s+const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*[\w<>]+\s*)?=>',
                line,
            )
            if arr_m:
                fm.symbols.append(Symbol(
                    kind="function", name=arr_m.group(1),
                    signature=f"{arr_m.group(1)}({_simplify_ts_kotlin_params(arr_m.group(2))})",
                    visibility="public", line=lineno,
                ))
                pending_anns.clear()
                continue

        # Métodos en el cuerpo directo de la clase
        if class_open_depth is not None and depth_before == class_open_depth:
            mm = _ts_method_match(line)
            if mm:
                name, params, vis = mm
                if vis in ("public", "default") and not name.startswith("_"):
                    h_method, h_path = _ts_http_info(pending_anns, class_http_base)
                    fm.symbols.append(Symbol(
                        kind="method", name=name,
                        signature=f"{name}({params})",
                        visibility="public" if vis == "default" else vis,
                        http_method=h_method,
                        http_path=h_path,
                        line=lineno,
                    ))

        pending_anns.clear()

    return fm


# --------------------------------------------------------------------------
# Parser Kotlin
# --------------------------------------------------------------------------

_RX_KT_FUN = re.compile(
    r'^[ \t]*'
    r'(?:(?:public|private|protected|internal|open|override|suspend|abstract|inline|operator|external)\s+)*'
    r'fun\s+'
    r'(?:<[^>]*>\s+)?'    # type params
    r'(?:[\w.]+\.)?'       # receiver opcional (función de extensión)
    r'(\w+)\s*'
    r'\(((?:[^)(]|\([^)]*\))*)\)',   # params con 1 nivel de anidamiento
)

_KT_SKIP = frozenset({
    "if", "for", "while", "return", "when", "throw", "catch", "run",
    "let", "also", "apply", "with",
})


def _kt_fun_match(line: str) -> tuple[str, str] | None:
    m = _RX_KT_FUN.match(line)
    if not m:
        return None
    name = m.group(1)
    if name in _KT_SKIP:
        return None
    return name, _simplify_ts_kotlin_params(m.group(2))


def _kt_vis(line: str) -> str:
    if "private" in line:
        return "private"
    if "protected" in line:
        return "protected"
    if "internal" in line:
        return "internal"
    return "public"


def _kt_http_base(anns: list[str]) -> str | None:
    for ann in anns:
        m = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', ann)
        if m:
            return m.group(1)
    return None


def _kt_http_info(anns: list[str], base: str | None) -> tuple[str | None, str | None]:
    for ann in anns:
        m = re.match(
            r'@(Get|Post|Put|Delete|Patch)Mapping\s*(?:\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\'])?',
            ann,
        )
        if m:
            verb = m.group(1).upper()
            sub = m.group(2) or ""
            if base and sub:
                path: str | None = base.rstrip("/") + "/" + sub.lstrip("/")
            elif base:
                path = base
            elif sub:
                path = sub
            else:
                path = None
            return verb, path
    return None, None


def _parse_kotlin(rel_path: str, text: str) -> FileMap:
    fm = FileMap(path=rel_path, language="kotlin")
    t = _strip_cpp_comments(text)
    t = _normalize_annotations(t)

    class_name: str | None = None
    class_http_base: str | None = None
    pending_anns: list[str] = []
    depth = 0
    class_open_depth: int | None = None

    for lineno, raw_line in enumerate(t.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        depth_before = depth
        depth += _strip_string_literals(line).count("{") - \
                 _strip_string_literals(line).count("}")

        if line.startswith("@"):
            pending_anns.append(line)
            continue

        # class / object / interface
        if class_name is None:
            cm = re.search(r'\b(class|object|interface)\s+(\w+)', line)
            if cm:
                class_name = cm.group(2)
                class_http_base = _kt_http_base(pending_anns)
                fm.symbols.append(Symbol(
                    kind=cm.group(1),
                    name=class_name,
                    signature=class_name,
                    visibility=_kt_vis(line),
                    http_path=class_http_base,
                    line=lineno,
                ))
                pending_anns.clear()
                class_open_depth = depth
                continue

        # fun: métodos en la clase o funciones top-level
        if "private" not in line:
            fun_m = _kt_fun_match(line)
            if fun_m:
                name, params = fun_m
                is_method = (class_open_depth is not None
                             and depth_before == class_open_depth)
                is_toplevel = class_name is None
                if is_method or is_toplevel:
                    h_method, h_path = _kt_http_info(pending_anns, class_http_base)
                    fm.symbols.append(Symbol(
                        kind="method" if is_method else "function",
                        name=name,
                        signature=f"{name}({params})",
                        visibility=_kt_vis(line),
                        http_method=h_method,
                        http_path=h_path,
                        line=lineno,
                    ))

        pending_anns.clear()

    return fm


# --------------------------------------------------------------------------
# Parser Dart
# --------------------------------------------------------------------------

_RX_DART_METHOD = re.compile(
    r'^([ \t]+)'                          # indentado = método de clase
    r'(?:(?:static|async|@override)\s+)*'
    r'(?:[\w<>\[\]?]+[ \t]+)?'            # tipo de retorno opcional
    r'([a-zA-Z]\w*)\s*'                   # nombre (empieza con letra, no _)
    r'\(([^)]*)\)',
    re.MULTILINE,
)

_DART_SKIP = frozenset({
    "if", "for", "while", "switch", "return", "throw", "new", "class",
    "var", "final", "const", "import", "export", "abstract", "extends",
    "implements", "with", "super", "Widget", "State",
})


def _parse_dart(rel_path: str, text: str) -> FileMap:
    fm = FileMap(path=rel_path, language="dart")
    t = _strip_cpp_comments(text)

    # Clases y mixins
    for m in re.finditer(
        r'^(?:abstract\s+)?(?:class|mixin|enum)\s+(\w+)',
        t, re.MULTILINE,
    ):
        kind = "class"  # enum y mixin se mapean a class para el render
        fm.symbols.append(Symbol(kind=kind, name=m.group(1), signature=m.group(1)))

    # Métodos públicos (indentados, sin _)
    seen_methods: set[str] = set()
    for m in _RX_DART_METHOD.finditer(t):
        name = m.group(2)
        if name in _DART_SKIP:
            continue
        key = name
        if key in seen_methods:
            continue
        seen_methods.add(key)
        params = _simplify_params(m.group(3))
        fm.symbols.append(Symbol(
            kind="method", name=name,
            signature=f"{name}({params})",
            visibility="public",
        ))

    return fm


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

def _render_symbol(sym: Symbol) -> str:
    if sym.kind in ("class", "interface", "enum", "record", "struct"):
        suffix = f"  [@{sym.kind} {sym.http_path}]" if sym.http_path else ""
        return f"{sym.kind} {sym.signature}{suffix}"

    if sym.kind in ("method", "function"):
        if sym.http_method:
            path = sym.http_path or ""
            return f"  {sym.http_method:<6} {path:<35} {sym.signature}"
        vis = "+" if sym.visibility == "public" else "~" if sym.visibility == "protected" else "-"
        static = " [static]" if sym.is_static else ""
        return f"  {vis} {sym.signature}{static}"

    return f"  {sym.signature}"
