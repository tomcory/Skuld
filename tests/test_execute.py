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
