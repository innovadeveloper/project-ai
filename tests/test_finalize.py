"""Tests para finalize.py."""
from __future__ import annotations

from pathlib import Path

from conftest import HMDM, NETCLIENT_FULL, make_tree

from project_ai.finalize import (
    AGENTS_FILE,
    FinalizeResult,
    _detect_verified,
    _generate_agents_md,
    _parse_journal_traps,
    finalize,
)
from project_ai.model import (
    Command, Endpoint, EntryPoint, Module,
    ProjectInfo, Fact, SourcePriority, StackDetection, Status,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _proj(tmp_path: Path) -> ProjectInfo:
    info = ProjectInfo(root=str(tmp_path))
    info.stacks.append(StackDetection(adapter="maven", confidence=1.0))
    info.add_command(Command(name="deps",  shell="mvn dependency:go-offline"))
    info.add_command(Command(name="build", shell="mvn -DskipTests package"))
    info.add_command(Command(name="test",  shell="mvn test"))
    info.add_command(Command(name="run",   shell='java -jar target/app.jar'))
    return info


def _write_log(tmp_path: Path, name: str, content: str) -> Path:
    logs = tmp_path / ".project-ai" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    f = logs / name
    f.write_text(content, encoding="utf-8")
    return f


def _write_project_json(tmp_path: Path, info: ProjectInfo) -> None:
    import json
    d = tmp_path / ".project-ai"
    d.mkdir(exist_ok=True)
    (d / "project.json").write_text(
        json.dumps(info.to_dict(), indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# _detect_verified
# --------------------------------------------------------------------------

class TestDetectVerified:
    def test_build_success_maven(self, tmp_path):
        info = _proj(tmp_path)
        _write_log(tmp_path, "step-02.log", "[INFO] BUILD SUCCESS\n[INFO] BUILD SUCCESS\n")
        kinds = _detect_verified(tmp_path, info)
        assert "build" in kinds

    def test_build_success_cmake(self, tmp_path):
        info = _proj(tmp_path)
        info.add_command(Command(name="build", shell="cmake --build --preset conan-debug"))
        _write_log(tmp_path, "step-02.log", "[100%] Built target my_app\n")
        kinds = _detect_verified(tmp_path, info)
        assert "build" in kinds

    def test_test_success_maven(self, tmp_path):
        info = _proj(tmp_path)
        _write_log(tmp_path, "step-03.log",
                   "Tests run: 42, Failures: 0, Errors: 0, Skipped: 1\n")
        kinds = _detect_verified(tmp_path, info)
        assert "test" in kinds

    def test_deps_success(self, tmp_path):
        info = _proj(tmp_path)
        _write_log(tmp_path, "step-01.log", "[INFO] BUILD SUCCESS\n")
        kinds = _detect_verified(tmp_path, info)
        assert "deps" in kinds

    def test_configure_success_cmake(self, tmp_path):
        info = _proj(tmp_path)
        info.add_command(Command(name="configure", shell="cmake --preset conan-debug"))
        _write_log(tmp_path, "step-01.log", "-- Build files have been written to: /tmp/build\n")
        kinds = _detect_verified(tmp_path, info)
        assert "configure" in kinds

    def test_no_log_no_verified(self, tmp_path):
        info = _proj(tmp_path)
        assert _detect_verified(tmp_path, info) == []

    def test_failed_log_not_verified(self, tmp_path):
        info = _proj(tmp_path)
        _write_log(tmp_path, "step-02.log", "[INFO] BUILD FAILURE\n[ERROR] Compilation failed\n")
        kinds = _detect_verified(tmp_path, info)
        assert "build" not in kinds

    def test_command_not_in_info_not_returned(self, tmp_path):
        info = ProjectInfo(root=str(tmp_path))
        # sin comandos
        _write_log(tmp_path, "step-01.log", "BUILD SUCCESS\n")
        assert _detect_verified(tmp_path, info) == []

    def test_no_logs_dir_returns_empty(self, tmp_path):
        info = _proj(tmp_path)
        assert _detect_verified(tmp_path, info) == []


# --------------------------------------------------------------------------
# _parse_journal_traps
# --------------------------------------------------------------------------

class TestParseJournalTraps:
    def _write_journal(self, tmp_path: Path, content: str) -> None:
        d = tmp_path / ".project-ai"
        d.mkdir(exist_ok=True)
        (d / "journal.md").write_text(content, encoding="utf-8")

    def test_extracts_n0_traps(self, tmp_path):
        self._write_journal(tmp_path, (
            "\n## 2026-10-09T12:00:00Z — step-01.log\n\n"
            "**Nivel**: N0  \n"
            "**Regla**: jdk-class-version  \n"
            "**Confianza**: 100%  \n"
            "**Causa**: JDK incorrecto  \n"
            "**Arreglo**: sdk use java 11\n"
        ))
        traps = _parse_journal_traps(tmp_path)
        assert len(traps) == 1
        assert "JDK incorrecto" in traps[0]
        assert "sdk use java 11" in traps[0]

    def test_ignores_n1_entries(self, tmp_path):
        self._write_journal(tmp_path, (
            "\n## 2026-10-09T12:00:00Z — step-01.log\n\n"
            "**Nivel**: N1  \n**Causa**: algo\n**Arreglo**: fix\n"
        ))
        assert _parse_journal_traps(tmp_path) == []

    def test_no_journal_returns_empty(self, tmp_path):
        assert _parse_journal_traps(tmp_path) == []

    def test_deduplicates_same_trap(self, tmp_path):
        entry = (
            "\n## 2026-10-09T12:00:00Z — step-01.log\n\n"
            "**Nivel**: N0  \n"
            "**Causa**: JDK incorrecto  \n"
            "**Arreglo**: sdk use java 11\n"
        )
        self._write_journal(tmp_path, entry + entry)
        traps = _parse_journal_traps(tmp_path)
        assert len(traps) == 1


# --------------------------------------------------------------------------
# _generate_agents_md
# --------------------------------------------------------------------------

class TestGenerateAgentsMd:
    def _make_info(self, tmp_path: Path) -> ProjectInfo:
        info = ProjectInfo(root=str(tmp_path))
        info.stacks.append(StackDetection(adapter="maven", confidence=1.0))
        info.add_command(Command(name="build", shell="mvn -DskipTests package",
                                 status=Status.VERIFIED))
        info.add_command(Command(name="test",  shell="mvn test"))
        info.modules.append(Module(name="server", path="server", build_system="maven",
                                   kind="application"))
        info.entry_points.append(EntryPoint(kind="spring-boot-app",
                                            symbol="HmdmApplication",
                                            file="src/main/java/com/hmdm/HmdmApplication.java"))
        info.endpoints.append(Endpoint(method="GET", path="/api/devices",
                                       handler="DeviceResource#list",
                                       file="src/.../DeviceResource.java"))
        return info

    def test_has_header(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, ["build"], "2026-10-09T00:00:00Z", [])
        assert "# AGENTS.md" in md

    def test_has_stack(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, ["build"], "2026-10-09T00:00:00Z", [])
        assert "maven" in md

    def test_verified_command_marked(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, ["build"], "2026-10-09T00:00:00Z", [])
        assert "✅" in md
        assert "verificado" in md

    def test_unverified_command_marked(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, ["build"], "2026-10-09T00:00:00Z", [])
        assert "⬜" in md

    def test_has_entry_points(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert "HmdmApplication" in md

    def test_has_endpoints(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert "/api/devices" in md

    def test_has_navigation_section(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert "repo-map.md" in md
        assert "project.json" in md

    def test_under_200_lines(self, tmp_path):
        info = self._make_info(tmp_path)
        # Añadir muchos endpoints para probar el cap
        for i in range(30):
            info.endpoints.append(Endpoint(
                method="GET", path=f"/api/item/{i}",
                handler=f"Res#get{i}", file="Res.java",
            ))
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert len(md.splitlines()) <= 200

    def test_traps_in_output(self, tmp_path):
        info = self._make_info(tmp_path)
        traps = ["javax → Tomcat 9 (no 10)", "lombok requiere JDK <= 11"]
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", traps)
        assert "javax" in md
        assert "lombok" in md

    def test_no_traps_placeholder(self, tmp_path):
        info = self._make_info(tmp_path)
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert "Sin entradas" in md

    def test_services_listed(self, tmp_path):
        info = self._make_info(tmp_path)
        fact = Fact(value="*", priority=SourcePriority.BUILD, status=Status.INFERRED)
        info.add_service("postgresql", fact)
        md = _generate_agents_md(tmp_path, info, [], "2026-10-09T00:00:00Z", [])
        assert "postgresql" in md


# --------------------------------------------------------------------------
# finalize()
# --------------------------------------------------------------------------

class TestFinalize:
    def test_returns_result(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = finalize(tmp_path, write=False)
        assert isinstance(result, FinalizeResult)

    def test_no_write_no_agents_md(self, tmp_path):
        make_tree(tmp_path, HMDM)
        finalize(tmp_path, write=False)
        assert not (tmp_path / AGENTS_FILE).exists()

    def test_write_creates_agents_md(self, tmp_path):
        make_tree(tmp_path, HMDM)
        finalize(tmp_path, write=True)
        assert (tmp_path / AGENTS_FILE).exists()

    def test_agents_md_has_runbook_pointer(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = finalize(tmp_path, write=False)
        assert "RUNBOOK.md" in result.agents_md

    def test_verified_empty_when_no_logs(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = finalize(tmp_path, write=False)
        assert result.verified == []

    def test_verified_when_build_log_success(self, tmp_path):
        make_tree(tmp_path, HMDM)
        _write_log(tmp_path, "step-02.log", "[INFO] BUILD SUCCESS\n")
        result = finalize(tmp_path, write=False)
        assert "build" in result.verified

    def test_project_json_updated_with_verified(self, tmp_path):
        make_tree(tmp_path, HMDM)
        _write_log(tmp_path, "step-02.log", "[INFO] BUILD SUCCESS\n")
        finalize(tmp_path, write=True)
        import json
        data = json.loads((tmp_path / ".project-ai" / "project.json").read_text())
        build_status = data["commands"]["build"]["status"]
        assert build_status == "verified"

    def test_netclient_finalize(self, tmp_path):
        make_tree(tmp_path, NETCLIENT_FULL)
        result = finalize(tmp_path, write=False)
        assert isinstance(result, FinalizeResult)
        assert "cmake" in result.agents_md or "conan" in result.agents_md

    def test_agents_md_under_200_lines(self, tmp_path):
        make_tree(tmp_path, HMDM)
        result = finalize(tmp_path, write=False)
        assert len(result.agents_md.splitlines()) <= 200

    def test_info_passed_directly(self, tmp_path):
        info = _proj(tmp_path)
        result = finalize(tmp_path, info=info, write=False)
        assert isinstance(result, FinalizeResult)

    def test_journal_traps_included(self, tmp_path):
        make_tree(tmp_path, HMDM)
        d = tmp_path / ".project-ai"
        d.mkdir(exist_ok=True)
        (d / "journal.md").write_text(
            "\n## 2026-10-09T12:00:00Z — step-01.log\n\n"
            "**Nivel**: N0  \n"
            "**Causa**: javax en Tomcat 10  \n"
            "**Arreglo**: usa Tomcat 9\n",
            encoding="utf-8",
        )
        result = finalize(tmp_path, write=False)
        assert "javax" in result.agents_md


# --------------------------------------------------------------------------
# CLI integration
# --------------------------------------------------------------------------

def test_finalize_cli(tmp_path):
    make_tree(tmp_path, HMDM)
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "finalize", str(tmp_path),
         "--no-write"],
        capture_output=True, text=True,
    )
    assert r.returncode in (0, 1)
    assert "AGENTS.md" in r.stdout or "Verificados" in r.stdout
