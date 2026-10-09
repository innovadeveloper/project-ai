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
    "readme.md": "# netclient\n\n```bash\nconan install . --build=missing\n"
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
    "pom.xml": "<project><modules><module>common</module><module>server</module>"
               "</modules></project>\n",
    "common/pom.xml": "<project/>\n",
    "server/pom.xml": "<project><packaging>war</packaging></project>\n",
    "server/src/main/webapp/WEB-INF/web.xml": "<web-app/>\n",
    "server/src/main/java/com/hmdm/App.java": "class App {}\n",
    "context.xml": "<Context/>\n",
    ".smarttomcat/hmdm/config.xml": "<option name='tomcat' value='/opt/apache-tomcat-9.0.71'/>\n",
    "BUILD.txt": "Requirements: Java 8 and Maven 3.6\n\nTo build:\n\n"
                 "    mvn install\n\nThen copy the war file.\n",
    "INSTALL.txt": "Install PostgreSQL 13 and Tomcat 9 first.\n"
                   "$ sudo ./hmdm_install.sh\n",
    "TROUBLESHOOTING.txt": "If the build fails, check JAVA_HOME.\n",
    "LICENSE": "Apache License 2.0 java 11 should be ignored\n",
    "hmdm_install.sh": "#!/bin/bash\n",
    "Dockerfile": "ARG BASE=tomcat:9-jdk11-openjdk\nFROM ${BASE}\n"
                  "RUN apt-get update && \\\n    apt-get install -y aapt\n"
                  "COPY server/target/launcher.war /usr/local/tomcat/webapps/ROOT.war\n"
                  "EXPOSE 8080 8443/tcp\n",
    "docker/hmdm-docker/docker-compose.yaml":
        "services:\n  db:\n    image: postgres:13\n  app:\n    image: headwindmdm/hmdm:0.1.5\n",
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
