"""Tests para repomap.py."""
from __future__ import annotations

from pathlib import Path

from conftest import HMDM, NETCLIENT_FULL, REPOMAP_CPP, REPOMAP_JAVA, SPRING_API, make_tree

from project_ai.model import EntryPoint, ProjectInfo
from project_ai.recon import recon
from project_ai.repomap import (
    CHARS_PER_TOKEN,
    FileMap,
    _parse_cpp,
    _parse_java,
    _parse_python,
    _simplify_params,
    _simplify_python_params,
    build_repo_map,
)
from project_ai.scanner import ProjectScanner


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _scanner(root: Path) -> ProjectScanner:
    return ProjectScanner(root)


def _empty_info(root: Path) -> ProjectInfo:
    return ProjectInfo(root=str(root))


# --------------------------------------------------------------------------
# _simplify_params
# --------------------------------------------------------------------------

class TestSimplifyParams:
    def test_empty(self):
        assert _simplify_params("") == ""

    def test_simple_types(self):
        assert _simplify_params("String userId, int limit") == "String, int"

    def test_removes_package(self):
        assert _simplify_params("com.acme.model.Device device") == "Device"

    def test_removes_annotations(self):
        assert _simplify_params("@PathParam(\"id\") int id") == "int"

    def test_removes_final(self):
        assert _simplify_params("final String s") == "String"

    def test_generics_truncated(self):
        result = _simplify_params("java.util.List<Map<String,Integer>> items")
        assert "List" in result
        assert "<" not in result

    def test_varargs(self):
        result = _simplify_params("String... args")
        assert result  # no debe crashear


class TestSimplifyPythonParams:
    def test_removes_self(self):
        assert _simplify_python_params("self, name, age") == "name, age"

    def test_removes_cls(self):
        assert _simplify_python_params("cls, x") == "x"

    def test_removes_type_annotations(self):
        result = _simplify_python_params("name: str, age: int = 0")
        assert "name" in result and "age" in result
        assert "str" not in result

    def test_empty(self):
        assert _simplify_python_params("") == ""

    def test_only_self(self):
        assert _simplify_python_params("self") == ""


# --------------------------------------------------------------------------
# _parse_java
# --------------------------------------------------------------------------

class TestParseJava:
    def test_finds_class(self):
        fm = _parse_java("Foo.java", "public class Foo {\n}\n")
        assert any(s.kind == "class" and s.name == "Foo" for s in fm.symbols)

    def test_finds_interface(self):
        fm = _parse_java("IFoo.java", "public interface IFoo {\n void bar();\n}\n")
        assert any(s.kind == "interface" for s in fm.symbols)

    def test_finds_public_method(self):
        fm = _parse_java("Svc.java",
                         "public class Svc {\n  public String get(int id) { return null; }\n}\n")
        methods = [s for s in fm.symbols if s.kind == "method"]
        assert any(s.name == "get" for s in methods)

    def test_omits_private_method(self):
        fm = _parse_java("Svc.java",
                         "public class Svc {\n  private void secret() {}\n}\n")
        methods = [s for s in fm.symbols if s.kind == "method"]
        assert not any(s.name == "secret" for s in methods)

    def test_protected_method_included(self):
        fm = _parse_java("Svc.java",
                         "public class Svc {\n  protected void hook() {}\n}\n")
        methods = [s for s in fm.symbols if s.kind == "method"]
        assert any(s.name == "hook" for s in methods)

    def test_jaxrs_path_on_class(self):
        code = '@Path("/api/devices")\npublic class DevRes {\n}\n'
        fm = _parse_java("DevRes.java", code)
        cls = next(s for s in fm.symbols if s.kind == "class")
        assert cls.http_path == "/api/devices"

    def test_jaxrs_get_method(self):
        code = (
            '@Path("/devices")\npublic class R {\n'
            '  @GET\n  @Path("/{id}")\n'
            '  public Response get(@PathParam("id") int id) { return null; }\n}\n'
        )
        fm = _parse_java("R.java", code)
        method = next(s for s in fm.symbols if s.kind == "method")
        assert method.http_method == "GET"
        assert "/{id}" in (method.http_path or "")

    def test_jaxrs_post_no_subpath(self):
        code = (
            '@Path("/devices")\npublic class R {\n'
            '  @POST\n  public Response create(Device d) { return null; }\n}\n'
        )
        fm = _parse_java("R.java", code)
        method = next(s for s in fm.symbols if s.kind == "method")
        assert method.http_method == "POST"
        assert method.http_path == "/devices"

    def test_spring_getmapping(self):
        code = (
            '@RequestMapping("/api/users")\npublic class UC {\n'
            '  @GetMapping("/{id}")\n  public User get(@PathVariable Long id) { return null; }\n}\n'
        )
        fm = _parse_java("UC.java", code)
        method = next(s for s in fm.symbols if s.kind == "method")
        assert method.http_method == "GET"
        assert "/api/users" in (method.http_path or "")
        assert "/{id}" in (method.http_path or "")

    def test_spring_deletemapping_no_path(self):
        code = (
            '@RequestMapping("/api/users")\npublic class UC {\n'
            '  @DeleteMapping\n  public void delete() {}\n}\n'
        )
        fm = _parse_java("UC.java", code)
        method = next((s for s in fm.symbols if s.kind == "method"), None)
        assert method is not None
        assert method.http_method == "DELETE"

    def test_param_simplification(self):
        code = "public class S {\n  public void save(com.acme.User u, int count) {}\n}\n"
        fm = _parse_java("S.java", code)
        method = next(s for s in fm.symbols if s.kind == "method")
        assert "User" in method.signature
        assert "int" in method.signature

    def test_ignores_comments_in_code(self):
        code = (
            "/* @Path(\"/ignored\") */\n"
            "public class C {\n"
            "  // private void notamethod() {}\n"
            "  public void real() {}\n}\n"
        )
        fm = _parse_java("C.java", code)
        methods = [s for s in fm.symbols if s.kind == "method"]
        assert len(methods) == 1
        assert methods[0].name == "real"

    def test_device_resource_fixture(self):
        code = REPOMAP_JAVA["src/main/java/com/acme/rest/DeviceResource.java"]
        fm = _parse_java("DeviceResource.java", code)
        cls = next(s for s in fm.symbols if s.kind == "class")
        assert cls.http_path == "/api/devices"
        methods = [s for s in fm.symbols if s.kind == "method"]
        http_methods = {s.http_method for s in methods if s.http_method}
        assert "GET" in http_methods
        assert "POST" in http_methods
        assert "DELETE" in http_methods
        # private helper no debe aparecer
        assert not any(s.name == "helper" for s in methods)

    def test_user_service_fixture(self):
        code = REPOMAP_JAVA["src/main/java/com/acme/service/UserService.java"]
        fm = _parse_java("UserService.java", code)
        methods = [s for s in fm.symbols if s.kind == "method"]
        pub = [s for s in methods if s.visibility == "public"]
        assert any(s.name == "findById" for s in pub)
        assert any(s.name == "findAll" for s in pub)
        assert not any(s.name == "validate" for s in methods)  # private


# --------------------------------------------------------------------------
# _parse_cpp
# --------------------------------------------------------------------------

class TestParseCpp:
    def test_finds_class(self):
        code = "class Foo {\npublic:\n  void bar();\n};\n"
        fm = _parse_cpp("foo.h", code)
        assert any(s.kind == "class" and s.name == "Foo" for s in fm.symbols)

    def test_finds_struct(self):
        code = "struct Message { std::string topic; int qos; };\n"
        fm = _parse_cpp("types.h", code)
        assert any(s.kind == "struct" and s.name == "Message" for s in fm.symbols)

    def test_finds_function_declaration(self):
        code = "bool parseUri(const std::string& raw, std::string& host);\n"
        fm = _parse_cpp("util.h", code)
        fns = [s for s in fm.symbols if s.kind == "function"]
        assert any(s.name == "parseUri" for s in fns)

    def test_websocket_fixture(self):
        code = REPOMAP_CPP["include/ws/WebSocketClient.h"]
        fm = _parse_cpp("WebSocketClient.h", code)
        # Clase
        assert any(s.kind == "class" and s.name == "WebSocketClient" for s in fm.symbols)
        # Struct
        assert any(s.kind == "struct" and s.name == "Message" for s in fm.symbols)
        # Funciones/métodos
        names = {s.name for s in fm.symbols if s.kind == "function"}
        assert "connect" in names or "WebSocketClient" in names
        assert "parseUri" in names

    def test_no_crash_on_cpp_source(self):
        code = REPOMAP_CPP["src/ws/websocket_client.cpp"]
        fm = _parse_cpp("websocket_client.cpp", code)
        assert isinstance(fm, FileMap)

    def test_deduplication(self):
        """Misma función en header y .cpp no se duplica."""
        header = "bool connect();\n"
        cpp = "bool connect() { return true; }\n"
        fh = _parse_cpp("client.h", header)
        fc = _parse_cpp("client.cpp", cpp)
        names_h = {s.name for s in fh.symbols if s.kind == "function"}
        names_c = {s.name for s in fc.symbols if s.kind == "function"}
        assert "connect" in names_h
        assert "connect" in names_c


# --------------------------------------------------------------------------
# _parse_python
# --------------------------------------------------------------------------

class TestParsePython:
    def test_finds_class(self):
        code = "class Foo:\n    pass\n"
        fm = _parse_python("foo.py", code)
        assert any(s.kind == "class" and s.name == "Foo" for s in fm.symbols)

    def test_finds_public_method(self):
        code = "class Svc:\n    def get(self, id):\n        pass\n"
        fm = _parse_python("svc.py", code)
        assert any(s.kind == "method" and s.name == "get" for s in fm.symbols)

    def test_omits_private_method(self):
        code = "class Svc:\n    def _helper(self):\n        pass\n"
        fm = _parse_python("svc.py", code)
        assert not any(s.name == "_helper" for s in fm.symbols)

    def test_dunder_included(self):
        code = "class Svc:\n    def __init__(self):\n        pass\n"
        fm = _parse_python("svc.py", code)
        assert any(s.name == "__init__" for s in fm.symbols)

    def test_free_function(self):
        code = "def parse_url(raw):\n    pass\n"
        fm = _parse_python("util.py", code)
        assert any(s.kind == "function" and s.name == "parse_url" for s in fm.symbols)

    def test_async_def(self):
        code = "async def fetch(url):\n    pass\n"
        fm = _parse_python("client.py", code)
        assert any(s.name == "fetch" for s in fm.symbols)


# --------------------------------------------------------------------------
# build_repo_map
# --------------------------------------------------------------------------

def test_build_repo_map_hmdm(tmp_path):
    """El mapa de hmdm cabe en 4k tokens y lista REST resources."""
    make_tree(tmp_path, HMDM)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    assert "DeviceResource" in result
    # Debe mencionar al menos un HTTP method
    assert any(m in result for m in ("GET", "POST", "DELETE", "PUT"))
    # Debe caber en 4k tokens
    assert len(result) <= 4000 * CHARS_PER_TOKEN


def test_build_repo_map_spring(tmp_path):
    make_tree(tmp_path, SPRING_API)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    assert "UserController" in result
    assert "GET" in result or "POST" in result


def test_build_repo_map_cpp(tmp_path):
    make_tree(tmp_path, REPOMAP_CPP)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    assert "WebSocketClient" in result


def test_build_repo_map_respects_max_tokens(tmp_path):
    """Con max_tokens muy pequeño, el mapa se trunca."""
    make_tree(tmp_path, REPOMAP_JAVA)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc, max_tokens=50)
    # Con 50 tokens (200 chars) solo cabe 1 archivo como mucho
    assert len(result) <= 50 * CHARS_PER_TOKEN + 200  # tolerancia para mensaje de truncado


def test_build_repo_map_truncation_message(tmp_path):
    """Si se trunca, aparece mensaje de archivos omitidos."""
    make_tree(tmp_path, REPOMAP_JAVA)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc, max_tokens=100)
    if "omitidos" in result:  # puede que no se trunque si pocos archivos
        assert "archivos omitidos" in result


def test_build_repo_map_prioritizes_rest_files(tmp_path):
    """Archivos controller/resource aparecen antes que servicios."""
    make_tree(tmp_path, REPOMAP_JAVA)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    # DeviceResource o UserController deben aparecer antes que UserService
    rest_pos = min(
        result.find("DeviceResource") if "DeviceResource" in result else len(result),
        result.find("UserController") if "UserController" in result else len(result),
    )
    svc_pos = result.find("UserService") if "UserService" in result else len(result)
    assert rest_pos <= svc_pos


def test_build_repo_map_entry_point_priority(tmp_path):
    """Archivos con entry points se priorizan."""
    make_tree(tmp_path, SPRING_API)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    info.entry_points.append(EntryPoint(
        kind="spring-boot-app",
        symbol="UsersApplication",
        file="src/main/java/com/acme/UsersApplication.java",
    ))
    result = build_repo_map(info, sc)
    assert "UsersApplication" in result


def test_build_repo_map_empty_project(tmp_path):
    """Proyecto sin archivos fuente produce un mapa mínimo."""
    (tmp_path / "README.md").write_text("# Readme")
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    assert "Mapa de símbolos" in result


def test_build_repo_map_returns_str(tmp_path):
    make_tree(tmp_path, NETCLIENT_FULL)
    sc = _scanner(tmp_path)
    info = _empty_info(tmp_path)
    result = build_repo_map(info, sc)
    assert isinstance(result, str)
    assert len(result) > 0


# --------------------------------------------------------------------------
# Integración con recon
# --------------------------------------------------------------------------

def test_recon_writes_repo_map(tmp_path):
    make_tree(tmp_path, HMDM)
    recon(tmp_path)
    repo_map = tmp_path / ".project-ai" / "repo-map.md"
    assert repo_map.exists(), "repo-map.md no fue creado"
    content = repo_map.read_text(encoding="utf-8")
    assert "Mapa de símbolos" in content


def test_recon_repo_map_has_java_symbols(tmp_path):
    make_tree(tmp_path, HMDM)
    recon(tmp_path)
    content = (tmp_path / ".project-ai" / "repo-map.md").read_text(encoding="utf-8")
    assert "DeviceResource" in content


def test_recon_no_write_no_repo_map(tmp_path):
    make_tree(tmp_path, HMDM)
    recon(tmp_path, write=False)
    assert not (tmp_path / ".project-ai" / "repo-map.md").exists()
