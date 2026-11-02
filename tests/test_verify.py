"""Checks of the verification that rest on what the Observation dimension reports."""

import json
from types import SimpleNamespace

from skuld import inputs
from skuld.experiments import analyse
from skuld.verify import Verification, _replaced, _rounded, _substitution
from tests import workspace as ws


def test_a_rounded_read_is_the_platforms_value_rounded():
    assert _rounded({"value": 52.52, "original": 52.520008}, 2)
    assert not _rounded({"value": 52.53, "original": 52.520008}, 2)
    assert _rounded({"value": 52.5}, 2)  # unchanged: it already had no more decimals
    assert not _rounded({"value": "?"}, 2)


def test_a_replaced_location_gives_each_coordinate_its_part():
    lat = {"value": 52.52, "api": "Location.getLatitude"}
    lon = {"value": 13.405, "api": "Location.getLongitude"}
    assert _replaced(lat, "location", "52.52,13.405") and _replaced(lon, "location", "52.52,13.405")
    assert not _replaced(lon, "location", "13.405,52.52")
    assert _replaced({"value": "0000"}, "advertising_id", "0000")
    assert not _replaced({"value": "1111"}, "advertising_id", "0000")


def _sdk33_run(**sources):
    return SimpleNamespace(
        meta={"device": {"ro.build.version.sdk": "33"}},
        verification={"sources": {s: {"status": status} for s, status in sources.items()}},
    )


def test_closed_sim_ids_are_skipped_unless_hooked():
    report = {"evidence": []}
    v = Verification(status="verified")
    _substitution(v, _sdk33_run(), report, "device-or-other-ids.advertising-id", {}, {})
    assert not any("sim-ids" in u or "hardware-ids" in u for u in v.unverifiable)
    v = Verification(status="verified")
    run = _sdk33_run(sim_id="not_exercised")
    _substitution(v, run, report, "device-or-other-ids.advertising-id", {"sim_id": "pass"}, {})
    assert {"node": "device-or-other-ids.sim-ids", "holds": True, "note": "0 read(s), at most 0 in a baseline run"} in (
        v.substitution
    )


def test_a_removed_recipient_needs_closed_sources(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["condition"] == "A2":
            path = root / "observation" / entry["run"] / "observation_report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["statuses"] = [
                {
                    "claim_type": "transmits",
                    "node": "personal-info.email-address",
                    "status": "not_found",
                    "methods": ["value_matching"],
                    "basis": [
                        {"method": "value_matching", "recall": "established", "sources": "open", "analysis": "recall"}
                    ],
                    "uncertainty": ws.LOW,
                    "observations": [entry["run"]],
                }
            ]
            path.write_text(json.dumps(report))
    from datetime import datetime

    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    a2 = [r for r in report["runs"] if r["alternative"] == "A2"]
    assert {r["verification"]["status"] for r in a2} == {"failed"}
    assert "open" in a2[0]["verification"]["effect"][0]["note"]


def test_os_claims_are_read_once_each_a_combined_claim_for_those_it_combines():
    from skuld.observe import claims, transmissions_to

    recipient = {"endpoint": {"host": "t.example.net"}, "entity": "tracky", "domain": "example.net"}
    matched = {"id": "c1", "type": "transmits", "combined": False, "recipient": recipient}
    inferred = {"id": "c2", "type": "transmits", "combined": False, "recipient": recipient}
    other = {"id": "c3", "type": "transmits", "combined": False, "recipient": recipient}
    combined = {"id": "c4", "type": "transmits", "combined": True, "of": ["c1", "c2"], "recipient": recipient}
    report = {"claims": [matched, inferred, other, combined]}
    assert [c["id"] for c in claims(report)] == ["c3", "c4"]
    assert [c["id"] for c in transmissions_to(report, "tracky")] == ["c3", "c4"]
    assert [c["id"] for c in claims({"claims": [matched]})] == ["c1"]  # a report from before channel claims
