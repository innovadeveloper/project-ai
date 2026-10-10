"""
schema.py — Documenta el esquema PostgreSQL de un proyecto.

Flujo:
  1. Localiza el dump .sql (auto-detección o --sql explícito).
  2. Extrae objetos: tablas, vistas, funciones/procedimientos (sin LLM).
  3. Escribe .project-ai/schema-map.md — resumen compacto para AGENTS.md y context.
  4. Opcionalmente (--document): llama a Ollama objeto por objeto y escribe
     .project-ai/schema/tablas/<nombre>.md  y  .project-ai/schema/funciones/<nombre>.md
     (reanudable: salta los que ya existen).

El parseo es un port del código de documentar_sql.py (stdlib puro).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OUTPUT_DIR   = ".project-ai"
SCHEMA_DIR   = ".project-ai/schema"
SCHEMA_MAP   = "schema-map.md"

# Ubicaciones donde buscar el dump si no se pasa --sql
_DUMP_CANDIDATES = [
    "schema.sql",
    "db/schema.sql",
    "database/schema.sql",
    "sql/schema.sql",
    "db/dump.sql",
    "database/dump.sql",
    ".project-ai/schema.sql",
]

# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------

@dataclass
class SchemaResult:
    sql_path:    str | None     # ruta del dump usado
    tables:      int            # tablas + vistas encontradas
    functions:   int            # funciones/procedimientos
    documented:  int            # objetos documentados con Ollama
    skipped:     int            # ya existían, se omitieron
    errors:      list[str]      # nombres de objetos con error
    schema_map:  str            # contenido de schema-map.md


# --------------------------------------------------------------------------
# Parser SQL (port de documentar_sql.py, stdlib puro)
# --------------------------------------------------------------------------

_IDENT  = r'((?:"[^"]+"|[\w$]+)(?:\s*\.\s*(?:"[^"]+"|[\w$]+))?)'
_FLAGS  = re.IGNORECASE | re.DOTALL

_RX_FUNC      = re.compile(r'^CREATE\s+(?:OR\s+REPLACE\s+)?(FUNCTION|PROCEDURE)\s+' + _IDENT, _FLAGS)
_RX_TABLE     = re.compile(
    r'^CREATE\s+(?:(?:GLOBAL\s+|LOCAL\s+)?(?:TEMP|TEMPORARY|UNLOGGED)\s+)?TABLE\s+'
    r'(?:IF\s+NOT\s+EXISTS\s+)?' + _IDENT, _FLAGS)
_RX_VIEW      = re.compile(
    r'^CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+'
    r'(?:IF\s+NOT\s+EXISTS\s+)?' + _IDENT, _FLAGS)
_RX_ALTER     = re.compile(r'^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?' + _IDENT, _FLAGS)
_RX_INDEX     = re.compile(r'^CREATE\s+(?:UNIQUE\s+)?INDEX\b.*?\bON\s+(?:ONLY\s+)?' + _IDENT, _FLAGS)
_RX_TRIGGER   = re.compile(r'^CREATE\s+(?:OR\s+REPLACE\s+)?(?:CONSTRAINT\s+)?TRIGGER\b.*?\bON\s+' + _IDENT, _FLAGS)
_RX_COM_TABLE = re.compile(r'^COMMENT\s+ON\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+' + _IDENT, _FLAGS)
_RX_COM_COL   = re.compile(r'^COMMENT\s+ON\s+COLUMN\s+' + _IDENT + r'\s*\.\s*(?:"[^"]+"|[\w$]+)\s+IS', _FLAGS)
_RX_COM_FUNC  = re.compile(r'^COMMENT\s+ON\s+(?:FUNCTION|PROCEDURE)\s+' + _IDENT, _FLAGS)
_RX_LEAD_CMTS = re.compile(r'^(?:\s*(?:--[^\n]*(?:\n|$)|/\*.*?\*/))*\s*', re.DOTALL)
_RX_PARTITION      = re.compile(r'\bPARTITION\s+OF\s+' + _IDENT, _FLAGS)
# pg_dump exporta: ALTER TABLE ONLY padre ATTACH PARTITION hijo FOR VALUES ...
_RX_ATTACH_PART    = re.compile(r'\bATTACH\s+PARTITION\s+' + _IDENT, _FLAGS)
_RX_COLUMN    = re.compile(r'^\s{2,4}(\w+)\s+(\S+)', re.MULTILINE)
_RX_PK        = re.compile(r'\bPRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE)


def _split_statements(sql: str) -> list[str]:
    """Divide el SQL en sentencias respetando comentarios, comillas y dollar-quoting."""
    sentencias, inicio, i, n = [], 0, 0, len(sql)
    while i < n:
        c = sql[i]
        if c == '-' and sql.startswith('--', i):
            j = sql.find('\n', i)
            i = (n if j == -1 else j + 1)
            continue
        if c == '/' and sql.startswith('/*', i):
            j = sql.find('*/', i + 2)
            i = (n if j == -1 else j + 2)
            continue
        if c == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            continue
        if c == '"':
            j = sql.find('"', i + 1)
            i = (n if j == -1 else j + 1)
            continue
        if c == '$':
            m = re.match(r'\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$', sql[i:i + 64])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                i = (n if j == -1 else j + len(tag))
                continue
        if c == ';':
            s = sql[inicio:i + 1].strip()
            if s:
                sentencias.append(s)
            inicio = i + 1
        i += 1
    resto = sql[inicio:].strip()
    if resto:
        sentencias.append(resto)
    return sentencias


def _normalize(name: str) -> str:
    parts = [p.strip().strip('"') for p in re.split(r'\s*\.\s*', name)]
    return '.'.join(p.lower() for p in parts)


def _short(name: str) -> str:
    return name.split('.')[-1]


def _count_args(stmt: str) -> int:
    i = stmt.find('(')
    if i == -1:
        return -1
    level, current, n = 0, '', 0
    for c in stmt[i + 1:]:
        if c == '(':
            level += 1
        elif c == ')':
            if level == 0:
                break
            level -= 1
        elif c == ',' and level == 0:
            n += 1
            current = ''
            continue
        current += c
    return n + 1 if (n or current.strip()) else 0


def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w.-]', '_', name) + '.md'


def _extract_objects(sql: str) -> tuple[list[dict], list[dict], int]:
    """Extrae tablas/vistas y funciones del dump SQL.

    Returns (tablas, funciones, huerfanas) — mismo contrato que documentar_sql.py.
    """
    tables: dict[str, dict] = {}
    functions: list[dict] = []
    pending: list[tuple[str, str, str]] = []
    attach_children: set[str] = set()   # tablas hija vía ATTACH PARTITION

    for stmt in _split_statements(sql):
        clean = _RX_LEAD_CMTS.sub('', stmt, count=1)
        if not clean:
            continue
        m = _RX_FUNC.match(clean)
        if m:
            functions.append({'tipo': m.group(1).lower(), 'nombre': _normalize(m.group(2)),
                               'partes': [clean]})
            continue
        m = _RX_TABLE.match(clean) or _RX_VIEW.match(clean)
        if m:
            tipo = 'tabla' if _RX_TABLE.match(clean) else 'vista'
            nombre = _normalize(m.group(1))
            if nombre in tables:
                tables[nombre]['partes'].append(clean)
            else:
                tables[nombre] = {'tipo': tipo, 'nombre': nombre, 'partes': [clean]}
            continue
        # pg_dump: ALTER TABLE padre ATTACH PARTITION hijo FOR VALUES ...
        ma = _RX_ATTACH_PART.search(clean)
        if ma:
            attach_children.add(_normalize(ma.group(1)))
        for rx, dest in ((_RX_ALTER, 'tabla'), (_RX_INDEX, 'tabla'), (_RX_TRIGGER, 'tabla'),
                         (_RX_COM_TABLE, 'tabla'), (_RX_COM_COL, 'tabla'), (_RX_COM_FUNC, 'funcion')):
            m = rx.match(clean)
            if m:
                if dest == 'tabla' and re.search(r'\bOWNER\s+TO\b', clean, re.IGNORECASE):
                    break
                pending.append((dest, _normalize(m.group(1)), clean))
                break

    def _index(objs: list[dict]) -> tuple[dict, dict]:
        completo: dict[str, dict] = {}
        for o in objs:
            completo.setdefault(o['nombre'], o)
        corto: dict[str, list] = {}
        for o in objs:
            corto.setdefault(_short(o['nombre']), []).append(o)
        return completo, corto

    t_full, t_short = _index(list(tables.values()))
    f_full, f_short = _index(functions)
    orphans = 0
    for dest, nombre, text in pending:
        full, short = (t_full, t_short) if dest == 'tabla' else (f_full, f_short)
        obj = full.get(nombre)
        if dest == 'funcion':
            overloads = [f for f in functions if f['nombre'] == nombre]
            if len(overloads) > 1:
                n_args = _count_args(text)
                obj = next((f for f in overloads if _count_args(f['partes'][0]) == n_args), obj)
        if obj is None and len(short.get(_short(nombre), [])) == 1:
            obj = short[_short(nombre)][0]
        if obj is not None:
            obj['partes'].append(text)
        else:
            orphans += 1

    # Marcar particiones (PARTITION OF inline + pg_dump ATTACH PARTITION)
    hijas: dict[str, list[str]] = {}
    for t in tables.values():
        m = _RX_PARTITION.search(t['partes'][0])
        is_partition = bool(m) or t['nombre'] in attach_children
        t['particion'] = is_partition
        if m:
            hijas.setdefault(_normalize(m.group(1)), []).append(t['nombre'])
    for padre, lista in hijas.items():
        obj = t_full.get(padre) or (t_short.get(_short(padre)) or [None])[0]
        if obj is not None:
            obj['partes'].append('-- Particiones de esta tabla: ' + ', '.join(sorted(lista)))

    # Nombres de archivo únicos para funciones sobrecargadas
    vistos: dict[str, int] = {}
    for f in functions:
        vistos[f['nombre']] = vistos.get(f['nombre'], 0) + 1
        f['archivo'] = f['nombre'] if vistos[f['nombre']] == 1 else f"{f['nombre']}__{vistos[f['nombre']]}"
    for t in tables.values():
        t['archivo'] = t['nombre']

    return list(tables.values()), functions, orphans


# --------------------------------------------------------------------------
# Schema-map compacto (sin LLM)
# --------------------------------------------------------------------------

def _extract_columns(create_sql: str) -> list[tuple[str, str]]:
    """Extrae (nombre, tipo) de las columnas de un CREATE TABLE."""
    cols = []
    for m in _RX_COLUMN.finditer(create_sql):
        name, typ = m.group(1), m.group(2).rstrip(',')
        # Ignorar palabras clave de PostgreSQL que no son columnas
        if name.upper() in ('CONSTRAINT', 'PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'EXCLUDE'):
            continue
        cols.append((name, typ))
    return cols[:15]   # máx 15 columnas en el mapa compacto


def _extract_pk(create_sql: str) -> str:
    """Extrae la clave primaria del CREATE TABLE."""
    m = _RX_PK.search(create_sql)
    if not m:
        # PK inline: columna ... PRIMARY KEY
        m2 = re.search(r'(\w+)\s+\w+.*?\bPRIMARY\s+KEY\b', create_sql, re.IGNORECASE)
        return m2.group(1) if m2 else ''
    return ', '.join(c.strip().strip('"') for c in m.group(1).split(','))


def build_schema_map(tables: list[dict], functions: list[dict], sql_name: str) -> str:
    """Genera el schema-map.md compacto para AGENTS.md y context.py."""
    lines = [
        "# Schema map",
        "",
        f"> Fuente: `{sql_name}`",
        "",
    ]

    real_tables = [t for t in tables if t['tipo'] == 'tabla' and not t.get('particion')]
    views       = [t for t in tables if t['tipo'] == 'vista']

    # --- Tablas -------------------------------------------------------------
    if real_tables:
        lines += [f"## Tablas ({len(real_tables)})", ""]
        for t in sorted(real_tables, key=lambda x: _short(x['nombre'])):
            name = _short(t['nombre'])
            create_sql = t['partes'][0]
            cols = _extract_columns(create_sql)
            pk   = _extract_pk(create_sql)
            col_txt = ', '.join(f"`{c}`" for c, _ in cols[:6])
            if len(cols) > 6:
                col_txt += f" … (+{len(cols) - 6})"
            pk_txt = f" · PK: `{pk}`" if pk else ""
            lines.append(f"### `{name}`")
            lines.append(f"Columnas: {col_txt}{pk_txt}  ")
            lines.append("")

    # --- Vistas -------------------------------------------------------------
    if views:
        lines += [f"## Vistas ({len(views)})", ""]
        for v in sorted(views, key=lambda x: _short(x['nombre'])):
            lines.append(f"- `{_short(v['nombre'])}`")
        lines.append("")

    # --- Funciones ----------------------------------------------------------
    non_partition_funcs = functions
    if non_partition_funcs:
        lines += [f"## Funciones y procedimientos ({len(non_partition_funcs)})", ""]
        for f in sorted(non_partition_funcs, key=lambda x: _short(x['nombre'])):
            tipo = f['tipo']
            lines.append(f"- `{_short(f['nombre'])}` ({tipo})")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Llamada a Ollama (para --document)
# --------------------------------------------------------------------------

_SYSTEM_SQL = (
    "Eres un documentador experto de bases de datos PostgreSQL. Escribes en español, "
    "en Markdown, de forma clara y concisa. Usa SOLO la información del SQL recibido: "
    "no inventes columnas, tipos, tablas ni relaciones. Si el propósito de algo no es "
    "evidente por los nombres o el código, escribe 'Por confirmar'. No repitas el SQL completo."
)

_TPL_TABLE = """\
Documenta este objeto ({tipo}) para un diccionario de datos.
Responde EXACTAMENTE con esta estructura:

## {nombre}
**Tipo:** {tipo}
**Propósito:** (1-2 frases)

| Columna | Tipo | Nulo | Por defecto | Descripción |
|---|---|---|---|---|
(una fila por columna)

**Clave primaria:** ...
**Claves foráneas:** (columna -> tabla.columna, o 'Ninguna')
**Índices y restricciones:** ...
**Observaciones:** (posibles problemas de diseño, si los hay)

SQL:
```sql
{sql}
```"""

_TPL_FUNC = """\
Documenta esta {tipo} de PostgreSQL.
Responde EXACTAMENTE con esta estructura:

## {nombre}
**Propósito:** (1-3 frases)

**Parámetros:**
| Nombre | Tipo | Descripción |
|---|---|---|

**Retorna:** ...
**Tablas que lee:** ...
**Tablas que modifica:** ...
**Lógica paso a paso:** (lista numerada breve)
**Observaciones:** (riesgos, rendimiento, SECURITY DEFINER, etc.)

SQL:
```sql
{sql}
```"""


def _call_ollama(url: str, model: str, user: str, *, num_ctx: int = 16384) -> str:
    payload = {
        'model': model,
        'stream': False,
        'messages': [
            {'role': 'system', 'content': _SYSTEM_SQL},
            {'role': 'user',   'content': user},
        ],
        'options': {'num_ctx': num_ctx, 'temperature': 0.2},
    }
    req = urllib.request.Request(
        url.rstrip('/') + '/api/chat',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())['message']['content'].strip()


# --------------------------------------------------------------------------
# Auto-detección del dump
# --------------------------------------------------------------------------

def find_sql_dump(root: Path) -> Path | None:
    """Busca un dump SQL en ubicaciones comunes del proyecto."""
    for rel in _DUMP_CANDIDATES:
        p = root / rel
        if p.exists():
            return p
    # Único .sql en la raíz
    sqls = [f for f in root.iterdir() if f.suffix == '.sql' and f.is_file()]
    if len(sqls) == 1:
        return sqls[0]
    return None


# --------------------------------------------------------------------------
# Función principal
# --------------------------------------------------------------------------

def schema(
    path: str | Path,
    *,
    sql_path: str | Path | None = None,
    document: bool = False,
    model: str | None = None,
    ollama_url: str = "http://localhost:11434",
    num_ctx: int = 16384,
    force: bool = False,
    write: bool = True,
) -> SchemaResult:
    """Extrae y documenta el esquema PostgreSQL del proyecto.

    Args:
        path:       Raíz del proyecto.
        sql_path:   Ruta al dump .sql. Si None, se auto-detecta.
        document:   Si True, llama a Ollama para documentar cada objeto.
        model:      Modelo Ollama (por defecto qwen2.5-coder:7b).
        ollama_url: URL del servidor Ollama.
        num_ctx:    Ventana de contexto por llamada.
        force:      Re-documentar aunque el .md ya exista.
        write:      Si False, no escribe nada en disco.
    """
    root = Path(path).resolve()
    model = model or "qwen2.5-coder:7b"

    # 1. Localizar el dump
    dump: Path | None = Path(sql_path).resolve() if sql_path else find_sql_dump(root)
    if dump is None or not dump.exists():
        raise FileNotFoundError(
            f"No se encontró dump SQL. Pasa --sql <ruta> o coloca el archivo en "
            f"{', '.join(_DUMP_CANDIDATES[:4])} (relativo a {root})."
        )

    # 2. Parsear
    sql_text  = dump.read_text(encoding='utf-8', errors='replace')
    tables, functions, orphans = _extract_objects(sql_text)

    # Excluir particiones del mapa compacto (ya están bajo la tabla padre)
    main_tables = [t for t in tables if not t.get('particion')]

    # 3. Generar schema-map.md
    map_text = build_schema_map(tables, functions, dump.name)

    if write:
        out_dir = root / OUTPUT_DIR
        out_dir.mkdir(exist_ok=True)
        (out_dir / SCHEMA_MAP).write_text(map_text, encoding='utf-8')

    documented = skipped = 0
    errors: list[str] = []

    # 4. Documentar con Ollama (opcional)
    if document and write:
        schema_dir = root / SCHEMA_DIR
        (schema_dir / 'tablas').mkdir(parents=True, exist_ok=True)
        (schema_dir / 'funciones').mkdir(parents=True, exist_ok=True)

        max_chars = max(4000, int((num_ctx - 3500) * 3.5))

        def _doc_objects(objs: list[dict], subfolder: str, tpl: str) -> None:
            nonlocal documented, skipped
            for obj in objs:
                dest = schema_dir / subfolder / _safe_filename(obj['archivo'])
                if dest.exists() and not force:
                    skipped += 1
                    continue
                sql_chunk = '\n\n'.join(obj['partes'])
                if len(sql_chunk) > max_chars:
                    sql_chunk = sql_chunk[:max_chars] + '\n-- [recortado]'
                prompt = tpl.format(tipo=obj['tipo'], nombre=obj['nombre'], sql=sql_chunk)
                try:
                    doc = _call_ollama(ollama_url, model, prompt, num_ctx=num_ctx)
                    dest.write_text(doc + '\n', encoding='utf-8')
                    documented += 1
                except (urllib.error.URLError, Exception) as e:
                    errors.append(f"{obj['nombre']}: {e}")

        _doc_objects(main_tables,    'tablas',    _TPL_TABLE)
        _doc_objects(functions, 'funciones', _TPL_FUNC)

    return SchemaResult(
        sql_path=str(dump),
        tables=len(main_tables),
        functions=len(functions),
        documented=documented,
        skipped=skipped,
        errors=errors,
        schema_map=map_text,
    )
