from project_ai.model import (Command, Evidence, Fact, ProjectInfo, SourcePriority as P,
                              StackDetection, Status)


def test_requirement_priority_and_evidence():
    p = ProjectInfo(root="/x")
    p.add_requirement("jdk", Fact("17", P.BUILD, evidence=[Evidence("pom.xml", 3)]))
    p.add_requirement("jdk", Fact("21", P.DEFAULT))
    p.add_requirement("jdk", Fact("17", P.EXPLICIT, evidence=[Evidence(".tool-versions", 1)]))
    f = p.requirements["jdk"]
    assert f.value == "17" and f.priority == P.EXPLICIT
    assert len(f.evidence) == 2
    assert f.alternatives[0]["value"] == "21"


def test_higher_priority_replaces():
    p = ProjectInfo(root="/x")
    p.add_requirement("jdk", Fact("11", P.HEURISTIC, evidence=[Evidence("README.md", 9)]))
    p.add_requirement("jdk", Fact("17", P.CI, evidence=[Evidence("ci.yml", 2)]))
    f = p.requirements["jdk"]
    assert f.value == "17" and f.alternatives[0]["value"] == "11"


def test_same_priority_conflict():
    p = ProjectInfo(root="/x")
    p.add_requirement("cmake", Fact("3.20", P.BUILD, evidence=[Evidence("a/CMakeLists.txt", 1)]))
    p.add_requirement("cmake", Fact("3.25", P.BUILD, evidence=[Evidence("b/CMakeLists.txt", 1)]))
    assert p.requirements["cmake"].status == Status.CONFLICT
    assert p.warnings


def test_services_merge():
    p = ProjectInfo(root="/x")
    p.add_service("postgresql", Fact("13", P.CI, evidence=[Evidence("a.yml", 3)]))
    p.add_service("postgresql", Fact("12", P.CI, evidence=[Evidence("b.yml", 3)]))
    p.add_service("postgresql", Fact("*", P.HEURISTIC, evidence=[Evidence("c.md", 1)]))
    assert len(p.services) == 1
    s = p.services[0].fact
    assert s.value == "13" and s.alternatives[0]["value"] == "12" and len(s.evidence) == 2


def test_list_fact_dedup():
    p = ProjectInfo(root="/x")
    for _ in range(3):
        p.add_list_fact("hints.ports", "8080", priority=P.CI)
    assert p.facts["hints.ports"].value == ["8080"]


def test_roundtrip(tmp_path):
    p = ProjectInfo(root="/x")
    p.add_requirement("jdk", Fact("17", P.BUILD, evidence=[Evidence("pom.xml", 1, "x")],
                                  adapter="maven"))
    p.add_service("redis", Fact("7", P.CI))
    p.add_list_fact("hints.commands", {"cmd": "mvn package"}, priority=P.CI)
    p.add_command(Command("build", "./mvnw package", fact=Fact("x", P.BUILD)))
    p.add_stack(StackDetection("maven", 0.9, evidence=[Evidence("pom.xml")]))
    out = p.save(tmp_path / "project.json")
    assert ProjectInfo.load(out).to_dict() == p.to_dict()
