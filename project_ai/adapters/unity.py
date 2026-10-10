"""
adapters/unity.py — Proyectos Unity (C#, juegos/simulaciones 2D/3D).

Señal de detección: ProjectSettings/ProjectVersion.txt  (requisito).
Las .csproj que Unity genera para el IDE son auto-generadas; no se usan
como señal de build. Si están en git, el adaptador dotnet también activará,
pero los comandos correctos son los de este adaptador.

Qué descubre:
  Versión Unity   ProjectSettings/ProjectVersion.txt → m_EditorVersion (EXPLICIT)
  Pipeline        URP / HDRP / Built-in desde Packages/manifest.json (BUILD)
  Servicios       Firebase, Unity Gaming Services, Nakama desde manifest.json
  Módulo          kind=unity-game
  Comandos        Unity -batchmode para test/build en CI; nota para Unity Hub.

Prioridades:
  ProjectSettings/ProjectVersion.txt  → EXPLICIT
  Packages/manifest.json              → BUILD
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..model import Command, Fact, Module, ProjectInfo, SourcePriority as P, StackDetection
from ..scanner import ProjectScanner
from .base import Adapter, add_service, ev, register

NAME = "unity"

# m_EditorVersion: 2022.3.15f1  (el colon separa de WithRevision)
_RX_UNITY_VER = re.compile(r'^m_EditorVersion:\s*([\w.]+)', re.MULTILINE)

_RENDER_PIPELINES: dict[str, str] = {
    "com.unity.render-pipelines.universal":       "URP",
    "com.unity.render-pipelines.high-definition": "HDRP",
}

_PKG_SERVICES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^com\.google\.firebase'),                                          "firebase"),
    (re.compile(r'^com\.unity\.services\.(authentication|core|cloudcode|economy)'), "unity-gaming-services"),
    (re.compile(r'^io\.nakama'),                                                     "nakama"),
    (re.compile(r'^com\.playfab'),                                                   "playfab"),
]


@register
class UnityAdapter(Adapter):
    name = NAME
    always_run = False

    def detect(self, sc: ProjectScanner) -> list[StackDetection]:
        ver_file = next(
            (f for f in sc.files if f.endswith("ProjectVersion.txt")),
            None,
        )
        if not ver_file:
            return []
        return [StackDetection(
            adapter=NAME, confidence=0.95,
            evidence=[ev(ver_file, None, "Unity ProjectVersion.txt encontrado")],
        )]

    def analyze(self, sc: ProjectScanner, info: ProjectInfo,
                detections: list[StackDetection]) -> None:
        root = Path(sc.root)

        _parse_project_version(root, info)
        _parse_packages(root, sc.files, info)

        # Si hay .csproj en git el adaptador dotnet también activa; sus comandos son incorrectos para Unity
        has_csproj = any(f.endswith(".csproj") for f in sc.files)
        if has_csproj:
            info.warnings.append(
                "Proyecto Unity: los archivos .csproj son auto-generados para el IDE. "
                "Ignorar los comandos 'dotnet' si aparecen — usar solo los comandos de Unity."
            )

        info.modules.append(Module(
            name=root.name, path=".", build_system=NAME, kind="unity-game",
        ))

        _add_commands(info)


def _parse_project_version(root: Path, info: ProjectInfo) -> None:
    path = root / "ProjectSettings" / "ProjectVersion.txt"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    m = _RX_UNITY_VER.search(text)
    if m:
        ver = m.group(1)
        info.set_fact("unity.version", Fact(
            value=ver, priority=P.EXPLICIT,
            evidence=[ev("ProjectSettings/ProjectVersion.txt", None,
                         f"m_EditorVersion: {ver}")],
            adapter=NAME,
        ))


def _parse_packages(root: Path, files: list[str], info: ProjectInfo) -> None:
    rel = next((f for f in files if f.endswith("manifest.json")
                and "Packages" in f), None)
    if rel is None:
        # Intentar ruta canónica aunque no esté en git index
        candidate = root / "Packages" / "manifest.json"
        if candidate.exists():
            rel = "Packages/manifest.json"
        else:
            return
    try:
        data = json.loads((root / rel).read_text(encoding="utf-8"))
    except Exception:
        return

    deps: dict[str, str] = data.get("dependencies", {})

    # Pipeline de renderizado
    pipeline = "Built-in"
    for pkg_id, name in _RENDER_PIPELINES.items():
        if pkg_id in deps:
            pipeline = name
            break
    info.set_fact("unity.render_pipeline", Fact(
        value=pipeline,
        priority=P.BUILD if pipeline != "Built-in" else P.HEURISTIC,
        evidence=[ev(rel, None, f"render pipeline: {pipeline}")],
        adapter=NAME,
    ))

    # Servicios desde paquetes UPM
    for pkg_id, ver in deps.items():
        for rx, svc_kind in _PKG_SERVICES:
            if rx.search(pkg_id):
                add_service(info, svc_kind, ver, P.BUILD,
                            rel, None, pkg_id, adapter=NAME)
                break


def _add_commands(info: ProjectInfo) -> None:
    info.add_command(Command(
        name="run",
        shell="# Abrir con Unity Hub: unity-hub --projectPath .",
        ide_hint="Unity Hub: Add project → selecciona esta carpeta; o doble clic en la versión en el Hub",
        success_hint="Unity Editor iniciado",
    ))
    info.add_command(Command(
        name="test",
        shell=(
            "Unity -quit -batchmode -projectPath . "
            "-runTests -testPlatform EditMode "
            "-testResults .project-ai/logs/unity-test-results.xml"
        ),
        success_hint="Test run succeeded",
    ))
    info.add_command(Command(
        name="build",
        shell=(
            "# Requiere BuildScript en Assets/Editor/ que llame BuildPipeline.BuildPlayer();\n"
            "# Unity -quit -batchmode -projectPath . -executeMethod BuildScript.Build"
        ),
        ide_hint="Unity Editor: File → Build Settings → Build",
        success_hint="Build succeeded",
    ))
