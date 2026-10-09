"""Tests para recon.py y cli.py."""
from __future__ import annotations

import json
import subprocess
import sys

from conftest import NETCLIENT_FULL, HMDM, make_tree, git_init, needs_git

from project_ai.recon import recon, OUTPUT_DIR, OUTPUT_FILE, _add_git_exclude


# ---------------------------------------------------------------------------
# recon() — escritura de project.json
# ---------------------------------------------------------------------------

def test_recon_writes_project_json(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    recon(tmp_path)
    out = tmp_path / OUTPUT_DIR / OUTPUT_FILE
    assert out.exists(), f"{out} no fue creado"
    data = json.loads(out.read_text())
    assert data["root"] == str(tmp_path)
    assert "stacks" in data


def test_recon_json_equals_stdout(tmp_path):
    """El JSON escrito en el archivo debe ser idéntico al que devuelve to_dict()."""
    make_tree(tmp_path, NETCLIENT_FULL)
    info = recon(tmp_path)
    out = tmp_path / OUTPUT_DIR / OUTPUT_FILE
    from_file = json.loads(out.read_text())
    from_info = info.to_dict()
    # generated_at puede diferir en microsegundos entre serialización → comparo el resto
    from_file.pop("generated_at", None)
    from_info.pop("generated_at", None)
    assert from_file == from_info


def test_recon_idempotent(tmp_path):
    """Ejecutar recon dos veces no lanza excepciones y el archivo existe."""
    make_tree(tmp_path, NETCLIENT_FULL)
    info1 = recon(tmp_path)
    info2 = recon(tmp_path)
    out = tmp_path / OUTPUT_DIR / OUTPUT_FILE
    assert out.exists()
    # Los stacks detectados deben ser iguales
    assert {s.adapter for s in info1.stacks} == {s.adapter for s in info2.stacks}


def test_recon_no_write(tmp_path):
    """--no-write no crea el directorio .project-ai/."""
    make_tree(tmp_path, NETCLIENT_FULL)
    recon(tmp_path, write=False)
    assert not (tmp_path / OUTPUT_DIR).exists()


def test_recon_project_ai_dir_not_in_scanner(tmp_path):
    """.project-ai/ creado por la primera pasada no se incluye en el scanner."""
    make_tree(tmp_path, NETCLIENT_FULL)
    recon(tmp_path)                # primera pasada: crea .project-ai/
    info2 = recon(tmp_path)        # segunda pasada
    # Los archivos de .project-ai/ no deben aparecer en requirements/stacks
    all_files_in_evidence = [
        e.file
        for req in info2.requirements.values()
        for e in req.evidence
    ]
    assert not any(OUTPUT_DIR in f for f in all_files_in_evidence)


def test_recon_hmdm(tmp_path):
    """Maven multi-módulo reconocido correctamente desde recon()."""
    make_tree(tmp_path, HMDM)
    info = recon(tmp_path, write=False)
    assert any(s.adapter == "maven" for s in info.stacks)
    assert "jdk" in info.requirements


# ---------------------------------------------------------------------------
# Git exclude
# ---------------------------------------------------------------------------

@needs_git
def test_recon_adds_git_exclude(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    git_init(tmp_path)
    recon(tmp_path)
    exclude = tmp_path / ".git" / "info" / "exclude"
    assert exclude.exists()
    assert ".project-ai/" in exclude.read_text()


@needs_git
def test_recon_git_exclude_idempotent(tmp_path):
    """Ejecutar dos veces no duplica la entrada en .git/info/exclude."""
    make_tree(tmp_path, NETCLIENT_FULL)
    git_init(tmp_path)
    recon(tmp_path)
    recon(tmp_path)
    exclude = tmp_path / ".git" / "info" / "exclude"
    content = exclude.read_text()
    assert content.count(".project-ai/") == 1


def test_add_git_exclude_no_git(tmp_path):
    """Sin repo git, _add_git_exclude devuelve False sin crear archivos."""
    result = _add_git_exclude(tmp_path)
    assert result is False
    assert not (tmp_path / ".git").exists()


# ---------------------------------------------------------------------------
# CLI (project_ai.cli)
# ---------------------------------------------------------------------------

def test_cli_recon_text(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "recon", str(tmp_path), "--no-write"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0 or result.returncode == 1  # 1 si hay warnings
    assert "cmake" in result.stdout.lower() or "conan" in result.stdout.lower()


def test_cli_recon_json(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "recon", str(tmp_path),
         "--no-write", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "stacks" in data
    assert "requirements" in data


def test_cli_recon_writes_file(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "recon", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert (tmp_path / OUTPUT_DIR / OUTPUT_FILE).exists()


def test_cli_json_equals_file(tmp_path):
    """project-ai recon --json == contenido de project.json (salvo generated_at)."""
    make_tree(tmp_path, NETCLIENT_FULL)
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "recon", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    from_stdout = json.loads(result.stdout)
    from_file   = json.loads((tmp_path / OUTPUT_DIR / OUTPUT_FILE).read_text())
    from_stdout.pop("generated_at", None)
    from_file.pop("generated_at", None)
    assert from_stdout == from_file


def test_cli_no_subcommand_shows_help(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "recon" in result.stdout


def test_cli_adapters_alias(tmp_path):
    """El subcomando 'adapters' no escribe archivos."""
    make_tree(tmp_path, HMDM)
    subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "adapters", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert not (tmp_path / OUTPUT_DIR).exists()
