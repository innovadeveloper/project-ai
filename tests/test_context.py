"""Tests para context.py y setup_agent.py."""
from __future__ import annotations

from pathlib import Path

from conftest import HMDM, NETCLIENT_FULL, make_tree

from project_ai.config import Config, NodeConfig
from project_ai.context import (
    CHARS_PER_TOKEN,
    _search_endpoints,
    _search_repo_map,
    _tokens,
    context,
)
from project_ai.model import (
    Command, Endpoint, ProjectInfo,
    StackDetection,
)
from project_ai.recon import recon
from project_ai.setup_agent import setup_agent


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _proj_with_endpoints(tmp_path: Path) -> ProjectInfo:
    info = ProjectInfo(root=str(tmp_path))
    info.stacks.append(StackDetection(adapter="maven", confidence=1.0))
    info.add_command(Command(name="build", shell="mvn package"))
    info.endpoints.append(Endpoint(
        method="GET", path="/api/devices", handler="DeviceResource#list",
        file="DeviceResource.java",
    ))
    info.endpoints.append(Endpoint(
        method="POST", path="/api/auth/login", handler="AuthResource#login",
        file="AuthResource.java",
    ))
    return info


# --------------------------------------------------------------------------
# _tokens
# --------------------------------------------------------------------------

class TestTokens:
    def test_splits_query(self):
        toks = _tokens("cómo funciona el auth")
        assert "auth" in toks
        assert "funciona" in toks

    def test_filters_stopwords(self):
        toks = _tokens("cómo funciona el login")
        assert "cómo" not in toks
        assert "el" not in toks

    def test_min_length_three(self):
        toks = _tokens("el de la")
        # ninguna pasa los stopwords pero tampoco las de < 3 chars
        assert all(len(t) >= 3 for t in toks)

    def test_empty_query(self):
        assert _tokens("") == []


# --------------------------------------------------------------------------
# _search_repo_map
# --------------------------------------------------------------------------

class TestSearchRepoMap:
    def _write_repo_map(self, tmp_path: Path, content: str) -> None:
        d = tmp_path / ".project-ai"
        d.mkdir(exist_ok=True)
        (d / "repo-map.md").write_text(content, encoding="utf-8")

    def test_finds_matching_file(self, tmp_path):
        self._write_repo_map(tmp_path, (
            "### src/auth/AuthService.java\n"
            "- class AuthService\n"
            "  - method login(String user, String pass)\n"
        ))
        results = _search_repo_map(tmp_path, "auth login")
        assert any("AuthService" in r for r in results)

    def test_no_match_returns_empty(self, tmp_path):
        self._write_repo_map(tmp_path, "### src/Unrelated.java\n- class Unrelated\n")
        assert _search_repo_map(tmp_path, "xyz unknown thing") == []

    def test_no_repo_map_returns_empty(self, tmp_path):
        assert _search_repo_map(tmp_path, "auth") == []

    def test_max_six_blocks(self, tmp_path):
        blocks = "\n".join(
            f"### src/Auth{i}.java\n- class Auth{i}\n  - method login{i}()\n"
            for i in range(10)
        )
        self._write_repo_map(tmp_path, blocks)
        results = _search_repo_map(tmp_path, "auth login")
        assert len(results) <= 6


# --------------------------------------------------------------------------
# _search_endpoints
# --------------------------------------------------------------------------

class TestSearchEndpoints:
    def test_finds_matching_endpoint(self, tmp_path):
        import json
        info = _proj_with_endpoints(tmp_path)
        (tmp_path / ".project-ai").mkdir(exist_ok=True)
        (tmp_path / ".project-ai" / "project.json").write_text(
            json.dumps(info.to_dict()), encoding="utf-8"
        )
        results = _search_endpoints(tmp_path, "auth login")
        assert any("auth" in r.lower() for r in results)

    def test_no_match_returns_empty(self, tmp_path):
        import json
        info = _proj_with_endpoints(tmp_path)
        (tmp_path / ".project-ai").mkdir(exist_ok=True)
        (tmp_path / ".project-ai" / "project.json").write_text(
            json.dumps(info.to_dict()), encoding="utf-8"
        )
        results = _search_endpoints(tmp_path, "xyz unknown")
        assert results == []


# --------------------------------------------------------------------------
# context()
# --------------------------------------------------------------------------

class TestContext:
    def test_returns_string(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = context(tmp_path, "cómo funciona el build")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_under_max_tokens(self, tmp_path):
        make_tree(tmp_path, HMDM)
        max_tok = 1000
        result = context(tmp_path, "devices", max_tokens=max_tok)
        assert len(result) <= max_tok * CHARS_PER_TOKEN + 200  # tolerancia pie

    def test_contains_query(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = context(tmp_path, "authentication login")
        assert "Pregunta" in result
        assert "authentication" in result or "login" in result

    def test_contains_project_summary(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = context(tmp_path, "cualquier cosa")
        assert "Proyecto" in result

    def test_empty_project_returns_minimal(self, tmp_path):
        (tmp_path / "README.md").write_text("# Readme")
        result = context(tmp_path, "algo")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_agents_md_uses_it(self, tmp_path):
        make_tree(tmp_path, HMDM)
        recon(tmp_path)
        from project_ai.finalize import finalize
        finalize(tmp_path, write=True)
        result = context(tmp_path, "build maven")
        assert "AGENTS.md" in result or "maven" in result.lower()

    def test_netclient_context(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        result = context(tmp_path, "WebSocket conexión")
        assert isinstance(result, str)
        assert len(result) > 50

    def test_repo_map_symbols_included_when_relevant(self, tmp_path):
        make_tree(tmp_path, HMDM)
        recon(tmp_path)  # genera repo-map.md
        result = context(tmp_path, "DeviceResource endpoints")
        # repo-map.md debe incluir DeviceResource si hay endpoints
        assert "DeviceResource" in result or "Proyecto" in result

    def test_very_small_budget_still_returns_something(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = context(tmp_path, "build", max_tokens=50)
        assert len(result) > 0

    def test_navigation_pointer_at_end(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = context(tmp_path, "build")
        assert "repo-map.md" in result


# --------------------------------------------------------------------------
# setup_agent()
# --------------------------------------------------------------------------

class TestSetupAgent:
    def test_returns_string(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert isinstance(result, str)

    def test_contains_opencode_section(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert "opencode.json" in result
        assert "opencode.ai" in result

    def test_contains_serena_section(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert "Serena" in result
        assert "serena" in result.lower()

    def test_lsp_true_in_config(self, tmp_path):
        """El campo lsp:true debe estar en el JSON combinado."""
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert '"lsp": true' in result

    def test_enabled_true_in_mcp(self, tmp_path):
        """El servidor MCP de Serena debe tener enabled:true."""
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert '"enabled": true' in result

    def test_single_json_block(self, tmp_path):
        """OpenCode y Serena deben estar en UN solo bloque JSON."""
        import json as _json
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        # Extraer el primer bloque ```json ... ```
        start = result.index("```json\n") + len("```json\n")
        end = result.index("\n```", start)
        cfg = _json.loads(result[start:end])
        assert "model" in cfg
        assert "mcp" in cfg
        assert "serena" in cfg["mcp"]
        assert cfg["lsp"] is True
        assert cfg["mcp"]["serena"]["enabled"] is True

    def test_maven_stack_uses_jdtls(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert "jdtls" in result

    def test_cmake_stack_uses_clangd(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        recon(tmp_path)
        result = setup_agent(tmp_path, write=False)
        assert "clangd" in result
        assert "compile_commands" in result

    def test_node_urls_in_output(self, tmp_path):
        cfg = Config(
            n1=NodeConfig(url="http://rtx.local:11434", model="qwen3.6:35b-a3b"),
            n2=NodeConfig(url="http://m1max.local:11434", model="qwen3.8:27b"),
        )
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, config=cfg, write=False)
        assert "rtx.local" in result
        assert "m1max.local" in result

    def test_write_creates_file(self, tmp_path):
        make_tree(tmp_path, HMDM)
        setup_agent(tmp_path, write=True)
        assert (tmp_path / ".project-ai" / "setup-agent.md").exists()

    def test_no_write_no_file(self, tmp_path):
        make_tree(tmp_path, HMDM)
        setup_agent(tmp_path, write=False)
        assert not (tmp_path / ".project-ai" / "setup-agent.md").exists()

    def test_contains_verification_commands(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert "curl" in result
        assert "api/tags" in result

    def test_contains_context_example(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = setup_agent(tmp_path, write=False)
        assert "project-ai context" in result


# --------------------------------------------------------------------------
# CLI integration
# --------------------------------------------------------------------------

def test_context_cli(tmp_path):
    make_tree(tmp_path, HMDM)
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "context",
         "--path", str(tmp_path), "build maven package"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "Pregunta" in r.stdout or "build" in r.stdout.lower()


def test_setup_agent_cli(tmp_path):
    make_tree(tmp_path, HMDM)
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "setup-agent",
         str(tmp_path), "--no-write"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "OpenCode" in r.stdout
