"""Tests of the assessment's subjects: practices (Q1), parties, declarations, the frame's conditions."""

import json
from pathlib import Path

import pytest
from ratatoskr.frames import Frame
from ratatoskr.registry import Registry

from skuld import assessment, frame, inputs, parties
from skuld.assess import SUBJECTS, subjects

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.example.app"
REGISTRY = Registry(
    {
        "entities": [
            {"id": "adco", "name": "AdCo", "domains": ["adco.example"]},
            {"id": "example-gmbh", "name": "Example GmbH", "domains": ["example.com"]},
        ]
    }
)


def claim(cid, node, entity=None, actor=None, episode="1", of=None, ctype="transmits", status="supported"):
    c = {
        "id": cid,
        "type": ctype,
        "datum": {"node": node},
        "qualifiers": {"contexts": [{"episode": episode, "time": "2026-10-22T10:00:00+00:00"}]},
        "polarity": "+",
        "status": status,
        "observations": ["run-1"],
    }
    if ctype == "transmits":
        c["recipient"] = {"entity": entity or "?", "domain": f"{entity}.example", "endpoint": {"host": "h"}}
    if actor:
        c["qualifiers"]["actor"] = {"kind": "component", "component": actor}
    if of:
        c.update(combined=True, of=of)
    return c


def o_report(claims, statuses=(), version="1.0"):
    return {
        "observations": [{"id": "run-1", "package": PACKAGE, "version": version}],
        "scopes": [{"observation": "run-1", "application": PACKAGE, "version": version}],
        "claims": claims,
        "statuses": list(statuses),
    }


def d_report(claims, documents=(), version="1.0"):
    """A D report whose claims are given rather than projected from its documents (no projection in its header), each
    with an id as D's projection would give it."""
    channels = [
        {"channel": "policy", "document": "p", "status": "analysed", "complete": True, "tilt": t} for t in documents
    ]
    for n, c in enumerate(claims):
        c.setdefault("id", f"{c['channels'][0]}:/dataDisclosed/{n}")
    return {"collection": {"package": PACKAGE, "store_version": version}, "channels": channels, "claims": claims}


def declared(ctype, polarity="+", kind="practice", value=None):
    """A D claim in the shared claim's shape; a recipient claim's value is its recipient."""
    return {
        "type": ctype,
        "kind": kind,
        "channels": ["policy"],
        "datum": {"node": "data"},
        **({"recipient": value} if ctype == "declares_recipient" else {"value": value}),
        "polarity": polarity,
        "qualifiers": {},
    }


def workspace(tmp_path, o_reports, d=None):
    paths = []
    for n, r in enumerate(o_reports):
        p = tmp_path / f"o{n}.json"
        p.write_text(json.dumps(r))
        paths.append((p, f"run-{n}"))
    dp = None
    if d is not None:
        dp = tmp_path / "d.json"
        dp.write_text(json.dumps(d))
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", paths, dp, None, ROOT / "corpus")
    return inputs.load_assessment(root)


def test_a_practice_aggregates_claims_by_type_node_recipient_and_actor(tmp_path):
    first = o_report(
        [
            claim("c1", "device-or-other-ids.advertising-id", "adco", "AdSDK", episode="1"),
            claim("c2", "device-or-other-ids.advertising-id", "adco", "AdSDK", episode="2"),
            # a combined claim and the channel claim it combines are one observation, not two
            claim("c3", "location.approximate-location", "adco", "AdSDK", of=["c4"]),
            claim("c4", "location.approximate-location", "adco", "AdSDK"),
            claim("c5", "device-or-other-ids.advertising-id", "adco", None),  # another actor: another practice
            claim("c6", "personal-info.name", "adco", "AdSDK", status="not_established"),  # not a practice
        ]
    )
    second = o_report([claim("c1", "device-or-other-ids.advertising-id", "adco", "AdSDK", episode="3")])
    built = assessment.build(workspace(tmp_path, [first, second]), REGISTRY)
    by = {(p.data, p.actor): p for p in built.practices}
    aaid = by[("device-or-other-ids.advertising-id", "component:AdSDK")]
    assert aaid.episodes == ["1", "2", "3"] and len(aaid.claims) == 3
    assert {c["claim"] for c in aaid.claims} == {"c1", "c2"} and len({c["report"] for c in aaid.claims}) == 2
    assert len(by[("location.approximate-location", "component:AdSDK")].claims) == 1
    assert ("device-or-other-ids.advertising-id", "?") in by and len(built.practices) == 3
    assert aaid.u0["D"] == ["device-or-other-ids.advertising-id"] and aaid.u0["R"] == ["adco"]
    # ids are stable across rebuilds
    assert assessment.build(workspace(tmp_path, [first, second]), REGISTRY).practices[0].id == built.practices[0].id


def test_parties_relate_recipients_to_the_controller():
    provider = parties.Controller(frozenset({"example gmbh"}), frozenset({"example.com"}), "example.com")
    assert parties.relate("example-gmbh", REGISTRY, provider).relation == parties.OWN
    assert parties.relate("adco", REGISTRY, provider).relation == parties.OTHER
    assert parties.relate("domain:api.example.com", REGISTRY, provider).relation == parties.OWN
    assert parties.relate("domain:cdn.unknown.example", REGISTRY, provider).relation == parties.UNKNOWN
    # without D, the package's domain read backwards
    bare = parties.controller(None, "de.wetteronline.wetterapp")
    assert parties.relate("domain:api.wetteronline.de", None, bare).relation == parties.OWN
    # a register entity on the package's domain is the provider's without D too
    assert parties.relate("example-gmbh", REGISTRY, parties.controller(None, "com.example.app")).relation == parties.OWN
    assert parties.relate("adco", REGISTRY, parties.controller(None, "com.example.app")).relation == parties.OTHER


def test_declarations_are_referenced_by_pointer_and_the_collection_keeps_completeness(tmp_path):
    d = d_report([declared("declares_collection"), declared("declares_purpose", kind="justification")], [{}])
    built = assessment.build(workspace(tmp_path, [o_report([])], d), None)
    assert [x.claim["claim"] for x in built.declarations] == ["policy:/dataDisclosed/0", "policy:/dataDisclosed/1"]
    assert built.declarations[1].kind == "justification"
    assert built.collection["documents"][0]["complete"] is True  # D's report says nothing otherwise
    assert built.comparability["comparable"] is True


def test_o_and_d_of_different_versions_are_not_comparable(tmp_path):
    a = workspace(tmp_path, [o_report([], version="2.0")], d_report([], version="1.0"))
    assert assessment.build(a, None).comparability["comparable"] is False


def decide(tmp_path, o_claims=(), statuses=(), d_claims=(), documents=({},)):
    d = d_report(list(d_claims), list(documents)) if d_claims or documents else None
    a = workspace(tmp_path, [o_report(list(o_claims), statuses)], d)
    built = assessment.build(a, REGISTRY)
    e = frame.evidence(built, [r.load() for r in a.observations], a.declaration.load() if a.declaration else None)
    return frame.decisions(Frame.load("gdpr-art5"), e)


def test_a_providers_denial_never_makes_a_requirement_inapplicable(tmp_path):
    denied = decide(tmp_path, d_claims=[declared("declares_collection", polarity="-")])
    # the denial is recorded, but D does not decide that collection fails
    assert denied["personal_data_collected"].fails == {"D": [denied["personal_data_collected"].fails["D"][0]]}
    assert denied["personal_data_collected"].value == "?"
    absent = [{"claim_type": "transmits", "node": "data", "status": "absence_established"}]
    assert decide(tmp_path, statuses=absent)["personal_data_collected"].value == "does_not_apply"
    observed = decide(tmp_path, o_claims=[claim("c1", "personal-info.name", "adco")])
    assert observed["personal_data_collected"].value == "applies"
    assert observed["recipients_exist"].value == "applies"  # AdCo is another organisation


def test_the_legal_bases_and_purposes_are_ds_either_way(tmp_path):
    consent = {"dataDisclosed": [{"legalBases": [{"reference": "GDPR-6-1-a"}]}], "_asgard": {"channels": ["policy"]}}
    decided = decide(tmp_path, d_claims=[declared("declares_collection")], documents=[consent])
    assert (decided["basis_a"].value, decided["basis_f"].value) == ("applies", "does_not_apply")
    assert decided["purpose_declared"].value == "does_not_apply"  # an analysed report that declares no purpose
    assert decided["dpo_designated"].value == "?"  # nobody decides that no DPO is designated


FIXTURES = [
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4",
    "air.nn.mobile.app.main@3.8.96",
    "de.wetteronline.wetterapp@2026.20",
]


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixtures_subjects(name, tmp_path):
    root = ROOT / "cases" / name
    if not (root / "assessment.yaml").is_file():
        pytest.skip("the case study's workspaces are not in this checkout")
    before = (root / SUBJECTS).read_text() if (root / SUBJECTS).is_file() else None
    try:
        out = subjects(root)
    finally:
        if before is not None:
            (root / SUBJECTS).write_text(before)
    assert out["practices"] and out["frame"]["id"] == "gdpr-art5"
    if name.startswith("pilates"):
        # the dry run's two components: the advertising ID, and AppsFlyer as a recipient
        assert any(p["data"] == "device-or-other-ids.advertising-id" for p in out["practices"])
        assert any(p["recipient"] == "appsflyer" for p in out["practices"])
        assert out["collection"] and all(
            "complete" in d for d in out["collection"]["documents"] if d["status"] == "analysed"
        )
    elif name.startswith("air.nn"):
        assert len({e for p in out["practices"] for e in p["episodes"] if e != "?"}) > 5  # practices per episode
    else:
        assert out["collection"] is None and out["declarations"] == []
        assert out["applicability"]["purpose_specific"]["applicability"] == "?"
