"""Tests of the assessment workspace: what an assessment reads, named by digest, and the case study's fixtures."""

import json
from pathlib import Path

import pytest
import yaml

from skuld import inputs

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"


def write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path):
    o = write(tmp_path / "o" / "observation_report.json", {"claims": []})
    d = write(tmp_path / "d" / "report.json", {"claims": []})
    run = tmp_path / "run"
    write(run / "run.json", {"run_id": "r1"})
    (run / "events.jsonl").write_text(json.dumps({"type": "screen", "texts": ["Welcome"]}) + "\n")
    root = tmp_path / "ws"
    inputs.describe_assessment(root, "app.example", "1.0", [(o, "r0")], d, run, CORPUS, comment="a test")
    return root, o, d, run


def test_an_assessment_names_what_it_reads_and_loads_it(workspace):
    root, o, d, run = workspace
    a = inputs.load_assessment(root)
    assert (a.package, a.version) == ("app.example", "1.0")
    assert [r.path for r in a.observations] == [o.resolve()] and a.observations[0].run == "r0"
    assert a.declaration.path == d.resolve() and a.exploration == run.resolve()
    assert a.frame.id == "gdpr-art5" and a.models["expectation"] == a.models["assessment"]
    assert a.cases is None  # no case workspace in this folder
    assert (
        yaml.safe_load((root / "assessment.yaml").read_text(encoding="utf-8"))["observation"][0]["path"]
        == "../o/observation_report.json"
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda o, d, run: o.write_text("{}"),
        lambda o, d, run: d.write_text("{}"),
        lambda o, d, run: (run / "run.json").write_text("{}"),
        # the screens' texts stage 1 reads are in the events, not the run record
        lambda o, d, run: (run / "events.jsonl").write_text(json.dumps({"type": "screen", "texts": ["Hi"]}) + "\n"),
    ],
)
def test_a_changed_report_or_run_is_refused(workspace, change):
    root, o, d, run = workspace
    change(o, d, run)
    with pytest.raises(inputs.InputError, match="changed"):
        inputs.load_assessment(root)
    inputs.load_assessment(root, check=False)  # unchecked, it loads


def test_a_frame_of_another_version_is_refused(workspace):
    root = workspace[0]
    data = yaml.safe_load((root / "assessment.yaml").read_text(encoding="utf-8"))
    data["frame"]["sha256"] = "0" * 64
    (root / "assessment.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(inputs.InputError, match="frame"):
        inputs.load_assessment(root)


def test_an_assessment_without_d_or_an_exploration(tmp_path):
    o = write(tmp_path / "o.json", {"claims": []})
    root = tmp_path / "ws"
    inputs.describe_assessment(root, "app.example", "1.0", [(o, None)], None, None, CORPUS)
    a = inputs.load_assessment(root)
    assert a.declaration is None and a.exploration is None
    data = yaml.safe_load((root / "assessment.yaml").read_text(encoding="utf-8"))
    data["observation"] = []
    (root / "assessment.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(inputs.InputError, match="at least one O report"):
        inputs.load_assessment(root)


FIXTURES = {
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4": (3, True, False, True),
    "air.nn.mobile.app.main@3.8.96": (1, True, True, False),
    # D since 2026-10-31: Data safety, listing and in-app notice; the policy did not render (G-5)
    "de.wetteronline.wetterapp@2026.20": (None, True, True, True),
}


@pytest.mark.parametrize("name", FIXTURES)
def test_the_case_studys_fixtures_load(name):
    root = ROOT / "workspaces" / name
    if not (root / "assessment.yaml").is_file():
        pytest.skip("the case study's workspaces are not in this checkout")
    a = inputs.load_assessment(root)
    observations, with_d, with_exploration, with_cases = FIXTURES[name]
    assert observations is None or len(a.observations) == observations
    assert (a.declaration is not None, a.exploration is not None, a.cases is not None) == (
        with_d,
        with_exploration,
        with_cases,
    )
    for report in a.observations:
        assert report.load()["observations"][0]["package"] == a.package
    if a.declaration:
        store_version = a.declaration.load()["collection"]["store_version"]
        # an unknown store version (WetterOnline's collection) is comparable, with the version recorded unknown
        assert store_version in (None, a.version) or frozenset((store_version, a.version)) in a.compatible_pairs()


def test_skuld_describe_writes_the_assessment_workspace(tmp_path):
    from skuld.cli import main

    o = write(tmp_path / "runs" / "r9" / "analysis" / "observation_report.json", {"claims": []})
    root = tmp_path / "ws"
    assert main(["describe", str(root), "--package", "app.example", "--version", "2.0", "--observation", str(o)]) == 0
    a = inputs.load_assessment(root)
    assert a.observations[0].run == "r9" and a.declaration is None and a.exploration is None


def test_an_assessment_is_read_with_the_frame_version_it_names(tmp_path):
    """Workspaces assessed before frame 1.1.0 name 1.0.1; they load with it, not with the current frame."""
    o = write(tmp_path / "o" / "observation_report.json", {"claims": []})
    root = tmp_path / "ws"
    inputs.describe_assessment(root, "app.example", "1.0", [(o, "r0")], None, None, CORPUS, frame_version="1.0.1")
    named = yaml.safe_load((root / "assessment.yaml").read_text(encoding="utf-8"))["frame"]
    assert named["version"] == "1.0.1"
    a = inputs.load_assessment(root)
    assert a.frame.version == "1.0.1" and a.frame.digest() == named["sha256"]
    assert "declaration_corresponds" not in a.frame.requirements


def test_a_frame_version_that_is_not_bundled_is_refused(tmp_path):
    o = write(tmp_path / "o" / "observation_report.json", {"claims": []})
    root = tmp_path / "ws"
    inputs.describe_assessment(root, "app.example", "1.0", [(o, "r0")], None, None, CORPUS)
    text = (root / "assessment.yaml").read_text(encoding="utf-8")
    from ratatoskr.frames import Frame

    current = Frame.load("gdpr-art5").version  # the bundled frame a new workspace names
    assert f"version: {current}" in text
    (root / "assessment.yaml").write_text(text.replace(f"version: {current}", "version: 0.9.0"), encoding="utf-8")
    from ratatoskr.errors import ConfigError

    with pytest.raises(ConfigError, match="not available in version 0.9.0"):
        inputs.load_assessment(root)


def test_a_key_given_twice_is_refused(workspace):
    """A second `compatible_versions:` silently replaced the first (qwen's Remini: 351 concerns to 1)."""
    root = workspace[0]
    text = (root / "assessment.yaml").read_text(encoding="utf-8")
    (root / "assessment.yaml").write_text(text + "corpus: {path: x, sha256: y}\n", encoding="utf-8")
    with pytest.raises(inputs.InputError, match="the key 'corpus' is given twice"):
        inputs.load_assessment(root)


def test_the_strict_loader_reads_what_yaml_reads_otherwise():
    from skuld import yamlio

    assert yamlio.load("a: 1\nb: {c: [1, 2]}\n") == {"a": 1, "b": {"c": [1, 2]}}
    assert yamlio.load("- {a: 1}\n- {a: 2}\n") == [{"a": 1}, {"a": 2}]  # equal keys in different mappings
    with pytest.raises(yamlio.DuplicateKeyError, match="first at line 2"):
        yamlio.load("x: 0\nb:\n  c: 1\nb: 2\n")


def test_describe_again_keeps_the_compatibility_statements_and_the_models(workspace):
    """The study re-applied them with add_compat.py and set_models.py after every describe (plan/archive/POST_PAPER_FIXES 3)."""
    root, o, d, run = workspace
    statement = inputs.add_compatible_versions(root, "1.0", "1.1", "the author compared them", "tomcory")
    assert statement["versions"] == ["1.0", "1.1"] and statement["author"] == {"kind": "person", "id": "tomcory"}
    inputs.describe_assessment(root, "app.example", "1.0", [(o, "r0")], d, run, CORPUS, model="qwen3.8:27b")
    inputs.describe_assessment(root, "app.example", "1.0", [(o, "r0")], d, run, CORPUS)  # again, without --model
    a = inputs.load_assessment(root)
    assert a.models == {"expectation": "qwen3.8:27b", "assessment": "qwen3.8:27b"}
    assert [s["versions"] for s in a.compatible_versions] == [["1.0", "1.1"]]


def test_a_compatibility_statement_is_refused_twice_or_without_a_reason(workspace):
    root = workspace[0]
    inputs.add_compatible_versions(root, "1.0", "1.1", "checked", "tomcory")
    with pytest.raises(inputs.InputError, match="stated compatible already"):
        inputs.add_compatible_versions(root, "1.1", "1.0", "again", "tomcory")
    with pytest.raises(inputs.InputError, match="two different versions"):
        inputs.add_compatible_versions(root, "1.0", "1.0", "same", "tomcory")
    with pytest.raises(inputs.InputError, match="gives its reason"):
        inputs.add_compatible_versions(root, "1.0", "2.0", "  ", "tomcory")
    assert (root / "assessment.yaml").read_text(encoding="utf-8").startswith("# a test\n")  # the comment kept


def test_compat_add_on_the_command_line(workspace, capsys):
    from skuld.cli import main

    root = workspace[0]
    assert main(["compat", "add", str(root), "--o", "1.0", "--d", "1.2", "--reason", "r", "--author", "a"]) == 0
    assert "1.0 ~ 1.2" in capsys.readouterr().out
    assert main(["compat", "add", str(root), "--o", "1.0", "--d", "1.2", "--reason", "r", "--author", "a"]) == 1


def o_report(path: Path, run: str, frida=("location=pass",), blocked=(), hosts=None) -> Path:
    """An O report of one run, with what Verðandi copies of the instruments' settings into its scope."""
    instruments = {
        "heimdall:capture/1": {"settings": {"blocked_hosts": list(blocked)}, "hosts": hosts or {}},
        "frida": {"settings": list(frida)},
    }
    scope = {"observation": run, "context": {"instruments": instruments}}
    return write(path, {"scopes": [scope], "claims": []})


@pytest.mark.parametrize(
    "report",
    [
        dict(frida=("location=round:1",)),
        dict(frida=("advertising_id=replace:00000000-0000-0000-0000-000000000000",)),
        dict(frida=("location=block",)),
        dict(blocked=("ads.example",)),
        dict(hosts={"ads.example": {"connections": 2, "blocked": 2}}),  # settings unread ("?"), connections blocked
    ],
)
def test_a_run_under_an_intervention_is_no_subject_of_the_assessment(tmp_path, report):
    o = o_report(tmp_path / "o" / "observation_report.json", "r1", **report)
    root = tmp_path / "ws"
    with pytest.raises(inputs.InputError, match=r"under an intervention .*\(Q9\)"):
        inputs.describe_assessment(root, "app.example", "1.0", [(o, "r1")], None, None, CORPUS)
    assert not (root / inputs.ASSESSMENT).exists()  # nothing written


def test_the_exploration_and_baseline_runs_are_subjects(tmp_path):
    # the re-run's setup on every run (its plan, D-13 and D-29): the German SIM by the telephony hook, and QUIC refused
    # by the capture's policy, which Verðandi 3.7.4 counts apart from blocked connections
    exploration = o_report(
        tmp_path / "e.json",
        "r0",
        frida=("location=pass", "clipboard=record", "telephony=replace:de,26201,Telekom.de"),
        hosts={"api.maps.example": {"connections": 7, "blocked": 0, "quic_refused": 1}},
    )
    baseline = o_report(tmp_path / "b.json", "r1", hosts={"api.example": {"connections": 3, "blocked": 0}})
    root = tmp_path / "ws"
    inputs.describe_assessment(root, "app.example", "1.0", [(exploration, "r0"), (baseline, "r1")], None, None, CORPUS)
    assert len(inputs.load_assessment(root).observations) == 2


@pytest.mark.parametrize(
    "entry, refused",
    [
        ({"condition": "baseline"}, False),  # a baseline replay: corroborates the exploration
        ({"condition": "baseline", "regime": "goal", "goal_id": "c1"}, False),  # a goal run under no intervention
        ({"condition": "G1"}, True),  # a replay under an alternative's condition
        ({"condition": "G1", "regime": "goal", "goal_id": "c1"}, True),  # a goal run under an intervention
        ({"condition": "control", "control_of": "c1"}, True),
    ],
)
def test_a_run_a_case_workspace_lists_under_another_condition_than_baseline_is_refused(tmp_path, entry, refused):
    # the report's settings show no intervention (as for an intervention that left none in it): the case workspace
    # whose observation/<run>/ holds the report says under which condition the run was made
    cases = tmp_path / "cases"
    o = o_report(cases / "observation" / "r5" / "observation_report.json", "r5")
    (cases / "runs.jsonl").write_text(json.dumps({"run": "r5", "dir": "r5", "order": 1, **entry}) + "\n")
    root = tmp_path / "ws"
    if refused:
        with pytest.raises(inputs.InputError, match=f"r5: condition {entry['condition']}"):
            inputs.describe_assessment(root, "app.example", "1.0", [(o, "r5")], None, None, CORPUS)
    else:
        inputs.describe_assessment(root, "app.example", "1.0", [(o, "r5")], None, None, CORPUS)
