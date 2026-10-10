"""Tests para adapters/unity.py."""
from __future__ import annotations

from pathlib import Path

from conftest import UNITY_BUILTIN, UNITY_HDRP, UNITY_URP, make_tree
from project_ai.adapters import run_adapters
from project_ai.model import ProjectInfo, SourcePriority
from project_ai.scanner import ProjectScanner


def _info(tmp_path: Path, files: dict) -> ProjectInfo:
    make_tree(tmp_path, files)
    sc = ProjectScanner(str(tmp_path))
    info = ProjectInfo(root=str(tmp_path))
    run_adapters(sc, info, only=["unity"])
    return info


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------

class TestDetect:
    def test_unity_detected(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert any(s.adapter == "unity" for s in info.stacks)

    def test_no_unity_without_project_version(self, tmp_path):
        make_tree(tmp_path, {"Assets/Scripts/Foo.cs": "using UnityEngine;\n"})
        sc = ProjectScanner(str(tmp_path))
        info = ProjectInfo(root=str(tmp_path))
        run_adapters(sc, info, only=["unity"])
        assert not any(s.adapter == "unity" for s in info.stacks)

    def test_confidence_high(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        unity_stack = next(s for s in info.stacks if s.adapter == "unity")
        assert unity_stack.confidence >= 0.9


# --------------------------------------------------------------------------
# Versión de Unity
# --------------------------------------------------------------------------

class TestUnityVersion:
    def test_version_extracted(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        v = info.facts.get("unity.version")
        assert v is not None
        assert v.value == "2022.3.15f1"

    def test_version_is_explicit(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert info.facts["unity.version"].priority == SourcePriority.EXPLICIT

    def test_version_2023(self, tmp_path):
        info = _info(tmp_path, UNITY_HDRP)
        assert info.facts["unity.version"].value == "2023.1.0f1"

    def test_version_2021(self, tmp_path):
        info = _info(tmp_path, UNITY_BUILTIN)
        assert info.facts["unity.version"].value == "2021.3.30f1"

    def test_version_not_with_revision(self, tmp_path):
        """No captura la línea WithRevision (que incluye hash entre paréntesis)."""
        info = _info(tmp_path, UNITY_URP)
        assert "(" not in info.facts["unity.version"].value


# --------------------------------------------------------------------------
# Pipeline de renderizado
# --------------------------------------------------------------------------

class TestRenderPipeline:
    def test_urp_detected(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        rp = info.facts.get("unity.render_pipeline")
        assert rp is not None
        assert rp.value == "URP"

    def test_urp_is_build_priority(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert info.facts["unity.render_pipeline"].priority == SourcePriority.BUILD

    def test_hdrp_detected(self, tmp_path):
        info = _info(tmp_path, UNITY_HDRP)
        assert info.facts["unity.render_pipeline"].value == "HDRP"

    def test_builtin_default(self, tmp_path):
        info = _info(tmp_path, UNITY_BUILTIN)
        assert info.facts["unity.render_pipeline"].value == "Built-in"

    def test_builtin_is_heuristic(self, tmp_path):
        info = _info(tmp_path, UNITY_BUILTIN)
        assert info.facts["unity.render_pipeline"].priority == SourcePriority.HEURISTIC


# --------------------------------------------------------------------------
# Servicios desde paquetes UPM
# --------------------------------------------------------------------------

class TestServices:
    def test_firebase_detected(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        kinds = [s.kind for s in info.services]
        assert "firebase" in kinds

    def test_unity_gaming_services(self, tmp_path):
        info = _info(tmp_path, UNITY_HDRP)
        kinds = [s.kind for s in info.services]
        assert "unity-gaming-services" in kinds

    def test_no_services_builtin(self, tmp_path):
        info = _info(tmp_path, UNITY_BUILTIN)
        assert len(info.services) == 0


# --------------------------------------------------------------------------
# Módulo
# --------------------------------------------------------------------------

class TestModuleKind:
    def test_unity_game_kind(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        kinds = [m.kind for m in info.modules]
        assert "unity-game" in kinds

    def test_one_module(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        unity_mods = [m for m in info.modules if m.build_system == "unity"]
        assert len(unity_mods) == 1


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

class TestCommands:
    def test_run_command_present(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert "run" in info.commands

    def test_test_command_present(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert "test" in info.commands
        assert "batchmode" in info.commands["test"].shell

    def test_build_command_present(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert "build" in info.commands

    def test_run_mentions_hub(self, tmp_path):
        info = _info(tmp_path, UNITY_URP)
        assert "hub" in info.commands["run"].shell.lower() or \
               "hub" in (info.commands["run"].ide_hint or "").lower()
