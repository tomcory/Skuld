"""A synthetic workspace: a case, its oracle, Loki run folders and Verðandi's reports of them, in their real layouts."""

import json
from pathlib import Path

import yaml

from skuld import inputs

PACKAGE = "com.example.app"
ZERO = "00000000-0000-0000-0000-000000000000"
DEVICE_ID = "74076b9a-0106-4d4f-8e05-751904c53fc9"
AUTHOR = {"kind": "person", "name": "test"}
FIXED = "2026-10-21T10:00:00+00:00"

CASE = {
    "id": "start",
    "feature": {"id": "F0", "name": "launch", "entry": "cold start", "path": None, "outcome": "the main screen"},
    "purposes": [
        {
            "id": "P1",
            "action": "show",
            "object": "the main screen",
            "beneficiary": "user",
            "context": "launch",
            "outcome": "ready for input",
            "node": "ServiceProvision",
            "provenance": "feature",
            "specificity": "sufficient",
            "role": "functional",
            "requirements": [{"id": "R1", "statement": "show the main screen"}],
            "oracle": "O@1",
        },
        {
            "id": "P2",
            "action": "attribute",
            "object": "the installation",
            "beneficiary": "provider",
            "context": "launch",
            "outcome": "the campaign credited",
            "node": "Marketing",
            "provenance": "technical",
            "specificity": "sufficient",
            "role": "ancillary",
            "oracle": None,
        },
    ],
    "components": [
        {"id": "aaid", "dimension": "D", "node": "device-or-other-ids.advertising-id"},
        {"id": "tracker", "dimension": "R", "entity": "tracker"},
    ],
    "search_space": {
        "alternatives": [
            {
                "id": "A1",
                "component": "aaid",
                "removal": True,
                "changes": [{"component": "aaid", "value": None}],
                "intervention": {"sources": {"advertising_id": f"replace:{ZERO}"}},
            },
            {
                "id": "A2",
                "component": "tracker",
                "removal": True,
                "changes": [{"component": "tracker", "value": None}],
                "intervention": {"block_hosts": ["tracker.example"]},
            },
        ],
    },
}

ORACLE = {
    "id": "O",
    "version": 1,
    "purpose": "P1",
    "reach": ["R1"],
    "success": [{"first_screen": {"activity_suffix": ".Main"}}, {"screen_reached": {"exact_key": "done"}}],
    "invalid": [{"hold_above_ms": 1000}],
    "measurements": [
        {"name": "app_messages", "metric": {"messages_to": ["app.example"]}, "better": "higher", "tolerance": 1}
    ],
}

LOW = {"level": "low", "reasons": []}


def run_folder(
    folder: Path,
    run_id: str,
    start: str,
    *,
    aaid: str,
    blocked: bool,
    done: bool = True,
    app_messages: int = 2,
    exclusions: dict | None = None,
    hostless: bool = False,
) -> Path:
    """A finished, captured and instrumented run of Loki."""
    setting = f"advertising_id=replace:{ZERO}" if aaid == ZERO else "advertising_id=pass"
    events = [
        {"seq": 1, "ts": start, "type": "run_start"},
        {
            "seq": 2,
            "ts": start,
            "type": "screen",
            "screen_id": "s1",
            "package": PACKAGE,
            "activity": f"{PACKAGE}.Main",
            "exact_key": "main",
        },
        {
            "seq": 3,
            "ts": start,
            "device_uptime_s": 10.0,
            "type": "source_read",
            "episode": 0,
            "device_time": 1,
            "pid": 9,
            "source": "advertising_id",
            "api": "IAdvertisingIdService.getId",
            "mode": "replace" if aaid == ZERO else "pass",
            "original": DEVICE_ID,
            "returned": aaid,
        },
        {"seq": 4, "ts": start, "type": "action", "kind": "tap", "episode": 0},
    ]
    if done:
        events.append(
            {
                "seq": 5,
                "ts": start,
                "type": "screen",
                "screen_id": "s2",
                "package": PACKAGE,
                "activity": f"{PACKAGE}.Main",
                "exact_key": "done",
            }
        )
    messages = [_message(f"{run_id}-m{i}", "app.example") for i in range(app_messages)]
    connections = [_connection(f"{run_id}-c1", "app.example", False)]
    if blocked:
        connections.append(_connection(f"{run_id}-c2", "t.tracker.example", True))
    if hostless:
        connections.append({**_connection(f"{run_id}-c3", None, False), "protocol": "UDP", "bytes_out": 1200})
    else:
        messages.append(_message(f"{run_id}-mt", "t.tracker.example"))
    export = "capture/1-x"
    record = {
        "schema_version": 2,
        "run_id": run_id,
        "package": PACKAGE,
        "status": "finished",
        "started_at": start,
        "finished_at": start.replace(":00+", ":30+"),
        "replay_of": "rec-1",
        "replay": {"divergences": 0, "repairs": 0, "skipped_actions": 0},
        "config": {"capture": {"block_hosts": ["tracker.example"] if blocked else []}},
        "capture": {
            "backend": "heimdall",
            "session": "1",
            "export": export,
            "records": {"messages": len(messages), "connections": len(connections)},
            "validated": {"ratatoskr": "0.8.0", "conforming": True},
        },
        "instrumentation": {
            "backend": "frida",
            "client": "17.23.3",
            "agent": "sources.js",
            "agent_sha256": "a" * 64,
            "settings": [setting],
            "held_ms": [300],
            "verification": {
                "verified": True,
                "checks": [{"name": "session", "passed": True, "detail": "started and stopped"}],
                "sources": {
                    "advertising_id": {"setting": setting, "status": "verified", "calls": 1, "returned": [aaid]}
                },
            },
            "validated": {"ratatoskr": "0.8.0", "conforming": True},
        },
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(record))
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (folder / export).mkdir(parents=True)
    (folder / export / "messages.jsonl").write_text("".join(json.dumps(m) + "\n" for m in messages))
    (folder / export / "connections.jsonl").write_text("".join(json.dumps(c) + "\n" for c in connections))
    (folder / export / "manifest.json").write_text(json.dumps({"exclusions": exclusions or {}}))
    graph = {
        "screens": {
            "s1": {
                "condensed": f"package={PACKAGE} activity=.Main title=''\n- [tap] Button | Welcome\n- [tap] Button | Start"
            },
            "s2": {"condensed": f"package={PACKAGE} activity=.Main title=''\n- [tap] View | Your plan is ready"},
        }
    }
    (folder / "graph.json").write_text(json.dumps(graph))
    return folder


def scope(folder: Path) -> dict:
    """O's scope of a run as Verðandi gives it: Loki's instrumentation and the capture's connections."""
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    export = folder / meta["capture"]["export"]
    connections = [
        json.loads(line) for line in (export / "connections.jsonl").read_text(encoding="utf-8").splitlines() if line
    ]
    hosts: dict = {}
    for c in connections:
        if host := c.get("host") or c.get("sni"):
            counts = hosts.setdefault(host, {"connections": 0, "blocked": 0})
            counts["connections"] += 1
            counts["blocked"] += 1 if c.get("blocked") else 0
    instrumentation = meta.get("instrumentation") or {}
    verification = instrumentation.get("verification") or {}
    frida = {
        "settings": instrumentation.get("settings"),
        "verified": verification.get("verified"),
        "checks_failed": [c["name"] for c in verification.get("checks") or () if not c.get("passed")],
        "hooks": verification.get("sources") or "?",
    }
    if instrumentation.get("error"):
        frida["error"] = " ".join(str(instrumentation[k]) for k in ("error", "detail") if instrumentation.get(k))
    heimdall = {
        "settings": {"blocked_hosts": meta["config"]["capture"]["block_hosts"]},
        "rejected": {},
        "hosts": hosts,
        "hostless": [
            c["id"]
            for c in connections
            if not (c.get("host") or c.get("sni")) and not c.get("blocked") and (c.get("bytes_out") or 0) > 0
        ],
    }
    return {
        "observation": meta["run_id"],
        "application": PACKAGE,
        "version": "1.0",
        "time": {"start": meta["started_at"], "end": meta["finished_at"]},
        "context": {"instruments": {"frida": frida, "heimdall:capture/1-x": heimdall}},
        "persona": "?",
        "consent": "?",
        "permissions": "?",
        "exclusions": "?",
    }


def rescope(root: Path) -> None:
    """Gives every run's observation report the scope of its run as it now is."""
    for folder in sorted((root / "runs").iterdir()):
        path = root / "observation" / folder.name / "observation_report.json"
        if path.is_file():
            report = json.loads(path.read_text(encoding="utf-8"))
            report["scopes"] = [scope(folder)]
            path.write_text(json.dumps(report))


def observation_report(run_id: str, *, aaid: str, blocked: bool) -> dict:
    """Verðandi's report of such a run: the read of the advertising ID and the transmissions."""
    evidence = [
        {
            "id": "x1",
            "proposition": {"kind": "source_read", "source": "advertising_id", "value": aaid},
            "kinds": ["rt"],
            "method": "source_hook",
            "provenance": [{"observation": run_id, "instrument": "frida.sources", "record": "events.jsonl#3"}],
            "uncertainty": LOW,
        }
    ]
    claims = [_claim("a1", "accesses", "device-or-other-ids.advertising-id", None, ["x1"])]
    claims.append(
        _claim(
            "t1",
            "transmits",
            "data",
            {"endpoint": {"host": "app.example"}, "entity": "?", "domain": "app.example"},
            ["x1"],
        )
    )
    if not blocked:
        claims.append(
            _claim("t2", "transmits", "data", {"endpoint": {"host": "t.tracker.example"}, "entity": "tracker"}, ["x1"])
        )
    return {
        "report": {
            "created": "2026-10-21T12:00:00+00:00",
            "verdandi": "3.0.0",
            "components": [],
            "claims": {"attributes": {"application": PACKAGE, "status": "supported", "polarity": "+"}},
        },
        "observations": [{"id": run_id, "package": PACKAGE, "version": "1.0", "files": []}],
        "vocabulary": {"id": "asgard-data", "version": "1.0.0"},
        "scopes": [],
        "evidence": evidence,
        "claims": claims,
        "statuses": [],
        "open": [],
        "gaps": [],
    }


def build(root: Path, plan: list[tuple[str, dict]] | None = None, freeze: bool = True) -> Path:
    """
    A workspace with runs in the given order, each (condition, options of run_folder).

    The default plan alternates baseline, A1 and A2, three runs each, all meeting the oracle.
    """
    plan = plan or [(c, {}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    (root / "cases").mkdir(parents=True)
    (root / "oracles").mkdir()
    (root / "workspace.yaml").write_text(
        yaml.safe_dump({"application": {"package": PACKAGE, "version": "1.0"}, "runs": "runs"})
    )
    (root / "cases" / "start.yaml").write_text(yaml.safe_dump(CASE, sort_keys=False))
    (root / "oracles" / "O@1.yaml").write_text(yaml.safe_dump(ORACLE, sort_keys=False))
    lines = []
    for n, (condition, options) in enumerate(plan, 1):
        run_id = f"run-{n:02d}"
        aaid = ZERO if condition == "A1" else DEVICE_ID
        blocked = condition == "A2"
        run_folder(
            root / "runs" / run_id, run_id, f"2026-10-21T11:{n:02d}:00+00:00", aaid=aaid, blocked=blocked, **options
        )
        report = root / "observation" / run_id / "observation_report.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps(observation_report(run_id, aaid=aaid, blocked=blocked)))
        lines.append(json.dumps({"run": run_id, "dir": run_id, "condition": condition, "order": n}))
    (root / "runs.jsonl").write_text("\n".join(lines) + "\n")
    rescope(root)
    if freeze:
        from datetime import datetime

        inputs.freeze(root, AUTHOR, now=datetime.fromisoformat(FIXED))
    return root


def _message(mid: str, host: str) -> dict:
    return {
        "id": mid,
        "time": {"start": 1, "end": 2},
        "http_request": {
            "method": "POST",
            "scheme": "https",
            "host": host,
            "port": 443,
            "path": "/",
            "headers": [],
            "body": "e30=",
            "body_encoding": "base64",
        },
        "http_response": None,
        "capture": {"backend": "heimdall", "session": 1, "tag": "t"},
    }


def _connection(cid: str, host: str, blocked: bool) -> dict:
    return {
        "id": cid,
        "time": {"start": 1},
        "protocol": "TCP",
        "host": host,
        "remote_ip": "203.0.113.7",
        "remote_port": 443,
        "blocked": blocked,
        "block_reason": "host_rule" if blocked else None,
        "capture": {"backend": "heimdall", "session": 1},
    }


def _claim(cid: str, type_: str, node: str, recipient: dict | None, evidence: list[str]) -> dict:
    claim = {
        "id": cid,
        "type": type_,
        "datum": {"node": node},
        "channels": ["value_matching"],
        "qualifiers": {"occurrence": "observed", "actor": "?", "frequency": 1, "contexts": [{"time": "t"}]},
        "observations": ["r"],
        "evidence": evidence,
        "uncertainty": LOW,
        "sufficiency": {"sufficient": True},
        "observability": "E1",
    }
    if recipient:
        claim["recipient"] = recipient
    return claim
