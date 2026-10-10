"""Tests para runbook.py."""
from __future__ import annotations

from unittest.mock import MagicMock

from conftest import HMDM, NETCLIENT_FULL, make_tree

from project_ai.model import Command, Fact, ProjectInfo, SourcePriority, Status
from project_ai.runbook import (
    RUNBOOK_FILE,
    RunStep,
    RunbookResult,
    _collect_setup_items,
    _make_cmd_steps,
    _make_service_steps,
    _run_success_hint,
    _with_tee,
    runbook,
)


# --------------------------------------------------------------------------
# Helpers de fixture
# --------------------------------------------------------------------------

def _info_with_cmds(**cmds: str) -> ProjectInfo:
    """Crea un ProjectInfo mínimo con los comandos dados (name → shell)."""
    info = ProjectInfo(root="/tmp/proj")
    for name, shell in cmds.items():
        info.add_command(Command(name=name, shell=shell))
    return info


def _make_check(key: str, status: str, needed: str | None = None,
                found: str | None = None, install_cmd: str | None = None):
    m = MagicMock()
    m.key = key
    m.status = status
    m.needed = needed
    m.found = found
    m.install_cmd = install_cmd
    return m


def _make_doctor(checks):
    m = MagicMock()
    m.checks = checks
    return m


# --------------------------------------------------------------------------
# _with_tee
# --------------------------------------------------------------------------

class TestWithTee:
    def test_simple_command(self):
        result = _with_tee("mvn package", ".project-ai/logs/step-01.log")
        assert "mvn package" in result
        assert "tee .project-ai/logs/step-01.log" in result
        assert "2>&1" in result

    def test_cmd_with_pipe_wrapped_in_subshell(self):
        result = _with_tee("cmd | grep x", ".project-ai/logs/step-01.log")
        assert result.startswith("(")
        assert "tee" in result

    def test_cmd_with_redirect_wrapped_in_subshell(self):
        result = _with_tee("cmd > file", ".project-ai/logs/step-01.log")
        assert result.startswith("(")

    def test_no_double_tee(self):
        result = _with_tee("mvn package", ".project-ai/logs/step-01.log")
        assert result.count("tee") == 1


# --------------------------------------------------------------------------
# _collect_setup_items
# --------------------------------------------------------------------------

class TestCollectSetupItems:
    def test_none_doctor_returns_empty(self):
        assert _collect_setup_items(None) == []

    def test_ok_checks_ignored(self):
        dr = _make_doctor([_make_check("jdk", "ok", "17", "17.0.9")])
        assert _collect_setup_items(dr) == []

    def test_missing_check_included(self):
        dr = _make_doctor([_make_check("maven", "missing", install_cmd="brew install maven")])
        items = _collect_setup_items(dr)
        assert len(items) == 1
        assert "maven" in items[0]
        assert "brew install maven" in items[0]

    def test_wrong_version_check_included(self):
        dr = _make_doctor([
            _make_check("jdk", "wrong_version", needed="17", found="8",
                        install_cmd="sdk install java 17.0.9-ms"),
        ])
        items = _collect_setup_items(dr)
        assert len(items) == 1
        assert "17" in items[0]
        assert "8" in items[0]

    def test_multiple_failures(self):
        dr = _make_doctor([
            _make_check("maven", "missing"),
            _make_check("jdk", "wrong_version", needed="17", found="8"),
        ])
        assert len(_collect_setup_items(dr)) == 2


# --------------------------------------------------------------------------
# _make_cmd_steps
# --------------------------------------------------------------------------

class TestMakeCmdSteps:
    def test_canonical_order(self):
        info = _info_with_cmds(build="mvn package", deps="mvn dependency:go-offline",
                               test="mvn test")
        steps = _make_cmd_steps(info)
        kinds = [s.kind for s in steps]
        assert kinds.index("deps") < kinds.index("build")
        assert kinds.index("build") < kinds.index("test")

    def test_cmake_order(self):
        info = _info_with_cmds(
            configure="cmake --preset conan-debug",
            build="cmake --build --preset conan-debug",
            deps="conan install .",
        )
        steps = _make_cmd_steps(info)
        kinds = [s.kind for s in steps]
        assert kinds.index("deps") < kinds.index("configure")
        assert kinds.index("configure") < kinds.index("build")

    def test_custom_kind_included_after_canonical(self):
        info = _info_with_cmds(build="mvn package", build_app="mvn -pl server package")
        steps = _make_cmd_steps(info)
        kinds = [s.kind for s in steps]
        assert "build" in kinds
        assert "build_app" in kinds
        assert kinds.index("build") < kinds.index("build_app")

    def test_no_commands_returns_empty(self):
        info = ProjectInfo(root="/tmp/proj")
        assert _make_cmd_steps(info) == []

    def test_shell_preserved(self):
        info = _info_with_cmds(build="mvn -DskipTests package")
        steps = _make_cmd_steps(info)
        assert steps[0].shell == "mvn -DskipTests package"

    def test_ide_hint_preserved(self):
        info = ProjectInfo(root="/tmp/proj")
        info.add_command(Command(
            name="build", shell="mvn package",
            ide_hint='IntelliJ → Run "Build"',
        ))
        steps = _make_cmd_steps(info)
        assert steps[0].ide_hint == 'IntelliJ → Run "Build"'


# --------------------------------------------------------------------------
# _make_service_steps
# --------------------------------------------------------------------------

class TestMakeServiceSteps:
    def _info_with_service(self, kind: str) -> ProjectInfo:
        info = ProjectInfo(root="/tmp/proj")
        fact = Fact(value="*", priority=SourcePriority.BUILD, status=Status.INFERRED)
        info.add_service(kind, fact)
        return info

    def test_no_services_returns_empty(self):
        info = ProjectInfo(root="/tmp/proj")
        assert _make_service_steps(info, "macos") == []

    def test_known_service_macos(self):
        info = self._info_with_service("postgresql")
        steps = _make_service_steps(info, "macos")
        assert len(steps) == 1
        assert "brew install postgresql" in steps[0].shell
        assert steps[0].kind == "service"

    def test_known_service_linux(self):
        info = self._info_with_service("redis")
        steps = _make_service_steps(info, "linux")
        assert "apt-get" in steps[0].shell

    def test_with_compose_uses_docker(self):
        info = self._info_with_service("postgresql")
        from project_ai.model import Evidence
        info.add_list_fact(
            "hints.compose_files", "docker-compose.yml",
            priority=SourcePriority.CI,
            evidence=Evidence(file="docker-compose.yml"),
        )
        steps = _make_service_steps(info, "macos")
        assert "docker compose up -d" in steps[0].shell
        assert "postgresql" in steps[0].shell

    def test_unknown_service_has_fallback(self):
        info = self._info_with_service("cassandra")
        steps = _make_service_steps(info, "macos")
        assert len(steps) == 1
        assert steps[0].shell is not None


# --------------------------------------------------------------------------
# runbook()
# --------------------------------------------------------------------------

class TestRunbook:
    def test_returns_result(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        assert isinstance(result, RunbookResult)

    def test_hmdm_has_build_step(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        kinds = [s.kind for s in result.steps]
        assert "build" in kinds

    def test_hmdm_order_deps_before_build(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        kinds = [s.kind for s in result.steps]
        assert kinds.index("deps") < kinds.index("build")

    def test_cmake_order_deps_configure_build(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        result = runbook(tmp_path, write=False)
        kinds = [s.kind for s in result.steps]
        assert kinds.index("deps") < kinds.index("configure")
        assert kinds.index("configure") < kinds.index("build")

    def test_steps_have_tee(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        cmd_steps = [s for s in result.steps if s.shell]
        assert cmd_steps, "debe haber pasos con shell"
        for step in cmd_steps:
            assert "tee" in step.shell, f"paso '{step.kind}' sin tee: {step.shell}"

    def test_step_numbers_sequential(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        nums = [s.number for s in result.steps]
        assert nums == list(range(len(nums)))

    def test_on_fail_references_log(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = runbook(tmp_path, write=False)
        for step in result.steps:
            if step.shell:
                assert step.on_fail is not None
                assert "triage" in step.on_fail

    def test_writes_file(self, tmp_path):
        make_tree(tmp_path, HMDM)
        runbook(tmp_path, write=True)
        assert (tmp_path / ".project-ai" / RUNBOOK_FILE).exists()

    def test_no_write_no_file(self, tmp_path):
        make_tree(tmp_path, HMDM)
        runbook(tmp_path, write=False)
        assert not (tmp_path / ".project-ai" / RUNBOOK_FILE).exists()

    def test_doctor_setup_step_added(self, tmp_path):
        make_tree(tmp_path, HMDM)
        dr = _make_doctor([_make_check("maven", "missing", install_cmd="brew install maven")])
        result = runbook(tmp_path, doctor_report=dr, write=False)
        setup = [s for s in result.steps if s.kind == "setup"]
        assert len(setup) == 1
        assert any("maven" in item for item in setup[0].items)

    def test_no_failing_checks_no_setup_step(self, tmp_path):
        make_tree(tmp_path, HMDM)
        dr = _make_doctor([_make_check("maven", "ok", "3.9", "3.9.1")])
        result = runbook(tmp_path, doctor_report=dr, write=False)
        assert not any(s.kind == "setup" for s in result.steps)

    def test_setup_step_is_number_zero(self, tmp_path):
        make_tree(tmp_path, HMDM)
        dr = _make_doctor([_make_check("jdk", "missing")])
        result = runbook(tmp_path, doctor_report=dr, write=False)
        setup = next(s for s in result.steps if s.kind == "setup")
        assert setup.number == 0

    def test_empty_project(self, tmp_path):
        (tmp_path / "README.md").write_text("# Readme")
        result = runbook(tmp_path, write=False)
        assert isinstance(result, RunbookResult)

    def test_ok_false_when_setup_step(self, tmp_path):
        make_tree(tmp_path, HMDM)
        dr = _make_doctor([_make_check("maven", "missing")])
        result = runbook(tmp_path, doctor_report=dr, write=False)
        assert result.ok is False

    def test_ok_true_when_no_issues(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = ProjectInfo(root=str(tmp_path))
        info.add_command(Command(name="build", shell="mvn package"))
        result = runbook(tmp_path, info=info, write=False)
        assert result.ok is True


# --------------------------------------------------------------------------
# RunbookResult.to_md
# --------------------------------------------------------------------------

class TestToMd:
    def _simple_result(self) -> RunbookResult:
        steps = [
            RunStep(number=0, kind="setup", title="Preparación",
                    items=["instalar jdk"]),
            RunStep(number=1, kind="build", title="Compilar",
                    shell="mvn package 2>&1 | tee .project-ai/logs/step-01.log",
                    ide_hint='IntelliJ → "Run"',
                    success_if="BUILD SUCCESS",
                    on_fail="project-ai triage ..."),
        ]
        return RunbookResult(root="/tmp", steps=steps)

    def test_contains_runbook_heading(self):
        assert "# RUNBOOK" in self._simple_result().to_md()

    def test_contains_step_titles(self):
        md = self._simple_result().to_md()
        assert "Preparación" in md
        assert "Compilar" in md

    def test_contains_shell_command(self):
        assert "mvn package" in self._simple_result().to_md()

    def test_contains_ide_hint(self):
        assert 'IntelliJ' in self._simple_result().to_md()

    def test_contains_success_if(self):
        assert "BUILD SUCCESS" in self._simple_result().to_md()

    def test_empty_steps_produces_minimal_md(self):
        result = RunbookResult(root="/tmp", steps=[])
        md = result.to_md()
        assert "# RUNBOOK" in md
        assert "recon" in md

    def test_step_numbers_in_headings(self):
        md = self._simple_result().to_md()
        assert "Paso 0" in md
        assert "Paso 1" in md

    def test_cwd_hint_shown(self):
        step = RunStep(number=1, kind="build", title="Compilar",
                       shell="mvn package", cwd="server")
        result = RunbookResult(root="/tmp", steps=[step])
        assert "server" in result.to_md()


# --------------------------------------------------------------------------
# CLI integration
# --------------------------------------------------------------------------

def test_runbook_cli(tmp_path):
    """CLI project-ai runbook crea RUNBOOK.md."""
    make_tree(tmp_path, HMDM)
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "runbook", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode in (0, 1)  # 0=ok, 1=hay warnings
    assert "# RUNBOOK" in r.stdout
    assert (tmp_path / ".project-ai" / RUNBOOK_FILE).exists()


# --------------------------------------------------------------------------
# spring.port → success_hint del paso run
# --------------------------------------------------------------------------

def _info_spring(port: str, ctx: str | None = None) -> ProjectInfo:
    info = ProjectInfo(root="/fake")
    info.set_fact("spring.port", Fact(port, SourcePriority.EXPLICIT, Status.INFERRED))
    if ctx:
        info.set_fact("spring.context_path", Fact(ctx, SourcePriority.EXPLICIT, Status.INFERRED))
    info.add_command(Command(name="run", shell="mvn spring-boot:run", success_hint="Started"))
    return info


def test_run_success_hint_with_port():
    info = _info_spring("9090")
    hint = _run_success_hint(info)
    assert hint is not None
    assert "9090" in hint
    assert "curl" in hint


def test_run_success_hint_with_port_and_context():
    info = _info_spring("9090", "/inventory")
    hint = _run_success_hint(info)
    assert "/inventory" in hint
    assert "9090" in hint


def test_run_success_hint_no_port():
    info = ProjectInfo(root="/fake")
    assert _run_success_hint(info) is None


def test_make_cmd_steps_uses_spring_port():
    info = _info_spring("8081", "/api/v1")
    steps = _make_cmd_steps(info)
    run_step = next(s for s in steps if s.kind == "run")
    assert "8081" in (run_step.success_if or "")
    assert "/api/v1" in (run_step.success_if or "")


def test_make_cmd_steps_keeps_original_hint_without_port():
    info = ProjectInfo(root="/fake")
    info.add_command(Command(name="run", shell="cargo run", success_hint="listening on"))
    steps = _make_cmd_steps(info)
    run_step = next(s for s in steps if s.kind == "run")
    assert run_step.success_if == "listening on"


# --------------------------------------------------------------------------
# config.required_env → ítem de setup
# --------------------------------------------------------------------------

def test_setup_items_required_env():
    info = ProjectInfo(root="/fake")
    info.set_fact("config.required_env",
                  Fact(["DB_USER", "DB_PASS", "API_KEY"], SourcePriority.EXPLICIT, Status.INFERRED))
    items = _collect_setup_items(None, info)
    assert len(items) == 1
    assert "DB_USER" in items[0]
    assert "DB_PASS" in items[0]


def test_setup_items_no_env_without_fact():
    info = ProjectInfo(root="/fake")
    items = _collect_setup_items(None, info)
    assert items == []


def test_setup_items_combined_doctor_and_env():
    info = ProjectInfo(root="/fake")
    info.set_fact("config.required_env",
                  Fact(["SECRET"], SourcePriority.EXPLICIT, Status.INFERRED))

    mock_check = MagicMock()
    mock_check.status = "missing"
    mock_check.key = "go"
    mock_check.needed = "1.21"
    mock_check.found = None
    mock_check.install_cmd = "brew install go"

    mock_report = MagicMock()
    mock_report.checks = [mock_check]

    items = _collect_setup_items(mock_report, info)
    assert len(items) == 2
    keys = " ".join(items)
    assert "go" in keys
    assert "SECRET" in keys
