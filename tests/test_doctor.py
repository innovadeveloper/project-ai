"""Tests para doctor.py."""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

from conftest import NETCLIENT_FULL, make_tree

from project_ai.doctor import (
    Check,
    CheckStatus,
    DoctorReport,
    ServiceCheck,
    _compare,
    _find_android_ndk,
    _find_android_sdk,
    _parse_jdk_major,
    _parse_ver,
    doctor,
)
from project_ai.model import Fact, ProjectInfo, Service, SourcePriority, Status


# --------------------------------------------------------------------------
# Helpers de test
# --------------------------------------------------------------------------

def _info_req(**reqs) -> ProjectInfo:
    """ProjectInfo mínimo con requirements {key: version_str}."""
    info = ProjectInfo(root="/fake")
    for key, val in reqs.items():
        info.requirements[key] = Fact(val, SourcePriority.BUILD, Status.INFERRED)
    return info


def _info_svc(*kinds) -> ProjectInfo:
    info = ProjectInfo(root="/fake")
    for kind in kinds:
        info.services.append(Service(kind=kind,
                                     fact=Fact("*", SourcePriority.BUILD, Status.INFERRED)))
    return info


# --------------------------------------------------------------------------
# _parse_jdk_major
# --------------------------------------------------------------------------

class TestParseJdkMajor:
    def test_legacy_java8(self):
        assert _parse_jdk_major('java version "1.8.0_392"') == (8, 0, 392)

    def test_java17(self):
        assert _parse_jdk_major('openjdk version "17.0.12" 2024-07-16') == (17, 0, 12)

    def test_java21(self):
        assert _parse_jdk_major('openjdk version "21" 2023-09-19') == (21,)

    def test_java11(self):
        assert _parse_jdk_major('java version "11.0.22" 2024-01-16 LTS') == (11, 0, 22)

    def test_empty(self):
        assert _parse_jdk_major("") == ()

    def test_no_version_keyword(self):
        assert _parse_jdk_major("command not found") == ()


# --------------------------------------------------------------------------
# _parse_ver
# --------------------------------------------------------------------------

class TestParseVer:
    def test_three_parts(self):
        assert _parse_ver("3.27.4") == (3, 27, 4)

    def test_two_parts(self):
        assert _parse_ver("3.20") == (3, 20)

    def test_single(self):
        assert _parse_ver("2") == (2,)

    def test_strips_whitespace(self):
        assert _parse_ver("  17.0.12  ") == (17, 0, 12)


# --------------------------------------------------------------------------
# _compare
# --------------------------------------------------------------------------

class TestCompare:
    def test_ok_exact_match(self):
        assert _compare("17.0.12", "17", None) == CheckStatus.OK

    def test_ok_above_min(self):
        assert _compare("17", "8", None) == CheckStatus.OK

    def test_wrong_below_min(self):
        assert _compare("8", "11", None) == CheckStatus.WRONG_VERSION

    def test_ok_at_lower_bound(self):
        assert _compare("8", "8", "11") == CheckStatus.OK

    def test_ok_at_upper_bound(self):
        assert _compare("11", "8", "11") == CheckStatus.OK

    def test_wrong_above_ceiling(self):
        assert _compare("17", "8", "11") == CheckStatus.WRONG_VERSION

    def test_wrong_conan1_needs_conan2(self):
        assert _compare("1.64.0", "2", None) == CheckStatus.WRONG_VERSION

    def test_ok_conan2(self):
        assert _compare("2.5.0", "2", None) == CheckStatus.OK

    def test_ok_no_constraint(self):
        assert _compare("99.0", None, None) == CheckStatus.OK


# --------------------------------------------------------------------------
# Checks de herramientas (subprocess mockeado)
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_check_cmake_ok(mock_run, tmp_path):
    mock_run.return_value = "cmake version 3.27.4\nCMake suite maintained and supported..."
    report = doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "cmake")
    assert c.status == CheckStatus.OK
    assert c.found == "3.27.4"


@patch("project_ai.doctor._run_cmd")
def test_check_cmake_missing(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "cmake")
    assert c.status == CheckStatus.MISSING
    assert c.found is None
    assert c.install_cmd is not None


@patch("project_ai.doctor._run_cmd")
def test_check_cmake_wrong_version(mock_run, tmp_path):
    mock_run.return_value = "cmake version 3.15.0\n..."
    report = doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "cmake")
    assert c.status == CheckStatus.WRONG_VERSION


@patch("project_ai.doctor._run_cmd")
def test_check_maven_ok(mock_run, tmp_path):
    mock_run.return_value = "Apache Maven 3.9.6 (bc0240f3c744dd6b6ec2920b3cd08dcc...)"
    report = doctor(tmp_path, info=_info_req(maven="3.6"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "maven")
    assert c.status == CheckStatus.OK
    assert c.found == "3.9.6"


@patch("project_ai.doctor._run_cmd")
def test_check_conan_version_mismatch(mock_run, tmp_path):
    mock_run.return_value = "Conan version 1.64.0"
    report = doctor(tmp_path, info=_info_req(conan="2"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "conan")
    assert c.status == CheckStatus.WRONG_VERSION
    assert c.install_cmd is not None


@patch("project_ai.doctor._run_cmd")
def test_check_conan2_ok(mock_run, tmp_path):
    mock_run.return_value = "Conan version 2.5.0"
    report = doctor(tmp_path, info=_info_req(conan="2"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "conan")
    assert c.status == CheckStatus.OK
    assert c.install_cmd is None  # OK → no recomendar instalación


# --------------------------------------------------------------------------
# JDK (con jdk_ceiling)
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_jdk_within_range(mock_run, tmp_path):
    mock_run.return_value = 'openjdk version "8" 2024-01-01'
    info = _info_req(jdk="8")
    info.requirements["jdk_ceiling"] = Fact("11", SourcePriority.BUILD, Status.INFERRED)
    report = doctor(tmp_path, info=info, skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "jdk")
    assert c.status == CheckStatus.OK
    assert c.ceiling == "11"


@patch("project_ai.doctor._run_cmd")
def test_jdk_above_ceiling(mock_run, tmp_path):
    mock_run.return_value = 'openjdk version "17.0.12" 2024-07-16'
    info = _info_req(jdk="8")
    info.requirements["jdk_ceiling"] = Fact("11", SourcePriority.BUILD, Status.INFERRED)
    report = doctor(tmp_path, info=info, skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "jdk")
    assert c.status == CheckStatus.WRONG_VERSION
    assert c.ceiling == "11"
    assert c.found == "17.0.12"


@patch("project_ai.doctor._run_cmd")
def test_jdk_below_min(mock_run, tmp_path):
    mock_run.return_value = 'java version "1.8.0_392"'
    report = doctor(tmp_path, info=_info_req(jdk="11"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "jdk")
    assert c.status == CheckStatus.WRONG_VERSION


@patch("project_ai.doctor._run_cmd")
def test_jdk_legacy_format_parsed_correctly(mock_run, tmp_path):
    mock_run.return_value = 'java version "1.8.0_392"\nJava(TM) SE Runtime Environment'
    report = doctor(tmp_path, info=_info_req(jdk="8"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "jdk")
    assert c.status == CheckStatus.OK
    assert c.found.startswith("8")  # "8.0.392"


@patch("project_ai.doctor._run_cmd")
def test_jdk_missing(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(jdk="11"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "jdk")
    assert c.status == CheckStatus.MISSING
    assert c.install_cmd is not None


# --------------------------------------------------------------------------
# Claves sin checker / skipped
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_cxx_standard_not_in_checks(mock_run, tmp_path):
    """cxx_standard está en _SKIP_KEYS y no genera Check."""
    mock_run.return_value = "cmake version 3.27.4"
    info = _info_req(cmake="3.20", cxx_standard="17")
    report = doctor(tmp_path, info=info, skip_services=True)
    assert not any(ch.key == "cxx_standard" for ch in report.checks)


@patch("project_ai.doctor._run_cmd")
def test_jdk_ceiling_not_standalone_check(mock_run, tmp_path):
    mock_run.return_value = 'openjdk version "11.0.22"'
    info = _info_req(jdk="8")
    info.requirements["jdk_ceiling"] = Fact("11", SourcePriority.BUILD, Status.INFERRED)
    report = doctor(tmp_path, info=info, skip_services=True)
    assert not any(ch.key == "jdk_ceiling" for ch in report.checks)
    assert sum(1 for ch in report.checks if ch.key == "jdk") == 1


@patch("project_ai.doctor._run_cmd")
def test_unknown_key_is_na(mock_run, tmp_path):
    """Clave sin checker conocido → NA (no rompe)."""
    info = _info_req(my_custom_tool="1.0")
    report = doctor(tmp_path, info=info, skip_services=True)
    c = next((ch for ch in report.checks if ch.key == "my_custom_tool"), None)
    assert c is not None
    assert c.status == CheckStatus.NA


def test_empty_requirements_no_checks(tmp_path):
    report = doctor(tmp_path, info=ProjectInfo(root="/fake"), skip_services=True)
    assert report.checks == []


# --------------------------------------------------------------------------
# Servicios TCP
# --------------------------------------------------------------------------

@patch("project_ai.doctor._probe_tcp")
def test_service_open(mock_probe, tmp_path):
    mock_probe.return_value = True
    report = doctor(tmp_path, info=_info_svc("postgresql"))
    assert any(s.name == "postgresql" and s.open for s in report.services)


@patch("project_ai.doctor._probe_tcp")
def test_service_closed(mock_probe, tmp_path):
    mock_probe.return_value = False
    report = doctor(tmp_path, info=_info_svc("postgresql"))
    assert any(s.name == "postgresql" and not s.open for s in report.services)


def test_skip_services_no_probe(tmp_path):
    with patch("project_ai.doctor._probe_tcp") as mock_probe:
        report = doctor(tmp_path, info=_info_svc("postgresql", "redis"), skip_services=True)
    mock_probe.assert_not_called()
    assert report.services == []


@patch("project_ai.doctor._probe_tcp")
def test_service_unknown_port_ignored(mock_probe, tmp_path):
    info = ProjectInfo(root="/fake")
    info.services.append(Service(kind="unknown-db",
                                 fact=Fact("*", SourcePriority.BUILD, Status.INFERRED)))
    report = doctor(tmp_path, info=info)
    assert report.services == []


@patch("project_ai.doctor._probe_tcp")
def test_service_duplicate_deduplicated(mock_probe, tmp_path):
    mock_probe.return_value = True
    info = _info_svc("redis", "redis")   # mismo kind dos veces
    report = doctor(tmp_path, info=info)
    redis_checks = [s for s in report.services if s.name == "redis"]
    assert len(redis_checks) == 1


# --------------------------------------------------------------------------
# DoctorReport.ok
# --------------------------------------------------------------------------

def test_report_ok_all_green():
    report = DoctorReport(
        root="/x",
        checks=[Check("cmake", "3.20", "3.27.4", CheckStatus.OK)],
        services=[ServiceCheck("redis", 6379, True)],
    )
    assert report.ok is True


def test_report_ok_false_missing():
    report = DoctorReport(
        root="/x",
        checks=[Check("cmake", "3.20", None, CheckStatus.MISSING)],
        services=[],
    )
    assert report.ok is False


def test_report_ok_false_wrong_version():
    report = DoctorReport(
        root="/x",
        checks=[Check("jdk", "8", "17", CheckStatus.WRONG_VERSION, ceiling="11")],
        services=[],
    )
    assert report.ok is False


def test_report_ok_unknown_and_na_do_not_fail():
    report = DoctorReport(
        root="/x",
        checks=[
            Check("cmake", "3.20", None, CheckStatus.UNKNOWN),
            Check("foo", "1", None, CheckStatus.NA),
        ],
        services=[],
    )
    assert report.ok is True


# --------------------------------------------------------------------------
# to_md()
# --------------------------------------------------------------------------

def test_to_md_header():
    report = DoctorReport(root="/x", checks=[], services=[])
    md = report.to_md()
    assert "Informe de entorno" in md
    assert "Generado" in md


def test_to_md_shows_requirements():
    report = DoctorReport(
        root="/x",
        checks=[
            Check("cmake", "3.20", "3.27.4", CheckStatus.OK),
            Check("conan", "2", None, CheckStatus.MISSING, install_cmd="pip install conan"),
        ],
        services=[],
    )
    md = report.to_md()
    assert "cmake" in md and "✅" in md
    assert "conan" in md and "❌" in md


def test_to_md_shows_ceiling_range():
    report = DoctorReport(
        root="/x",
        checks=[Check("jdk", "8", "17", CheckStatus.WRONG_VERSION, ceiling="11")],
        services=[],
    )
    md = report.to_md()
    assert "≤ 11" in md
    assert "≥ 8" in md


def test_to_md_shows_services():
    report = DoctorReport(
        root="/x",
        checks=[],
        services=[ServiceCheck("postgresql", 5432, False)],
    )
    md = report.to_md()
    assert "postgresql" in md
    assert "5432" in md
    assert "❌" in md


def test_to_md_actions_when_issues():
    report = DoctorReport(
        root="/x",
        checks=[Check("cmake", "3.20", None, CheckStatus.MISSING, install_cmd="brew install cmake")],
        services=[ServiceCheck("redis", 6379, False)],
    )
    md = report.to_md()
    assert "Acciones" in md
    assert "brew install cmake" in md
    assert "redis" in md


def test_to_md_no_actions_section_when_all_ok():
    report = DoctorReport(
        root="/x",
        checks=[Check("cmake", "3.20", "3.27.4", CheckStatus.OK)],
        services=[ServiceCheck("redis", 6379, True)],
    )
    md = report.to_md()
    assert "Acciones" not in md


def test_to_md_no_services_section_when_empty():
    report = DoctorReport(root="/x", checks=[], services=[])
    md = report.to_md()
    assert "Servicios" not in md


# --------------------------------------------------------------------------
# Escritura de env-report.md
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_write_creates_env_report(mock_run, tmp_path):
    mock_run.return_value = "cmake version 3.27.4"
    doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True, write=True)
    out = tmp_path / ".project-ai" / "env-report.md"
    assert out.exists()
    assert "cmake" in out.read_text(encoding="utf-8")


@patch("project_ai.doctor._run_cmd")
def test_no_write_by_default(mock_run, tmp_path):
    mock_run.return_value = "cmake version 3.27.4"
    doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True)
    assert not (tmp_path / ".project-ai" / "env-report.md").exists()


@patch("project_ai.doctor._run_cmd")
def test_write_idempotent(mock_run, tmp_path):
    mock_run.return_value = "cmake version 3.27.4"
    doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True, write=True)
    doctor(tmp_path, info=_info_req(cmake="3.20"), skip_services=True, write=True)
    assert (tmp_path / ".project-ai" / "env-report.md").exists()


# --------------------------------------------------------------------------
# Integración tolerante (sin mocks, puede tener MISSING/UNKNOWN)
# --------------------------------------------------------------------------

def test_doctor_netclient_no_crash(tmp_path):
    """Doctor no lanza excepciones con el fixture de netclient."""
    make_tree(tmp_path, NETCLIENT_FULL)
    report = doctor(tmp_path, skip_services=True)
    assert isinstance(report, DoctorReport)
    assert all(isinstance(c, Check) for c in report.checks)
    # cmake y conan deben estar en los checks (son requisitos de netclient)
    keys = {c.key for c in report.checks}
    assert "cmake" in keys or "conan" in keys


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_doctor_text(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "doctor",
         str(tmp_path), "--no-write", "--skip-services"],
        capture_output=True, text=True,
    )
    assert result.returncode in (0, 1)
    out = result.stdout
    assert "cmake" in out.lower() or "conan" in out.lower() or "Requisitos" in out


def test_cli_doctor_writes_file(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    subprocess.run(
        [sys.executable, "-m", "project_ai.cli", "doctor",
         str(tmp_path), "--skip-services"],
        capture_output=True, text=True,
    )
    assert (tmp_path / ".project-ai" / "env-report.md").exists()


def test_cli_doctor_no_subcommand_help():
    result = subprocess.run(
        [sys.executable, "-m", "project_ai.cli"],
        capture_output=True, text=True,
    )
    assert "doctor" in result.stdout


# --------------------------------------------------------------------------
# Android SDK / NDK checks
# --------------------------------------------------------------------------

def _android_info(compile_sdk: str | None = "33", has_ndk: bool = False) -> ProjectInfo:
    """ProjectInfo con facts Android como los generaría gradle.py."""
    info = ProjectInfo(root="/fake")
    if compile_sdk:
        info.set_fact("android.compileSdk", Fact(
            compile_sdk, SourcePriority.BUILD, Status.INFERRED,
        ))
    if has_ndk:
        info.set_fact("android.ndk", Fact(
            True, SourcePriority.BUILD, Status.INFERRED,
        ))
    return info


@patch("project_ai.doctor._find_android_sdk", return_value=None)
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_sdk_missing(mock_run, mock_sdk, tmp_path):
    info = _android_info("33")
    report = doctor(tmp_path, info=info, skip_services=True)
    sdk_check = next((c for c in report.checks if c.key == "android_sdk"), None)
    assert sdk_check is not None
    assert sdk_check.status == CheckStatus.MISSING
    assert sdk_check.install_cmd is not None


@patch("project_ai.doctor._find_android_sdk", return_value="/fake/sdk")
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_sdk_found_platform_missing(mock_run, mock_sdk, tmp_path):
    info = _android_info("33")
    report = doctor(tmp_path, info=info, skip_services=True)
    sdk_check = next((c for c in report.checks if c.key == "android_sdk"), None)
    assert sdk_check is not None
    # /fake/sdk/platforms/android-33 no existe → WRONG_VERSION
    assert sdk_check.status == CheckStatus.WRONG_VERSION
    assert "android-33" in (sdk_check.install_cmd or "")


@patch("project_ai.doctor._find_android_sdk")
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_sdk_found_platform_ok(mock_run, mock_sdk, tmp_path):
    # Crear platform dir real
    platform_dir = tmp_path / "sdk" / "platforms" / "android-33"
    platform_dir.mkdir(parents=True)
    mock_sdk.return_value = str(tmp_path / "sdk")
    info = _android_info("33")
    report = doctor(tmp_path, info=info, skip_services=True)
    sdk_check = next((c for c in report.checks if c.key == "android_sdk"), None)
    assert sdk_check is not None
    assert sdk_check.status == CheckStatus.OK


@patch("project_ai.doctor._find_android_sdk", return_value="/fake/sdk")
@patch("project_ai.doctor._find_android_ndk", return_value=None)
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_ndk_missing(mock_run, mock_ndk, mock_sdk, tmp_path):
    info = _android_info("33", has_ndk=True)
    report = doctor(tmp_path, info=info, skip_services=True)
    ndk_check = next((c for c in report.checks if c.key == "android_ndk"), None)
    assert ndk_check is not None
    assert ndk_check.status == CheckStatus.MISSING
    assert ndk_check.install_cmd is not None


@patch("project_ai.doctor._find_android_sdk", return_value="/fake/sdk")
@patch("project_ai.doctor._find_android_ndk", return_value="/fake/sdk/ndk/26.1.0")
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_ndk_found(mock_run, mock_ndk, mock_sdk, tmp_path):
    info = _android_info("33", has_ndk=True)
    report = doctor(tmp_path, info=info, skip_services=True)
    ndk_check = next((c for c in report.checks if c.key == "android_ndk"), None)
    assert ndk_check is not None
    assert ndk_check.status == CheckStatus.OK
    assert "26.1.0" in (ndk_check.found or "")


@patch("project_ai.doctor._find_android_sdk", return_value=None)
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_no_ndk_check_without_ndk_fact(mock_run, mock_sdk, tmp_path):
    """Si no hay android.ndk fact, no debe aparecer check de NDK."""
    info = _android_info("33", has_ndk=False)
    report = doctor(tmp_path, info=info, skip_services=True)
    ndk_check = next((c for c in report.checks if c.key == "android_ndk"), None)
    assert ndk_check is None


@patch("project_ai.doctor._find_android_sdk", return_value=None)
@patch("project_ai.doctor._run_cmd",
       return_value="Android Debug Bridge version 1.0.41\nVersion 34.0.4")
def test_android_adb_found(mock_run, mock_sdk, tmp_path):
    info = _android_info("33")
    report = doctor(tmp_path, info=info, skip_services=True)
    adb_check = next((c for c in report.checks if c.key == "adb"), None)
    assert adb_check is not None
    assert adb_check.status == CheckStatus.OK
    assert "1.0.41" in (adb_check.found or "")


@patch("project_ai.doctor._find_android_sdk", return_value=None)
@patch("project_ai.doctor._run_cmd", return_value=None)
def test_android_adb_missing(mock_run, mock_sdk, tmp_path):
    info = _android_info("33")
    report = doctor(tmp_path, info=info, skip_services=True)
    adb_check = next((c for c in report.checks if c.key == "adb"), None)
    assert adb_check is not None
    assert adb_check.status == CheckStatus.MISSING


def test_android_checks_not_triggered_for_non_android(tmp_path):
    """Para proyectos sin facts Android, no deben aparecer checks android_sdk/adb."""
    info = ProjectInfo(root="/fake")
    info.requirements["cmake"] = Fact("3.20", SourcePriority.BUILD, Status.INFERRED)
    with patch("project_ai.doctor._run_cmd", return_value="cmake version 3.27.4\n"):
        report = doctor(tmp_path, info=info, skip_services=True)
    android_keys = {c.key for c in report.checks if c.key.startswith("android") or c.key == "adb"}
    assert android_keys == set()


# Helpers directos

def test_find_android_sdk_env_var(monkeypatch, tmp_path):
    sdk_dir = tmp_path / "my_sdk"
    sdk_dir.mkdir()
    monkeypatch.setenv("ANDROID_HOME", str(sdk_dir))
    result = _find_android_sdk()
    assert result == str(sdk_dir)


def test_find_android_sdk_env_missing(monkeypatch):
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    # No podemos controlar ~/Library/Android/sdk en tests, solo verificamos que no crashea
    result = _find_android_sdk()
    assert result is None or isinstance(result, str)


def test_find_android_ndk_in_ndk_dir(tmp_path):
    ndk_dir = tmp_path / "ndk" / "26.1.0"
    ndk_dir.mkdir(parents=True)
    result = _find_android_ndk(str(tmp_path))
    assert result is not None
    assert "26.1.0" in result


def test_find_android_ndk_legacy_bundle(tmp_path):
    legacy = tmp_path / "ndk-bundle"
    legacy.mkdir()
    result = _find_android_ndk(str(tmp_path))
    assert result is not None
    assert "ndk-bundle" in result


def test_find_android_ndk_not_found(tmp_path):
    result = _find_android_ndk(str(tmp_path))
    assert result is None


# --------------------------------------------------------------------------
# Go checks
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_go_ok(mock_run, tmp_path):
    mock_run.return_value = "go version go1.21.5 linux/amd64"
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "go")
    assert c.status == CheckStatus.OK
    assert c.found == "1.21.5"


@patch("project_ai.doctor._run_cmd")
def test_go_missing(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "go")
    assert c.status == CheckStatus.MISSING
    assert c.install_cmd is not None


@patch("project_ai.doctor._run_cmd")
def test_go_wrong_version(mock_run, tmp_path):
    mock_run.return_value = "go version go1.18.0 linux/amd64"
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "go")
    assert c.status == CheckStatus.WRONG_VERSION


@patch("project_ai.doctor._run_cmd")
def test_go_install_cmd_macos(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True,
                    os_hint="macos")
    c = next(ch for ch in report.checks if ch.key == "go")
    assert "brew" in (c.install_cmd or "")


@patch("project_ai.doctor._run_cmd")
def test_go_install_cmd_linux(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True,
                    os_hint="linux")
    c = next(ch for ch in report.checks if ch.key == "go")
    assert c.install_cmd is not None


@patch("project_ai.doctor._run_cmd")
def test_go_install_cmd_windows(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(go="1.21"), skip_services=True,
                    os_hint="windows")
    c = next(ch for ch in report.checks if ch.key == "go")
    assert "winget" in (c.install_cmd or "")


# --------------------------------------------------------------------------
# Rust checks
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_rust_ok(mock_run, tmp_path):
    mock_run.return_value = "rustc 1.75.0 (82e1608df 2023-12-21)"
    report = doctor(tmp_path, info=_info_req(rust="1.70"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "rust")
    assert c.status == CheckStatus.OK
    assert c.found == "1.75.0"


@patch("project_ai.doctor._run_cmd")
def test_rust_missing(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(rust="1.70"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "rust")
    assert c.status == CheckStatus.MISSING
    assert c.install_cmd is not None


@patch("project_ai.doctor._run_cmd")
def test_rust_wrong_version(mock_run, tmp_path):
    mock_run.return_value = "rustc 1.56.0 (09c42c458 2021-10-18)"
    report = doctor(tmp_path, info=_info_req(rust="1.70"), skip_services=True)
    c = next(ch for ch in report.checks if ch.key == "rust")
    assert c.status == CheckStatus.WRONG_VERSION


@patch("project_ai.doctor._run_cmd")
def test_rust_install_cmd_macos(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(rust="1.70"), skip_services=True,
                    os_hint="macos")
    c = next(ch for ch in report.checks if ch.key == "rust")
    assert "rustup" in (c.install_cmd or "")


@patch("project_ai.doctor._run_cmd")
def test_rust_install_cmd_windows(mock_run, tmp_path):
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(rust="1.70"), skip_services=True,
                    os_hint="windows")
    c = next(ch for ch in report.checks if ch.key == "rust")
    assert "winget" in (c.install_cmd or "")


# --------------------------------------------------------------------------
# c_standard skip
# --------------------------------------------------------------------------

@patch("project_ai.doctor._run_cmd")
def test_c_standard_skipped(mock_run, tmp_path):
    """c_standard no debe producir un check (no hay herramienta que verificar)."""
    mock_run.return_value = None
    report = doctor(tmp_path, info=_info_req(c_standard="11"), skip_services=True)
    assert not any(ch.key == "c_standard" for ch in report.checks)
