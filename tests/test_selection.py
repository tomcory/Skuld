"""Experiments in the assessment: the components a case varies, ≈ between case and hypothesis purposes, the
combination deciding by strength, concern (v) from a comparison, and the choice of experiments."""

import json
from types import SimpleNamespace

import pytest
from ratatoskr.frames import Frame
from ratatoskr.vocabularies import Vocabulary

from skuld import combine, concerns, select, space

DATA = Vocabulary.load("asgard-data")
PURPOSES = Vocabulary.load("dpv-purposes")
LOW = {"t": "moderate", "s": "low", "n": "not_applicable"}


def practice(pid, data, recipient=None, claim_type="accesses", relation=None):
    return SimpleNamespace(
        id=pid,
        data=data,
        recipient=recipient,
        claim_type=claim_type,
        party={"relation": relation} if relation else None,
        episodes=["1"],
    )


def hypothesis(pid, subject, node, who="user", status="supported"):
    return {
        "id": pid,
        "type": "purpose",
        "stage": "expectation",
        "of": [f"e1/s1:p{pid[-1]}"],
        "subject": subject,
        "purpose": {"node": node, "beneficiary": who},
        "status": status,
        "channels": ["reasoning:e1/s1"],
        "supporting": [],
        "challenging": [],
        "uncertainty": LOW,
        "sufficiency": {"sufficient": True},
    }


def premise(n, kind, status, subject="P-loc", node="ServiceProvision", **fields):
    return {
        "id": f"ex:forecast:{n}",
        "type": kind,
        "stage": "assessment",
        "channels": ["ex:forecast"],
        "subject": subject,
        "case": "forecast",
        "scope": {"case": "forecast", "requirements": ["R-W1.1"]},
        "purpose": {"id": "P-W1", "node": node, "beneficiary": "user", "provenance": "case"},
        "component": f"{subject}.data",
        "status": status,
        "supporting": [f"x{n}"] if status == "supported" else [],
        "challenging": [f"x{n}"] if status == "refuted" else [],
        "uncertainty": LOW,
        "sufficiency": {"sufficient": status in ("supported", "refuted")},
        **({"strength": "run"} if status in ("supported", "refuted") else {}),
        **fields,
    }


def test_a_case_component_varies_the_practices_of_its_datum_and_recipient():
    loc = {"id": "x-loc", "dimension": "G", "node": "location.coordinates"}
    tracker = {"id": "x-adco", "dimension": "R", "entity": "adco"}
    assert space.varies(loc, practice("P1", "location.coordinates"), DATA) == "P1.data"
    assert space.varies({**loc, "node": "location"}, practice("P1", "location.coordinates"), DATA) == "P1.data"
    assert space.varies(loc, practice("P2", "location.city"), DATA) is None
    assert space.varies(tracker, practice("P3", "data", "adco", "transmits"), DATA) == "P3.recipient"
    assert space.varies(tracker, practice("P4", "data", "other", "transmits"), DATA) is None


def test_skuld_imposes_what_its_rules_derive_and_never_blocks_the_provider():
    assert space.imposable(practice("P1", "location.coordinates")) == [
        {"component": "P1.data", "dimension": "G", "alternatives": ["G-round1", "G-round0"]}
    ]
    assert space.imposable(practice("P2", "device-or-other-ids.advertising-id"))[0]["alternatives"] == [
        "D-advertising_id"
    ]
    assert space.imposable(practice("P3", "data", "adco", "transmits", "other"))[0]["alternatives"] == ["R-adco"]
    assert space.imposable(practice("P4", "data", "example", "transmits", "own")) == []
    assert space.imposable(practice("P5", "data", "domain:cdn.example", "transmits")) == []


def test_a_hypothesis_aligns_with_the_nearest_case_purpose_above_it_of_its_beneficiary():
    cases = [
        {"id": "P-A", "node": "ServiceManagement", "beneficiary": "user"},
        {"id": "P-B", "node": "ServiceProvision", "beneficiary": "user"},
        {"id": "P-C", "node": "ServiceProvision", "beneficiary": "provider"},
    ]
    to = combine.aligned(
        [
            hypothesis("claim:P:1", "P", "RequestedServiceProvision"),
            hypothesis("claim:P:2", "P", "Advertising", "provider"),
        ],
        cases,
        PURPOSES,
    )
    assert to == {"claim:P:1": cases[1]}


def test_a_removal_names_the_aligned_hypotheses_and_stands_alone_where_reasoning_is_silent():
    h = hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision")
    premises = [
        premise(1, "alternative", "refuted", alternative="forecast:G-remove", level="demonstrated", removal=True),
        premise(3, "alternative", "supported", subject="P-ads", node="ServiceProvision", removal=True),
    ]
    out = combine.experimental([h], premises, PURPOSES, combine.Numbers())
    removal = next(c for c in out if c["subject"] == "P-loc")
    assert (removal["status"], removal["removal"], removal["strength"]) == ("refuted", True, "run")
    assert removal["of"] == ["ex:forecast:1"] and removal["basis"] == ["claim:P-loc:1"]
    assert removal["challenging"] == ["x1"] and removal["supporting"] == []
    silent = next(c for c in out if c["subject"] == "P-ads")
    assert silent["status"] == "supported" and silent["basis"] == [] and silent["of"] == ["ex:forecast:3"]


def test_a_demonstrated_alternative_is_a_minimisation_concern():
    frame = Frame.load("gdpr-art5")
    h = hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision")
    tested = combine.experimental(
        [h],
        [
            premise(1, "alternative", "supported", alternative="forecast:G1", level="demonstrated"),
            premise(2, "alternative", "refuted", alternative="forecast:G0", level="demonstrated"),
        ],
        PURPOSES,
        combine.Numbers(),
    )
    stated, covered = concerns.less_invasive_alternative(frame, [h], [], set(), {}, tested)
    assert [(c.requirement, c.subject) for c in covered] == [("data_minimised", "P-loc")] and len(stated) == 1
    c = stated[0]
    assert (c.status, c.observability) == ("supported", "E2")
    assert "forecast:G1 demonstrated" in c.reason
    assert c.channels == ["ex:forecast"] and c.supporting == ["x1"]
    assert c.uncertainty["t"] == "moderate" and c.uncertainty["n"] == "moderate"


def test_an_experiment_that_cannot_observe_the_purpose_leaves_the_concern_not_assessable():
    frame = Frame.load("gdpr-art5")
    h = hypothesis("claim:P-ads:1", "P-ads", "Advertising", "provider")
    reason = "the purpose has no observable oracle"
    unobservable = premise(1, "alternative", "not_assessable", subject="P-ads", node="Marketing", reason=reason)
    unobservable["sufficiency"] = {"sufficient": False, "reason": "oracle_not_observable"}
    unobservable["alternative"] = "launch:A1"
    tested = combine.experimental([h], [unobservable], PURPOSES, combine.Numbers())
    for t in tested:
        t["basis"] = ["claim:P-ads:1"]
    stated, _ = concerns.less_invasive_alternative(frame, [h], [], set(), {}, tested)
    assert (stated[0].status, stated[0].reason, stated[0].observability) == ("not_assessable", reason, "E3")


def report(claims, concerns_=()):
    return {"claims": claims, "concerns": list(concerns_)}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 0, "repeats": 3, "run_seconds": 100})
    practices = [
        {"id": "P-loc", "claim_type": "accesses", "data": "location.coordinates", "recipient": None, "episodes": ["1"]},
        {
            "id": "P-ads",
            "claim_type": "transmits",
            "data": "data",
            "recipient": "adco",
            "episodes": ["0"],
            "party": {"relation": "other"},
        },
        {
            "id": "P-own",
            "claim_type": "transmits",
            "data": "data",
            "recipient": "example",
            "episodes": ["2"],
            "party": {"relation": "own"},
        },
    ]
    (tmp_path / "subjects.json").write_text(json.dumps({"practices": practices}))
    claims = [
        hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision"),
        hypothesis("claim:P-ads:1", "P-ads", "Advertising", "provider"),
        hypothesis("claim:P-own:1", "P-own", "ServiceOptimisation", "provider"),
        hypothesis("claim:P-own:2", "P-own", "ServiceMonitoring", "provider", status="not_established"),
    ]
    (tmp_path / "assessment.json").write_text(json.dumps(report(claims)))
    return tmp_path


def test_with_experiments_off_every_candidate_is_refused_with_its_reason(workspace):
    selection = select.select(workspace)
    by = {e["purpose"]: e for e in selection["entries"]}
    assert set(by) == {"claim:P-loc:1", "claim:P-ads:1", "claim:P-own:1"}  # supported purposes only
    assert by["claim:P-own:1"]["reason"] == "Skuld can impose nothing on its components"
    assert all(e["kind"] == select.REFUSAL for e in by.values())
    assert "experiments are off" in by["claim:P-loc:1"]["reason"]
    assert by["claim:P-loc:1"]["cost_seconds"] == ((1 + 2) * 3 + 1) * 100
    assert selection["device_seconds"] == 0
    with pytest.raises(select.SelectionError):
        select.select(workspace)


def test_a_pursued_practice_is_chosen_and_the_budget_takes_the_rest_in_order(workspace, monkeypatch):
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-ads, reason: pursue}\n")
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 1000, "repeats": 3, "run_seconds": 100})
    selection = select.select(workspace)
    by = {e["purpose"]: e for e in selection["entries"]}
    assert by["claim:P-ads:1"]["kind"] == select.CHOICE and by["claim:P-ads:1"]["reason"].startswith("pursued")
    assert by["claim:P-loc:1"]["kind"] == select.REFUSAL and "over the budget" in by["claim:P-loc:1"]["reason"]
    named = select.named(workspace)
    assert {(n["kind"], n["id"]) for n in named} >= {(select.CHOICE, "selection:P-ads:1")}
    assert all(len(n["sha256"]) == 64 for n in named)
    episodes, keep = select.keeps(selection, DATA)
    assert episodes == {"0"}
    assert keep({"id": "x-adco", "dimension": "R", "entity": "adco"})
    assert not keep({"id": "x-loc", "dimension": "G", "node": "location.coordinates"})


def test_what_an_experiment_decided_or_could_not_assess_is_not_asked_again(workspace):
    claims = json.loads((workspace / "assessment.json").read_text())["claims"]
    decided = {**premise(1, "alternative", "supported"), "id": "claim:P-loc:2", "basis": ["claim:P-loc:1"]}
    tried = {
        **premise(2, "alternative", "not_assessable", subject="P-ads"),
        "id": "claim:P-ads:2",
        "basis": ["claim:P-ads:1"],
        "reason": "no oracle observes the purpose",
    }
    (workspace / "assessment.json").write_text(json.dumps(report(claims + [decided, tried])))
    by = {e["purpose"]: e for e in select.select(workspace)["entries"]}
    assert "claim:P-loc:1" not in by
    assert by["claim:P-ads:1"]["kind"] == select.REFUSAL and "could not assess it" in by["claim:P-ads:1"]["reason"]


def test_a_combined_claims_uncertainty_ranks_not_applicable_lowest():
    run = {"t": "moderate", "s": "low", "n": "not_applicable"}
    model = {"t": "not_applicable", "s": "high", "n": "not_applicable"}
    members = [{"uncertainty": run}, {"uncertainty": model}]
    assert combine._uncertainty(members, minimum=False) == {"t": "moderate", "s": "high", "n": "not_applicable"}
    assert combine._uncertainty(members, minimum=True) == {"t": "moderate", "s": "low", "n": "not_applicable"}


def test_an_undecided_combination_gives_the_reason_of_the_claim_that_cannot_assess_it():
    def sample(n, status, reason):
        return {
            **hypothesis(f"b/s{n}:p0", "P", "ServiceProvision", status=status),
            "channels": [f"reasoning:b/s{n}"],
            "sufficiency": {"sufficient": False, "missing": [reason]},
            "reason": reason,
        }

    out = combine.hypotheses(
        [
            sample(1, "not_established", "its action is not shown by the context"),
            sample(2, "not_assessable", "too vague"),
        ],
        combine.Numbers(),
    )
    assert (out[0]["status"], out[0]["reason"]) == ("not_assessable", "too vague")


def test_the_chosen_entries_name_their_reason(workspace, monkeypatch):
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-loc, reason: calibrate}\n")
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 0, "repeats": 3, "run_seconds": 100})
    by = {e["purpose"]: e for e in select.select(workspace)["entries"]}
    assert by["claim:P-loc:1"]["kind"] == select.CHOICE and by["claim:P-loc:1"]["reason"].startswith(
        "in the calibration"
    )
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-loc, reason: because}\n")
    with pytest.raises(select.SelectionError, match="the reason is one of"):
        select.select(workspace, replace=True)
