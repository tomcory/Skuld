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
    observation.write_text(
        observation.read_text(encoding="utf-8").replace("advertising_id", "android_id", 1), encoding="utf-8"
    )
    problems = check(workspace, report)
    assert any("run-02: its observation report does not verify" in p for p in problems)


def test_a_pointer_to_a_missing_record_is_found(tmp_path):
    root = ws.build(tmp_path / "ws")
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    item = next(i for i in report["evidence"] if (i["provenance"] or [{}])[0].get("source", "").startswith("run:"))
    item["provenance"][0]["record"] = "missing.json"
    assert any("missing.json is missing" in p for p in check(workspace, report))


def test_a_kept_answer_with_a_carriage_return_verifies_by_its_bytes(tmp_path):
    import hashlib
    import json

    from skuld.provenance import _samples

    folder = tmp_path / "assessment" / "minimisation" / "P-1" / "s1"
    folder.mkdir(parents=True)
    parts = [{"id": "A1", "text": "x"}]
    answer = '{"alternatives": [\n \r \r ]}'
    (folder / "context.json").write_text(json.dumps({"parts": parts}), encoding="utf-8")
    (folder / "answer.json").write_text(answer, encoding="utf-8", newline="\n")
    context_sha = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    record = {"context": {"sha256": context_sha}, "answer": {"sha256": hashlib.sha256(answer.encode()).hexdigest()}}
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")
    assert _samples(tmp_path)[1] == []

    (folder / "answer.json").write_text(answer + " ", encoding="utf-8", newline="\n")
    assert _samples(tmp_path)[1] == ["sample assessment/minimisation/P-1/s1: its answer does not verify"]
