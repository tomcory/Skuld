"""The installed version checked against the recording's before a series of runs (20 Nov 2026), with a stand-in for
Loki and for the device."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from skuld import execute, inputs
from tests import workspace as ws
from tests.test_execute import FAKE_LOKI

#: Loki whose replays record the version the device has (`version` beside the script), as Loki's run.json does
VERSIONED_LOKI = FAKE_LOKI.replace(
    'print("replaying")',
    """version = (pathlib.Path(sys.argv[0]).parent / "version").read_text().strip()
(out / "run.json").write_text(json.dumps({"app": {"version_name": version}}))""",
)


def _setup(tmp_path: Path, recorded_version: str = "1.0", device_version: str = "1.0"):
    root = ws.build(tmp_path / "ws")
    base = tmp_path / "loki.yaml"
    base.write_text(yaml.safe_dump({"capture": {"backend": "heimdall"}}))
    recorded = tmp_path / "rec-1"
    recorded.mkdir()
    (recorded / "run.json").write_text(json.dumps({"app": {"version_name": recorded_version}}))
    script = tmp_path / "loki.py"
    script.write_text(VERSIONED_LOKI)
    (tmp_path / "version").write_text(device_version)
    return root, base, recorded, [sys.executable, str(script)]


def _lines(root: Path) -> list[dict]:
    return [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_series_on_the_recordings_version_is_made_without_a_drift(tmp_path):
    root, base, recorded, loki = _setup(tmp_path)
    asked = []

    def installed(device, package):
        asked.append((device, package))
        return "1.0"

    made = execute.run(inputs.load(root), recorded, base, "d", ["baseline"], 1, loki, installed=installed)
    assert asked == [("d", ws.PACKAGE)]
    assert len(made) == 1 and "version_drift" not in _lines(root)[-1]


def test_another_installed_version_stops_the_series_before_its_first_run(tmp_path):
    root, base, recorded, loki = _setup(tmp_path, device_version="2.0")
    before = len(_lines(root))
    with pytest.raises(execute.ExecutionError, match=r"2\.0 installed, the recording is of 1\.0.*skuld compat add"):
        execute.run(inputs.load(root), recorded, base, "d", ["baseline"], 1, loki, installed=lambda d, p: "2.0")
    assert len(_lines(root)) == before and not (tmp_path / "made").exists()


def test_an_application_not_installed_stops_the_series(tmp_path):
    root, base, recorded, loki = _setup(tmp_path)
    with pytest.raises(execute.ExecutionError, match="not installed"):
        execute.run(inputs.load(root), recorded, base, "d", ["baseline"], 1, loki, installed=lambda d, p: None)


def test_a_version_stated_compatible_is_run_and_flagged(tmp_path):
    root, base, recorded, loki = _setup(tmp_path, device_version="2.0")
    statement = {
        "versions": ["1.0", "2.0"],
        "reason": "the same release notes",
        "author": {"kind": "person", "id": "author"},
        "fixed": "2026-11-20T10:00:00+00:00",
    }
    (root / "assessment.yaml").write_text(yaml.safe_dump({"compatible_versions": [statement]}))
    made = execute.run(
        inputs.load(root), recorded, base, "d", ["baseline", "A1"], 1, loki, installed=lambda d, p: "2.0"
    )
    drift = {
        "installed": "2.0",
        "recorded": "1.0",
        "workspace": "1.0",
        "stated": [{"versions": ["1.0", "2.0"], "reason": "the same release notes", "fixed": statement["fixed"]}],
    }
    assert [e["version_drift"] for e in made] == [drift, drift]
    assert [e["version_drift"] for e in _lines(root)[-2:]] == [drift, drift]


def test_a_version_that_changes_during_the_series_stops_it(tmp_path):
    root, base, recorded, loki = _setup(tmp_path, device_version="1.1")  # the app updated after the check
    before = len(_lines(root))
    with pytest.raises(execute.ExecutionError, match=r"run \d+ \(baseline\) is of version 1\.1, not 1\.0"):
        execute.run(inputs.load(root), recorded, base, "d", ["baseline", "A1"], 2, loki, installed=lambda d, p: "1.0")
    assert len(_lines(root)) == before + 1  # the run is kept in runs.jsonl; the analysis excludes it


def test_the_installed_version_is_read_with_dumpsys(monkeypatch):
    calls = []

    def run(command, **options):
        calls.append(command)
        out = "Packages:\n  Package [a.b] (1f):\n    versionCode=42 minSdk=24\n    versionName=3.1.4\n"
        return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")

    monkeypatch.setattr(execute.subprocess, "run", run)
    assert execute.installed_version("emulator-5554", "a.b") == "3.1.4"
    assert calls == [["adb", "-s", "emulator-5554", "shell", "dumpsys", "package", "a.b"]]
    monkeypatch.setattr(
        execute.subprocess, "run", lambda c, **o: subprocess.CompletedProcess(c, 0, "Unable to find package: a.b", "")
    )
    assert execute.installed_version("d", "a.b") is None

    def missing(command, **options):
        raise FileNotFoundError("adb")

    monkeypatch.setattr(execute.subprocess, "run", missing)
    with pytest.raises(execute.ExecutionError, match="cannot be read"):
        execute.installed_version("d", "a.b")
