"""A launcher-first launch is an invalid run, made once more; a case's control tests its oracle, never the application
(21 Nov 2026)."""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from ratatoskr.schemas import validate

from skuld import catalogue as cat
from skuld import execute, inputs, oracles
from skuld.experiments import analyse, case_claims
from skuld.report import markdown
from skuld.runs import load as load_run
from tests import workspace as ws
from tests.test_execute import FAKE_LOKI

CONTROL = {"intervention": "network", "expected": "breaks"}


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    """No device: the installed version is the workspace's."""
    monkeypatch.setattr(execute, "installed_version", lambda device, package: "1.0")


def edit(root: Path, name: str, change) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def launcher_first(folder: Path) -> Path:
    """A run whose cold start brought up the launcher before the app (Weather's baseline, 13 Nov 2026)."""
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    launcher = {**events[1], "package": "com.google.android.apps.nexuslauncher", "activity": "Launcher"}
    events.insert(1, launcher)
    for seq, e in enumerate(events, 1):
        e["seq"] = seq
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return folder


# -- launcher_first ---------------------------------------------------------------------------------------------------


def test_a_launch_that_brought_up_the_launcher_first_is_invalid(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    edit(root, "oracles/O@1.yaml", lambda o: o["invalid"].append({"launcher_first": {}}))
    oracle = inputs.load(root).oracles["O@1"]
    assert oracles.decide(oracle, load_run(root / "runs" / "run-01")).decision == "met"
    decision = oracles.decide(oracle, load_run(launcher_first(root / "runs" / "run-02")))
    assert decision.decision == "invalid" and "launcher_first" in decision.reasons[0]
    assert {"launcher_first": {}} in cat.LAUNCH_INVALID


#: Loki whose first replay brings up the launcher first; it copies a prepared run folder
COPYING_LOKI = FAKE_LOKI.replace(
    """out.mkdir(parents=True)
(out / "config.yaml")""",
    """count = pathlib.Path(sys.argv[0]).parent / "count"
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
import shutil
shutil.copytree(pathlib.Path(sys.argv[0]).parent / ("launcher" if n == 0 else "ok"), out)
(out / "config.yaml")""",
)


def test_a_run_whose_launch_decides_invalid_is_made_once_more(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    edit(root, "oracles/O@1.yaml", lambda o: o["invalid"].append({"launcher_first": {}}))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    shutil.copytree(root / "runs" / "run-01", tmp_path / "ok")
    launcher_first(shutil.copytree(root / "runs" / "run-01", tmp_path / "launcher"))
    script = tmp_path / "loki.py"
    script.write_text(COPYING_LOKI)
    base = tmp_path / "loki.yaml"
    base.write_text("{}")
    made = execute.run(
        inputs.load(root), tmp_path / "rec-1", base, "d", ["baseline", "A2"], 1, [sys.executable, str(script)]
    )
    assert [e["condition"] for e in made] == ["baseline", "baseline", "A2"]
    assert "launcher_first" in made[0]["repeated"] and not made[1].get("repeated")
    assert len((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()) == 9 + 3  # the invalid one is kept


def test_an_invalid_launch_is_made_once_more_only(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    edit(root, "oracles/O@1.yaml", lambda o: o["invalid"].append({"launcher_first": {}}))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    launcher_first(shutil.copytree(root / "runs" / "run-01", tmp_path / "launcher"))
    shutil.copytree(tmp_path / "launcher", tmp_path / "ok")  # every launch brings up the launcher
    script = tmp_path / "loki.py"
    script.write_text(COPYING_LOKI)
    base = tmp_path / "loki.yaml"
    base.write_text("{}")
    made = execute.run(inputs.load(root), tmp_path / "rec-1", base, "d", ["baseline"], 1, [sys.executable, str(script)])
    assert len(made) == 2 and made[0].get("repeated") and not made[1].get("repeated")


# -- controls ---------------------------------------------------------------------------------------------------------


def controlled(root: Path, control_done: bool) -> Path:
    """The synthetic workspace with a control declared, and three control runs blocking the app's host; their screens
    show the outcome (`control_done`) or not. Fixed before the runs."""
    edit(root, "cases/start.yaml", lambda c: c.update(control=CONTROL, family={"id": "launch", "version": 3}))
    lines = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    for n in range(10, 13):
        run_id = f"run-{n:02d}"
        folder = ws.run_folder(
            root / "runs" / run_id,
            run_id,
            f"2026-10-21T11:{n:02d}:00+00:00",
            aaid=ws.DEVICE_ID,
            blocked=False,
            done=control_done,
        )
        meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        meta["config"]["capture"]["block_hosts"] = ["app.example", "t.tracker.example"]
        (folder / "run.json").write_text(json.dumps(meta), encoding="utf-8")
        report = root / "observation" / run_id / "observation_report.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps(ws.observation_report(run_id, aaid=ws.DEVICE_ID, blocked=False)))
        lines.append({"run": run_id, "dir": run_id, "condition": "control", "order": n, "control_of": "start"})
    (root / "runs.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    ws.rescope(root)
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    return root


def test_a_control_that_breaks_is_recorded_and_makes_no_claim(tmp_path):
    root = controlled(ws.build(tmp_path / "ws", freeze=False), control_done=False)
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)
    (control,) = report["cases"][0]["controls"]
    assert control["family"] == "launch@3" and control["expected"] == "breaks"
    assert (control["outcome"], control["sensitivity_failure"]) == ("breaks", False)
    assert control["control_runs"] == ["run-10", "run-11", "run-12"] and len(control["baseline_runs"]) == 3
    assert control["block_hosts"] == ["app.example", "t.tracker.example"]
    # the control is no comparison: the alternatives' comparisons and claims are those without it
    assert {k["alternative"] for k in report["comparisons"]} == {"A1", "A2"}
    made = case_claims(workspace, report)["start"]
    assert all(c.alternative in (None, "A1", "A2") for c in made)
    assert all(k.id.split(":")[-1] != "control" for c in made for k in c.comparisons)
    control_run = next(r for r in report["runs"] if r["id"] == "run-10")
    assert control_run["alternative"] is None and control_run["control"] == {"case": "start", "intervention": "network"}
    assert "Sensitivity failures" not in markdown(report)


def test_a_control_expected_to_break_that_preserves_is_a_sensitivity_failure_of_the_familys_oracle(tmp_path):
    root = controlled(ws.build(tmp_path / "ws", freeze=False), control_done=True)
    report = analyse(inputs.load(root), make_observations=False)
    validate("expectation_report", report)
    (control,) = report["cases"][0]["controls"]
    assert (control["outcome"], control["sensitivity_failure"]) == ("preserves", True)
    rendered = markdown(report)
    assert "Sensitivity failures of the oracles of: launch@3." in rendered and "| launch@3 | start | P1 |" in rendered


def test_a_control_run_blocks_every_host_the_cases_baseline_runs_contacted(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    edit(root, "cases/start.yaml", lambda c: c.update(control=CONTROL))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    workspace = inputs.load(root)
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    script = tmp_path / "loki.py"
    script.write_text(FAKE_LOKI)
    made = execute.run(
        workspace, tmp_path / "rec", base, "d", ["baseline", "control"], 1, [sys.executable, str(script)], case="start"
    )
    control = next(e for e in made if e["condition"] == "control")
    assert control["control_of"] == "start"
    blocked = yaml.safe_load((Path(control["dir"]) / "config.yaml").read_text(encoding="utf-8"))["capture"]
    assert blocked["block_hosts"] == ["app.example", "t.tracker.example"]  # the baseline runs' hosts, not blocked there
    with pytest.raises(execute.ExecutionError, match="control"):
        execute.run(workspace, tmp_path / "rec", base, "d", ["control"], 1, [sys.executable, str(script)])


def test_a_family_declares_a_control_the_catalogue_checks():
    from tests.test_propose import FORECAST as family

    cat.check({**family, "control": CONTROL})
    with pytest.raises(cat.CatalogueError, match="intervention"):
        cat.check({**family, "control": {"intervention": "airplane", "expected": "breaks"}})
    with pytest.raises(cat.CatalogueError, match="expected"):
        cat.check({**family, "control": {"intervention": "network", "expected": "maybe"}})
    with pytest.raises(cat.CatalogueError, match="intervention, expected"):
        cat.check({**family, "control": {"intervention": "network"}})
