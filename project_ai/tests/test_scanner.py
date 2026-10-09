from conftest import HMDM, NETCLIENT, git_init, make_tree, needs_git

from project_ai.scanner import ProjectScanner


def _check_netclient(sc: ProjectScanner):
    assert sc.generated_dirs == ["build", "build-android"]
    assert not any(f.startswith(("build/", "build-android/", ".cache/")) for f in sc.files)
    assert ".DS_Store" not in sc.files
    assert "bin/run.sh" in sc.files                        # bin legítimo se conserva
    assert sc.build_artifacts["compile_commands"] == ["build/Debug/compile_commands.json"]
    assert len(sc.build_artifacts["cmake_cache"]) == 2
    kf = sc.key_files()
    assert "readme.md" in kf["docs"]                       # minúsculas
    assert "CMakeUserPresets.json" in kf["build"]
    assert not any("generators" in f for f in kf["build"])
    assert "new_module_c++.sh" in kf["scripts"]
    assert ".vscode/launch.json" in kf["ide"]


def test_netclient_walk(tmp_path):
    _check_netclient(ProjectScanner(make_tree(tmp_path, NETCLIENT), use_git=False))


@needs_git
def test_netclient_git_tracked_build_dirs(tmp_path):
    root = make_tree(tmp_path, NETCLIENT)
    git_init(root)
    sc = ProjectScanner(root)
    assert sc.listing_method == "git"
    _check_netclient(sc)


def test_hmdm_key_files(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, HMDM), use_git=False)
    assert sc.generated_dirs == ["server/target"]
    kf = sc.key_files()
    assert {"BUILD.txt", "INSTALL.txt", "TROUBLESHOOTING.txt"} <= set(kf["docs"])
    assert "LICENSE" not in kf["docs"]
    assert ".smarttomcat/server/conf/web.xml" in kf["ide"]
    assert "context.xml" in kf["config"]
    assert "server/src/main/webapp/WEB-INF/web.xml" in kf["config"]
    assert "hmdm_install.sh" in kf["scripts"]
    assert len(kf["container"]) == 4


def test_target_without_pom_is_kept(tmp_path):
    root = make_tree(tmp_path, {"docs/target/notes.md": "x", "README.md": "x"})
    assert "docs/target/notes.md" in ProjectScanner(root, use_git=False).files


def test_glob_semantics(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, HMDM), use_git=False)
    assert sc.glob("**/pom.xml") == ["pom.xml", "common/pom.xml", "server/pom.xml"]
    assert sc.glob("*.xml") == ["context.xml", "pom.xml"]
    assert sc.glob("server/**/*.java") == ["server/src/main/java/com/hmdm/App.java"]
    assert sc.glob("**/DOCKERFILE", icase=True) == [
        "Dockerfile", "docker/hmdm-docker-0.1.5/Dockerfile"]


def test_grep(tmp_path):
    sc = ProjectScanner(make_tree(tmp_path, HMDM), use_git=False)
    hits = sc.grep(r"<packaging>war", exts={".xml"})
    assert [(h.file, h.line) for h in hits] == [("server/pom.xml", 1)]
