"""Goal-directed runs of a deeper case (21 Nov 2026): Loki's goal regime instead of a replay of the recorded path, the
goal episode as the oracles' window, and qualification by the oracle, never by the agent's statement alone."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from ratatoskr.schemas import validate

from skuld import execute, inputs, oracles
from skuld.experiments import GOAL_NOT_REACHED, RunState, analyse, case_claims, runs_of
from skuld.runs import goal_window
from skuld.runs import load as load_run
from tests import workspace as ws
from tests.test_execute import FAKE_LOKI

#: The case's path in the recording: its first action
PATH = {"run": "rec-1", "from": 0, "actions": 1}


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    """No device: the installed version is the workspace's."""
    monkeypatch.setattr(execute, "installed_version", lambda device, package: "1.0")


def deep(root: Path) -> Path:
    """The synthetic workspace with its case given a path, so that it is run goal-directed; fixed."""
    from datetime import datetime

    case = yaml.safe_load((root / "cases" / "start.yaml").read_text(encoding="utf-8"))
    case["feature"]["path"] = PATH
    (root / "cases" / "start.yaml").write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    return root


def goal_run(folder: Path, goal: str = "start", reached: bool = True, done_in_window: bool = True) -> Path:
    """
    Turns a replay folder of tests/workspace.py into a goal-directed run: the goal episode shows the app's main
    screen, takes one action and shows its outcome ('done') before the agent's statement, or shows it only in the
    logout episode after it (`done_in_window` False); without `reached`, the agent made no statement.
    """
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    old = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    start = meta["started_at"]
    stop = "goal_reached" if reached else "goal_not_reached (capped_duration)"
    for key in ("replay_of", "replay"):
        meta.pop(key, None)
    meta |= {
        "regime": "goal",
        "stop_reason": stop,
        "regime_summary": {"goal": {"feature": "launch: the main screen", "id": goal, "reached": reached}},
    }
    main, read = old[1], old[2]
    done = {**main, "screen_id": "s2", "exact_key": "done"}
    events = [
        {"type": "run_start"},
        {"type": "episode_start", "episode": 1, "kind": "goal", "item_id": goal},
        main,
        read,
        {"type": "action", "kind": "tap", "episode": 1},
        *([done] if done_in_window else []),
        *([{"type": "goal_reached", "episode": 1, "screen_id": "s2", "description": "done"}] if reached else []),
        {"type": "episode_end", "episode": 1},
        {"type": "episode_start", "episode": 2, "kind": "logout", "item_id": None},
        *([] if done_in_window else [done]),
        {"type": "run_end", "stop_reason": stop},
    ]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
        event.setdefault("ts", start)
    (folder / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    scope = {"goal": {"feature": "launch: the main screen", "id": goal, "reached": reached, "method": "the agent's"}}
    (folder / "run_scope.json").write_text(json.dumps(scope), encoding="utf-8")
    return folder


def as_goal_runs(root: Path, **options) -> None:
    """Every run of the workspace a goal-directed run of its case, as `skuld run --case` records it."""
    lines = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    for e in lines:
        goal_run(root / "runs" / e["dir"], **options.get(e["run"], {}))
        e |= {"regime": "goal", "goal_id": "start"}
    (root / "runs.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")


def test_a_case_with_a_path_is_run_goal_directed_and_recorded_with_its_goal(tmp_path):
    script = tmp_path / "loki.py"
    script.write_text(FAKE_LOKI.replace('print("replaying")', "print(json.dumps(sys.argv[1:]))"))
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    loki = [sys.executable, str(script)]
    made = execute.run(inputs.load(root), tmp_path / "rec-1", base, "d", ["baseline", "A2"], 1, loki, case="start")
    assert [e["condition"] for e in made] == ["baseline", "A2"]
    entry = json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["regime"], entry["goal_id"], entry["max_duration_s"]) == ("goal", "start", 900)
    assert "until_action" not in entry
    folder = Path(made[1]["dir"])
    blocked = yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8"))["capture"]["block_hosts"]
    assert blocked == ["tracker.example"]  # the same configuration as a replay's
    replayed = execute.run(
        inputs.load(root), tmp_path / "rec-1", base, "d", ["baseline"], 1, loki, case="start", replay=True
    )
    assert replayed[0]["until_action"] == 1 and "regime" not in replayed[0]


def test_the_goal_command_names_the_package_the_feature_and_the_cap(tmp_path, capsys):
    script = tmp_path / "loki.py"
    script.write_text(
        FAKE_LOKI.replace(
            'print("replaying")',
            '(pathlib.Path(sys.argv[0]).parent / "argv.json").write_text(json.dumps(sys.argv[1:]))',
        )
    )
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    base = tmp_path / "loki.yaml"
    base.write_text("{}")
    execute.run(
        inputs.load(root),
        tmp_path / "rec-1",
        base,
        "dev",
        ["baseline"],
        1,
        [sys.executable, str(script)],
        case="start",
        max_duration=600,
    )
    argv = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert argv[0] == "-c" and argv[2:] == [
        "crawl",
        ws.PACKAGE,
        "-d",
        "dev",
        "--goal",
        "launch: the main screen",
        "--goal-id",
        "start",
        "--max-duration",
        "600",
    ]


def test_a_goal_run_is_a_run_of_the_case_its_goal_names_only(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    run = load_run(goal_run(root / "runs" / "run-01"))
    case = inputs.load(root).cases[0]
    assert run.regime == "goal" and run.goal_id == "start" and run.goal_reached
    assert runs_of(case, RunState(run.run_id, None, run=run))
    other = load_run(goal_run(root / "runs" / "run-02", goal="other"))
    assert not runs_of(case, RunState(other.run_id, None, run=other))
    # a launch case (no path) takes no goal-directed run: it is a replay of the cold start
    launch = replace(case, id="launch", feature=replace(case.feature, path_run=None, actions=0))
    assert not runs_of(launch, RunState(run.run_id, None, run=run))


def test_the_window_of_a_goal_run_is_its_goal_episode_up_to_the_agents_statement(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    run = load_run(goal_run(root / "runs" / "run-01"))
    window = run.window
    assert (window.episode, window.start, window.end, window.reached) == (1, 0, 1, True)
    assert [s["exact_key"] for _, s in oracles.after_actions(run)] == ["main", "done"]
    late = load_run(goal_run(root / "runs" / "run-02", done_in_window=False))
    assert [s["exact_key"] for _, s in oracles.after_actions(late)] == ["main"]  # the logout episode is outside
    oracle = inputs.load(root).oracles["O@1"]
    assert oracles.decide(oracle, run, (0, 1)).decision == "met"
    assert oracles.decide(oracle, late, (0, 1)).decision == "unmet"
    # a window given in the recording's actions is read against the case's path: its end is the agent's statement
    at_end = {"screen_reached": {"exact_key": "main", "after_action": 48, "until_action": 48}}
    assert oracles.rebased(at_end, window, (40, 48)) == {
        "screen_reached": {"exact_key": "main", "after_action": 1, "until_action": 1}
    }
    from_start = {"text_shown": {"any": ["x"], "after_action": 40, "until_action": 48}}
    assert oracles.rebased(from_start, window, (40, 48))["text_shown"] | {"any": ["x"]} == {
        "any": ["x"],
        "after_action": 0,
        "until_action": 1,
    }
    assert oracles.rebased(at_end, None, (40, 48)) is at_end  # a replay's window stays
    unreached = goal_window([{"type": "episode_start", "episode": 3, "kind": "goal"}, {"type": "action"}])
    assert (unreached.episode, unreached.end, unreached.reached) == (3, 1, False)


def test_a_goal_run_qualifies_only_where_the_goal_was_reached_and_the_oracle_is_met(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    workspace = inputs.load(root)
    assert execute.qualification(workspace, goal_run(root / "runs" / "run-01")) == {}
    unmet = execute.qualification(workspace, goal_run(root / "runs" / "run-02", done_in_window=False))
    assert any("O@1 decides unmet" in p for p in unmet["start"])  # the agent's statement alone qualifies nothing
    missed = execute.qualification(workspace, goal_run(root / "runs" / "run-03", reached=False))
    assert missed["start"] == [f"{GOAL_NOT_REACHED} (goal_not_reached (capped_duration))"]


def test_goal_runs_are_compared_and_reported_with_their_goal(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    as_goal_runs(root)
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)
    assert {k["outcome"] for k in report["comparisons"]} == {"preserves"}
    run = report["runs"][0]
    assert run["regime"] == "goal" and run["goal"]["reached"] and run["goal"]["window"] == [0, 1]


def test_a_goal_not_reached_is_no_break_but_requirements_not_reached(tmp_path):
    """Runs under A1 whose goal was not reached are no runs of the feature: A1's claims are not established, with the
    reason requirements_not_reached (next step: explore), not refuted by a break."""
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    as_goal_runs(root, **{f"run-{n:02d}": {"reached": False} for n in (2, 5, 8)})  # every A1 run
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)
    case = report["cases"][0]
    assert all(case["excluded"][f"run-{n:02d}"].startswith(GOAL_NOT_REACHED) for n in (2, 5, 8))
    assert {"purpose": "P1", "alternative": "A1", "reason": "requirements_not_reached"} in case["untested"]
    made = case_claims(workspace, report)["start"]
    a1 = next(c for c in made if c.alternative == "A1" and c.purpose == "P1")
    assert (a1.status, a1.why) == ("not_established", "requirements_not_reached")
    assert not any(k["outcome"] == "breaks" for k in report["comparisons"])


def test_a_feature_no_baseline_run_reached_leaves_its_claims_to_an_exploration(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    as_goal_runs(root, **{f"run-{n:02d}": {"reached": False} for n in (1, 4, 7)})  # every baseline run
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    made = case_claims(workspace, report)["start"]
    p1 = [c for c in made if c.purpose == "P1"]
    assert p1 and {(c.status, c.why) for c in p1} == {("not_established", "requirements_not_reached")}


def test_a_qualifying_goal_run_that_missed_its_goal_leaves_the_alternatives_in_the_search_space(tmp_path):
    root = deep(ws.build(tmp_path / "ws", freeze=False))
    as_goal_runs(root)
    missed = f"{GOAL_NOT_REACHED} (goal_not_reached)"
    (root / execute.QUALIFICATION).write_text(json.dumps({"run": "run-01", "cases": {"start": [missed]}}))
    report = analyse(inputs.load(root), make_observations=False)
    case = report["cases"][0]
    assert not any(a.get("problems") for a in case["scope"]["search_space"])
    assert {u["reason"] for u in case["untested"] if u["purpose"] == "P1"} == {"requirements_not_reached"}
