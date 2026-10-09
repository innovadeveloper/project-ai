import pytest
from conftest import HMDM, NETCLIENT, SMARTTOMCAT_FP, make_tree

from project_ai.adapters import run_adapters
from project_ai.adapters.base import jdk_major, normalize_version
from project_ai.adapters.hints import _yaml_commands, parse_image
from project_ai.model import SourcePriority as P
from project_ai.scanner import ProjectScanner


@pytest.mark.parametrize("raw,major", [
    ("1.8.0_292", "8"), ("17.0.12-tem", "17"), ("temurin-21.0.1+12", "21"),
    ("8u342-b07", "8"), ("jdk17", "17"), ("zulu-11", "11"), ("latest", None),
])
def test_jdk_major(raw, major):
    assert jdk_major(raw) == major


def test_normalize_version_skips_placeholders():
    assert normalize_version("maven", "${MAVEN_VERSION}") is None
    assert normalize_version("node", "v18.17.0") == "18.17.0"
    assert normalize_version("jdk", "lts") is None


@pytest.mark.parametrize("image,expected", [
    ("maven:3.9.6-eclipse-temurin-17", [("maven", "3.9.6"), ("jdk", "17")]),
    ("maven:3.6-jdk-8", [("maven", "3.6"), ("jdk", "8")]),
    ("eclipse-temurin:17-jdk", [("jdk", "17")]),
    ("eclipse-temurin:21-jre-alpine", [("jdk_runtime", "21")]),
    ("openjdk:8u342-jdk", [("jdk", "8")]),
    ("tomcat:9-jdk11-openjdk", [("tomcat", "9"), ("jdk_runtime", "11")]),
    ("gradle:8.5-jdk17", [("gradle", "8.5"), ("jdk", "17")]),
    ("gcc:12", [("gcc", "12")]),
    ("conanio/gcc11", [("gcc", "11")]),
    ("mcr.microsoft.com/dotnet/sdk:8.0", [("dotnet", "8.0")]),
    ("registry.local:5000/team/maven:3.8-openjdk-11", [("maven", "3.8"), ("jdk", "11")]),
    ("ubuntu:22.04", []),
    ("${BASE}", []),
])
def test_parse_image(image, expected):
    assert parse_image(image) == expected


def test_yaml_commands():
    lines = ["steps:", "  - run: mvn -B verify", "  - name: x", "    run: |",
             "      ./gradlew build", "      # comentario", "      echo ok",
             "build:", "  script:", "    - cmake --build build", "    - ctest"]
    cmds = [c for _, c in _yaml_commands(lines)]
    assert cmds == ["mvn -B verify", "./gradlew build", "echo ok",
                    "cmake --build build", "ctest"]


@pytest.fixture
def hmdm(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, HMDM), use_git=False)
    return run_adapters(sc, only=["hints"])


def test_hmdm_requirements(hmdm):
    r = hmdm.requirements
    assert not hmdm.warnings, hmdm.warnings
    # .tool-versions (EXPLICIT) gana; CI y docs coinciden en 8
    assert r["jdk"].value == "8" and r["jdk"].priority == P.EXPLICIT
    assert len(r["jdk"].evidence) >= 3
    # la imagen de Tomcat es de runtime; el Dockerfile raíz gana al anidado sin conflicto
    assert r["jdk_runtime"].value == "8" and r["jdk_runtime"].priority == P.CI
    assert any(a["value"] == "11" for a in r["jdk_runtime"].alternatives)
    assert r["tomcat"].value == "9" and r["tomcat"].priority == P.CI
    assert r["maven"].value == "3.8.8"
    assert any(a["value"] == "3.6" for a in r["maven"].alternatives)
    # el Tomcat del IDE describe la máquina local, no es un requisito
    assert not any(a["value"] == "10.1" for a in r["tomcat"].alternatives)
    assert hmdm.facts["ide.tomcat_local"].value == "10.1"


def test_hmdm_services_and_facts(hmdm):
    assert [s.kind for s in hmdm.services] == ["postgresql"]
    pg = hmdm.services[0].fact
    assert pg.value == "13" and any(a["value"] == "12" for a in pg.alternatives)
    f = hmdm.facts
    assert f["runtime.servlet_container"].value == "tomcat"
    assert f["hints.ports"].value == ["8080", "8443"]
    assert "headwindmdm/hmdm:0.1.5" in f["hints.compose_images"].value
    assert "foo 1.0" in f["toolchain.other"].value
    assert any("webapps" in d for d in f["hints.deploy"].value)


def test_hmdm_commands(hmdm):
    cmds = {(c["origin"], c["cmd"]) for c in hmdm.facts["hints.commands"].value}
    assert ("ci", "mvn -B install -DskipTests") in cmds
    assert ("ci", "mvn clean package") in cmds
    assert ("docs", "mvn install") in cmds
    assert ("docs", "./hmdm_install.sh") in cmds
    assert not any("apt-get" in c for _, c in cmds)          # no es comando de build


def test_hmdm_command_kinds_dedup_and_multiline(hmdm):
    by_cmd = {c["cmd"]: c for c in hmdm.facts["hints.commands"].value}
    assert by_cmd["mvn clean install -pl common,jwt,notification,plugins -am -DskipTests"][
        "kind"] == "build"
    assert by_cmd["mvn clean package"]["kind"] == "build"
    assert by_cmd["./hmdm_install.sh"]["kind"] == "script"
    assert len(by_cmd["./hmdm_install.sh"]["sources"]) == 2           # deduplicado
    joined = "docker exec mqtt-connections mosquitto_passwd -b /mosquitto/config/passwd user secret"
    assert by_cmd[joined]["kind"] == "ops"                           # multilínea unido


def test_hmdm_undefined_containers(hmdm):
    assert hmdm.facts["hints.undefined_containers"].value == ["mqtt-connections"]


@pytest.mark.parametrize("cmd,kind", [
    ("conan install . --build=missing -s build_type=Debug", "deps"),
    ("rm -rf build/CMakeCache.txt && cmake -B build -S .", "configure"),
    ("cmake --build build", "build"),
    ("ctest --test-dir build", "test"),
    ("./gradlew test", "test"),
    ("mvn -B verify", "test"),
    ("./mvnw spring-boot:run", "run"),
    ("docker-compose -f docker/db/docker-compose.yml up -d", "run"),
    ("docker restart mqtt-connections", "ops"),
    ("./step_001_create_image_and_publish.sh", "script"),
])
def test_classify_cmd(cmd, kind):
    from project_ai.adapters.base import classify_cmd
    assert classify_cmd(cmd) == kind


def test_multistage_dockerfile(tmp_path):
    root = make_tree(tmp_path, {"Dockerfile":
        "FROM maven:3.9.6-eclipse-temurin-17 AS build\nRUN mvn -q package\n"
        "FROM build AS test\n"
        "FROM eclipse-temurin:17-jre\nCOPY --from=build /app/target/app.jar /app.jar\n"})
    info = run_adapters(ProjectScanner(root, use_git=False), only=["hints"])
    assert info.requirements["jdk"].value == "17"
    assert info.requirements["jdk_runtime"].value == "17"
    assert info.requirements["maven"].value == "3.9.6"
    assert info.facts["hints.commands"].value[0]["cmd"] == "mvn -q package"


def test_netclient_hints(tmp_path):
    info = run_adapters(ProjectScanner(make_tree(tmp_path, NETCLIENT), use_git=False),
                        only=["hints"])
    prev = info.facts["hints.previous_cmake_builds"].value
    assert prev[0]["CMAKE_CXX_COMPILER"] == "/usr/bin/clang++"
    assert info.facts["hints.compile_commands"].value == ["build/Debug/compile_commands.json"]
    assert info.facts["hints.executables"].value == ["${workspaceFolder}/build/Debug/netclient"]
    cmds = [c["cmd"] for c in info.facts["hints.commands"].value]
    assert "conan install . --build=missing" in cmds
    assert "cmake --build --preset conan-debug" in cmds


def test_smarttomcat_comment_no_false_positive(tmp_path):
    """Comentario '<!-- Will be removed in Tomcat 10.1 -->' no debe producir ide.tomcat_local."""
    info = run_adapters(ProjectScanner(make_tree(tmp_path, SMARTTOMCAT_FP), use_git=False),
                        only=["hints"])
    assert "ide.tomcat_local" not in info.facts


def test_broken_adapter_does_not_crash(tmp_path, monkeypatch):
    from project_ai.adapters import hints
    monkeypatch.setattr(hints.HintsAdapter, "_docs",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    info = run_adapters(ProjectScanner(make_tree(tmp_path, HMDM), use_git=False),
                        only=["hints"])
    assert any("boom" in w for w in info.warnings)
