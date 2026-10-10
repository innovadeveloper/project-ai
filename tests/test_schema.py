"""Tests para project_ai/schema.py y su integración con finalize/context/cli."""
from __future__ import annotations

from pathlib import Path

from project_ai.schema import (
    SchemaResult,
    _extract_objects,
    _split_statements,
    build_schema_map,
    find_sql_dump,
    schema,
)


# --------------------------------------------------------------------------
# Fixtures SQL
# --------------------------------------------------------------------------

_SQL_BASIC = """\
CREATE TABLE devices (
    id          SERIAL PRIMARY KEY,
    hostname    VARCHAR(255) NOT NULL,
    ip_address  INET,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE fleets (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

ALTER TABLE devices ADD COLUMN fleet_id INTEGER REFERENCES fleets(id);

CREATE OR REPLACE FUNCTION get_device(p_id INTEGER)
RETURNS devices AS $$
    SELECT * FROM devices WHERE id = p_id;
$$ LANGUAGE sql;

CREATE VIEW active_devices AS
SELECT * FROM devices WHERE ip_address IS NOT NULL;
"""

_SQL_PARTITION = """\
CREATE TABLE events (
    id         BIGSERIAL,
    created_at TIMESTAMPTZ NOT NULL,
    kind       TEXT
) PARTITION BY RANGE (created_at);

CREATE TABLE events_2024 PARTITION OF events
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE events_2025 PARTITION OF events
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
"""

# Patrón pg_dump: CREATE TABLE hijo (...) + ALTER TABLE padre ATTACH PARTITION hijo
_SQL_PGDUMP_PARTITION = """\
CREATE TABLE logs (
    id         BIGSERIAL NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    message    TEXT
) PARTITION BY RANGE (created_at);

CREATE TABLE logs_2026_01 (
    id         BIGSERIAL NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    message    TEXT
);

CREATE TABLE logs_2026_02 (
    id         BIGSERIAL NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    message    TEXT
);

ALTER TABLE ONLY logs ATTACH PARTITION logs_2026_01
    FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2026-02-01 00:00:00+00');

ALTER TABLE ONLY logs ATTACH PARTITION logs_2026_02
    FOR VALUES FROM ('2026-02-01 00:00:00+00') TO ('2026-03-01 00:00:00+00');
"""

_SQL_FUNCTIONS = """\
CREATE FUNCTION add(a INT, b INT) RETURNS INT
    LANGUAGE sql AS $$ SELECT a + b; $$;

CREATE PROCEDURE reset_device(dev_id INT)
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE devices SET ip_address = NULL WHERE id = dev_id;
END;
$$;
"""

_SQL_COMMENT = """\
-- Este es un comentario
/* Bloque de comentario */
CREATE TABLE users (
    id   SERIAL PRIMARY KEY,
    name TEXT
);

-- Fin
"""


# --------------------------------------------------------------------------
# _split_statements
# --------------------------------------------------------------------------

class TestSplitStatements:
    def test_splits_basic(self):
        stmts = _split_statements(_SQL_BASIC)
        assert len(stmts) >= 4

    def test_dollar_quoting(self):
        stmts = _split_statements(_SQL_FUNCTIONS)
        assert len(stmts) == 2

    def test_comment_ignored(self):
        stmts = _split_statements(_SQL_COMMENT)
        assert any("CREATE TABLE users" in s for s in stmts)

    def test_empty_sql(self):
        assert _split_statements("") == []

    def test_single_statement_no_semicolon(self):
        stmts = _split_statements("SELECT 1")
        assert len(stmts) == 1


# --------------------------------------------------------------------------
# _extract_objects
# --------------------------------------------------------------------------

class TestExtractObjects:
    def test_basic_tables(self):
        tables, functions, _ = _extract_objects(_SQL_BASIC)
        names = {t['nombre'] for t in tables}
        assert 'devices' in names
        assert 'fleets' in names

    def test_detects_view(self):
        tables, _, _ = _extract_objects(_SQL_BASIC)
        types = {t['tipo'] for t in tables}
        assert 'vista' in types

    def test_detects_function(self):
        _, funcs, _ = _extract_objects(_SQL_BASIC)
        assert any('get_device' in f['nombre'] for f in funcs)

    def test_partition_detected(self):
        tables, _, _ = _extract_objects(_SQL_PARTITION)
        # La tabla madre existe
        assert any('events' == t['nombre'] for t in tables)
        # Las hijas están marcadas como partición
        hijas = [t for t in tables if t.get('particion')]
        assert len(hijas) >= 2

    def test_functions_sql(self):
        _, funcs, _ = _extract_objects(_SQL_FUNCTIONS)
        tipos = {f['tipo'] for f in funcs}
        assert 'function' in tipos
        assert 'procedure' in tipos

    def test_pgdump_attach_partition_excluded(self):
        """pg_dump: CREATE TABLE hijo + ALTER TABLE padre ATTACH PARTITION hijo."""
        tables, _, _ = _extract_objects(_SQL_PGDUMP_PARTITION)
        non_partition = [t for t in tables if not t.get('particion')]
        partition = [t for t in tables if t.get('particion')]
        # Solo la tabla madre es "real"
        assert any('logs' == t['nombre'] for t in non_partition)
        # Las dos hijas son particiones
        assert len(partition) == 2
        child_names = {t['nombre'] for t in partition}
        assert 'logs_2026_01' in child_names
        assert 'logs_2026_02' in child_names

    def test_pgdump_partitions_not_in_schema_map(self):
        tables, funcs, _ = _extract_objects(_SQL_PGDUMP_PARTITION)
        result = build_schema_map(tables, funcs, "dump.sql")
        assert 'logs_2026_01' not in result
        assert 'logs_2026_02' not in result
        assert '`logs`' in result

    def test_alter_attached_to_table(self):
        """El ALTER TABLE se debe adjuntar a la tabla devices."""
        tables, _, _ = _extract_objects(_SQL_BASIC)
        devices = next(t for t in tables if t['nombre'] == 'devices')
        alter_parts = [p for p in devices['partes'] if 'ALTER' in p.upper()]
        assert alter_parts

    def test_empty_sql(self):
        tables, funcs, _ = _extract_objects("")
        assert tables == []
        assert funcs == []


# --------------------------------------------------------------------------
# build_schema_map
# --------------------------------------------------------------------------

class TestBuildSchemaMap:
    def test_contains_table_names(self):
        tables, funcs, _ = _extract_objects(_SQL_BASIC)
        result = build_schema_map(tables, funcs, "schema.sql")
        assert "devices" in result
        assert "fleets" in result

    def test_contains_function_name(self):
        tables, funcs, _ = _extract_objects(_SQL_BASIC)
        result = build_schema_map(tables, funcs, "schema.sql")
        assert "get_device" in result

    def test_contains_view(self):
        tables, funcs, _ = _extract_objects(_SQL_BASIC)
        result = build_schema_map(tables, funcs, "schema.sql")
        assert "active_devices" in result or "Vistas" in result

    def test_source_filename(self):
        tables, funcs, _ = _extract_objects(_SQL_BASIC)
        result = build_schema_map(tables, funcs, "mi_dump.sql")
        assert "mi_dump.sql" in result

    def test_excludes_partitions(self):
        tables, funcs, _ = _extract_objects(_SQL_PARTITION)
        result = build_schema_map(tables, funcs, "schema.sql")
        # La tabla madre aparece, las hijas no como tablas independientes
        assert "events" in result
        # Sección de particiones no tiene subsección propia
        assert "events_2024" not in result.split("###")[1] if "###" in result else True

    def test_functions_section(self):
        _, funcs, _ = _extract_objects(_SQL_FUNCTIONS)
        result = build_schema_map([], funcs, "funcs.sql")
        assert "add" in result
        assert "reset_device" in result


# --------------------------------------------------------------------------
# find_sql_dump
# --------------------------------------------------------------------------

class TestFindSqlDump:
    def test_finds_schema_sql(self, tmp_path):
        (tmp_path / "schema.sql").write_text("CREATE TABLE t (id int);")
        assert find_sql_dump(tmp_path) == tmp_path / "schema.sql"

    def test_finds_db_schema(self, tmp_path):
        db = tmp_path / "db"
        db.mkdir()
        (db / "schema.sql").write_text("CREATE TABLE t (id int);")
        assert find_sql_dump(tmp_path) == db / "schema.sql"

    def test_finds_single_sql_in_root(self, tmp_path):
        (tmp_path / "dump.sql").write_text("CREATE TABLE t (id int);")
        assert find_sql_dump(tmp_path) == tmp_path / "dump.sql"

    def test_no_sql_returns_none(self, tmp_path):
        assert find_sql_dump(tmp_path) is None

    def test_multiple_sqls_no_candidate_returns_none(self, tmp_path):
        (tmp_path / "a.sql").write_text("SELECT 1;")
        (tmp_path / "b.sql").write_text("SELECT 2;")
        # No hay schema.sql ni candidato único → None
        assert find_sql_dump(tmp_path) is None


# --------------------------------------------------------------------------
# schema() — función principal (sin write ni LLM)
# --------------------------------------------------------------------------

class TestSchemaFunction:
    def _write_sql(self, tmp_path, content=_SQL_BASIC) -> Path:
        p = tmp_path / "schema.sql"
        p.write_text(content, encoding="utf-8")
        return p

    def test_returns_result(self, tmp_path):
        self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert isinstance(result, SchemaResult)

    def test_detects_tables_and_functions(self, tmp_path):
        self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert result.tables >= 2
        assert result.functions >= 1

    def test_sql_path_in_result(self, tmp_path):
        p = self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert str(p) == result.sql_path

    def test_schema_map_in_result(self, tmp_path):
        self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert "devices" in result.schema_map

    def test_writes_schema_map(self, tmp_path):
        self._write_sql(tmp_path)
        schema(tmp_path, write=True)
        assert (tmp_path / ".project-ai" / "schema-map.md").exists()

    def test_no_write_does_not_create_file(self, tmp_path):
        self._write_sql(tmp_path)
        schema(tmp_path, write=False)
        assert not (tmp_path / ".project-ai" / "schema-map.md").exists()

    def test_explicit_sql_path(self, tmp_path):
        sql = tmp_path / "custom_dump.sql"
        sql.write_text(_SQL_BASIC, encoding="utf-8")
        result = schema(tmp_path, sql_path=sql, write=False)
        assert result.sql_path == str(sql)

    def test_raises_if_no_sql(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            schema(tmp_path, write=False)

    def test_documented_zero_when_no_document(self, tmp_path):
        self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert result.documented == 0
        assert result.skipped == 0

    def test_no_errors_basic(self, tmp_path):
        self._write_sql(tmp_path)
        result = schema(tmp_path, write=False)
        assert result.errors == []


# --------------------------------------------------------------------------
# Integración con finalize
# --------------------------------------------------------------------------

class TestFinalizeSchemaIntegration:
    def test_schema_map_in_navigation_when_present(self, tmp_path):
        from conftest import HMDM, make_tree
        from project_ai.finalize import finalize
        from project_ai.recon import recon

        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        # Crear schema-map.md manualmente
        out = tmp_path / ".project-ai"
        out.mkdir(exist_ok=True)
        (out / "schema-map.md").write_text("# Schema map\n\n## Tablas\n", encoding="utf-8")

        result = finalize(tmp_path, info=info, write=False)
        assert "schema-map.md" in result.agents_md

    def test_schema_map_not_in_navigation_when_absent(self, tmp_path):
        from conftest import HMDM, make_tree
        from project_ai.finalize import finalize
        from project_ai.recon import recon

        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        result = finalize(tmp_path, info=info, write=False)
        assert "schema-map.md" not in result.agents_md


# --------------------------------------------------------------------------
# Integración con context
# --------------------------------------------------------------------------

class TestContextSchemaIntegration:
    def test_context_includes_schema_match(self, tmp_path):
        from conftest import HMDM, make_tree
        from project_ai.context import context
        from project_ai.finalize import finalize
        from project_ai.recon import recon

        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        finalize(tmp_path, info=info, write=True)

        # Crear schema-map.md con tabla relevante
        (tmp_path / ".project-ai" / "schema-map.md").write_text(
            "# Schema map\n\n## Tablas\n\n### `dispositivos`\nColumnas: `id`, `nombre`\n",
            encoding="utf-8",
        )

        result = context(tmp_path, "tabla dispositivos")
        assert "dispositivos" in result

    def test_context_no_schema_section_without_file(self, tmp_path):
        from conftest import HMDM, make_tree
        from project_ai.context import context
        from project_ai.finalize import finalize
        from project_ai.recon import recon

        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        finalize(tmp_path, info=info, write=True)

        result = context(tmp_path, "tabla dispositivos")
        assert "Schema SQL relevante" not in result


# --------------------------------------------------------------------------
# CLI subcomando schema
# --------------------------------------------------------------------------

class TestCLISchema:
    def test_schema_command_writes_map(self, tmp_path):
        (tmp_path / "schema.sql").write_text(_SQL_BASIC, encoding="utf-8")
        from project_ai.cli import main
        ret = main(["schema", str(tmp_path)])
        assert ret == 0
        assert (tmp_path / ".project-ai" / "schema-map.md").exists()

    def test_schema_command_no_write(self, tmp_path, capsys):
        (tmp_path / "schema.sql").write_text(_SQL_BASIC, encoding="utf-8")
        from project_ai.cli import main
        ret = main(["schema", str(tmp_path), "--no-write"])
        assert ret == 0
        assert not (tmp_path / ".project-ai" / "schema-map.md").exists()

    def test_schema_command_reports_counts(self, tmp_path, capsys):
        (tmp_path / "schema.sql").write_text(_SQL_BASIC, encoding="utf-8")
        from project_ai.cli import main
        main(["schema", str(tmp_path), "--no-write"])
        out = capsys.readouterr().out
        assert "Tablas" in out
        assert "Funciones" in out

    def test_schema_command_explicit_sql(self, tmp_path, capsys):
        sql = tmp_path / "custom.sql"
        sql.write_text(_SQL_BASIC, encoding="utf-8")
        from project_ai.cli import main
        ret = main(["schema", str(tmp_path), "--sql", str(sql), "--no-write"])
        assert ret == 0

    def test_schema_command_error_no_sql(self, tmp_path, capsys):
        from project_ai.cli import main
        ret = main(["schema", str(tmp_path)])
        assert ret == 1
        err = capsys.readouterr().err
        assert "Error" in err or "sql" in err.lower()

    def test_schema_command_prints_map_path(self, tmp_path, capsys):
        (tmp_path / "schema.sql").write_text(_SQL_BASIC, encoding="utf-8")
        from project_ai.cli import main
        main(["schema", str(tmp_path)])
        out = capsys.readouterr().out
        assert "schema-map.md" in out


# --------------------------------------------------------------------------
# setup_agent con schema
# --------------------------------------------------------------------------

class TestSetupAgentSchema:
    def test_setup_agent_includes_schema_section_when_map_present(self, tmp_path):
        from project_ai.setup_agent import setup_agent

        (tmp_path / ".project-ai").mkdir(exist_ok=True)
        (tmp_path / ".project-ai" / "schema-map.md").write_text(
            "# Schema map\n", encoding="utf-8"
        )
        result = setup_agent(tmp_path, write=False)
        assert "Schema SQL" in result or "schema" in result.lower()

    def test_setup_agent_no_schema_section_when_absent(self, tmp_path):
        from project_ai.setup_agent import setup_agent

        result = setup_agent(tmp_path, write=False)
        assert "Schema SQL" not in result
