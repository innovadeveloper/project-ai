"""Utilidades de test: crear árboles de proyecto falsos en tmp_path."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def make_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return root


def git_init(root: Path) -> None:
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a],  # noqa: E731
                                    check=True, capture_output=True)
    run("init", "-q")
    run("add", "-A", "-f")          # -f: versiona incluso lo ignorado (como netclient)


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git no instalado")


CMAKE_CACHE = """\
# This is the CMakeCache file.
CMAKE_BUILD_TYPE:STRING=Debug
CMAKE_CXX_COMPILER:FILEPATH=/usr/bin/clang++
CMAKE_GENERATOR:INTERNAL=Unix Makefiles
CMAKE_TOOLCHAIN_FILE:FILEPATH=generators/conan_toolchain.cmake
"""

# Imita netclient: C++ + CMake + Conan con carpetas de build versionadas.
NETCLIENT = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.15)\nproject(netclient CXX)\n",
    "CMakeUserPresets.json": '{"include": ["build/Debug/generators/CMakePresets.json"]}',
    "conanfile.py": "from conan import ConanFile\nclass C(ConanFile):\n    pass\n",
    "main.cpp": "int main() { return 0; }\n",
    "include/netclient/client.h": "#pragma once\nclass Client {};\n",
    "src/client.cpp": '#include "netclient/client.h"\n',
    "readme.md": "# netclient\n\n```bash\nconan install . \\\n  --build=missing\n"
                 "cmake --preset conan-debug\ncmake --build --preset conan-debug\n```\n",
    "new_module_c++.sh": "#!/bin/sh\necho new\n",
    "bin/run.sh": "#!/bin/sh\n./build/Debug/netclient\n",      # bin legítimo
    ".DS_Store": b"\x00\x01binary",
    ".cache/clangd/index/client.cpp.idx": b"\x00idx",
    ".vscode/launch.json": '{"configurations": [{"type": "lldb",\n'
                           '  "program": "${workspaceFolder}/build/Debug/netclient"}]}\n',
    "build/Debug/CMakeCache.txt": CMAKE_CACHE,
    "build/Debug/Makefile": "all:\n",
    "build/Debug/CMakeFiles/foo.cmake": "set(X 1)\n",
    "build/Debug/compile_commands.json": "[]\n",
    "build/Debug/generators/CMakePresets.json": "{}\n",
    "build/Debug/generators/conan_toolchain.cmake": "set(Y 1)\n",
    "build/android/build/Release/generators/CMakePresets.json": "{}\n",
    "build-android/CMakeCache.txt": CMAKE_CACHE,
    "build-android/Makefile": "all:\n",
}

# Imita hmdm: Maven multi-módulo, WAR en Tomcat, Docker, Postgres, docs .txt
HMDM = {
    "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.hmdm</groupId>
  <artifactId>hmdm</artifactId>
  <version>5.30.3</version>
  <packaging>pom</packaging>
  <properties>
    <maven.compiler.source>1.8</maven.compiler.source>
    <maven.compiler.target>1.8</maven.compiler.target>
    <jersey.version>2.35</jersey.version>
    <lombok.version>1.18.12</lombok.version>
  </properties>
  <modules>
    <module>common</module>
    <module>jwt</module>
    <module>server</module>
  </modules>
  <profiles><profile><id>release</id></profile></profiles>
  <repositories>
    <repository><id>private</id><url>https://nexus.example.com/repository/maven-releases/</url></repository>
    <repository><id>central</id><url>https://repo.maven.apache.org/maven2</url></repository>
  </repositories>
</project>
""",
    "common/pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>com.hmdm</groupId><artifactId>hmdm</artifactId><version>5.30.3</version></parent>
  <artifactId>hmdm-common</artifactId>
  <dependencies>
    <dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId>
      <version>${lombok.version}</version></dependency>
    <dependency><groupId>javax.servlet</groupId><artifactId>javax.servlet-api</artifactId>
      <version>3.1.0</version><scope>provided</scope></dependency>
    <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>
      <version>42.2.5</version></dependency>
    <dependency><groupId>org.glassfish.jersey.containers</groupId>
      <artifactId>jersey-container-servlet</artifactId><version>${jersey.version}</version></dependency>
  </dependencies>
</project>
""",
    "jwt/pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>com.hmdm</groupId><artifactId>hmdm</artifactId><version>5.30.3</version></parent>
  <artifactId>jwt</artifactId>
  <dependencies>
    <dependency><groupId>com.hmdm</groupId><artifactId>hmdm-common</artifactId>
      <version>${project.version}</version></dependency>
    <dependency><groupId>com.vendor</groupId><artifactId>legacy</artifactId><version>1.0</version>
      <scope>system</scope><systemPath>${project.basedir}/lib/legacy.jar</systemPath></dependency>
  </dependencies>
</project>
""",
    "server/pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>com.hmdm</groupId><artifactId>hmdm</artifactId><version>5.30.3</version></parent>
  <artifactId>server</artifactId>
  <packaging>war</packaging>
  <dependencies>
    <dependency><groupId>com.hmdm</groupId><artifactId>hmdm-common</artifactId>
      <version>${project.version}</version></dependency>
    <dependency><groupId>com.hmdm</groupId><artifactId>jwt</artifactId>
      <version>${project.version}</version></dependency>
    <dependency><groupId>org.eclipse.paho</groupId><artifactId>org.eclipse.paho.client.mqttv3</artifactId>
      <version>1.2.5</version></dependency>
    <dependency><groupId>com.other</groupId><artifactId>lib</artifactId><version>2.0-SNAPSHOT</version></dependency>
  </dependencies>
  <build>
    <finalName>launcher</finalName>
    <plugins><plugin><artifactId>maven-antrun-plugin</artifactId></plugin></plugins>
  </build>
</project>
""",
    "server/src/main/webapp/WEB-INF/web.xml":
        "<web-app>\n  <listener>\n    <listener-class>com.hmdm.guice.Initializer</listener-class>\n"
        "  </listener>\n</web-app>\n",
    "server/src/main/java/com/hmdm/guice/Initializer.java":
        "package com.hmdm.guice;\n\npublic class Initializer extends GuiceServletContextListener {\n}\n",
    "server/src/main/java/com/hmdm/rest/resource/DeviceResource.java": """package com.hmdm.rest.resource;

import javax.ws.rs.*;
import javax.servlet.http.HttpServletRequest;

/**
 * Devices. @Path("/fake") @GET en javadoc se ignora
 */
@Singleton
@Path("/private/devices")
public class DeviceResource {
    private final String x;

    @GET
    @Path("/search")
    @Produces(MediaType.APPLICATION_JSON)
    public Response search(@QueryParam("q") String q) {
        return null;
    }

    @POST
    public Response create(Device d) { return null; }

    @DELETE @Path("/{id}")
    public Response delete(@PathParam("id") int id) { return null; }

    @Path("/sub")
    public SubResource sub() { return null; }
}
""",
    "server/src/main/resources/app.properties": "jdbc.url=jdbc:postgresql://localhost:5432/hmdm\n",
    "install/sql/hmdm_init.en.sql": "CREATE TABLE x();\n",
    "context.xml": "<Context/>\n",
    # version fuera de comentarios (catalina.properties) para no activar el falso positivo
    ".smarttomcat/server/conf/catalina.properties": "server.info=Apache Tomcat/10.1\nserver.number=10.1.0.0\n",
    ".smarttomcat/server/conf/web.xml": "<!-- default web.xml -->\n<web-app version=\"6.0\"></web-app>\n",
    "README.md": "## Build\n\n```bash\n"
                 "mvn clean install -pl common,jwt,notification,plugins -am -DskipTests\n"
                 "mvn clean package -pl server -am -DskipTests\n```\n\n"
                 "```bash\ndocker exec mqtt-connections mosquitto_passwd -b \\\n"
                 "    /mosquitto/config/passwd user secret\n"
                 "docker exec -it hmdm_db_prod psql -U hmdm -d hmdm\n```\n",
    "docker/hmdm-docker-0.1.5/Dockerfile": "FROM tomcat:9-jdk11-temurin-jammy\n",
    "BUILD.txt": "Requirements: Java 8 and Maven 3.6\n\nTo build:\n\n"
                 "    mvn install\n\nThen copy the war file.\n",
    "INSTALL.txt": "Install PostgreSQL 13 and Tomcat 9 first.\n"
                   "$ sudo ./hmdm_install.sh\n",
    "BUILD2.txt": "Same as INSTALL:\n    ./hmdm_install.sh\n",
    "TROUBLESHOOTING.txt": "If the build fails, check JAVA_HOME.\n",
    "LICENSE": "Apache License 2.0 java 11 should be ignored\n",
    "hmdm_install.sh": "#!/bin/bash\n",
    "Dockerfile": "ARG BASE=tomcat:9-jdk8-openjdk\nFROM ${BASE}\n"
                  "RUN apt-get update && \\\n    apt-get install -y aapt\n"
                  "COPY server/target/launcher.war /usr/local/tomcat/webapps/ROOT.war\n"
                  "EXPOSE 8080 8443/tcp\n",
    "docker/hmdm-docker/docker-compose.yaml":
        "services:\n  db:\n    image: postgres:13\n    container_name: hmdm_db_prod\n"
        "  app:\n    image: headwindmdm/hmdm:0.1.5\n",
    "docker/postgres_only/docker-compose.yml": 'services:\n  db:\n    image: "postgres:12-alpine"\n',
    "docker/postgres_only/.env.example": "DB_PASS=\n",
    ".github/workflows/build.yml":
        "jobs:\n  build:\n    steps:\n      - uses: actions/setup-java@v4\n"
        "        with:\n          java-version: '8'\n          distribution: temurin\n"
        "      - run: |\n          mvn -B install -DskipTests\n          echo done\n",
    "Jenkinsfile": "pipeline {\n  tools {\n    jdk 'jdk8'\n  }\n  stages { stage('b') {\n"
                   "    steps { sh 'mvn clean package' }\n  } }\n}\n",
    ".tool-versions": "java temurin-8.0.392+8\nmaven 3.8.8\nfoo 1.0  # herramienta rara\n",
    "server/target/classes/App.class": b"\xca\xfe\xba\xbe",
    "server/target/launcher.war": b"PK\x03\x04",
}

# API Spring Boot 3 de un solo módulo, con Maven Wrapper.
SPRING_API = {
    "mvnw": "#!/bin/sh\n",
    ".mvn/wrapper/maven-wrapper.properties":
        "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/"
        "apache-maven/3.9.6/apache-maven-3.9.6-bin.zip\n",
    "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.1</version>
    <relativePath/>
  </parent>
  <groupId>com.acme</groupId>
  <artifactId>users-api</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <properties>
    <java.version>21</java.version>
  </properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><scope>runtime</scope></dependency>
    <dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId></dependency>
    <dependency><groupId>org.flywaydb</groupId><artifactId>flyway-core</artifactId></dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin>
      <plugin><groupId>org.openapitools</groupId><artifactId>openapi-generator-maven-plugin</artifactId></plugin>
    </plugins>
  </build>
</project>
""",
    "src/main/java/com/acme/UsersApplication.java": """package com.acme;

@SpringBootApplication
public class UsersApplication {
    public static void main(String[] args) { SpringApplication.run(UsersApplication.class, args); }
}
""",
    "src/main/java/com/acme/web/UserController.java": """package com.acme.web;

import jakarta.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping("/{id}")
    public User get(@PathVariable Long id) { return null; }

    @PostMapping
    public User create(@RequestBody User u) { return null; }

    @RequestMapping(
        value = "/search",
        method = RequestMethod.GET)
    public List<User> search() { return null; }

    @DeleteMapping(path = "/{id}")
    public void delete(@PathVariable Long id) { }
}
""",
    "src/main/resources/application.yml":
        "spring:\n  datasource:\n    url: jdbc:postgresql://localhost:5432/users\n",
    "src/test/resources/fixtures/pom.xml": "<project><artifactId>fixture</artifactId></project>\n",
}

# ---------------------------------------------------------------------------
# Fixtures para cmake.py / conan.py
# ---------------------------------------------------------------------------

# CMakePresets generado por Conan (lo que genera 'conan install . --build=missing -s build_type=Debug')
_CONAN_PRESET = """\
{
  "version": 4,
  "vendor": {"conan": {}},
  "configurePresets": [
    {
      "name": "conan-debug",
      "displayName": "Conan Debug",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/Debug",
      "toolchainFile": "${sourceDir}/build/Debug/generators/conan_toolchain.cmake",
      "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug"}
    }
  ],
  "buildPresets": [{"name": "conan-debug", "configurePreset": "conan-debug"}],
  "testPresets":  [{"name": "conan-debug", "configurePreset": "conan-debug"}]
}
"""

# Imita netclient real: cmake 3.20, C++17, SHARED lib + 2 exe, find_package x3, APPLE/ANDROID
NETCLIENT_FULL = {
    "CMakeLists.txt": """\
cmake_minimum_required(VERSION 3.20)
project(system_sora LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_library(system_sora_ws SHARED src/sample.cpp)
target_include_directories(system_sora_ws
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

find_package(CURL CONFIG REQUIRED)
find_package(eclipse-paho-mqtt-c CONFIG REQUIRED)
find_package(Libwebsockets CONFIG REQUIRED)

target_sources(system_sora_ws PRIVATE src/websocket/lws_websocket_client.cpp)
target_link_libraries(system_sora_ws PRIVATE websockets)

if(APPLE)
    target_sources(system_sora_ws PRIVATE src/platform/macos/transport_macos.cpp)
elseif(ANDROID)
    target_sources(system_sora_ws PRIVATE src/platform/android/transport_android.cpp)
else()
    message(FATAL_ERROR "sistema_sora_ws: plataforma no soportada")
endif()

add_executable(system_sora_ws_test main.cpp)
target_link_libraries(system_sora_ws_test PRIVATE
    system_sora_ws
    CURL::libcurl
    eclipse-paho-mqtt-c::paho-mqtt3as-static
    websockets)

find_package(Threads REQUIRED)
add_executable(event_loop_demo examples/event_loop_demo.cpp)
target_link_libraries(event_loop_demo PRIVATE Threads::Threads)
""",
    "conanfile.py": """\
from conan import ConanFile
from conan.tools.cmake import CMakeToolchain, CMakeDeps, cmake_layout

class sampleConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeToolchain", "CMakeDeps"

    def requirements(self):
        self.requires("libcurl/8.5.0")
        self.requires("paho-mqtt-c/1.3.16")
        self.requires("libwebsockets/4.5.8")

    def layout(self):
        cmake_layout(self)
""",
    "CMakeUserPresets.json": '{"version": 4, "vendor": {"conan": {}}, '
                             '"include": ["build/Debug/generators/CMakePresets.json"]}',
    "main.cpp": "int main() {}\n",
    "examples/event_loop_demo.cpp": "int main() {}\n",
    "src/sample.cpp": "// lib\n",
    "include/system_sora/client.h": "#pragma once\n",
    ".vscode/tasks.json": """\
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "conan install",
      "type": "shell",
      "command": "conan install . --build=missing -s build_type=Debug"
    },
    {
      "label": "cmake configure",
      "type": "shell",
      "command": "rm -rf build/CMakeCache.txt build/CMakeFiles && cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=build/Debug/generators/conan_toolchain.cmake -DCMAKE_BUILD_TYPE=Debug"
    },
    {
      "label": "cmake build",
      "type": "shell",
      "command": "cmake --build build"
    }
  ]
}
""",
    ".vscode/launch.json": """\
{
  "configurations": [
    {"type": "lldb", "request": "launch", "name": "test",
     "program": "${workspaceFolder}/build/system_sora_ws_test"},
    {"type": "lldb", "request": "launch", "name": "demo",
     "program": "${workspaceFolder}/build/event_loop_demo"}
  ]
}
""",
    "readme.md": "# netclient\n\n```bash\nconan install . --build=missing\n"
                 "cmake --preset conan-debug\ncmake --build --preset conan-debug\n```\n",
    "build/Debug/CMakeCache.txt": CMAKE_CACHE,
    "build/Debug/compile_commands.json": "[]\n",
    "build/Debug/generators/CMakePresets.json": _CONAN_PRESET,
    "build/Debug/generators/conan_toolchain.cmake": "set(CMAKE_CXX_STANDARD 17)\n",
}

# CMake básico sin Conan (para tests unitarios de cmake.py)
CMAKE_BASIC = {
    "CMakeLists.txt": """\
cmake_minimum_required(VERSION 3.15)
project(myapp LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_library(mylib SHARED src/lib.cpp)
find_package(CURL CONFIG REQUIRED)
find_package(Threads REQUIRED)
add_executable(myapp main.cpp)
target_link_libraries(myapp PRIVATE mylib CURL::libcurl Threads::Threads)
enable_testing()
add_test(NAME mytest COMMAND myapp)
""",
    "main.cpp": "int main() {}\n",
    "src/lib.cpp": "// lib\n",
}

# CMakeUserPresets.json con includes que NO existen aún (conan install pendiente)
CMAKE_MISSING_PRESET = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(demo LANGUAGES CXX)\n",
    "CMakeUserPresets.json": '{"version": 4, "include": ["build/Debug/generators/CMakePresets.json"]}',
    "main.cpp": "int main() {}\n",
}

# Conan 2 básico
CONAN2_BASIC = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(mylib LANGUAGES CXX)\n",
    "conanfile.py": """\
from conan import ConanFile
from conan.tools.cmake import CMakeToolchain, CMakeDeps, cmake_layout

class MyConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeToolchain", "CMakeDeps"

    def requirements(self):
        self.requires("libcurl/8.5.0")
        self.requires("paho-mqtt-c/1.3.16")
        self.requires("libwebsockets/4.5.8")

    def layout(self):
        cmake_layout(self)
""",
    "main.cpp": "int main() {}\n",
}

# Conan 1 clásico
CONAN1_BASIC = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.10)\nproject(mylib LANGUAGES CXX)\n",
    "conanfile.py": """\
from conans import ConanFile, CMake

class MyConan(ConanFile):
    requires = "boost/1.79.0", "zlib/1.2.13"
    generators = "cmake", "cmake_find_package"
    settings = "os", "compiler", "build_type", "arch"

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()
""",
    "main.cpp": "int main() {}\n",
}

# conanfile.txt (formato INI, Conan 1/2)
CONAN_TXT_BASIC = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.15)\nproject(demo LANGUAGES CXX)\n",
    "conanfile.txt": """\
[requires]
fmt/10.2.1
spdlog/1.13.0
nlohmann_json/3.11.3

[generators]
CMakeToolchain
CMakeDeps

[layout]
cmake_layout
""",
    "main.cpp": "int main() {}\n",
}

# ---------------------------------------------------------------------------
# Fixtures para repomap.py
# ---------------------------------------------------------------------------

# Código Java con JAX-RS y Spring MVC para testear el parser de símbolos
REPOMAP_JAVA = {
    # JAX-RS (hmdm-style)
    "src/main/java/com/acme/rest/DeviceResource.java": """\
package com.acme.rest;

import javax.ws.rs.*;

@Singleton
@Path("/api/devices")
public class DeviceResource {

    @GET
    @Path("/{id}")
    public Response get(@PathParam("id") int id) { return null; }

    @POST
    public Response create(Device d) { return null; }

    @PUT
    @Path("/{id}")
    public Response update(@PathParam("id") int id, Device d) { return null; }

    @DELETE @Path("/{id}")
    public Response delete(@PathParam("id") int id) { return null; }

    private void helper() {}
}
""",
    # Spring MVC
    "src/main/java/com/acme/web/UserController.java": """\
package com.acme.web;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping("/{id}")
    public User get(@PathVariable Long id) { return null; }

    @PostMapping
    public User create(@RequestBody User u) { return null; }

    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {}

    protected void internalMethod() {}
    private void secret() {}
}
""",
    # Clase sin HTTP (servicio)
    "src/main/java/com/acme/service/UserService.java": """\
package com.acme.service;

public class UserService {
    public User findById(long id) { return null; }
    public java.util.List<User> findAll() { return null; }
    public void save(User u) {}
    private void validate(User u) {}
}
""",
    # Interface
    "src/main/java/com/acme/repo/UserRepo.java": """\
package com.acme.repo;

public interface UserRepo {
    User findById(long id);
    void save(User u);
}
""",
}

# C++ header y fuente para testear el parser
REPOMAP_CPP = {
    "include/ws/WebSocketClient.h": """\
#pragma once
#include <string>
#include <functional>

namespace ws {

class WebSocketClient {
public:
    explicit WebSocketClient(const std::string& uri, int port);
    ~WebSocketClient();

    bool connect();
    void disconnect();
    bool send(const std::string& msg);
    void onMessage(std::function<void(std::string)> handler);

private:
    std::string uri_;
    int port_;
    bool connected_ = false;
};

struct Message {
    std::string topic;
    std::string payload;
    int qos = 0;
};

bool parseUri(const std::string& raw, std::string& host, int& port);

} // namespace ws
""",
    "src/ws/websocket_client.cpp": """\
#include "ws/WebSocketClient.h"

namespace ws {

WebSocketClient::WebSocketClient(const std::string& uri, int port)
    : uri_(uri), port_(port) {}

WebSocketClient::~WebSocketClient() { disconnect(); }

bool WebSocketClient::connect() {
    connected_ = true;
    return true;
}

void WebSocketClient::disconnect() {
    connected_ = false;
}

bool WebSocketClient::send(const std::string& msg) {
    if (!connected_) return false;
    return true;
}

} // namespace ws
""",
}

# Fixture para verificar que comentarios HTML no generan falsos positivos en smarttomcat
SMARTTOMCAT_FP = {
    ".smarttomcat/server/conf/web.xml": (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<web-app version="4.0">\n'
        '<!--   ieClassId  Deprecated. Will be removed in Tomcat 10.1 -->\n'
        '</web-app>\n'
    ),
    ".smarttomcat/server/conf/server.xml": '<Server port="8005"></Server>\n',
}

# ---------------------------------------------------------------------------
# Fixtures Python
# ---------------------------------------------------------------------------

# FastAPI con uv (pyproject.toml PEP 621 + uv.lock)
FASTAPI_UV = {
    "pyproject.toml": """\
[project]
name = "myapi"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "sqlalchemy>=2.0",
    "psycopg2-binary>=2.9",
]

[project.scripts]
myapi = "myapi.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = ["pytest>=8", "httpx>=0.27"]
""",
    "uv.lock": "# uv lockfile v1\n",
    ".python-version": "3.11\n",
    "myapi/__init__.py": "",
    "myapi/main.py": """\
from fastapi import FastAPI
from myapi.routers import devices, auth

app = FastAPI(title="MyAPI")
app.include_router(devices.router, prefix="/api/devices")
app.include_router(auth.router, prefix="/api/auth")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
""",
    "myapi/routers/__init__.py": "",
    "myapi/routers/devices.py": """\
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def list_devices():
    return []

@router.get("/{device_id}")
def get_device(device_id: int):
    return {"id": device_id}

@router.post("/")
def create_device():
    return {}

@router.delete("/{device_id}")
def delete_device(device_id: int):
    return {}
""",
    "myapi/routers/auth.py": """\
from fastapi import APIRouter

router = APIRouter()

@router.post("/login")
def login():
    return {"token": "xxx"}

@router.post("/logout")
def logout():
    return {}
""",
    "README.md": """\
## Desarrollo

```bash
uv run uvicorn myapi.main:app --reload
uv run pytest
```
""",
}

# Django con poetry + PostgreSQL
DJANGO_POETRY = {
    "pyproject.toml": """\
[tool.poetry]
name = "mysite"
version = "0.1.0"
description = ""

[tool.poetry.dependencies]
python = "^3.10"
Django = "^4.2"
psycopg2-binary = "^2.9"
djangorestframework = "^3.15"

[tool.poetry.dev-dependencies]
pytest-django = "^4.8"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
""",
    "poetry.lock": "# Poetry lock\n",
    "manage.py": """\
#!/usr/bin/env python
import os, sys

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
""",
    "mysite/__init__.py": "",
    "mysite/settings.py": """\
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'mydb',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
INSTALLED_APPS = [
    'django.contrib.admin',
    'rest_framework',
    'devices',
]
""",
    "mysite/urls.py": """\
from django.urls import path, include

urlpatterns = [
    path('api/devices/', include('devices.urls')),
    path('api/auth/', include('mysite.auth_urls')),
]
""",
    "devices/views.py": """\
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def list_devices(request):
    return Response([])

@api_view(['POST'])
def create_device(request):
    return Response({})
""",
    "devices/urls.py": """\
from django.urls import path
from . import views

urlpatterns = [
    path('', views.list_devices),
    path('create/', views.create_device),
]
""",
}

# Flask con requirements.txt (clásico, sin pyproject.toml)
FLASK_REQS = {
    "requirements.txt": """\
Flask==3.0.3
SQLAlchemy==2.0.30
redis==5.0.4
""",
    "requirements-dev.txt": "pytest==8.2.0\n",
    "app.py": """\
from flask import Flask

app = Flask(__name__)

@app.route('/api/items', methods=['GET'])
def list_items():
    return []

@app.route('/api/items', methods=['POST'])
def create_item():
    return {}

@app.route('/api/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    return {}

if __name__ == '__main__':
    app.run(debug=True, port=5000)
""",
}

# Proyecto Python mínimo: solo setup.py (legacy)
PYTHON_SETUP_PY = {
    "setup.py": """\
from setuptools import setup, find_packages

setup(
    name="mylib",
    version="0.1.0",
    python_requires=">=3.8",
    packages=find_packages(),
    install_requires=["requests>=2.31"],
)
""",
    "src/mylib/__init__.py": "",
    "src/mylib/client.py": "class Client: pass\n",
}

# ---------------------------------------------------------------------------
# Fixtures .NET / ASP.NET Core
# ---------------------------------------------------------------------------

# ASP.NET Core Minimal API (.NET 8, PostgreSQL + Redis, launchSettings)
DOTNET_MINIMAL_API = {
    "MyApi.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.OpenApi" Version="8.0.0" />
    <PackageReference Include="Npgsql.EntityFrameworkCore.PostgreSQL" Version="8.0.4" />
    <PackageReference Include="StackExchange.Redis" Version="2.7.33" />
  </ItemGroup>
</Project>
""",
    "global.json": '{"sdk": {"version": "8.0.100", "rollForward": "latestMinor"}}',
    "Program.cs": """\
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
var app = builder.Build();
app.MapGet("/api/products", () => Results.Ok(new[] { "product1" }));
app.MapGet("/api/products/{id}", (int id) => Results.Ok(id));
app.MapPost("/api/products", (Product p) => Results.Created($"/api/products/1", p));
app.MapPut("/api/products/{id}", (int id, Product p) => Results.NoContent());
app.MapDelete("/api/products/{id}", (int id) => Results.NoContent());
app.Run();
record Product(string Name, decimal Price);
""",
    "Properties/launchSettings.json": """\
{
  "profiles": {
    "MyApi": {
      "commandName": "Project",
      "applicationUrl": "https://localhost:7001;http://localhost:5001",
      "environmentVariables": {
        "ASPNETCORE_ENVIRONMENT": "Development"
      }
    }
  }
}
""",
}

# ASP.NET Core MVC con controladores (.NET 7)
DOTNET_MVC_CONTROLLERS = {
    "PaymentApi.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net7.0</TargetFramework>
    <Nullable>enable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.Mvc.NewtonsoftJson" Version="7.0.0" />
  </ItemGroup>
</Project>
""",
    "Program.cs": """\
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
var app = builder.Build();
app.MapControllers();
app.Run();
""",
    "Controllers/PaymentController.cs": """\
using Microsoft.AspNetCore.Mvc;

namespace PaymentApi.Controllers;

[ApiController]
[Route("api/[controller]")]
public class PaymentController : ControllerBase
{
    [HttpGet]
    public IActionResult GetAll() => Ok();

    [HttpGet("{id:int}")]
    public IActionResult GetById(int id) => Ok();

    [HttpPost("create")]
    public IActionResult Create([FromBody] object dto) => Created("/api/payment/1", dto);

    [HttpPut("{id:int}")]
    public IActionResult Update(int id, [FromBody] object dto) => NoContent();

    [HttpDelete("{id:int}")]
    public IActionResult Delete(int id) => NoContent();
}
""",
}

# Solución multi-proyecto: web + test (xunit)
DOTNET_SOLUTION = {
    "MyApp.sln": """\

Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MyApp", "MyApp/MyApp.csproj", "{11111111-1111-1111-1111-111111111111}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MyApp.Tests", "MyApp.Tests/MyApp.Tests.csproj", "{22222222-2222-2222-2222-222222222222}"
EndProject
""",
    "MyApp/MyApp.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
""",
    "MyApp/Program.cs": """\
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/health", () => "ok");
app.Run();
""",
    "MyApp.Tests/MyApp.Tests.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="xunit" Version="2.9.0" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.0" />
    <ProjectReference Include="../MyApp/MyApp.csproj" />
  </ItemGroup>
</Project>
""",
    "MyApp.Tests/HealthTests.cs": """\
public class HealthTests
{
    [Fact]
    public void Health_Returns_Ok() { }
}
""",
}

# ---------------------------------------------------------------------------
# Fixtures Gradle / Android
# ---------------------------------------------------------------------------

# Android nativo: Kotlin DSL, AGP 8.3.2, libs.versions.toml, NDK (C++)
ANDROID_APP = {
    "settings.gradle.kts": """\
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "MyApp"
include(":app")
""",
    "build.gradle.kts": """\
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
}
""",
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
""",
    "gradle/libs.versions.toml": """\
[versions]
agp = "8.3.2"
kotlin = "1.9.24"
coreKtx = "1.13.1"
junit = "4.13.2"

[libraries]
androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
junit = { group = "junit", name = "junit", version.ref = "junit" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
""",
    "app/build.gradle.kts": """\
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.example.myapp"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.myapp"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    externalNativeBuild {
        cmake {
            path = "src/main/cpp/CMakeLists.txt"
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    testImplementation(libs.junit)
}
""",
    "app/src/main/cpp/CMakeLists.txt": (
        "cmake_minimum_required(VERSION 3.22.1)\n"
        "project(\"myapp\")\n"
        "add_library(myapp SHARED myapp.cpp)\n"
        "find_library(log-lib log)\n"
        "target_link_libraries(myapp ${log-lib})\n"
    ),
    "local.properties": "sdk.dir=/Users/mac/Library/Android/sdk\n",
}

# Multi-módulo: app (nativo) + core (library) – Kotlin DSL
ANDROID_MULTI = {
    "settings.gradle.kts": """\
rootProject.name = "MyMultiApp"
include(":app", ":core")
""",
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionUrl=https\\://services.gradle.org/distributions/gradle-8.4-bin.zip
""",
    "gradle/libs.versions.toml": """\
[versions]
agp = "8.1.4"
kotlin = "1.9.10"

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
android-library = { id = "com.android.library", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
""",
    "app/build.gradle.kts": """\
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.example.app"
    compileSdk = 34
    defaultConfig {
        applicationId = "com.example.app"
        minSdk = 21
        targetSdk = 34
    }
    kotlinOptions { jvmTarget = "11" }
}
""",
    "core/build.gradle.kts": """\
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.example.core"
    compileSdk = 34
    defaultConfig { minSdk = 21 }
}
""",
}

# Spring Boot + Kotlin (sin Android)
KOTLIN_SPRING = {
    "settings.gradle.kts": 'rootProject.name = "myservice"\n',
    "build.gradle.kts": """\
plugins {
    id("org.springframework.boot") version "3.2.0"
    id("io.spring.dependency-management") version "1.1.4"
    kotlin("jvm") version "1.9.24"
    kotlin("plugin.spring") version "1.9.24"
}

group = "com.example"
version = "0.0.1-SNAPSHOT"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.kafka:spring-kafka:3.1.2")
    implementation("org.jetbrains.kotlin:kotlin-reflect")
    testImplementation("org.springframework.boot:spring-boot-starter-test")
}
""",
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionUrl=https\\://services.gradle.org/distributions/gradle-8.5-bin.zip
""",
    "src/main/kotlin/com/example/ProductController.kt": """\
package com.example

import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/products")
class ProductController {

    @GetMapping
    fun getAll(): List<String> = listOf()

    @GetMapping("/{id}")
    fun getById(@PathVariable id: Long): String = ""

    @PostMapping
    fun create(@RequestBody dto: Map<String, Any>): Map<String, Any> = mapOf()

    @DeleteMapping("/{id}")
    fun delete(@PathVariable id: Long) {}
}
""",
}

# Android library con id("...") style (Kotlin DSL, sin version catalog)
# Replica el patrón de proyectos como ws-mobile-library
ANDROID_LIBRARY_ID_STYLE = {
    "settings.gradle.kts": 'rootProject.name = "ws-mobile-library"\n',
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip
""",
    "build.gradle.kts": """\
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

android {
    namespace = "com.abexa.ws_mobile_library"
    compileSdk = 34

    defaultConfig {
        minSdk = 24
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
""",
}

# Java puro con Groovy DSL (sin Android, sin Kotlin)
GRADLE_JAVA = {
    "settings.gradle": "rootProject.name = 'myapp'\n",
    "build.gradle": """\
plugins {
    id 'java'
    id 'application'
}

group = 'com.example'
version = '1.0.0'

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

application {
    mainClass = 'com.example.Main'
}

dependencies {
    testImplementation 'junit:junit:4.13.2'
}
""",
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionUrl=https\\://services.gradle.org/distributions/gradle-7.6-bin.zip
""",
    "src/main/java/com/example/Main.java": """\
package com.example;
public class Main {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
""",
}

# Android antiguo con sourceCompatibility JavaVersion.VERSION_1_8 (legacy 1.x style)
GRADLE_JAVA_LEGACY_COMPAT = {
    "settings.gradle": "rootProject.name = 'legacy-app'\ninclude ':app'\n",
    "app/build.gradle": """\
plugins {
    id 'com.android.application'
}

android {
    compileSdkVersion 28
    defaultConfig {
        applicationId "com.example.legacy"
        minSdkVersion 19
        targetSdkVersion 22
    }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }
}
""",
    "gradle/wrapper/gradle-wrapper.properties": """\
distributionUrl=https\\://services.gradle.org/distributions/gradle-6.1.1-bin.zip
""",
}

# Windows Forms .NET (net8.0-windows, WinExe)
DOTNET_WINDOWS_FORMS = {
    "WinApp.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWindowsForms>true</UseWindowsForms>
  </PropertyGroup>
</Project>
""",
    "Form1.cs": "public class Form1 : Form { }\n",
}

# Aplicación de consola simple (sin web, sin tests)
DOTNET_CONSOLE = {
    "ConsoleApp.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
""",
    "Program.cs": 'Console.WriteLine("Hello, World!");\n',
}

# --------------------------------------------------------------------------
# JavaScript / Node.js / Frontend
# --------------------------------------------------------------------------

# Express API con PostgreSQL y Redis, npm, .nvmrc
NODEJS_EXPRESS = {
    ".nvmrc": "20.11.0\n",
    "package.json": """\
{
  "name": "my-api",
  "version": "1.0.0",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "dev": "nodemon src/index.js",
    "test": "jest --runInBand"
  },
  "dependencies": {
    "express": "^4.18.2",
    "pg": "^8.11.3",
    "redis": "^4.6.7",
    "cors": "^2.8.5",
    "dotenv": "^16.3.1"
  },
  "devDependencies": {
    "jest": "^29.7.0",
    "supertest": "^6.3.3",
    "nodemon": "^3.0.1"
  }
}
""",
    "package-lock.json": '{"name":"my-api","lockfileVersion":3,"requires":true,"packages":{}}\n',
    "src/index.js": """\
const express = require('express');
const app = express();
app.use(express.json());

const usersRouter = require('./routes/users');
const productsRouter = require('./routes/products');
app.use('/api/users', usersRouter);
app.use('/api/products', productsRouter);

app.get('/health', (req, res) => res.json({ status: 'ok' }));

module.exports = app;
""",
    "src/routes/users.js": """\
const router = require('express').Router();

router.get('/', async (req, res) => {
    res.json([]);
});
router.post('/', async (req, res) => {
    res.status(201).json({});
});
router.get('/:id', async (req, res) => {
    res.json({});
});
router.delete('/:id', async (req, res) => {
    res.status(204).end();
});

module.exports = router;
""",
    "src/routes/products.js": """\
const router = require('express').Router();

router.get('/', (req, res) => res.json([]));
router.post('/', (req, res) => res.status(201).json({}));

module.exports = router;
""",
    "src/db.js": """\
const { Pool } = require('pg');
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
module.exports = pool;
""",
    "src/cache.js": """\
const { createClient } = require('redis');
const client = createClient({ url: process.env.REDIS_URL });
module.exports = client;
""",
}

# Angular 17 con app.routes.ts, yarn
ANGULAR_APP = {
    ".node-version": "20\n",
    "package.json": """\
{
  "name": "my-angular-app",
  "version": "0.0.0",
  "scripts": {
    "ng": "ng",
    "start": "ng serve",
    "build": "ng build",
    "test": "ng test",
    "lint": "ng lint"
  },
  "private": true,
  "dependencies": {
    "@angular/animations": "^17.0.0",
    "@angular/common": "^17.0.0",
    "@angular/compiler": "^17.0.0",
    "@angular/core": "^17.0.0",
    "@angular/forms": "^17.0.0",
    "@angular/platform-browser": "^17.0.0",
    "@angular/router": "^17.0.0",
    "rxjs": "~7.8.0",
    "tslib": "^2.6.2",
    "zone.js": "~0.14.2"
  },
  "devDependencies": {
    "@angular-devkit/build-angular": "^17.0.0",
    "@angular/cli": "^17.0.0",
    "@types/jasmine": "~5.1.0",
    "jasmine-core": "~5.1.0",
    "karma": "~6.4.0",
    "typescript": "~5.2.2"
  }
}
""",
    "yarn.lock": "# THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.\n",
    "angular.json": """\
{
  "$schema": "./node_modules/@angular/cli/lib/config/schema.json",
  "version": 1,
  "newProjectRoot": "projects",
  "projects": {
    "my-angular-app": {
      "projectType": "application",
      "root": "",
      "sourceRoot": "src",
      "architect": {
        "build": {
          "builder": "@angular-devkit/build-angular:application",
          "options": {
            "outputPath": "dist/my-angular-app",
            "index": "src/index.html",
            "browser": "src/main.ts"
          }
        },
        "serve": {
          "builder": "@angular-devkit/build-angular:dev-server",
          "configurations": {
            "production": { "buildTarget": "my-angular-app:build:production" },
            "development": { "buildTarget": "my-angular-app:build:development" }
          }
        }
      }
    }
  }
}
""",
    "src/app/app.routes.ts": """\
import { Routes } from '@angular/router';
import { HomeComponent } from './home/home.component';
import { DashboardComponent } from './dashboard/dashboard.component';
import { UsersComponent } from './users/users.component';
import { UserDetailComponent } from './users/user-detail.component';
import { NotFoundComponent } from './not-found/not-found.component';

export const routes: Routes = [
  { path: '', component: HomeComponent },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'users', component: UsersComponent },
  { path: 'users/:id', component: UserDetailComponent },
  { path: '**', component: NotFoundComponent },
];
""",
    "src/app/app.component.ts": """\
import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  template: '<router-outlet />',
})
export class AppComponent {}
""",
    "src/main.ts": """\
import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { provideRouter } from '@angular/router';
import { routes } from './app/app.routes';

bootstrapApplication(AppComponent, {
  providers: [provideRouter(routes)],
}).catch(err => console.error(err));
""",
}

# React 18 + Vite + React Router v6, pnpm
REACT_VITE = {
    "package.json": """\
{
  "name": "my-react-app",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.20.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.43",
    "@types/react-dom": "^18.2.17",
    "@vitejs/plugin-react": "^4.2.1",
    "typescript": "^5.2.2",
    "vite": "^5.0.8",
    "vitest": "^1.0.4"
  }
}
""",
    "pnpm-lock.yaml": "lockfileVersion: '6.0'\n",
    "vite.config.ts": """\
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
})
""",
    "src/main.tsx": """\
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
""",
    "src/App.tsx": """\
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import UserList from './pages/UserList'
import UserDetail from './pages/UserDetail'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/users" element={<UserList />} />
      <Route path="/users/:id" element={<UserDetail />} />
    </Routes>
  )
}

export default App
""",
    "src/router.tsx": """\
import { createBrowserRouter } from 'react-router-dom'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'

export const router = createBrowserRouter([
  { path: '/', element: <Home /> },
  { path: '/dashboard', element: <Dashboard /> },
  { path: '/users', element: <div>Users</div> },
  { path: '/users/:id', element: <div>User</div> },
])
""",
    "index.html": """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>My React App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""",
}

# NestJS API con controladores, npm
NESTJS_API = {
    "package.json": """\
{
  "name": "my-nestjs-api",
  "version": "0.0.1",
  "scripts": {
    "build": "nest build",
    "start": "nest start",
    "start:dev": "nest start --watch",
    "test": "jest",
    "test:e2e": "jest --config ./test/jest-e2e.json"
  },
  "dependencies": {
    "@nestjs/common": "^10.0.0",
    "@nestjs/core": "^10.0.0",
    "@nestjs/platform-express": "^10.0.0",
    "reflect-metadata": "^0.1.13",
    "rxjs": "^7.8.1"
  },
  "devDependencies": {
    "@nestjs/cli": "^10.0.0",
    "@nestjs/schematics": "^10.0.0",
    "@nestjs/testing": "^10.0.0",
    "@types/express": "^4.17.17",
    "@types/jest": "^29.5.2",
    "@types/node": "^20.3.1",
    "jest": "^29.5.0",
    "ts-jest": "^29.1.0",
    "typescript": "^5.1.3"
  }
}
""",
    "package-lock.json": '{"name":"my-nestjs-api","lockfileVersion":3,"requires":true,"packages":{}}\n',
    "src/main.ts": """\
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  await app.listen(3000);
}
bootstrap();
""",
    "src/app.module.ts": """\
import { Module } from '@nestjs/common';
import { UsersModule } from './users/users.module';
import { ProductsModule } from './products/products.module';

@Module({
  imports: [UsersModule, ProductsModule],
})
export class AppModule {}
""",
    "src/users/users.controller.ts": """\
import { Controller, Get, Post, Put, Delete, Body, Param } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get()
  findAll() {
    return [];
  }

  @Get(':id')
  findOne(@Param('id') id: string) {
    return { id };
  }

  @Post()
  create(@Body() body: any) {
    return body;
  }

  @Delete(':id')
  remove(@Param('id') id: string) {
    return { deleted: id };
  }
}
""",
    "src/products/products.controller.ts": """\
import { Controller, Get, Post, Put, Patch, Param, Body } from '@nestjs/common';

@Controller('products')
export class ProductsController {
  @Get()
  findAll() {
    return [];
  }

  @Post()
  create(@Body() body: any) {
    return body;
  }

  @Put(':id')
  update(@Param('id') id: string, @Body() body: any) {
    return { id, ...body };
  }

  @Patch(':id')
  patch(@Param('id') id: string) {
    return { id };
  }
}
""",
}

# Vite + HTML estático / frontend bundled (sin framework)
STATIC_HTML = {
    "package.json": """\
{
  "name": "my-static-site",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "devDependencies": {
    "vite": "^5.0.8"
  }
}
""",
    "package-lock.json": '{"name":"my-static-site","lockfileVersion":3,"requires":true,"packages":{}}\n',
    "vite.config.js": """\
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    outDir: 'dist',
  },
  server: {
    port: 8080,
  },
})
""",
    "index.html": """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>My Static Site</title>
    <link rel="stylesheet" href="/src/style.css" />
  </head>
  <body>
    <h1>Hello World</h1>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
""",
    "src/main.js": """\
document.getElementById('app').innerHTML = '<p>Vanilla JS app</p>';
""",
    "src/style.css": """\
body { margin: 0; font-family: sans-serif; }
""",
}

# --------------------------------------------------------------------------
# Flutter / Dart
# --------------------------------------------------------------------------

# App Flutter móvil (Android + iOS): GoRouter, Firebase, Riverpod
FLUTTER_APP = {
    "pubspec.yaml": """\
name: my_flutter_app
description: "A Flutter mobile application."
version: 1.0.0+1
publish_to: 'none'

environment:
  sdk: '>=3.0.0 <4.0.0'
  flutter: '>=3.16.0'

dependencies:
  flutter:
    sdk: flutter
  go_router: ^13.0.0
  flutter_riverpod: ^2.4.9
  riverpod_annotation: ^2.3.3
  firebase_core: ^2.24.2
  firebase_auth: ^4.15.3
  cloud_firestore: ^4.13.6
  cached_network_image: ^3.3.1

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0
  build_runner: ^2.4.7
  riverpod_generator: ^2.3.9

flutter:
  uses-material-design: true
  assets:
    - assets/images/
    - assets/icons/
""",
    "pubspec.lock": "# Generated by pub tool.\n",
    "lib/main.dart": """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';
import 'router.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  runApp(ProviderScope(child: MyApp()));
}

class MyApp extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'My App',
      routerConfig: router,
    );
  }
}
""",
    "lib/router.dart": """\
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'pages/home_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/users_page.dart';
import 'pages/user_detail_page.dart';
import 'pages/settings_page.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const HomePage(),
      ),
      GoRoute(
        path: '/dashboard',
        builder: (context, state) => const DashboardPage(),
      ),
      GoRoute(
        path: '/users',
        builder: (context, state) => const UsersPage(),
        routes: [
          GoRoute(
            path: ':id',
            builder: (context, state) => UserDetailPage(
              userId: state.pathParameters['id']!,
            ),
          ),
        ],
      ),
      GoRoute(
        path: '/settings',
        builder: (context, state) => const SettingsPage(),
      ),
    ],
  );
});
""",
    "lib/pages/home_page.dart": """\
import 'package:flutter/material.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Text('Home'));
  }
}
""",
    "android/app/build.gradle": """\
plugins {
    id 'com.android.application'
    id 'kotlin-android'
    id 'dev.flutter.flutter-gradle-plugin'
}

android {
    namespace "com.example.my_flutter_app"
    compileSdkVersion flutter.compileSdkVersion
    ndkVersion flutter.ndkVersion

    defaultConfig {
        applicationId "com.example.my_flutter_app"
        minSdkVersion flutter.minSdkVersion
        targetSdkVersion flutter.targetSdkVersion
        versionCode flutterVersionCode.toInteger()
        versionName flutterVersionName
    }
}

dependencies {
    implementation "org.jetbrains.kotlin:kotlin-stdlib-jdk7:$kotlin_version"
}
""",
    "ios/Podfile": """\
platform :ios, '12.0'

ENV['COCOAPODS_DISABLE_STATS'] = 'true'

project 'Runner', {
  'Debug' => :debug,
  'Profile' => :release,
  'Release' => :release,
}

def flutter_root
  generated_xcode_build_settings_path = File.expand_path(File.join('..', 'Flutter', 'Generated.xcconfig'), __FILE__)
  unless File.exist?(generated_xcode_build_settings_path)
    raise "#{generated_xcode_build_settings_path} must exist."
  end
  File.foreach(generated_xcode_build_settings_path) do |line|
    matches = line.match(/FLUTTER_ROOT\\=(.*)/)
    return matches[1].strip if matches
  end
  raise "FLUTTER_ROOT not found in #{generated_xcode_build_settings_path}."
end

require File.expand_path(File.join('packages', 'flutter_tools', 'bin', 'podhelper'), flutter_root)

flutter_ios_podfile_setup

target 'Runner' do
  use_frameworks!
  use_modular_headers!
  flutter_install_all_ios_pods File.dirname(File.realpath(__FILE__))
end
""",
    "analysis_options.yaml": """\
include: package:flutter_lints/flutter.yaml
""",
}

# Plugin Flutter (implementación nativa Android e iOS)
FLUTTER_PLUGIN = {
    "pubspec.yaml": """\
name: my_camera_plugin
description: "A Flutter plugin for camera access."
version: 0.1.0

environment:
  sdk: '>=3.0.0 <4.0.0'
  flutter: '>=3.10.0'

dependencies:
  flutter:
    sdk: flutter

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  plugin:
    platforms:
      android:
        package: com.example.my_camera_plugin
        pluginClass: MyCameraPlugin
      ios:
        pluginClass: MyCameraPlugin
""",
    "lib/my_camera_plugin.dart": """\
import 'package:flutter/services.dart';

class MyCameraPlugin {
  static const MethodChannel _channel = MethodChannel('my_camera_plugin');

  static Future<String?> getPlatformVersion() async {
    final version = await _channel.invokeMethod<String>('getPlatformVersion');
    return version;
  }
}
""",
    "android/src/main/kotlin/com/example/my_camera_plugin/MyCameraPlugin.kt": """\
package com.example.my_camera_plugin

import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.MethodChannel.MethodCallHandler

class MyCameraPlugin: FlutterPlugin, MethodCallHandler {
  private lateinit var channel: MethodChannel

  override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
    channel = MethodChannel(binding.binaryMessenger, "my_camera_plugin")
    channel.setMethodCallHandler(this)
  }

  override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
    if (call.method == "getPlatformVersion") {
      result.success("Android " + android.os.Build.VERSION.RELEASE)
    } else {
      result.notImplemented()
    }
  }

  override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
    channel.setMethodCallHandler(null)
  }
}
""",
    "ios/Classes/MyCameraPlugin.swift": """\
import Flutter
import UIKit

public class MyCameraPlugin: NSObject, FlutterPlugin {
  public static func register(with registrar: FlutterPluginRegistrar) {
    let channel = FlutterMethodChannel(name: "my_camera_plugin", binaryMessenger: registrar.messenger())
    let instance = MyCameraPlugin()
    registrar.addMethodCallDelegate(instance, channel: channel)
  }

  public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "getPlatformVersion":
      result("iOS " + UIDevice.current.systemVersion)
    default:
      result(FlutterMethodNotImplemented)
    }
  }
}
""",
    "CHANGELOG.md": "## 0.1.0\n\n* Initial release.\n",
}

# Paquete Dart puro (sin Flutter, solo Dart)
DART_PACKAGE = {
    "pubspec.yaml": """\
name: my_utils
description: "A Dart utility library."
version: 1.2.0
homepage: https://github.com/example/my_utils

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  collection: ^1.18.0
  meta: ^1.11.0

dev_dependencies:
  test: ^1.24.0
  lints: ^3.0.0
""",
    "pubspec.lock": "# Generated by pub tool.\n",
    "lib/my_utils.dart": """\
/// A utility library for Dart.
library my_utils;

export 'src/string_utils.dart';
export 'src/collection_utils.dart';
""",
    "lib/src/string_utils.dart": """\
/// String utility functions.
class StringUtils {
  static String capitalize(String s) =>
      s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

  static bool isPalindrome(String s) => s == s.split('').reversed.join();
}
""",
    "test/string_utils_test.dart": """\
import 'package:test/test.dart';
import 'package:my_utils/my_utils.dart';

void main() {
  group('StringUtils', () {
    test('capitalize', () {
      expect(StringUtils.capitalize('hello'), 'Hello');
    });
  });
}
""",
    "analysis_options.yaml": "include: package:lints/recommended.yaml\n",
}

# ---------------------------------------------------------------------------
# Fixtures Go
# ---------------------------------------------------------------------------

# API REST con Gin + PostgreSQL (estructura cmd/)
GO_GIN_API = {
    "go.mod": """\
module github.com/acme/device-api

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgithub.com/lib/pq v1.10.9
\tgithub.com/go-redis/redis/v9 v9.3.0
)

require (
\tgolang.org/x/net v0.18.0 // indirect
)
""",
    "go.sum": "github.com/gin-gonic/gin v1.9.1 h1:...\n",
    "cmd/server/main.go": """\
package main

import (
\t"github.com/gin-gonic/gin"
\t"github.com/acme/device-api/internal/handler"
)

func main() {
\tr := gin.Default()
\tr.GET("/api/devices", handler.ListDevices)
\tr.POST("/api/devices", handler.CreateDevice)
\tr.GET("/api/devices/:id", handler.GetDevice)
\tr.Run(":8080")
}
""",
    "internal/handler/device.go": """\
package handler

import "github.com/gin-gonic/gin"

func ListDevices(c *gin.Context) {
\tc.JSON(200, gin.H{"devices": []string{}})
}

func CreateDevice(c *gin.Context) {
\tc.JSON(201, gin.H{"id": "new"})
}

func GetDevice(c *gin.Context) {
\tc.JSON(200, gin.H{"id": c.Param("id")})
}
""",
    "Makefile": "build:\n\tgo build -o bin/server ./cmd/server\ntest:\n\tgo test ./...\n",
    ".gitignore": "bin/\n",
}

# Librería Go pura (sin main)
GO_LIBRARY = {
    "go.mod": """\
module github.com/acme/go-utils

go 1.20

require (
\tgolang.org/x/text v0.14.0
)
""",
    "utils.go": "package utils\n\nfunc Slugify(s string) string { return s }\n",
    "utils_test.go": "package utils_test\n",
}

# Go con net/http estándar (sin frameworks externos)
GO_STD_HTTP = {
    "go.mod": """\
module github.com/acme/simple-api

go 1.22

require (
\tgithub.com/jackc/pgx/v5 v5.5.0
)
""",
    "main.go": """\
package main

import (
\t"net/http"
)

func main() {
\thttp.HandleFunc("/health", healthHandler)
\thttp.HandleFunc("/api/users", usersHandler)
\thttp.ListenAndServe(":8080", nil)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {}
func usersHandler(w http.ResponseWriter, r *http.Request) {}
""",
}

# Go con múltiples comandos en cmd/
GO_MULTI_CMD = {
    "go.mod": """\
module github.com/acme/tools

go 1.21

require (
\tgithub.com/spf13/cobra v1.8.0
\tgithub.com/twmb/franz-go v1.15.0
\tgithub.com/redis/go-redis/v9 v9.3.0
)
""",
    "cmd/worker/main.go": "package main\nfunc main() {}\n",
    "cmd/cli/main.go": "package main\nfunc main() {}\n",
    "cmd/api/main.go": "package main\nfunc main() {}\n",
}

# ---------------------------------------------------------------------------
# Fixtures para repomap — nuevos lenguajes
# ---------------------------------------------------------------------------

# NestJS controller (TypeScript con decoradores HTTP)
REPOMAP_TS_NESTJS = {
    "src/devices/devices.controller.ts": """\
import { Controller, Get, Post, Delete, Param, Body } from '@nestjs/common';
import { DevicesService } from './devices.service';

@Controller('devices')
export class DevicesController {
  constructor(private readonly svc: DevicesService) {}

  @Get()
  findAll() {
    return this.svc.findAll();
  }

  @Get(':id')
  findOne(@Param('id') id: string) {
    return this.svc.findOne(+id);
  }

  @Post()
  create(@Body() dto: CreateDeviceDto) {
    return this.svc.create(dto);
  }

  @Delete(':id')
  remove(@Param('id') id: string) {
    return this.svc.remove(+id);
  }

  private _validate(dto: any) {
    return !!dto;
  }
}
""",
    "src/devices/devices.service.ts": """\
import { Injectable } from '@nestjs/common';

@Injectable()
export class DevicesService {
  private readonly devices: Device[] = [];

  findAll(): Device[] {
    return this.devices;
  }

  findOne(id: number): Device | undefined {
    return this.devices.find(d => d.id === id);
  }

  create(dto: CreateDeviceDto): Device {
    const device = { id: Date.now(), ...dto };
    this.devices.push(device);
    return device;
  }

  remove(id: number): void {
    const idx = this.devices.findIndex(d => d.id === id);
    if (idx >= 0) this.devices.splice(idx, 1);
  }
}
""",
    "package.json": '{"name":"nest-api","dependencies":{"@nestjs/core":"^10.0.0"}}',
}

# Spring Boot Kotlin (anotaciones HTTP)
REPOMAP_KT_SPRING = {
    "src/main/kotlin/com/acme/web/UserController.kt": """\
package com.acme.web

import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/users")
class UserController(private val svc: UserService) {

    @GetMapping("/{id}")
    fun getUser(@PathVariable id: Long): User = svc.findById(id)

    @PostMapping
    fun createUser(@RequestBody dto: CreateUserDto): User = svc.create(dto)

    @DeleteMapping("/{id}")
    fun deleteUser(@PathVariable id: Long) = svc.delete(id)

    private fun validate(dto: Any) = dto != null
}
""",
    "src/main/kotlin/com/acme/service/UserService.kt": """\
package com.acme.service

import org.springframework.stereotype.Service

@Service
class UserService(private val repo: UserRepo) {

    fun findById(id: Long): User = repo.findById(id).orElseThrow()

    fun findAll(): List<User> = repo.findAll()

    fun create(dto: CreateUserDto): User {
        val user = User(name = dto.name)
        return repo.save(user)
    }

    fun delete(id: Long) = repo.deleteById(id)
}
""",
    "build.gradle.kts": 'plugins { id("org.springframework.boot") version "3.2.0" }\n',
}

# Flutter app con GoRouter (Dart)
REPOMAP_DART_FLUTTER = {
    "lib/main.dart": """\
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'router.dart';

void main() => runApp(MyApp());

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(routerConfig: appRouter);
  }
}
""",
    "lib/router.dart": """\
import 'package:go_router/go_router.dart';
import 'screens/home_screen.dart';
import 'screens/device_screen.dart';

final appRouter = GoRouter(
  routes: [
    GoRoute(
      path: '/',
      builder: (ctx, state) => const HomeScreen(),
    ),
    GoRoute(
      path: '/devices',
      builder: (ctx, state) => const DeviceScreen(),
      routes: [
        GoRoute(
          path: ':id',
          builder: (ctx, state) => DeviceDetail(id: state.params['id']!),
        ),
      ],
    ),
  ],
);
""",
    "lib/screens/home_screen.dart": """\
import 'package:flutter/material.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(appBar: AppBar(title: const Text('Home')));
  }
}
""",
    "lib/services/device_service.dart": """\
import 'package:http/http.dart' as http;
import '../models/device.dart';

class DeviceService {
  final String baseUrl;

  DeviceService(this.baseUrl);

  Future<List<Device>> fetchDevices() async {
    final resp = await http.get(Uri.parse('$baseUrl/devices'));
    return parseDevices(resp.body);
  }

  List<Device> parseDevices(String json) => [];

  Future<Device> createDevice(Map<String, dynamic> data) async {
    return Device();
  }
}
""",
    "pubspec.yaml": """\
name: my_app
environment:
  sdk: '>=3.0.0 <4.0.0'
  flutter: '>=3.16.0'
dependencies:
  flutter:
    sdk: flutter
  go_router: ^12.0.0
  http: ^1.1.0
flutter:
  uses-material-design: true
""",
    "android/build.gradle": 'buildscript { ext.kotlin_version = "1.9.0" }\n',
}

# Spring Boot con application.yml completo
SPRING_WITH_CONFIG = {
    "mvnw": "#!/bin/sh\n",
    ".mvn/wrapper/maven-wrapper.properties":
        "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/"
        "apache-maven/3.9.6/apache-maven-3.9.6-bin.zip\n",
    "pom.xml": """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.1</version>
    <relativePath/>
  </parent>
  <groupId>com.acme</groupId>
  <artifactId>inventory-api</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
""",
    "src/main/java/com/acme/InventoryApp.java": """\
package com.acme;
@SpringBootApplication
public class InventoryApp {
    public static void main(String[] args) {}
}
""",
    "src/main/resources/application.yml": """\
server:
  port: 9090
  servlet:
    context-path: /inventory

spring:
  profiles:
    active: dev
  datasource:
    url: jdbc:postgresql://localhost:5432/inventory
    username: ${DB_USER}
    password: ${DB_PASS}
  jpa:
    hibernate:
      ddl-auto: validate

app:
  api-key: ${API_KEY}
  allowed-origins: http://localhost:3000
""",
    "src/main/resources/application-prod.yml": """\
server:
  port: 8080

spring:
  datasource:
    url: jdbc:postgresql://${DB_HOST}:5432/inventory
""",
}

# Spring Boot con application.properties (en lugar de YAML)
SPRING_WITH_PROPERTIES = {
    "pom.xml": """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.1</version>
    <relativePath/>
  </parent>
  <groupId>com.acme</groupId>
  <artifactId>notif-service</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
""",
    "src/main/java/com/acme/NotifApp.java": """\
@SpringBootApplication
public class NotifApp { public static void main(String[] a) {} }
""",
    "src/main/resources/application.properties": """\
server.port=8081
server.servlet.context-path=/api/v1
spring.profiles.active=staging
spring.datasource.url=jdbc:mysql://localhost:3306/notif
spring.datasource.username=${MYSQL_USER}
spring.datasource.password=${MYSQL_PASS}
""",
}

# ---------------------------------------------------------------------------
# Rust fixtures
# ---------------------------------------------------------------------------

# Actix-web API con PostgreSQL y Redis
RUST_ACTIX_API = {
    "Cargo.toml": """\
[package]
name = "device-api"
version = "0.1.0"
edition = "2021"
rust-version = "1.70"

[[bin]]
name = "device-api"
path = "src/main.rs"

[dependencies]
actix-web = "4"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
sqlx = { version = "0.7", features = ["postgres", "runtime-tokio"] }
redis = "0.23"
tokio = { version = "1", features = ["full"] }
config = "0.13"
""",
    "src/main.rs": """\
use actix_web::{web, App, HttpServer};

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    HttpServer::new(|| {
        App::new()
            .service(list_devices)
            .service(create_device)
            .service(get_device)
            .service(delete_device)
    })
    .bind("0.0.0.0:8080")?
    .run()
    .await
}

#[get("/api/devices")]
pub async fn list_devices() -> impl actix_web::Responder {
    actix_web::HttpResponse::Ok().json(vec!["device1"])
}

#[post("/api/devices")]
pub async fn create_device() -> impl actix_web::Responder {
    actix_web::HttpResponse::Created().finish()
}

#[get("/api/devices/{id}")]
pub async fn get_device() -> impl actix_web::Responder {
    actix_web::HttpResponse::Ok().finish()
}

#[delete("/api/devices/{id}")]
pub async fn delete_device() -> impl actix_web::Responder {
    actix_web::HttpResponse::NoContent().finish()
}
""",
}

# Library crate (sin binary, sin servicios)
RUST_LIBRARY = {
    "Cargo.toml": """\
[package]
name = "mylib"
version = "0.2.0"
edition = "2021"

[lib]
name = "mylib"
path = "src/lib.rs"

[dependencies]
serde = { version = "1", features = ["derive"] }
""",
    "src/lib.rs": """\
pub fn add(a: i32, b: i32) -> i32 { a + b }
""",
}

# Workspace con múltiples crates
RUST_WORKSPACE = {
    "Cargo.toml": """\
[workspace]
members = [
    "api",
    "core",
    "worker",
]
resolver = "2"
""",
    "api/Cargo.toml": """\
[package]
name = "api"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
sqlx = { version = "0.7", features = ["postgres", "runtime-tokio"] }
""",
    "api/src/main.rs": """\
use axum::{routing::get, Router};

#[tokio::main]
async fn main() {
    let app = Router::new()
        .route("/health", get(health))
        .route("/users", get(list_users))
        .route("/users/:id", get(get_user));
    axum::Server::bind(&"0.0.0.0:3000".parse().unwrap())
        .serve(app.into_make_service())
        .await
        .unwrap();
}

async fn health() -> &'static str { "ok" }
async fn list_users() -> &'static str { "[]" }
async fn get_user() -> &'static str { "{}" }
""",
    "core/Cargo.toml": """\
[package]
name = "core"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
""",
    "core/src/lib.rs": "pub struct Config {}",
    "worker/Cargo.toml": """\
[package]
name = "worker"
version = "0.1.0"
edition = "2021"

[dependencies]
rdkafka = "0.36"
tokio = { version = "1", features = ["full"] }
""",
    "worker/src/main.rs": "fn main() { println!(\"worker\"); }",
}

# Binary con Diesel ORM (postgresql), sin web framework
RUST_CLI = {
    "Cargo.toml": """\
[package]
name = "db-tool"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "db-tool"
path = "src/main.rs"

[dependencies]
diesel = { version = "2.1", features = ["postgres"] }
dotenvy = "0.15"
clap = { version = "4", features = ["derive"] }
""",
    "src/main.rs": "fn main() { println!(\"db-tool\"); }",
}

# ---------------------------------------------------------------------------
# Make fixtures
# ---------------------------------------------------------------------------

# Proyecto C++ con Makefile puro (sin CMakeLists.txt)
MAKE_CPP = {
    "Makefile": """\
CXX      = g++
CXXFLAGS = -std=c++17 -Wall -O2
LDFLAGS  =

SRCS = src/main.cpp src/server.cpp
OBJS = $(SRCS:.cpp=.o)
TARGET = myserver

all: $(TARGET)

$(TARGET): $(OBJS)
\t$(CXX) $(LDFLAGS) -o $@ $^

%.o: %.cpp
\t$(CXX) $(CXXFLAGS) -c -o $@ $<

test:
\t./run_tests.sh

install: $(TARGET)
\tinstall -m 755 $(TARGET) /usr/local/bin/

clean:
\trm -f $(OBJS) $(TARGET)

.PHONY: all test install clean
""",
    "src/main.cpp": "int main() { return 0; }\n",
    "src/server.cpp": "void serve() {}\n",
}

# Makefile C con biblioteca (sin target run)
MAKE_C_LIB = {
    "Makefile": """\
CC      = gcc
CFLAGS  = -std=c11 -fPIC -Wall
TARGET  = libmylib.so

all: $(TARGET)

$(TARGET): mylib.o
\t$(CC) -shared -o $@ $<

mylib.o: mylib.c
\t$(CC) $(CFLAGS) -c mylib.c

test: $(TARGET)
\tgcc -L. -lmylib test_mylib.c -o test_mylib && ./test_mylib

clean:
\trm -f *.o *.so test_mylib

.PHONY: all test clean
""",
    "mylib.c": "void noop() {}\n",
    "mylib.h": "void noop();\n",
}

# Makefile con CMakeLists.txt presente → no debe activarse (CMake tiene prioridad)
MAKE_WITH_CMAKE = {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.15)\nproject(demo CXX)\n",
    "Makefile": """\
all:
\tcmake --build build

.PHONY: all
""",
    "src/main.cpp": "int main(){}\n",
}

# Makefile simple sin CXX/CC y sin target test
MAKE_SIMPLE = {
    "Makefile": """\
all:
\techo "building"

.PHONY: all
""",
}

# --------------------------------------------------------------------------
# Unity
# --------------------------------------------------------------------------

UNITY_URP = {
    "ProjectSettings/ProjectVersion.txt": (
        "m_EditorVersion: 2022.3.15f1\n"
        "m_EditorVersionWithRevision: 2022.3.15f1 (bdfd5f8139e0)\n"
    ),
    "Packages/manifest.json": """\
{
  "dependencies": {
    "com.unity.render-pipelines.universal": "14.0.9",
    "com.google.firebase.app": "10.3.0",
    "com.unity.2d.sprite": "1.0.0",
    "com.unity.textmeshpro": "3.0.6"
  }
}
""",
    "Assets/Scripts/PlayerController.cs": (
        "using UnityEngine;\n"
        "public class PlayerController : MonoBehaviour { }\n"
    ),
    "Assets/Scenes/Main.unity": "# Unity scene\n",
    "Assets/Scripts/PlayerController.cs.meta": "fileFormatVersion: 2\n",
}

UNITY_HDRP = {
    "ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 2023.1.0f1\n",
    "Packages/manifest.json": """\
{
  "dependencies": {
    "com.unity.render-pipelines.high-definition": "15.0.6",
    "com.unity.services.authentication": "2.7.2"
  }
}
""",
    "Assets/Scripts/GameManager.cs": "using UnityEngine;\npublic class GameManager : MonoBehaviour { }\n",
}

UNITY_BUILTIN = {
    "ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 2021.3.30f1\n",
    "Packages/manifest.json": '{"dependencies":{"com.unity.2d.sprite":"1.0.0"}}',
    "Assets/Scripts/Main.cs": "using UnityEngine;\n",
}

# --------------------------------------------------------------------------
# PlatformIO
# --------------------------------------------------------------------------

PLATFORMIO_ARDUINO = {
    "platformio.ini": """\
[env:uno]
platform = atmelavr
board = uno
framework = arduino
lib_deps =
    arduino-libraries/Ethernet@^2.0.0
    Wire
""",
    "src/main.cpp": "#include <Arduino.h>\nvoid setup() {}\nvoid loop() {}\n",
    "include/main.h": "#pragma once\n",
}

PLATFORMIO_ESP32 = {
    "platformio.ini": """\
[platformio]
default_envs = esp32dev

[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
lib_deps =
    bblanchon/ArduinoJson@^7.0.0
    knolleary/pubsubclient@^2.8.0
""",
    "src/main.cpp": "#include <Arduino.h>\nvoid setup() {}\nvoid loop() {}\n",
}

PLATFORMIO_MULTI_ENV = {
    "platformio.ini": """\
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino

[env:esp32s3-idf]
platform = espressif32
board = esp32s3dev
framework = espidf
""",
    "src/main.cpp": "#include <Arduino.h>\nvoid setup() {}\nvoid loop() {}\n",
}

# Flutter monorepo (pubspec.yaml en subdirectorio, no en raíz)
FLUTTER_MONOREPO = {
    "beex_mobile/pubspec.yaml": """\
name: beex_mobile
description: Flutter monorepo app
environment:
  sdk: ">=3.0.0 <4.0.0"
  flutter: ">=3.16.0"
dependencies:
  flutter:
    sdk: flutter
  firebase_core: ^2.24.2
  mqtt_client: ^10.0.0

flutter:
  uses-material-design: true
""",
    "beex_mobile/lib/main.dart": "import 'package:flutter/material.dart';\nvoid main() => runApp(const MyApp());\n",
    "beex_mobile/android/build.gradle": "// Android build\n",
    "beex_mobile/android/gradle/wrapper/gradle-wrapper.properties": "distributionUrl=https://services.gradle.org/distributions/gradle-8.0-bin.zip\n",
    "beex_mobile/ios/Runner.xcodeproj/project.pbxproj": "// Xcode\n",
    ".vscode/launch.json": '{"version":"0.2.0","configurations":[]}\n',
}

# Python con [tool.uv] pero sin uv.lock (índice privado Artifactory)
PYTHON_TOOL_UV_NO_LOCK = {
    "pyproject.toml": """\
[project]
name = "my_service"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.34.2"]

[project.scripts]
my-run = "my_service.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
index-url = "https://artifactory.example.com/repository/pypi-hosted/simple/"
extra-index-url = ["https://pypi.org/simple/"]
""",
    "my_service/app.py": "def main(): pass\n",
}

# Python uv workspace monorepo (apps/ + libs/)
PYTHON_UV_WORKSPACE = {
    "pyproject.toml": """\
[project]
name = "myworkspace"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = ["typer>=0.26.7"]

[tool.uv.workspace]
members = [
    "apps/my-cli",
    "libs/my-shared-lib",
]
""",
    "uv.lock": "# uv lock\n",
    ".python-version": "3.12\n",
    "apps/my-cli/pyproject.toml": """\
[project]
name = "my-cli"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["my-shared-lib==0.1.0"]

[project.scripts]
my-cli = "my_cli.main:main"

[tool.uv.sources]
my-shared-lib = { workspace = true }
""",
    "apps/my-cli/src/my_cli/main.py": """\
def main():
    print('hello')

if __name__ == '__main__':
    main()
""",
    "libs/my-shared-lib/pyproject.toml": """\
[project]
name = "my-shared-lib"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""",
    "libs/my-shared-lib/src/my_shared_lib/__init__.py": "# shared lib\n",
}

# Python monorepo con run command apuntando a archivo basura (bug: delete_after/)
PYTHON_JUNK_MAINSCRIPT = {
    "pyproject.toml": """\
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.11"
""",
    "uv.lock": "# uv lock\n",
    # archivo basura profundo con __main__ (debe ignorarse)
    "src/myapp/delete_after/backtest.py": """\
import sys

if __name__ == '__main__':
    print('junk')
""",
    # archivo canónico con __main__ (debe elegirse)
    "src/myapp/main.py": """\
def run(): pass

if __name__ == '__main__':
    run()
""",
}
