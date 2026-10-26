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
        yaml.safe_load((root / "assessment.yaml").read_text())["observation"][0]["path"]
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
    data = yaml.safe_load((root / "assessment.yaml").read_text())
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
    data = yaml.safe_load((root / "assessment.yaml").read_text())
    data["observation"] = []
    (root / "assessment.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(inputs.InputError, match="at least one O report"):
        inputs.load_assessment(root)


FIXTURES = {
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4": (3, True, False, True),
    "air.nn.mobile.app.main@3.8.96": (1, True, True, False),
    "de.wetteronline.wetterapp@2026.20": (None, False, True, True),
}


@pytest.mark.parametrize("name", FIXTURES)
def test_the_case_studys_fixtures_load(name):
    root = ROOT / "cases" / name
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
        assert a.declaration.load()["collection"]["store_version"] == a.version


def test_skuld_describe_writes_the_assessment_workspace(tmp_path):
    from skuld.cli import main

    o = write(tmp_path / "runs" / "r9" / "analysis" / "observation_report.json", {"claims": []})
    root = tmp_path / "ws"
    assert main(["describe", str(root), "--package", "app.example", "--version", "2.0", "--observation", str(o)]) == 0
    a = inputs.load_assessment(root)
    assert a.observations[0].run == "r9" and a.declaration is None and a.exploration is None
