"""Making the runs through Loki's command line, with a stand-in for Loki."""

import json
import sys
from pathlib import Path

import pytest
import yaml

from skuld import execute, inputs
from tests import workspace as ws

#: A stand-in for `loki -c <config> replay <run> -d <device> --force`: it makes a folder and names it
FAKE_LOKI = """
import json, pathlib, sys
if "frida-server" in sys.argv:
    with (pathlib.Path(sys.argv[0]).parent / "frida.log").open("a") as log:
        log.write(sys.argv[-1] + "\\n")
    sys.exit(0)
config = sys.argv[sys.argv.index("-c") + 1]
out = pathlib.Path(sys.argv[0]).parent / "made" / pathlib.Path(config).stem
out.mkdir(parents=True)
(out / "config.yaml").write_text(pathlib.Path(config).read_text(encoding="utf-8"), encoding="utf-8")
print("replaying")
print(json.dumps({"run_dir": str(out), "stop_reason": "max_flows"}))
"""


def fake(tmp_path: Path) -> list[str]:
    script = tmp_path / "loki.py"
    script.write_text(FAKE_LOKI)
    return [sys.executable, str(script)]


def test_conditions_are_rotated():
    assert execute.schedule(["baseline", "A1", "A2"], 2) == ["baseline", "A1", "A2", "A1", "A2", "baseline"]


def test_a_condition_hooks_every_source_and_changes_only_its_own():
    config = execute.configuration({"capture": {"backend": "heimdall"}}, {"sources": {"advertising_id": "replace:0"}})
    assert config["instrumentation"]["sources"]["advertising_id"] == "replace:0"
    assert {v for k, v in config["instrumentation"]["sources"].items() if k != "advertising_id"} == {"pass"}
    assert set(config["instrumentation"]["sources"]) >= {"android_id", "app_set_id", "drm_id", "gsf_id"}
    assert config["capture"] == {"backend": "heimdall", "block_hosts": []}


def test_the_runs_are_made_recorded_and_appended(tmp_path):
    root = ws.build(tmp_path / "ws")
    before = len((root / "runs.jsonl").read_text(encoding="utf-8").splitlines())
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    made = execute.run(
        inputs.load(root), tmp_path / "recorded", base, "emulator-5554", ["baseline", "A2"], 2, fake(tmp_path)
    )
    assert not (tmp_path / "frida.log").exists()  # no instrumentation in the base: frida-server is left alone
    assert [e["condition"] for e in made] == ["baseline", "A2", "A2", "baseline"]
    assert [e["order"] for e in made] == [10, 11, 12, 13]
    lines = (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == before + 4 and json.loads(lines[-1])["condition"] == "baseline"
    blocked = yaml.safe_load((Path(made[1]["dir"]) / "config.yaml").read_text(encoding="utf-8"))["capture"][
        "block_hosts"
    ]
    assert blocked == ["tracker.example"]


def test_runs_are_refused_before_the_inputs_are_fixed(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    with pytest.raises(execute.ExecutionError, match="not fixed"):
        execute.run(inputs.load(root), tmp_path, tmp_path / "x.yaml", "d", ["baseline"], 1, fake(tmp_path))


def test_an_unknown_condition_is_refused(tmp_path):
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text("{}")
    with pytest.raises(execute.ExecutionError, match="no case defines"):
        execute.run(inputs.load(root), tmp_path, base, "d", ["A9"], 1, fake(tmp_path))


def test_the_base_configurations_sinks_are_recorded_in_every_condition():
    base = {"instrumentation": {"backend": "frida", "sources": {"storage": "record", "location": "round:1"}}}
    config = execute.configuration(base, {"sources": {"android_id": "replace:0"}})
    sources = config["instrumentation"]["sources"]
    assert sources["storage"] == "record" and sources["location"] == "pass" and sources["android_id"] == "replace:0"


def test_a_base_configuration_with_dates_is_copied_unchanged():
    """A persona's birth date is a date in YAML (the study configs have one); the copy keeps it and leaves the base alone."""
    base = yaml.safe_load("persona:\n  birth_date: 1992-03-03\ninstrumentation:\n  sources: {storage: record}\n")
    config = execute.configuration(base, {"sources": {"advertising_id": "replace:0"}})
    assert yaml.safe_load(yaml.safe_dump(config))["persona"] == base["persona"]
    assert base["instrumentation"]["sources"] == {"storage": "record"}


def test_frida_server_runs_for_the_series_of_an_instrumented_configuration(tmp_path):
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"instrumentation": {"backend": "frida", "required": True}}))
    execute.run(inputs.load(root), tmp_path / "recorded", base, "d", ["baseline"], 1, fake(tmp_path))
    assert (tmp_path / "frida.log").read_text(encoding="utf-8").split() == ["start", "stop"]


def test_a_series_stops_when_its_qualifying_replay_qualifies_no_case(tmp_path):
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text("{}")
    with pytest.raises(execute.ExecutionError, match="qualified no case"):
        execute.run(inputs.load(root), tmp_path / "rec", base, "d", ["baseline", "A1"], 1, fake(tmp_path), qualify=True)
    lines = (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["condition"] == "baseline" and len(lines) == 10  # kept; the series not made
    record = json.loads((root / execute.QUALIFICATION).read_text(encoding="utf-8"))
    assert record["run"] == json.loads(lines[-1])["run"] and all(record["cases"].values())


def test_a_replay_qualifies_if_it_follows_the_path_and_the_oracles_are_met(tmp_path):
    root = ws.build(tmp_path / "ws")
    assert execute.qualification(inputs.load(root), root / "runs" / "run-01") == {}
    ws.run_folder(
        tmp_path / "unmet", "unmet", "2026-10-21T11:59:00+00:00", aaid=ws.DEVICE_ID, blocked=False, done=False
    )
    problems = execute.qualification(inputs.load(root), tmp_path / "unmet")
    assert any("O@1 decides unmet" in p for found in problems.values() for p in found)


#: Loki whose first replay (of the series) finds no instrumented process, as on the study's emulators
FLAKY_LOKI = FAKE_LOKI.replace(
    'print(json.dumps({"run_dir": str(out), "stop_reason": "max_flows"}))',
    """count = pathlib.Path(sys.argv[0]).parent / "count"
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
stop = "error: InstrumentationFailed('app_not_instrumented: no process of a.b started within 30 s')" if n == 0 else "replayed"
print(json.dumps({"run_dir": str(out), "stop_reason": stop}))
sys.exit(1 if n == 0 else 0)""",
)


def test_a_replay_with_no_instrumented_process_is_kept_and_replayed_once_more(tmp_path):
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    script = tmp_path / "loki.py"
    script.write_text(FLAKY_LOKI)
    made = execute.run(
        inputs.load(root), tmp_path / "recorded", base, "d", ["baseline", "A2"], 1, [sys.executable, str(script)]
    )
    assert [(e["condition"], e["exit"]) for e in made] == [("baseline", 1), ("baseline", 0), ("A2", 0)]
    # the failed attempt is marked as replaced, so the series does not count it as a failure
    assert [bool(e.get("retried")) for e in made] == [True, False, False]
    assert [e["order"] for e in made] == [10, 11, 12]


def test_a_run_for_one_case_replays_up_to_its_path_and_records_it(tmp_path):
    """skuld run --case (12 Nov 2026): Loki replays the recording up to the end of the case's path; the launch case
    has no path, so its replays are the cold start alone."""
    script = tmp_path / "loki.py"
    script.write_text(FAKE_LOKI.replace('print("replaying")', 'print(" ".join(sys.argv[1:]))'))
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    workspace = inputs.load(root)
    case = workspace.cases[0].id
    made = execute.run(
        workspace, tmp_path / "rec", base, "d", ["baseline"], 1, [sys.executable, str(script)], case=case
    )
    entry = json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert made[0]["until_action"] == 0 and entry["until_action"] == 0
    with pytest.raises(execute.ExecutionError, match="no case"):
        execute.run(workspace, tmp_path / "rec", base, "d", ["baseline"], 1, [sys.executable, str(script)], case="x")


def test_a_prefix_replay_is_a_run_only_of_the_cases_whose_path_it_covers():
    from types import SimpleNamespace

    from skuld.experiments import RunState, runs_of

    def case(path_run, actions):
        return SimpleNamespace(feature=SimpleNamespace(path_run=path_run, actions=actions))

    def state(until, replay_of="rec"):
        replay = {"divergences": 0} if until is None else {"until_action": until}
        return RunState("r", None, run=SimpleNamespace(run_id="r", meta={"replay_of": replay_of, "replay": replay}))

    launch, onboarding, deep = case(None, 0), case("rec", 16), case("rec", 48)
    assert runs_of(launch, state(0)) and not runs_of(onboarding, state(0))
    assert runs_of(onboarding, state(16)) and not runs_of(deep, state(16))
    assert runs_of(deep, state(None)) and not runs_of(deep, state(None, replay_of="other"))


def test_a_departure_counts_only_within_the_path_from_reaching_its_episode_on(tmp_path):
    """12 Nov 2026: a replay that departed before the path but then reached the path's screens follows the feature;
    one that could not reach the path's episode start (a divergence between the action before it and its first)
    does not."""
    from types import SimpleNamespace

    from skuld.experiments import departed

    recorded = tmp_path / "rec"
    recorded.mkdir()
    (recorded / "events.jsonl").write_text(
        "\n".join(json.dumps({"seq": s, "type": "action"}) for s in (10, 20, 30, 40, 50)), encoding="utf-8"
    )
    case = SimpleNamespace(feature=SimpleNamespace(path_run="rec", start=2, actions=4))  # actions 2 and 3: seq 30, 40

    def run(*seqs):
        events = [{"type": "divergence", "source_seq": s} for s in seqs]
        return SimpleNamespace(meta={"replay_of": "rec"}, directory=tmp_path / "replay", events=events)

    assert departed(case, run(10, 20)) is None  # before the path
    assert departed(case, run(50)) is None  # after it
    assert departed(case, run(25))  # its episode start, between action 1 and 2
    assert departed(case, run(40))
    case.feature.start = 0
    assert departed(case, run(10))  # a path from the start: every departure up to its end counts, as before


def test_a_launch_replay_takes_the_recordings_leading_actions_on_system_screens(tmp_path):
    """CamScanner and pedometer (12 Nov 2026): Android's 'Viewing full screen' confirmation (package android) covers the
    app at its first start; the recording's agent dismissed it, and a cold start alone leaves it there."""
    graph = {"screens": {"s1": {"package": "android"}, "s2": {"package": "p"}, "s3": {"package": "android"}}}
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    events = [
        {"type": "screen"},
        {"type": "action", "src": "s1"},
        {"type": "action", "src": "s2"},
        {"type": "action", "src": "s3"},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(map(json.dumps, events)))
    assert execute.system_prefix(tmp_path) == 1
    graph["screens"]["s1"]["package"] = "p"
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    assert execute.system_prefix(tmp_path) == 0


def test_a_samples_options_record_recommended_sampling_only_where_set():
    from ratatoskr.llm.client import Options

    from skuld.ask import _options

    assert _options(Options(temperature=0.4, seed=1)) == {"temperature": 0.4, "seed": 1}  # as every earlier sample
    gemma = _options(Options(temperature=1.0, seed=1, top_p=0.95, top_k=64), think="low")
    assert gemma == {"temperature": 1.0, "seed": 1, "top_p": 0.95, "top_k": 64, "think": "low"}
