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
