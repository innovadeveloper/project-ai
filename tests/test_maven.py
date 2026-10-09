import pytest
from conftest import HMDM, SPRING_API, make_tree

from project_ai.adapters import run_adapters
from project_ai.adapters.maven import _parse_endpoints
from project_ai.model import SourcePriority as P
from project_ai.scanner import ProjectScanner


@pytest.fixture
def hmdm(tmp_path):
    return run_adapters(ProjectScanner(make_tree(tmp_path, HMDM), use_git=False))


@pytest.fixture
def spring(tmp_path):
    return run_adapters(ProjectScanner(make_tree(tmp_path, SPRING_API), use_git=False))


# ------------------------------------------------------------------ hmdm (WAR)

def test_hmdm_detection_and_modules(hmdm):
    assert [(s.adapter, s.root) for s in hmdm.stacks] == [("maven", ".")]
    kinds = {m.name: m.kind for m in hmdm.modules}
    assert kinds == {"hmdm": "aggregator", "hmdm-common": "library",
                     "jwt": "library", "server": "war"}
    server = next(m for m in hmdm.modules if m.name == "server")
    assert set(server.depends_on) == {"hmdm", "hmdm-common", "jwt"}
    assert hmdm.facts["maven.build_order"].value == ["hmdm", "hmdm-common", "jwt", "server"]
    assert hmdm.facts["maven.artifacts"].value == [
        {"module": "server", "path": "server/target/launcher.war", "kind": "war"}]
    assert hmdm.facts["maven.profiles"].value == ["release"]


def test_hmdm_not_spring_boot_and_javax(hmdm):
    assert "framework" not in hmdm.facts
    assert hmdm.facts["java.ee_namespace"].value == "javax"
    # tomcat: Docker (CI) dice 9 y maven lo deduce (HEURISTIC) => coincide
    assert hmdm.requirements["tomcat"].value == "9"
    # el Tomcat del IDE (10.1) es incompatible con javax => aviso claro
    assert any("javax" in w and "10.1" in w for w in hmdm.warnings), hmdm.warnings


def test_hmdm_jdk_and_ceiling(hmdm):
    jdk = hmdm.requirements["jdk"]
    assert jdk.value == "8"
    assert any(e.file == "pom.xml" for e in jdk.evidence)       # pom aporta evidencia
    ceil = hmdm.facts["jdk_ceiling"]
    assert ceil.value == "16" and "lombok 1.18.12" in ceil.note


def test_hmdm_risks(hmdm):
    f = hmdm.facts
    assert f["maven.repositories"].value == [
        {"id": "private", "url": "https://nexus.example.com/repository/maven-releases/"}]
    assert f["maven.system_deps"].value[0]["dep"] == "com.vendor:legacy"
    assert f["maven.external_snapshots"].value == ["com.other:lib:2.0-SNAPSHOT"]
    assert f["maven.notable_plugins"].value[0].startswith("maven-antrun-plugin")
    assert f["db.sql_scripts"].value == ["install/sql/hmdm_init.en.sql"]


def test_hmdm_services(hmdm):
    kinds = {s.kind: s.fact for s in hmdm.services}
    assert set(kinds) == {"postgresql", "mqtt"}
    assert kinds["postgresql"].value == "13"            # versión del compose
    files = {e.file for e in kinds["postgresql"].evidence}
    assert {"common/pom.xml", "server/src/main/resources/app.properties"} <= files


def test_hmdm_entry_points_and_endpoints(hmdm):
    eps = {(e.kind, e.symbol) for e in hmdm.entry_points}
    assert ("servlet-listener", "Initializer") in eps
    assert ("web.xml-listener", "com.hmdm.guice.Initializer") in eps
    got = [(e.method, e.path, e.handler) for e in hmdm.endpoints]
    assert got == [("GET", "/private/devices/search", "DeviceResource#search"),
                   ("POST", "/private/devices", "DeviceResource#create"),
                   ("DELETE", "/private/devices/{id}", "DeviceResource#delete")]


def test_hmdm_commands(hmdm):
    c = hmdm.commands
    assert c["build"].shell == "mvn -DskipTests package"
    assert c["build_app"].shell == "mvn -pl server -am -DskipTests package"
    assert "server/target/launcher.war" in c["run"].shell and "catalina.sh" in c["run"].shell
    assert "generate" in c                      # por maven-antrun-plugin
    assert c["build"].ide_hint.startswith("IntelliJ")


# ------------------------------------------------------------------ Spring Boot 3

def test_spring_basics(spring):
    assert spring.facts["framework"].value == "spring-boot 3.2.1"
    assert [m.kind for m in spring.modules] == ["spring-boot-app"]
    jdk = spring.requirements["jdk"]
    assert jdk.value == "21" and jdk.priority == P.BUILD
    assert any(a["value"] == "17" for a in jdk.alternatives)
    assert spring.requirements["maven"].value == "3.9.6"
    assert spring.requirements["maven"].priority == P.EXPLICIT
    assert spring.facts["java.ee_namespace"].value == "jakarta"
    assert "jdk_ceiling" not in spring.facts       # lombok gestionado por el BOM: sin versión


def test_spring_ignores_test_poms(spring):
    assert len(spring.modules) == 1


def test_spring_services_and_db(spring):
    assert [s.kind for s in spring.services] == ["postgresql"]
    assert spring.facts["db.migrations"].value == ["flyway-core"]


def test_spring_endpoints(spring):
    got = [(e.method, e.path, e.handler) for e in spring.endpoints]
    assert got == [("GET", "/api/users/{id}", "UserController#get"),
                   ("POST", "/api/users", "UserController#create"),
                   ("GET", "/api/users/search", "UserController#search"),
                   ("DELETE", "/api/users/{id}", "UserController#delete")]
    kinds = {e.kind for e in spring.entry_points}
    assert {"spring-boot-app", "main-function"} <= kinds


def test_spring_commands(spring):
    c = spring.commands
    assert c["build"].shell == "./mvnw -DskipTests package"
    assert c["run"].shell == "./mvnw spring-boot:run"
    assert "build_app" not in c
    assert "generate" in c                      # openapi-generator


# ------------------------------------------------------------------ casos sueltos

def test_endpoint_parser_constants_and_interface():
    src = """@Path(Constants.API)
public interface Api {
    @GET
    @Path("ping")
    String ping();
}""".splitlines()
    eps = _parse_endpoints("Api.java", src)
    assert [(e.method, e.path) for e in eps] == [("GET", "/{Constants.API}/ping")]


def test_invalid_pom_is_warning_not_crash(tmp_path):
    root = make_tree(tmp_path, {"pom.xml": "<project><artifactId>x</artifactId>",
                                "a/pom.xml": "<project><artifactId>a</artifactId></project>"})
    info = run_adapters(ProjectScanner(root, use_git=False))
    assert any("XML inválido" in w for w in info.warnings)
    assert [m.name for m in info.modules] == ["a"]
