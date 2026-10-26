"""The provenance check of a case report: every digest verifies and every pointer resolves, and a tampered record is
found."""

from skuld import inputs
from skuld.experiments import analyse
from skuld.provenance import check
from tests import workspace as ws


def test_a_reports_provenance_is_complete_and_a_tampered_record_is_found(tmp_path):
    root = ws.build(tmp_path / "ws")
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    assert check(workspace, report) == []

    observation = root / "observation" / "run-02" / "observation_report.json"
    observation.write_text(observation.read_text().replace("advertising_id", "android_id", 1))
    problems = check(workspace, report)
    assert any("run-02: its observation report does not verify" in p for p in problems)


def test_a_pointer_to_a_missing_record_is_found(tmp_path):
    root = ws.build(tmp_path / "ws")
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    item = next(i for i in report["evidence"] if (i["provenance"] or [{}])[0].get("source", "").startswith("run:"))
    item["provenance"][0]["record"] = "missing.json"
    assert any("missing.json is missing" in p for p in check(workspace, report))
