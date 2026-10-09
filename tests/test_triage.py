"""Tests para triage.py, llm.py y config.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_ai.config import Config
from project_ai.llm import LLMError, LLMResponse, _extract_json
from project_ai.model import ProjectInfo, StackDetection
from project_ai.triage import (
    RULES_DIR,
    _build_context,
    _find_project_root,
    _load_rules,
    _match_n0,
    _stack_matches,
    _trim_log,
    triage,
)


# --------------------------------------------------------------------------
# Fixtures de reglas inline
# --------------------------------------------------------------------------

_RULES_JDK = [
    {
        "id": "jdk-class-version",
        "stack": ["maven", "gradle"],
        "match": r"invalid target release: (\S+)",
        "cause": "JDK incorrecto",
        "fix": "Usa sdk use java <versión>",
    }
]

_RULES_STAR = [
    {
        "id": "port-in-use",
        "stack": ["*"],
        "match": r"Address already in use|EADDRINUSE",
        "cause": "Puerto ocupado",
        "fix": "lsof -i TCP:<puerto>",
    }
]

_RULES_ALL = _RULES_JDK + _RULES_STAR


def _log_file(tmp_path: Path, content: str) -> Path:
    (tmp_path / ".project-ai" / "logs").mkdir(parents=True)
    (tmp_path / ".project-ai" / "project.json").write_text('{"root":".","stacks":[]}')
    f = tmp_path / ".project-ai" / "logs" / "step-01.log"
    f.write_text(content, encoding="utf-8")
    return f


# --------------------------------------------------------------------------
# _trim_log
# --------------------------------------------------------------------------

class TestTrimLog:
    def test_finds_error_line(self):
        log = "info: compiling\nERROR: invalid target release: 17\nmore info\n"
        result = _trim_log(log)
        assert result.startswith("ERROR:")

    def test_removes_download_noise(self):
        log = "Downloading: foo.jar\nDownloaded: foo.jar\nERROR: failed\n"
        result = _trim_log(log)
        assert "Downloading" not in result
        assert "Downloaded" not in result
        assert "ERROR" in result

    def test_no_error_uses_tail(self):
        lines = [f"line {i}" for i in range(60)]
        log = "\n".join(lines)
        result = _trim_log(log)
        # debe tener como máximo 40 líneas y venir del final
        assert "line 59" in result
        assert "line 0" not in result

    def test_context_lines_respected(self):
        log = "ERROR: something\n" + "\n".join(f"  at StackFrame {i}" for i in range(50))
        result = _trim_log(log, context=10)
        assert len(result.splitlines()) <= 10

    def test_exception_line_detected(self):
        log = "INFO: starting\njava.lang.NullPointerException: msg\n  at Foo.bar(Foo.java:10)\n"
        result = _trim_log(log)
        assert "NullPointerException" in result

    def test_build_failure_detected(self):
        log = "compiling...\nBUILD FAILURE\n[INFO] ...\n"
        result = _trim_log(log)
        assert "BUILD FAILURE" in result


# --------------------------------------------------------------------------
# _stack_matches
# --------------------------------------------------------------------------

class TestStackMatches:
    def test_star_matches_any(self):
        assert _stack_matches(["*"], ["maven"])
        assert _stack_matches(["*"], [])

    def test_specific_match(self):
        assert _stack_matches(["maven", "gradle"], ["maven"])

    def test_no_overlap(self):
        assert not _stack_matches(["cmake"], ["maven"])

    def test_empty_project_stacks_no_match(self):
        assert not _stack_matches(["maven"], [])


# --------------------------------------------------------------------------
# _match_n0
# --------------------------------------------------------------------------

class TestMatchN0:
    def test_matches_correct_stack(self):
        log = "[ERROR] Fatal error compiling: invalid target release: 17"
        result = _match_n0(log, _RULES_JDK, ["maven"])
        assert result is not None
        assert result["id"] == "jdk-class-version"

    def test_no_match_wrong_stack(self):
        log = "[ERROR] Fatal error compiling: invalid target release: 17"
        result = _match_n0(log, _RULES_JDK, ["cmake"])
        assert result is None

    def test_star_rule_matches_any_stack(self):
        log = "Address already in use"
        result = _match_n0(log, _RULES_STAR, ["maven"])
        assert result is not None

    def test_star_rule_matches_empty_stack(self):
        log = "Address already in use"
        result = _match_n0(log, _RULES_STAR, [])
        assert result is not None

    def test_no_match_returns_none(self):
        log = "Everything went fine"
        result = _match_n0(log, _RULES_ALL, ["maven"])
        assert result is None

    def test_first_matching_rule_wins(self):
        rules = [
            {"id": "r1", "stack": ["*"], "match": "ERROR", "cause": "A", "fix": "a"},
            {"id": "r2", "stack": ["*"], "match": "ERROR", "cause": "B", "fix": "b"},
        ]
        result = _match_n0("ERROR: something", rules, [])
        assert result["id"] == "r1"


# --------------------------------------------------------------------------
# _load_rules
# --------------------------------------------------------------------------

class TestLoadRules:
    def test_loads_initial_toml(self):
        rules = _load_rules(RULES_DIR)
        assert len(rules) >= 13

    def test_all_rules_have_required_fields(self):
        rules = _load_rules(RULES_DIR)
        for r in rules:
            assert {"id", "stack", "match", "cause", "fix"} <= set(r)

    def test_empty_dir_returns_empty(self, tmp_path):
        assert _load_rules(tmp_path) == []

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        assert _load_rules(tmp_path / "nonexistent") == []

    def test_custom_rules_loaded(self, tmp_path):
        (tmp_path / "test.toml").write_text(
            '[[rule]]\nid="x"\nstack=["*"]\nmatch="foo"\ncause="c"\nfix="f"\n',
            encoding="utf-8",
        )
        rules = _load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["id"] == "x"


# --------------------------------------------------------------------------
# _find_project_root
# --------------------------------------------------------------------------

class TestFindProjectRoot:
    def test_finds_root_from_log(self, tmp_path):
        log = _log_file(tmp_path, "ERROR: something")
        root = _find_project_root(log)
        assert root == tmp_path

    def test_returns_none_when_no_project_json(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / "step-01.log"
        log.write_text("error")
        assert _find_project_root(log) is None


# --------------------------------------------------------------------------
# triage() N0
# --------------------------------------------------------------------------

class TestTriageN0:
    def test_n0_jdk_class_version(self, tmp_path):
        log = _log_file(
            tmp_path,
            "[ERROR] Fatal error compiling: invalid target release: 17\n"
            "To see the full stack trace of the errors, re-run Maven\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="maven", confidence=1.0))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "jdk-class-version"
        assert result.confidence == 1.0

    def test_n0_conan_missing_binary(self, tmp_path):
        log = _log_file(
            tmp_path,
            "ERROR: Missing prebuilt package for 'fmt/10.2.1'\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="conan", confidence=1.0))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "conan-missing-binary"

    def test_n0_port_in_use_any_stack(self, tmp_path):
        log = _log_file(
            tmp_path,
            "Web server failed to start. Port 8080 was already in use.\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "port-in-use"

    def test_n0_cmake_no_compiler(self, tmp_path):
        log = _log_file(
            tmp_path,
            "No CMAKE_CXX_COMPILER could be found.\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="cmake", confidence=1.0))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "cmake-no-compiler"

    def test_n0_db_connection_refused(self, tmp_path):
        log = _log_file(
            tmp_path,
            "org.postgresql.util.PSQLException: "
            "Connection to localhost:5432 refused.\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "db-connection-refused"

    def test_n0_pkix_star_stack(self, tmp_path):
        log = _log_file(
            tmp_path,
            "sun.security.validator.ValidatorException: "
            "PKIX path building failed\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="cmake", confidence=1.0))
        result = triage(log, info=info, write=False)
        assert result.level == "N0"
        assert result.rule_id == "pkix-certificates"

    def test_n0_wrong_stack_no_match(self, tmp_path):
        # jdk rule solo aplica a maven/gradle; con cmake no debe coincidir
        log = _log_file(
            tmp_path,
            "[ERROR] Fatal error compiling: invalid target release: 17\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="cmake", confidence=1.0))
        result = triage(log, info=info, dry_run=True, write=False)
        assert result.level == "N3"  # no match → N3 en dry_run


# --------------------------------------------------------------------------
# triage() N3 / dry_run
# --------------------------------------------------------------------------

class TestTriageN3:
    def test_dry_run_no_match_returns_n3(self, tmp_path):
        log = _log_file(tmp_path, "Something unexpected happened\n")
        result = triage(log, write=False, dry_run=True)
        assert result.level == "N3"

    def test_n3_has_nonempty_fix(self, tmp_path):
        log = _log_file(tmp_path, "Unknown error\n")
        result = triage(log, write=False, dry_run=True)
        assert result.fix


# --------------------------------------------------------------------------
# triage() con LLM mockeado
# --------------------------------------------------------------------------

class TestTriageLLM:
    def _mock_resp(self, confianza: float) -> MagicMock:
        m = MagicMock(spec=LLMResponse)
        m.causa = "problema de red"
        m.confianza = confianza
        m.comando = "ping localhost"
        m.explicacion = "No hay red disponible"
        return m

    def test_n1_high_confidence(self, tmp_path):
        log = _log_file(tmp_path, "Unknown network error\n")
        info = ProjectInfo(root=str(tmp_path))
        cfg = Config.default()
        with patch("project_ai.llm.chat", return_value=self._mock_resp(0.85)):
            result = triage(log, info=info, config=cfg, write=False)
        assert result.level == "N1"
        assert result.confidence == 0.85

    def test_n1_low_confidence_escalates_to_n2(self, tmp_path):
        log = _log_file(tmp_path, "Unknown error\n")
        info = ProjectInfo(root=str(tmp_path))
        cfg = Config.default()
        responses = [self._mock_resp(0.3), self._mock_resp(0.75)]
        with patch("project_ai.llm.chat", side_effect=responses):
            result = triage(log, info=info, config=cfg, write=False)
        assert result.level == "N2"

    def test_both_llm_fail_returns_n3(self, tmp_path):
        log = _log_file(tmp_path, "Unknown error\n")
        info = ProjectInfo(root=str(tmp_path))
        cfg = Config.default()
        with patch("project_ai.llm.chat", side_effect=LLMError("sin conexión")):
            result = triage(log, info=info, config=cfg, write=False)
        assert result.level == "N3"

    def test_both_llm_low_confidence_returns_n3(self, tmp_path):
        log = _log_file(tmp_path, "Unknown error\n")
        cfg = Config.default()
        with patch("project_ai.llm.chat", return_value=self._mock_resp(0.2)):
            result = triage(log, config=cfg, write=False)
        assert result.level == "N3"


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------

class TestJournal:
    def test_journal_written_on_n0(self, tmp_path):
        log = _log_file(
            tmp_path,
            "ERROR: Missing prebuilt package for 'fmt/10.2.1'\n",
        )
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="conan", confidence=1.0))
        triage(log, info=info, write=True)
        journal = tmp_path / ".project-ai" / "journal.md"
        assert journal.exists()
        content = journal.read_text(encoding="utf-8")
        assert "N0" in content
        assert "conan-missing-binary" in content

    def test_no_write_no_journal(self, tmp_path):
        log = _log_file(tmp_path, "Address already in use\n")
        triage(log, write=False)
        assert not (tmp_path / ".project-ai" / "journal.md").exists()

    def test_journal_appended_on_second_call(self, tmp_path):
        log = _log_file(tmp_path, "Address already in use\n")
        triage(log, write=True)
        triage(log, write=True)
        content = (tmp_path / ".project-ai" / "journal.md").read_text()
        assert content.count("## ") >= 2


# --------------------------------------------------------------------------
# _extract_json (llm.py)
# --------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        d = _extract_json('{"causa":"x","confianza":0.9,"comando":null,"explicacion":"y"}')
        assert d["causa"] == "x"
        assert d["confianza"] == 0.9

    def test_json_in_markdown_block(self):
        text = '```json\n{"causa":"a","confianza":0.8,"comando":"cmd","explicacion":"b"}\n```'
        d = _extract_json(text)
        assert d["causa"] == "a"

    def test_json_with_surrounding_text(self):
        text = 'Here is my answer: {"causa":"a","confianza":0.7,"comando":null,"explicacion":"b"}'
        d = _extract_json(text)
        assert d["confianza"] == 0.7

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            _extract_json("This is just text without any JSON")


# --------------------------------------------------------------------------
# LLMResponse.parse
# --------------------------------------------------------------------------

class TestLLMResponseParse:
    def test_full_response(self):
        raw = '{"causa":"JDK","confianza":0.9,"comando":"sdk use java 17","explicacion":"..."}'
        r = LLMResponse.parse(raw)
        assert r.causa == "JDK"
        assert r.confianza == 0.9
        assert r.comando == "sdk use java 17"

    def test_null_comando(self):
        raw = '{"causa":"X","confianza":0.5,"comando":null,"explicacion":"Y"}'
        r = LLMResponse.parse(raw)
        assert r.comando is None

    def test_missing_fields_use_defaults(self):
        r = LLMResponse.parse('{"causa":"X"}')
        assert r.confianza == 0.0
        assert r.comando is None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

class TestConfig:
    def test_default_n1_url(self):
        cfg = Config.default()
        assert cfg.n1.url == "http://localhost:11434"

    def test_default_n2_model(self):
        cfg = Config.default()
        assert "coder" in cfg.n2.model

    def test_load_from_toml(self, tmp_path):
        toml = (
            '[n1]\nurl = "http://n1:11434"\nmodel = "phi4"\ntimeout = 30\nnum_ctx = 2048\n'
            '[n2]\nurl = "http://n2:11434"\nmodel = "deepseek"\ntimeout = 90\nnum_ctx = 8192\n'
        )
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(toml, encoding="utf-8")
        cfg = Config.load(cfg_file)
        assert cfg.n1.url == "http://n1:11434"
        assert cfg.n1.model == "phi4"
        assert cfg.n2.model == "deepseek"

    def test_partial_toml_uses_defaults(self, tmp_path):
        toml = '[n1]\nmodel = "custom"\n'
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(toml, encoding="utf-8")
        cfg = Config.load(cfg_file)
        assert cfg.n1.model == "custom"
        assert cfg.n1.url == "http://localhost:11434"  # default

    def test_from_project_no_file_returns_default(self, tmp_path):
        cfg = Config.from_project(tmp_path)
        assert isinstance(cfg, Config)
        assert cfg.n1.url == "http://localhost:11434"

    def test_from_project_reads_file(self, tmp_path):
        (tmp_path / ".project-ai").mkdir()
        (tmp_path / ".project-ai" / "config.toml").write_text(
            '[n1]\nmodel = "local"\n', encoding="utf-8"
        )
        cfg = Config.from_project(tmp_path)
        assert cfg.n1.model == "local"


# --------------------------------------------------------------------------
# _build_context
# --------------------------------------------------------------------------

class TestBuildContext:
    def test_no_info(self):
        ctx = _build_context(None)
        assert "sin contexto" in ctx

    def test_with_stacks(self):
        info = ProjectInfo(root="/tmp")
        info.stacks.append(StackDetection(adapter="maven", confidence=1.0))
        ctx = _build_context(info)
        assert "maven" in ctx


# --------------------------------------------------------------------------
# CLI integration
# --------------------------------------------------------------------------

def test_triage_cli_n0(tmp_path):
    log = _log_file(tmp_path, "Address already in use\n")
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "triage", str(log), "--dry-run",
         "--no-write"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "N0" in r.stdout

def test_triage_cli_n3(tmp_path):
    log = _log_file(tmp_path, "Something completely unrecognized xyzzy\n")
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "triage", str(log), "--dry-run",
         "--no-write"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "N3" in r.stdout
