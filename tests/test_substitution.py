"""A substitute identifier as an outcome of a run of its own: the application fell back to another identifier once the
changed one was replaced (20 Nov 2026; before, the run's verification failed and the run was refused)."""

import json
from pathlib import Path
from types import SimpleNamespace

from ratatoskr.schemas import validate

from skuld import inputs
from skuld.experiments import analyse, case_claims
from skuld.report import markdown
from skuld.verify import Verification, _substitution
from tests import workspace as ws

APP_SET_ID = "device-or-other-ids.app-set-id"


def _run():
    return SimpleNamespace(meta={"device": {"ro.build.version.sdk": "33"}})


def test_a_substitute_is_named_with_its_reads_and_does_not_fail_the_check_list(monkeypatch):
    import skuld.verify as verify

    found = [{"id": "r1", "kinds": ["rt"]}, {"id": "r2", "kinds": ["rt"]}]
    monkeypatch.setattr(verify, "source_reads", lambda report, source: found if source == "app_set_id" else [])
    monkeypatch.setattr(verify, "hook_status", lambda report, source: "verified")
    v = Verification(status="verified")
    node = "device-or-other-ids.advertising-id"
    _substitution(v, _run(), {"evidence": []}, node, {"app_set_id": "pass"}, {"app_set_id": [0, 0, 0]})
    check = next(c for c in v.substitution if c["node"] == APP_SET_ID)
    assert check["holds"] is False and check["substitute"] is True and check["evidence"] == ["r1", "r2"]
    assert "fell back" in check["note"]
    # a source that is not hooked stays an unverifiable part, not a substitute
    assert any(u.startswith("substitution by device-or-other-ids.android-id") for u in v.unverifiable)


def _hook_app_set_id(root: Path, reads: dict[str, int]) -> None:
    """Every run hooks the App Set ID as well (`pass`); a run in `reads` has that many reads of it in O's report."""
    for folder in sorted((root / "runs").iterdir()):
        path = folder / "run.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        instrumentation = meta["instrumentation"]
        instrumentation["settings"].append("app_set_id=pass")
        n = reads.get(folder.name, 0)
        instrumentation["verification"]["sources"]["app_set_id"] = {
            "setting": "app_set_id=pass",
            "status": "verified" if n else "not_exercised",
            "calls": n,
            "returned": ["set-1"] * n,
        }
        path.write_text(json.dumps(meta))
        report_path = root / "observation" / folder.name / "observation_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for i in range(n):
            report["evidence"].append(
                {
                    "id": f"s{i}",
                    "proposition": {"kind": "source_read", "source": "app_set_id", "value": "set-1"},
                    "kinds": ["rt"],
                    "method": "source_hook",
                    "provenance": [
                        {"observation": folder.name, "instrument": "frida.sources", "record": "events.jsonl"}
                    ],
                    "uncertainty": ws.LOW,
                }
            )
        report_path.write_text(json.dumps(report))
    ws.rescope(root)


def test_a_run_that_fell_back_to_the_app_set_id_is_verified_and_its_comparison_names_the_substitute(tmp_path):
    root = ws.build(tmp_path)
    runs = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    a1 = [e["run"] for e in runs if e["condition"] == "A1"]
    # identical baselines (no read) leave no tolerance: two of the three runs under A1 fall back, as Remini's did
    _hook_app_set_id(root, {a1[0]: 2, a1[1]: 1})
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)

    by_run = {r["id"]: r for r in report["runs"]}
    assert by_run[a1[0]]["verification"]["status"] == "verified"
    assert by_run[a1[0]]["verification"]["substitutes"] == [APP_SET_ID]
    assert "substitutes" not in by_run[a1[2]]["verification"]
    assert not any(r in report["cases"][0]["excluded"] for r in a1)

    k = next(k for k in report["comparisons"] if k["alternative"] == "A1")
    assert k["alternative_runs"] == a1 and k["substitutes"] == [APP_SET_ID]
    assert k["outcome"] == "preserves"  # the oracle's outcome is unchanged; the substitute is reported beside it
    assert "substitutes" not in next(k for k in report["comparisons"] if k["alternative"] == "A2")
    verification = next(e for e in report["evidence"] if e["id"] == f"v:start:{a1[0]}")
    assert verification["proposition"]["substitutes"] == [APP_SET_ID]
    assert next(c for c in report["report"]["components"] if c["id"] == "skuld.verify")["version"] == "2"

    claims = [c for made in case_claims(workspace, report).values() for c in made]
    read = next(c for c in claims if c.type == "dependency" and c.component == "aaid" and c.purpose == "P1")
    assert read.comparisons[0].substitutes == [APP_SET_ID]
    assert f"preserves (substitute: {APP_SET_ID})" in markdown(report)


def test_a_failed_effect_still_fails_the_run(tmp_path):
    """The substitute is reported; the intervention's own effect still decides the verification."""
    root = ws.build(tmp_path)
    runs = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    a1 = [e["run"] for e in runs if e["condition"] == "A1"]
    _hook_app_set_id(root, {a1[0]: 1})
    path = root / "runs" / a1[0] / "run.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["instrumentation"]["verification"]["sources"]["advertising_id"]["status"] = "violated"
    path.write_text(json.dumps(meta))
    ws.rescope(root)
    report = analyse(inputs.load(root), make_observations=False)
    assert report["cases"][0]["excluded"][a1[0]] == "intervention for A1 not verified"
    assert a1[0] not in next(k for k in report["comparisons"] if k["alternative"] == "A1")["alternative_runs"]
