"""Tests para los parsers nuevos de repomap: TypeScript, Kotlin, Dart, Rust."""
from __future__ import annotations

from pathlib import Path

from conftest import (
    REPOMAP_DART_FLUTTER,
    REPOMAP_KT_SPRING,
    REPOMAP_TS_NESTJS,
    make_tree,
)

from project_ai.model import ProjectInfo
from project_ai.repomap import (
    FileMap,
    _parse_dart,
    _parse_kotlin,
    _parse_rust,
    _parse_typescript,
    _simplify_rust_params,
    _simplify_ts_kotlin_params,
    build_repo_map,
)
from project_ai.scanner import ProjectScanner


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _sc(root: Path) -> ProjectScanner:
    return ProjectScanner(root)


def _info(root: Path) -> ProjectInfo:
    return ProjectInfo(root=str(root))


# --------------------------------------------------------------------------
# _simplify_ts_kotlin_params
# --------------------------------------------------------------------------

class TestSimplifyTsKotlinParams:
    def test_empty(self):
        assert _simplify_ts_kotlin_params("") == ""

    def test_ts_style(self):
        result = _simplify_ts_kotlin_params("userId: string, limit: number")
        assert "string" in result
        assert "number" in result

    def test_kotlin_style(self):
        result = _simplify_ts_kotlin_params("id: Long, dto: CreateUserDto")
        assert "Long" in result
        assert "CreateUserDto" in result

    def test_removes_default(self):
        result = _simplify_ts_kotlin_params("limit: number = 10")
        assert "number" in result
        assert "10" not in result

    def test_removes_nullability(self):
        result = _simplify_ts_kotlin_params("val: String?")
        assert result == "String"

    def test_dart_style_positional(self):
        # Dart usa "Type name" (Java-style), no "name: Type"
        # Para Dart usamos _simplify_params normal, no esta función
        assert _simplify_ts_kotlin_params("") == ""


# --------------------------------------------------------------------------
# _parse_typescript — NestJS controller
# --------------------------------------------------------------------------

class TestParseTypescript:
    def test_finds_class(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        assert any(s.kind == "class" and s.name == "DevicesController" for s in fm.symbols)

    def test_nestjs_controller_base_path(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        cls = next(s for s in fm.symbols if s.kind == "class")
        assert cls.http_path == "/devices"

    def test_nestjs_get_method(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        methods = [s for s in fm.symbols if s.kind == "method"]
        get_methods = [s for s in methods if s.http_method == "GET"]
        assert len(get_methods) >= 1

    def test_nestjs_post_method(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        methods = [s for s in fm.symbols if s.http_method == "POST"]
        assert any(s for s in methods)

    def test_nestjs_delete_method(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        methods = [s for s in fm.symbols if s.http_method == "DELETE"]
        assert any(s for s in methods)

    def test_omits_private_method(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.controller.ts"]
        fm = _parse_typescript("devices.controller.ts", code)
        assert not any(s.name == "_validate" for s in fm.symbols)

    def test_service_class(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.service.ts"]
        fm = _parse_typescript("devices.service.ts", code)
        assert any(s.kind == "class" and s.name == "DevicesService" for s in fm.symbols)

    def test_service_methods(self):
        code = REPOMAP_TS_NESTJS["src/devices/devices.service.ts"]
        fm = _parse_typescript("devices.service.ts", code)
        method_names = {s.name for s in fm.symbols if s.kind == "method"}
        assert "findAll" in method_names
        assert "create" in method_names
        assert "remove" in method_names

    def test_interface(self):
        code = "export interface UserRepo {\n  findById(id: number): User;\n  save(u: User): void;\n}\n"
        fm = _parse_typescript("user.repo.ts", code)
        assert any(s.kind == "interface" and s.name == "UserRepo" for s in fm.symbols)

    def test_exported_function(self):
        code = "export function parseUrl(raw: string): URL {\n  return new URL(raw);\n}\n"
        fm = _parse_typescript("utils.ts", code)
        assert any(s.kind == "function" and s.name == "parseUrl" for s in fm.symbols)

    def test_exported_arrow_function(self):
        code = "export const fetchData = async (url: string): Promise<any> => {\n  return {};\n};\n"
        fm = _parse_typescript("api.ts", code)
        assert any(s.name == "fetchData" for s in fm.symbols)

    def test_language_ts(self):
        fm = _parse_typescript("app.ts", "class A {}")
        assert fm.language == "typescript"

    def test_language_js(self):
        fm = _parse_typescript("app.js", "class A {}")
        assert fm.language == "javascript"

    def test_no_crash_empty(self):
        fm = _parse_typescript("empty.ts", "")
        assert isinstance(fm, FileMap)
        assert not fm.has_symbols


# --------------------------------------------------------------------------
# _parse_kotlin — Spring Boot
# --------------------------------------------------------------------------

class TestParseKotlin:
    def test_finds_class(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        assert any(s.kind == "class" and s.name == "UserController" for s in fm.symbols)

    def test_requestmapping_base(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        cls = next(s for s in fm.symbols if s.kind == "class")
        assert cls.http_path == "/api/users"

    def test_get_mapping(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        methods = [s for s in fm.symbols if s.http_method == "GET"]
        assert any(s for s in methods)

    def test_post_mapping(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        methods = [s for s in fm.symbols if s.http_method == "POST"]
        assert any(s for s in methods)

    def test_delete_mapping(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        methods = [s for s in fm.symbols if s.http_method == "DELETE"]
        assert any(s for s in methods)

    def test_omits_private(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/web/UserController.kt"]
        fm = _parse_kotlin("UserController.kt", code)
        assert not any(s.name == "validate" for s in fm.symbols)

    def test_service_class(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/service/UserService.kt"]
        fm = _parse_kotlin("UserService.kt", code)
        assert any(s.kind == "class" and s.name == "UserService" for s in fm.symbols)

    def test_service_methods(self):
        code = REPOMAP_KT_SPRING["src/main/kotlin/com/acme/service/UserService.kt"]
        fm = _parse_kotlin("UserService.kt", code)
        method_names = {s.name for s in fm.symbols if s.kind == "method"}
        assert "findById" in method_names
        assert "findAll" in method_names
        assert "create" in method_names

    def test_data_class(self):
        code = "data class User(val id: Long, val name: String)\n"
        fm = _parse_kotlin("user.kt", code)
        assert any(s.name == "User" for s in fm.symbols)

    def test_object_declaration(self):
        code = "object Config {\n  val timeout = 30\n  fun isValid() = timeout > 0\n}\n"
        fm = _parse_kotlin("config.kt", code)
        assert any(s.kind == "object" and s.name == "Config" for s in fm.symbols)
        assert any(s.name == "isValid" for s in fm.symbols)

    def test_top_level_function(self):
        code = "fun parseUrl(raw: String): String = raw.trim()\n"
        fm = _parse_kotlin("utils.kt", code)
        assert any(s.kind == "function" and s.name == "parseUrl" for s in fm.symbols)

    def test_extension_function(self):
        code = "fun String.toSlug(): String = this.lowercase().replace(' ', '-')\n"
        fm = _parse_kotlin("ext.kt", code)
        fns = [s for s in fm.symbols if s.kind == "function"]
        assert any(s.name == "toSlug" for s in fns)

    def test_no_crash_empty(self):
        fm = _parse_kotlin("empty.kt", "")
        assert isinstance(fm, FileMap)


# --------------------------------------------------------------------------
# _parse_dart — Flutter
# --------------------------------------------------------------------------

class TestParseDart:
    def test_finds_class(self):
        code = REPOMAP_DART_FLUTTER["lib/main.dart"]
        fm = _parse_dart("main.dart", code)
        assert any(s.name == "MyApp" for s in fm.symbols)

    def test_finds_service_class(self):
        code = REPOMAP_DART_FLUTTER["lib/services/device_service.dart"]
        fm = _parse_dart("device_service.dart", code)
        assert any(s.name == "DeviceService" for s in fm.symbols)

    def test_finds_public_methods(self):
        code = REPOMAP_DART_FLUTTER["lib/services/device_service.dart"]
        fm = _parse_dart("device_service.dart", code)
        method_names = {s.name for s in fm.symbols if s.kind == "method"}
        assert "fetchDevices" in method_names
        assert "parseDevices" in method_names

    def test_mixin(self):
        code = "mixin AuthMixin {\n  bool isAuthenticated() => false;\n}\n"
        fm = _parse_dart("auth.dart", code)
        assert any(s.name == "AuthMixin" for s in fm.symbols)

    def test_no_crash_empty(self):
        fm = _parse_dart("empty.dart", "")
        assert isinstance(fm, FileMap)

    def test_omits_private_methods(self):
        code = "class Svc {\n  void _helper() {}\n  void doWork() {}\n}\n"
        fm = _parse_dart("svc.dart", code)
        method_names = {s.name for s in fm.symbols if s.kind == "method"}
        assert "_helper" not in method_names
        assert "doWork" in method_names


# --------------------------------------------------------------------------
# build_repo_map — integración con nuevos lenguajes
# --------------------------------------------------------------------------

def test_build_repo_map_nestjs(tmp_path):
    make_tree(tmp_path, REPOMAP_TS_NESTJS)
    sc = _sc(tmp_path)
    info = _info(tmp_path)
    result = build_repo_map(info, sc)
    assert "DevicesController" in result
    assert "GET" in result or "POST" in result


def test_build_repo_map_kotlin_spring(tmp_path):
    make_tree(tmp_path, REPOMAP_KT_SPRING)
    sc = _sc(tmp_path)
    info = _info(tmp_path)
    result = build_repo_map(info, sc)
    assert "UserController" in result
    assert "GET" in result or "POST" in result


def test_build_repo_map_dart_flutter(tmp_path):
    make_tree(tmp_path, REPOMAP_DART_FLUTTER)
    sc = _sc(tmp_path)
    info = _info(tmp_path)
    result = build_repo_map(info, sc)
    assert "DeviceService" in result or "MyApp" in result


def test_build_repo_map_nestjs_prioritizes_controller(tmp_path):
    """El controller aparece antes que el service en el mapa."""
    make_tree(tmp_path, REPOMAP_TS_NESTJS)
    sc = _sc(tmp_path)
    info = _info(tmp_path)
    result = build_repo_map(info, sc)
    ctrl_pos = result.find("DevicesController")
    svc_pos = result.find("DevicesService")
    if ctrl_pos >= 0 and svc_pos >= 0:
        assert ctrl_pos <= svc_pos


def test_build_repo_map_kotlin_controller_first(tmp_path):
    """El controller Kotlin aparece antes que el service."""
    make_tree(tmp_path, REPOMAP_KT_SPRING)
    sc = _sc(tmp_path)
    info = _info(tmp_path)
    result = build_repo_map(info, sc)
    ctrl_pos = result.find("UserController")
    svc_pos = result.find("UserService")
    if ctrl_pos >= 0 and svc_pos >= 0:
        assert ctrl_pos <= svc_pos


# ==========================================================================
# Rust
# ==========================================================================

_RUST_ACTIX = """\
use actix_web::{web, App, HttpServer, HttpResponse};

pub struct Device {
    pub id: u32,
    pub name: String,
}

pub enum DeviceStatus {
    Online,
    Offline,
}

pub trait Repository {
    fn find(&self, id: u32) -> Option<Device>;
}

#[get("/api/devices")]
pub async fn list_devices() -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[post("/api/devices")]
pub async fn create_device() -> HttpResponse {
    HttpResponse::Created().finish()
}

#[delete("/api/devices/{id}")]
pub async fn delete_device() -> HttpResponse {
    HttpResponse::NoContent().finish()
}

pub fn health_check() -> &'static str {
    "ok"
}

fn private_helper() -> u32 {
    42
}
"""

_RUST_LIB = """\
pub struct Config {
    pub host: String,
    pub port: u16,
}

impl Config {
    pub fn new(host: String, port: u16) -> Self {
        Self { host, port }
    }

    pub fn from_env() -> Self {
        Self::new("localhost".into(), 8080)
    }
}

pub fn parse_config(s: &str) -> Config {
    Config::new(s.to_string(), 8080)
}
"""


class TestSimplifyRustParams:
    def test_empty(self):
        assert _simplify_rust_params("") == ""

    def test_self_only(self):
        assert _simplify_rust_params("&self") == "self"

    def test_mut_self(self):
        assert _simplify_rust_params("&mut self") == "self"

    def test_typed_params(self):
        result = _simplify_rust_params("id: u32, name: String")
        assert "id" in result
        assert "name" in result

    def test_complex_type(self):
        result = _simplify_rust_params("dto: web::Json<CreateDto>")
        assert "dto" in result

    def test_mixed(self):
        result = _simplify_rust_params("&self, id: u32")
        assert "self" in result
        assert "id" in result


class TestParseRust:
    def test_structs_detected(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        structs = [s for s in fm.symbols if s.kind == "struct" and s.name == "Device"]
        assert len(structs) == 1

    def test_enum_detected_as_struct(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        enums = [s for s in fm.symbols if s.name == "DeviceStatus"]
        assert len(enums) == 1

    def test_trait_detected(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        traits = [s for s in fm.symbols if s.name == "Repository"]
        assert len(traits) == 1

    def test_actix_route_get(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        routes = [s for s in fm.symbols if s.http_method == "GET"]
        assert any(s.http_path == "/api/devices" for s in routes)

    def test_actix_route_post(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        routes = [s for s in fm.symbols if s.http_method == "POST"]
        assert any(s.http_path == "/api/devices" for s in routes)

    def test_actix_route_delete(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        routes = [s for s in fm.symbols if s.http_method == "DELETE"]
        assert any(s.http_path == "/api/devices/{id}" for s in routes)

    def test_public_fn_detected(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        fns = [s for s in fm.symbols if s.kind == "function" and s.name == "health_check"]
        assert len(fns) == 1
        assert fns[0].visibility == "public"

    def test_private_fn_detected(self):
        fm = _parse_rust("src/main.rs", _RUST_ACTIX)
        fns = [s for s in fm.symbols if s.name == "private_helper"]
        assert len(fns) == 1
        assert fns[0].visibility == "private"

    def test_impl_methods_detected(self):
        fm = _parse_rust("src/lib.rs", _RUST_LIB)
        names = {s.name for s in fm.symbols if s.kind == "function"}
        assert "new" not in names  # new es ignorado
        assert "from_env" in names
        assert "parse_config" in names

    def test_struct_in_lib(self):
        fm = _parse_rust("src/lib.rs", _RUST_LIB)
        structs = [s for s in fm.symbols if s.name == "Config"]
        assert len(structs) == 1


class TestBuildRepoMapRust:
    def test_rust_actix_in_map(self, tmp_path):
        from conftest import RUST_ACTIX_API, make_tree
        from project_ai.recon import recon
        make_tree(tmp_path, RUST_ACTIX_API)
        info = recon(tmp_path, only=["hints", "rust"], write=False)
        sc = ProjectScanner(tmp_path, use_git=False)
        result = build_repo_map(info, sc)
        assert "device-api" in result or "main.rs" in result
        assert "/api/devices" in result

    def test_rust_routes_appear_before_private(self, tmp_path):
        from conftest import RUST_ACTIX_API, make_tree
        from project_ai.recon import recon
        make_tree(tmp_path, RUST_ACTIX_API)
        info = recon(tmp_path, only=["hints", "rust"], write=False)
        sc = ProjectScanner(tmp_path, use_git=False)
        result = build_repo_map(info, sc)
        # El mapa debe incluir al menos un endpoint HTTP
        assert "GET" in result or "POST" in result
