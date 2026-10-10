"""Tests para project_ai/notes.py y su integración con finalize/context."""
from __future__ import annotations

from pathlib import Path

from conftest import HMDM, make_tree

from project_ai.notes import (
    NOTES_FILE,
    OUTPUT_DIR,
    ensure_notes_template,
    load_notes,
    notes_path,
)


# --------------------------------------------------------------------------
# notes_path
# --------------------------------------------------------------------------

class TestNotesPath:
    def test_returns_correct_path(self, tmp_path):
        p = notes_path(tmp_path)
        assert p == tmp_path / OUTPUT_DIR / NOTES_FILE

    def test_resolves_relative(self, tmp_path):
        import os
        orig = os.getcwd()
        os.chdir(tmp_path)
        try:
            p = notes_path(".")
            assert p.is_absolute()
        finally:
            os.chdir(orig)


# --------------------------------------------------------------------------
# ensure_notes_template
# --------------------------------------------------------------------------

class TestEnsureNotesTemplate:
    def test_creates_file_if_missing(self, tmp_path):
        created = ensure_notes_template(tmp_path)
        assert created is True
        assert notes_path(tmp_path).exists()

    def test_returns_false_if_exists(self, tmp_path):
        ensure_notes_template(tmp_path)
        created = ensure_notes_template(tmp_path)
        assert created is False

    def test_template_has_sections(self, tmp_path):
        ensure_notes_template(tmp_path)
        text = notes_path(tmp_path).read_text()
        assert "¿Qué hace este proyecto?" in text
        assert "Entidades clave" in text
        assert "Reglas de negocio" in text
        assert "Notas para el agente" in text

    def test_creates_output_dir(self, tmp_path):
        ensure_notes_template(tmp_path)
        assert (tmp_path / OUTPUT_DIR).is_dir()

    def test_does_not_overwrite(self, tmp_path):
        ensure_notes_template(tmp_path)
        notes_path(tmp_path).write_text("contenido previo", encoding="utf-8")
        ensure_notes_template(tmp_path)
        assert notes_path(tmp_path).read_text() == "contenido previo"


# --------------------------------------------------------------------------
# load_notes
# --------------------------------------------------------------------------

class TestLoadNotes:
    def test_returns_none_if_no_file(self, tmp_path):
        assert load_notes(tmp_path) is None

    def test_returns_none_for_empty_file(self, tmp_path):
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text("", encoding="utf-8")
        assert load_notes(tmp_path) is None

    def test_returns_none_for_template_only(self, tmp_path):
        ensure_notes_template(tmp_path)
        assert load_notes(tmp_path) is None

    def test_returns_content_when_filled(self, tmp_path):
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\n## ¿Qué hace?\n\nGestiona dispositivos MDM.\n",
            encoding="utf-8",
        )
        result = load_notes(tmp_path)
        assert result is not None
        assert "Gestiona dispositivos MDM" in result

    def test_returns_full_text_when_filled(self, tmp_path):
        content = "# Notas\n\nEsta es una API REST para gestionar flotas.\n"
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(content, encoding="utf-8")
        result = load_notes(tmp_path)
        assert result is not None
        assert result.strip() == content.strip()

    def test_returns_none_for_only_html_comments(self, tmp_path):
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\n<!-- Solo comentarios -->\n<!-- Nada real -->\n",
            encoding="utf-8",
        )
        assert load_notes(tmp_path) is None

    def test_partial_fill_returns_content(self, tmp_path):
        """Aunque algunas secciones estén vacías, si hay texto real devuelve el contenido."""
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\n## ¿Qué hace?\n\nAPI de inventario.\n\n## Entidades clave\n\n<!-- pendiente -->\n",
            encoding="utf-8",
        )
        result = load_notes(tmp_path)
        assert result is not None
        assert "API de inventario" in result


# --------------------------------------------------------------------------
# Integración con finalize
# --------------------------------------------------------------------------

class TestFinalizeIntegration:
    def test_finalize_creates_notes_template(self, tmp_path):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        finalize(tmp_path, info=info, write=True)
        assert notes_path(tmp_path).exists()

    def test_finalize_does_not_overwrite_existing_notes(self, tmp_path):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text("mi contenido previo", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        assert notes_path(tmp_path).read_text() == "mi contenido previo"

    def test_agents_md_includes_notes_when_filled(self, tmp_path):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\nGestiona dispositivos MDM corporativos.\n",
            encoding="utf-8",
        )
        result = finalize(tmp_path, info=info, write=True)
        assert "## 0. Contexto del proyecto" in result.agents_md
        assert "Gestiona dispositivos MDM" in result.agents_md

    def test_agents_md_no_section0_when_notes_empty(self, tmp_path):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        result = finalize(tmp_path, info=info, write=False)
        assert "## 0. Contexto del proyecto" not in result.agents_md

    def test_agents_md_section0_before_section1(self, tmp_path):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\nDominio: MDM corporativo.\n",
            encoding="utf-8",
        )
        result = finalize(tmp_path, info=info, write=False)
        idx0 = result.agents_md.index("## 0. Contexto")
        idx1 = result.agents_md.index("## 1. Proyecto")
        assert idx0 < idx1


# --------------------------------------------------------------------------
# Integración con context
# --------------------------------------------------------------------------

class TestContextIntegration:
    def _setup(self, tmp_path, notes_content: str | None = None):
        from project_ai.recon import recon
        from project_ai.finalize import finalize
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        if notes_content:
            notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
            notes_path(tmp_path).write_text(notes_content, encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        return info

    def test_context_includes_notes(self, tmp_path):
        from project_ai.context import context
        self._setup(tmp_path, "# Notas\n\nAPI de inventario.\n")
        result = context(tmp_path, "cómo funciona el auth")
        assert "API de inventario" in result

    def test_context_no_notes_section_when_missing(self, tmp_path):
        from project_ai.context import context
        self._setup(tmp_path, notes_content=None)
        result = context(tmp_path, "build del proyecto")
        assert "Contexto del proyecto" not in result

    def test_context_notes_before_project_summary(self, tmp_path):
        from project_ai.context import context
        self._setup(tmp_path, "# Notas\n\nDominio: MDM corporativo.\n")
        result = context(tmp_path, "dispositivos")
        idx_notes = result.find("Contexto del proyecto")
        idx_proj  = result.find("## Proyecto")
        assert idx_notes < idx_proj


# --------------------------------------------------------------------------
# CLI subcomando notes
# --------------------------------------------------------------------------

class TestCLINotes:
    def test_creates_template_and_prints_path(self, tmp_path, capsys):
        from project_ai.cli import main
        ret = main(["notes", str(tmp_path)])
        out = capsys.readouterr().out
        assert ret == 0
        assert "notes.md" in out or "Plantilla creada" in out
        assert notes_path(tmp_path).exists()

    def test_prints_content_when_filled(self, tmp_path, capsys):
        from project_ai.cli import main
        notes_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        notes_path(tmp_path).write_text(
            "# Notas\n\nGestiona flotas de dispositivos.\n",
            encoding="utf-8",
        )
        ret = main(["notes", str(tmp_path)])
        out = capsys.readouterr().out
        assert ret == 0
        assert "Gestiona flotas" in out

    def test_reports_empty_template(self, tmp_path, capsys):
        from project_ai.cli import main
        ensure_notes_template(tmp_path)
        ret = main(["notes", str(tmp_path)])
        out = capsys.readouterr().out
        assert ret == 0
        assert "plantilla vacía" in out or "Edítalo" in out
