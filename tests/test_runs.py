"""Reading a Loki run folder: what is returned, and what is refused."""

import json
import os
from pathlib import Path

import pytest

from skuld.runs import RunRefused, load

PACKAGE = "com.example.app"
SETTINGS = ["location=pass"]

MESSAGE = {
    "id": "heimdall:12:7",
    "time": {"start": 1791805790120, "end": 1791805790480},
    "http_request": {
        "method": "POST",
        "scheme": "https",
        "host": "api.example.com",
        "port": 443,
        "path": "/v1/events",
        "headers": [],
        "body": "e30=",
        "body_encoding": "base64",
    },
    "http_response": None,
    "capture": {"backend": "heimdall", "session": 12, "tag": "run-1"},
}
CONNECTION = {
    "id": "3",
    "time": {"start": 1791805790100},
    "protocol": "TCP",
    "remote_ip": "203.0.113.7",
    "remote_port": 443,
    "blocked": False,
    "capture": {"backend": "heimdall", "session": 12},
}


def read(seq, returned, mode="round", **fields):
    return {
        "seq": seq,
        "ts": "2026-10-14T08:15:27.510+00:00",
        "device_uptime_s": 43614.7,
        "type": "source_read",
        "episode": 2,
        "device_time": 1791965666904,
        "pid": 9,
        "source": "location",
        "api": "Location.getLatitude",
        "mode": mode,
        "original": 47.376887,
        "returned": returned,
        **fields,
    }


def write_run(folder: Path, *, meta=None, events=None, messages=(MESSAGE, MESSAGE), connections=(CONNECTION,)) -> Path:
    """A finished, captured and instrumented run with one setting change, in Loki's layout."""
    events = events or [
        {"seq": 1, "ts": "t1", "type": "run_start"},
        {"seq": 2, "ts": "t2", "type": "action", "kind": "tap", "episode": 1},
        {
            "seq": 3,
            "ts": "t3",
            "type": "source_read",
            **{k: v for k, v in read(3, 47.376887, "pass").items() if k not in ("seq", "type")},
        },
        {
            "seq": 4,
            "ts": "2026-10-14T08:15:16.176+00:00",
            "device_uptime_s": 43603.4,
            "type": "setting_change",
            "settings": ["location=round:2"],
            "origin": "plan",
            "episode": 1,
            "item_id": "f2",
        },
        read(5, 47.38),
        {"seq": 6, "ts": "t6", "type": "action", "kind": "tap", "episode": 2},
    ]
    export = "capture/12-20261014-081500"
    record = {
        "schema_version": 2,
        "run_id": "run-1",
        "package": PACKAGE,
        "status": "finished",
        "capture": {
            "backend": "heimdall",
            "session": "12",
            "export": export,
            "records": {"messages": 2, "connections": 1},
            "validated": {"ratatoskr": "0.2.0", "conforming": True},
        },
        "instrumentation": {
            "backend": "frida",
            "client": "17.23.3",
            "agent": "sources.js",
            "agent_sha256": "a" * 64,
            "settings": SETTINGS,
            "changes": [{"seq": 4, "settings": ["location=round:2"], "origin": "plan"}],
            "verification": {
                "verified": True,
                "checks": [{"name": "session", "passed": True, "detail": "started and stopped"}],
                "sources": {"location": {"setting": "location=pass", "status": "verified", "calls": 2}},
            },
            "validated": {"ratatoskr": "0.2.0", "conforming": True},
        },
        **(meta or {}),
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(record))
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (folder / export).mkdir(parents=True)
    (folder / export / "messages.jsonl").write_text("".join(json.dumps(m) + "\n" for m in messages))
    (folder / export / "connections.jsonl").write_text("".join(json.dumps(c) + "\n" for c in connections))
    return folder


def refused(folder, **kwargs) -> str:
    with pytest.raises(RunRefused) as refusal:
        load(folder, **kwargs)
    return refusal.value.reason


def test_a_run_gives_its_actions_reads_changes_traffic_and_verification(tmp_path):
    run = load(write_run(tmp_path / "run"))
    assert (run.run_id, run.package) == ("run-1", PACKAGE)
    assert [a["seq"] for a in run.actions] == [2, 6]
    assert [(r["mode"], r["returned"]) for r in run.source_reads] == [("pass", 47.376887), ("round", 47.38)]
    change = run.changes[0]
    assert (change.seq, change.settings, change.origin, change.applied) == (4, ("location=round:2",), "plan", True)
    assert change.ts.startswith("2026-10-14T08:15:16") and change.device_uptime_s == 43603.4
    assert len(run.messages) == 2 and len(run.connections) == 1
    assert run.verified and run.verification["sources"]["location"]["status"] == "verified"


def test_a_run_without_instrumentation_has_no_verification(tmp_path):
    events = [{"seq": 1, "ts": "t1", "type": "action", "kind": "tap"}]
    folder = write_run(tmp_path / "run", events=events)
    record = json.loads((folder / "run.json").read_text())
    del record["instrumentation"]
    (folder / "run.json").write_text(json.dumps(record))
    run = load(folder)
    assert run.instrumentation is None and run.verification is None and not run.verified and run.source_reads == ()


def test_an_instrumentation_that_failed_to_start_is_no_verification(tmp_path):
    folder = write_run(tmp_path / "run", events=[{"seq": 1, "ts": "t1", "type": "action"}])
    record = json.loads((folder / "run.json").read_text())
    record["instrumentation"] = {"backend": "frida", "error": "server_unreachable", "detail": "closed"}
    (folder / "run.json").write_text(json.dumps(record))
    run = load(folder)
    assert run.instrumentation["error"] == "server_unreachable" and not run.verified


def test_the_capture_can_be_left_out(tmp_path):
    folder = write_run(tmp_path / "run", meta={"capture": None})
    run = load(folder, capture=False)
    assert run.messages is None and run.connections is None
    assert refused(folder) == "no_capture"


def test_a_folder_that_is_no_run_is_refused(tmp_path):
    assert refused(tmp_path) == "not_a_run"


@pytest.mark.parametrize(
    ("meta", "reason"),
    [
        ({"schema_version": 1}, "unsupported_version"),
        ({"status": "running"}, "unfinished"),
        ({"capture": {"backend": "heimdall", "error": "vpn_consent_missing"}}, "capture_failed"),
    ],
)
def test_a_run_that_cannot_be_relied_on_is_refused(tmp_path, meta, reason):
    assert refused(write_run(tmp_path / "run", meta=meta)) == reason


def test_an_export_that_was_not_validated_is_refused(tmp_path):
    folder = write_run(tmp_path / "run")
    record = json.loads((folder / "run.json").read_text())
    for validated in ({"ratatoskr": "0.2.0", "conforming": False}, None):
        record["capture"]["validated"] = validated
        (folder / "run.json").write_text(json.dumps(record))
        assert refused(folder) == "export_not_validated"


def test_an_export_that_is_not_complete_is_refused(tmp_path):
    assert refused(write_run(tmp_path / "short", messages=(MESSAGE,))) == "incomplete_export"
    folder = write_run(tmp_path / "missing")
    next((folder / "capture").iterdir()).joinpath("connections.jsonl").unlink()
    assert refused(folder) == "incomplete_export"


def test_an_instrumentation_record_that_does_not_conform_is_refused(tmp_path):
    no_returned = {k: v for k, v in read(5, 47.38).items() if k != "returned"}
    assert refused(write_run(tmp_path / "read", events=[no_returned])) == "invalid_record"

    folder = write_run(tmp_path / "block")
    record = json.loads((folder / "run.json").read_text())
    record["instrumentation"]["settings"] = ["location round:2"]
    del record["instrumentation"]["validated"]  # Skuld checks for itself, whatever Loki said
    (folder / "run.json").write_text(json.dumps(record))
    assert refused(folder) == "invalid_record"

    record["instrumentation"]["settings"] = SETTINGS
    record["instrumentation"]["validated"] = {"ratatoskr": "0.2.0", "conforming": False, "detail": "x"}
    (folder / "run.json").write_text(json.dumps(record))
    assert refused(folder) == "invalid_record"


SCAN = {
    "id": "12-com.example.app",
    "scanned_at": 1791805800000,
    "app": {"package": PACKAGE, "label": "Example", "version_name": "1.0", "version_code": 1},
    "permissions": [{"name": "android.permission.ACCESS_FINE_LOCATION", "dangerous": True}],
    "libraries": [{"exodus_id": 27, "name": "Google Firebase Analytics"}],
    "catalogue": {"source": "exodus", "trackers": 432},
    "capture": {"backend": "heimdall", "session": 12, "tag": "run-1"},
}


def with_scans(folder: Path, scans=(SCAN,), count=None) -> Path:
    """Adds the apps' scans to a run's export, as a run with `capture.export: [..., scans]` has them."""
    record = json.loads((folder / "run.json").read_text())
    record["capture"]["records"]["scans"] = len(scans) if count is None else count
    (folder / "run.json").write_text(json.dumps(record))
    (folder / record["capture"]["export"] / "scans.jsonl").write_text("".join(json.dumps(s) + "\n" for s in scans))
    return folder


def test_a_run_gives_the_scans_of_its_apps_if_it_exported_them(tmp_path):
    assert load(write_run(tmp_path / "without")).scans is None
    run = load(with_scans(write_run(tmp_path / "with")))
    scan = run.scans[PACKAGE]
    assert scan["permissions"][0]["dangerous"] and scan["libraries"][0]["name"] == "Google Firebase Analytics"
    assert load(with_scans(write_run(tmp_path / "unread")), capture=False).scans is None


def test_scans_that_are_incomplete_or_do_not_conform_are_refused(tmp_path):
    assert refused(with_scans(write_run(tmp_path / "short"), count=2)) == "incomplete_export"
    no_permissions = {k: v for k, v in SCAN.items() if k != "permissions"}
    assert refused(with_scans(write_run(tmp_path / "broken"), scans=(no_permissions,))) == "invalid_record"


# -- a real run folder of Loki --------------------------------------------------------------------


def real_run() -> Path | None:
    """SKULD_RUN_DIR, or the latest run in the sibling Loki folder that was captured and instrumented."""
    if os.environ.get("SKULD_RUN_DIR"):
        return Path(os.environ["SKULD_RUN_DIR"])
    runs = Path(__file__).resolve().parents[2] / "Loki" / "runs"
    found = []
    for meta in runs.glob("*/*/run.json"):
        record = json.loads(meta.read_text(encoding="utf-8"))
        capture, instrumentation = record.get("capture") or {}, record.get("instrumentation") or {}
        if (capture.get("validated") or {}).get("conforming") and instrumentation.get("verification"):
            found.append(meta.parent)
    return max(found, default=None, key=lambda path: path.name)


@pytest.mark.skipif(real_run() is None, reason="no captured and instrumented Loki run on this machine")
def test_a_real_run_of_loki():
    folder = real_run()
    run = load(folder)
    record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert run.run_id == record["run_id"] and run.verification == record["instrumentation"]["verification"]
    assert len(run.messages) == record["capture"]["records"]["messages"]
    assert len(run.connections) == record["capture"]["records"]["connections"]
    assert run.actions and all(a["type"] == "action" for a in run.actions)
    assert all(r["source"] in record["instrumentation"]["verification"]["sources"] for r in run.source_reads)
