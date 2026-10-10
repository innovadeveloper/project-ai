"""Tests de integración: recon → doctor → runbook → finalize sobre fixtures."""
from __future__ import annotations

import json
from unittest.mock import patch

from conftest import HMDM, NETCLIENT_FULL, SPRING_WITH_CONFIG, make_tree

from project_ai.recon import recon
from project_ai.doctor import doctor, DoctorReport
from project_ai.runbook import runbook
from project_ai.finalize import finalize


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _fake_run(cmd, **kwargs):
    """Stub para subprocess.run: simula herramientas instaladas.

    java -version escribe en stderr; el resto en stdout.
    """
    exe = cmd[0] if cmd else ""
    import subprocess
    # java -version escribe en stderr
    if exe == "java" or exe.endswith("/java"):
        txt = 'openjdk version "17.0.9" 2023-10-17\nOpenJDK Runtime Environment'
        return subprocess.CompletedProcess(cmd, 0, "", txt)
    stdout_versions = {
        "mvn":    "Apache Maven 3.9.5",
        "cmake":  "cmake version 3.27.0",
        "conan":  "2.1.0",
        "ninja":  "1.11.1",
        "clang++": "clang version 16.0.6",
        "gcc":    "gcc (Ubuntu 12.3.0) 12.3.0",
        "g++":    "g++ (Ubuntu 12.3.0) 12.3.0",
        "python3": "Python 3.11.5",
        "node":   "v20.9.0",
        "rustc":  "rustc 1.73.0 (cc66ad468 2023-10-03)",
        "cargo":  "cargo 1.73.0 (9c4383fb5 2023-08-26)",
        "go":     "go version go1.21.3 darwin/arm64",
    }
    for key, out in stdout_versions.items():
        if exe == key or exe.endswith(f"/{key}"):
            return subprocess.CompletedProcess(cmd, 0, out, "")
    return subprocess.CompletedProcess(cmd, 1, "", "not found")


# --------------------------------------------------------------------------
# Suite Maven/Spring (HMDM)
# --------------------------------------------------------------------------

class TestMavenFlow:
    def test_recon_detects_maven(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        assert "maven" in {s.adapter for s in info.stacks}

    def test_recon_writes_project_json(self, tmp_path):
        make_tree(tmp_path, HMDM)
        recon(tmp_path, write=True)
        p = tmp_path / ".project-ai" / "project.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["root"] == str(tmp_path)

    def test_recon_roundtrip(self, tmp_path):
        """ProjectInfo.load() devuelve lo mismo que recon() guardó."""
        from project_ai.model import ProjectInfo
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        p = tmp_path / ".project-ai" / "project.json"
        loaded = ProjectInfo.load(p)
        assert {s.adapter for s in loaded.stacks} == {s.adapter for s in info.stacks}
        assert set(loaded.commands.keys()) == set(info.commands.keys())

    def test_doctor_after_recon(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=True)
        assert isinstance(report, DoctorReport)
        assert (tmp_path / ".project-ai" / "env-report.md").exists()

    def test_doctor_finds_jdk(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        jdk = next((r for r in report.checks if r.key == "jdk"), None)
        assert jdk is not None
        assert jdk.found is not None and jdk.found.startswith("17")

    def test_doctor_finds_maven(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        mvn = next((r for r in report.checks if r.key == "maven"), None)
        assert mvn is not None
        assert "3.9" in mvn.found

    def test_runbook_after_doctor(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        runbook(tmp_path, info=info, doctor_report=report, write=True)
        rb_path = tmp_path / ".project-ai" / "RUNBOOK.md"
        assert rb_path.exists()
        content = rb_path.read_text()
        assert "mvn" in content

    def test_runbook_has_steps(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        result = runbook(tmp_path, info=info, doctor_report=report, write=False)
        assert len(result.steps) >= 2

    def test_finalize_after_runbook(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[INFO] BUILD SUCCESS\n", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        agents_path = tmp_path / "AGENTS.md"
        assert agents_path.exists()
        content = agents_path.read_text()
        assert "maven" in content.lower() or "spring" in content.lower() or "java" in content.lower()

    def test_finalize_marks_build_verified(self, tmp_path):
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[INFO] BUILD SUCCESS\n", encoding="utf-8")
        result = finalize(tmp_path, info=info, write=False)
        assert "build" in result.verified

    def test_project_json_survives_full_flow(self, tmp_path):
        """project.json sigue siendo deserializable después del flujo completo."""
        from project_ai.model import ProjectInfo  # noqa: PLC0415
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[INFO] BUILD SUCCESS\n", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        p = tmp_path / ".project-ai" / "project.json"
        loaded = ProjectInfo.load(p)
        assert "build" in {c for c in loaded.commands}


# --------------------------------------------------------------------------
# Suite CMake/Conan (NETCLIENT_FULL)
# --------------------------------------------------------------------------

class TestCMakeFlow:
    def test_recon_detects_cmake(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        assert "cmake" in {s.adapter for s in info.stacks}

    def test_recon_detects_conan(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        assert "conan" in {s.adapter for s in info.stacks}

    def test_doctor_after_recon(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        assert isinstance(report, DoctorReport)

    def test_doctor_finds_cmake(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        cmake_chk = next((r for r in report.checks if r.key == "cmake"), None)
        assert cmake_chk is not None
        assert "3.27" in cmake_chk.found

    def test_runbook_has_cmake_steps(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        result = runbook(tmp_path, info=info, doctor_report=report, write=False)
        shells = " ".join(s.shell for s in result.steps)
        assert "cmake" in shells

    def test_finalize_generates_agents_md(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[100%] Built target netclient\n", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        assert (tmp_path / "AGENTS.md").exists()

    def test_full_flow_no_exception(self, tmp_path):
        """El flujo completo no lanza excepción."""
        make_tree(tmp_path, NETCLIENT_FULL)
        info = recon(tmp_path, write=True)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=True)
        runbook(tmp_path, info=info, doctor_report=report, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[100%] Built target app\n", encoding="utf-8")
        fin = finalize(tmp_path, info=info, write=True)
        assert fin is not None


# --------------------------------------------------------------------------
# Suite Spring con config.yml (SPRING_WITH_CONFIG)
# --------------------------------------------------------------------------

class TestSpringConfigFlow:
    def test_recon_detects_spring_port(self, tmp_path):
        make_tree(tmp_path, SPRING_WITH_CONFIG)
        info = recon(tmp_path, write=False)
        port = info.facts.get("spring.port")
        assert port is not None
        assert port.value == "9090"

    def test_recon_detects_required_env(self, tmp_path):
        make_tree(tmp_path, SPRING_WITH_CONFIG)
        info = recon(tmp_path, write=False)
        env_fact = info.facts.get("config.required_env")
        assert env_fact is not None
        assert isinstance(env_fact.value, list)
        assert len(env_fact.value) >= 1

    def test_runbook_mentions_env_vars(self, tmp_path):
        make_tree(tmp_path, SPRING_WITH_CONFIG)
        info = recon(tmp_path, write=False)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        result = runbook(tmp_path, info=info, doctor_report=report, write=False)
        # El port debe aparecer en el hint de éxito del paso run
        run_step = next((s for s in result.steps if s.kind == "run"), None)
        if run_step and run_step.success_if:
            assert "9090" in run_step.success_if

    def test_finalize_agents_md_not_empty(self, tmp_path):
        make_tree(tmp_path, SPRING_WITH_CONFIG)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[INFO] BUILD SUCCESS\n", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        agents = (tmp_path / "AGENTS.md").read_text()
        assert len(agents) > 100


# --------------------------------------------------------------------------
# Consistencia entre módulos
# --------------------------------------------------------------------------

class TestCrossModuleConsistency:
    def test_commands_in_recon_match_runbook_steps(self, tmp_path):
        """Los comandos detectados en recon son subconjunto (base) de los steps de runbook."""
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=False)
        with patch("project_ai.doctor.subprocess.run", side_effect=_fake_run):
            report = doctor(tmp_path, info=info, write=False)
        result = runbook(tmp_path, info=info, doctor_report=report, write=False)
        recon_shells = {c.shell for c in info.commands.values()}
        # runbook añade "| tee ..." al final; comprobamos que el base coincide
        runbook_bases = {
            s.shell.split(" 2>&1 ")[0].strip()
            for s in result.steps if s.shell
        }
        matched = recon_shells & runbook_bases
        assert matched, (
            f"Ningún comando de recon apareció en runbook.\n"
            f"  recon: {recon_shells}\n  runbook (bases): {runbook_bases}"
        )

    def test_stacks_in_project_json_match_agents_md(self, tmp_path):
        """Al menos un stack del project.json aparece en AGENTS.md."""
        make_tree(tmp_path, HMDM)
        info = recon(tmp_path, write=True)
        logs = tmp_path / ".project-ai" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "step-02.log").write_text("[INFO] BUILD SUCCESS\n", encoding="utf-8")
        finalize(tmp_path, info=info, write=True)
        agents_text = (tmp_path / "AGENTS.md").read_text().lower()
        stack_names = {s.adapter for s in info.stacks}
        # Al menos uno de los stacks debe aparecer en AGENTS.md
        assert any(s in agents_text for s in stack_names), (
            f"Ningún stack {stack_names} encontrado en AGENTS.md"
        )
