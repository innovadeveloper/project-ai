"""Tests para project_ai/setup_agent.py."""
import json
from pathlib import Path

import pytest

from project_ai.setup_agent import setup_agent, _serena_args, _generate
from project_ai.config import Config
from project_ai.model import ProjectInfo, StackDetection


def _make_info(stacks: list[str], root: Path | None = None) -> ProjectInfo:
    info = ProjectInfo(root=root or Path("/tmp/dummy"))
    for s in stacks:
        info.add_stack(StackDetection(adapter=s, confidence=0.9, evidence=[]))
    return info


def _default_config() -> Config:
    return Config.from_project(Path("/tmp/dummy"))


# --------------------------------------------------------------------------
# _serena_args por stack
# --------------------------------------------------------------------------

class TestSerenaArgs:
    def test_cmake_uses_clangd(self, tmp_path):
        args = _serena_args(tmp_path, ["cmake"])
        assert "--lsp-binary" in args
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "clangd"

    def test_maven_uses_jdtls(self, tmp_path):
        args = _serena_args(tmp_path, ["maven"])
        assert "--lsp-binary" in args
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "jdtls"

    def test_gradle_uses_jdtls(self, tmp_path):
        args = _serena_args(tmp_path, ["gradle"])
        assert "--lsp-binary" in args
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "jdtls"

    def test_rust_uses_rust_analyzer(self, tmp_path):
        args = _serena_args(tmp_path, ["rust"])
        assert "--lsp-binary" in args
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "rust-analyzer"

    def test_go_uses_gopls(self, tmp_path):
        args = _serena_args(tmp_path, ["go"])
        assert "--lsp-binary" in args
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "gopls"

    def test_generic_no_lsp_binary(self, tmp_path):
        args = _serena_args(tmp_path, ["python"])
        assert "--lsp-binary" not in args
        assert "serena" in args

    def test_cmake_takes_priority_over_rust(self, tmp_path):
        args = _serena_args(tmp_path, ["cmake", "rust"])
        idx = args.index("--lsp-binary")
        assert args[idx + 1] == "clangd"

    def test_project_root_always_present(self, tmp_path):
        for stacks in [["rust"], ["go"], ["python"], ["cmake"]]:
            args = _serena_args(tmp_path, stacks)
            assert "--project-root" in args
            idx = args.index("--project-root")
            assert args[idx + 1] == str(tmp_path)


# --------------------------------------------------------------------------
# Sección de prerrequisitos en el markdown
# --------------------------------------------------------------------------

class TestPrerequisitesSection:
    def test_rust_section_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        assert "rust-analyzer" in md
        assert "rustup component add rust-analyzer" in md

    def test_rust_section_mentions_cargo_fetch(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        assert "cargo fetch" in md

    def test_go_section_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        assert "gopls" in md
        assert "go install golang.org/x/tools/gopls@latest" in md

    def test_go_section_mentions_go_mod_download(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        assert "go mod download" in md

    def test_cmake_section_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["cmake"], cfg)
        assert "clangd" in md
        assert "compile_commands.json" in md

    def test_jvm_section_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["maven"], cfg)
        assert "jdtls" in md

    def test_generic_section_when_no_known_stack(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["python"], cfg)
        assert "Stack genérico" in md

    def test_no_generic_section_when_rust(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        assert "Stack genérico" not in md

    def test_no_generic_section_when_go(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        assert "Stack genérico" not in md


# --------------------------------------------------------------------------
# opencode.json en el markdown
# --------------------------------------------------------------------------

class TestOpencodeConfig:
    def _extract_json(self, md: str) -> dict:
        """Extrae el primer bloque ```json del markdown."""
        start = md.index("```json\n") + len("```json\n")
        end = md.index("\n```", start)
        return json.loads(md[start:end])

    def test_rust_serena_uses_rust_analyzer(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        data = self._extract_json(md)
        args = data["mcp"]["serena"]["args"]
        assert "--lsp-binary" in args
        assert args[args.index("--lsp-binary") + 1] == "rust-analyzer"

    def test_go_serena_uses_gopls(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        data = self._extract_json(md)
        args = data["mcp"]["serena"]["args"]
        assert "--lsp-binary" in args
        assert args[args.index("--lsp-binary") + 1] == "gopls"

    def test_model_uses_llamacpp_prefix(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        data = self._extract_json(md)
        assert data["model"].startswith("llamacpp/")

    def test_mcp_serena_enabled(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        data = self._extract_json(md)
        assert data["mcp"]["serena"]["enabled"] is True

    def test_plugin_field_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["rust"], cfg)
        data = self._extract_json(md)
        assert "opencode-ollama-toolcall-proxy" in data["plugin"]

    def test_instructions_field_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["maven"], cfg)
        data = self._extract_json(md)
        assert ".project-ai/notes.md" in data["instructions"]

    def test_providers_linux_mac_llamacpp(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        data = self._extract_json(md)
        assert "linux" in data["provider"]
        assert "mac" in data["provider"]
        assert "llamacpp" in data["provider"]

    def test_permission_field_present(self, tmp_path):
        cfg = _default_config()
        md = _generate(tmp_path, ["go"], cfg)
        data = self._extract_json(md)
        assert data["permission"]["edit"] == "ask"
        assert data["permission"]["bash"]["grep *"] == "allow"


# --------------------------------------------------------------------------
# setup_agent() — función principal
# --------------------------------------------------------------------------

class TestSetupAgentFunction:
    def test_writes_file(self, tmp_path):
        info = _make_info(["rust"])
        result = setup_agent(tmp_path, info=info)
        out = tmp_path / ".project-ai" / "setup-agent.md"
        assert out.exists()
        assert "rust-analyzer" in out.read_text()

    def test_no_write(self, tmp_path):
        info = _make_info(["go"])
        result = setup_agent(tmp_path, info=info, write=False)
        out = tmp_path / ".project-ai" / "setup-agent.md"
        assert not out.exists()
        assert "gopls" in result

    def test_returns_string(self, tmp_path):
        info = _make_info(["rust"])
        result = setup_agent(tmp_path, info=info, write=False)
        assert isinstance(result, str)
        assert len(result) > 100
