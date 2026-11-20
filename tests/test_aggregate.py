"""The aggregate (skuld.aggregate): structural keys, the purpose hierarchy (option c), losslessness, order, files."""

import json
from pathlib import Path

import pytest
from ratatoskr.schemas import validate

from skuld import aggregate as ag

FROM_DOC = {"t": "not_applicable", "s": "moderate", "n": "moderate"}
DISAGREED = {"t": "not_applicable", "s": "high", "n": "moderate"}
BY_RULE = {"t": "not_applicable", "s": "low", "n": "low"}


def practice(pid, data, recipient):
    return {"id": pid, "data": data, "recipient": recipient, "party": {"owner": recipient}}


def purpose_claim(pid, node, n=1):
    return {
        "id": f"claim:{pid}:{n}",
        "type": "purpose",
        "subject": pid,
        "purpose": {"node": node},
        "status": "supported",
    }


def alternative(pid, n, status="not_established", level="plausible", component="data", text="coarser data", **extra):
    return {
        "id": f"claim:{pid}:{n}",
        "type": "alternative",
        "subject": pid,
        "status": status,
        "level": level,
        "component": f"{pid}.{component}",
        "alternative": text,
        **extra,
    }


def minimisation(cid, pid, purpose_n, basis, status="not_established", uncertainty=FROM_DOC):
    return {
        "id": cid,
        "subject": pid,
        "requirement": "data_minimised",
        "principle": "data_minimisation",
        "provisions": ["GDPR Art. 5(1)(c)"],
        "step": "less_invasive_alternative",
        "tier": "reasoning",
        "status": status,
        "uncertainty": uncertainty,
        "observability": "E2",
        "purpose": f"claim:{pid}:{purpose_n}",
        "basis": basis,
        "reason": "…",
    }


def not_specific(cid, did, text, status="supported", uncertainty=FROM_DOC):
    return {
        "id": cid,
        "subject": did,
        "requirement": "purpose_specific",
        "principle": "transparency",
        "provisions": ["GDPR Art. 5(1)(b)"],
        "step": "not_specific",
        "tier": "reasoning",
        "status": status,
        "uncertainty": uncertainty,
        "observability": "E2",
        "reason": f'"{text}": 3 of 3 samples judge it not specific (action lacking)',
    }


def report(concerns, claims=(), practices=(), declarations=(), open_=()):
    return {
        "report": {"created": "2026-11-12T00:00:00+00:00"},
        "application": {"package": "a.b", "version": "1"},
        "subjects": {"practices": list(practices), "declarations": list(declarations)},
        "claims": list(claims),
        "concerns": list(concerns),
        "open": list(open_),
    }


def aggregated_of(a, requirement):
    return [f for f in a["aggregated_concerns"] if f["requirement"] == requirement]


def test_recipients_of_one_data_type_and_purpose_are_one_finding():
    ps = [practice(f"P-{r}", "location.city", r) for r in ("appnexus", "yahoo", "criteo")]
    claims, concerns = [], []
    for i, p in enumerate(ps):
        claims += [purpose_claim(p["id"], "TargetedAdvertising"), alternative(p["id"], 2)]
        concerns.append(minimisation(f"concern:{i}", p["id"], 1, [f"claim:{p['id']}:2"]))
    a = ag.aggregate(report(concerns, claims, ps))
    [f] = aggregated_of(a, "data_minimised")
    assert f["key"] == {"data": "location.city", "outcome": "none_supported", "purposes": ["TargetedAdvertising"]}
    assert sorted(m["recipient"] for m in f["members"]) == ["appnexus", "criteo", "yahoo"]
    assert f["label"].endswith("3 recipients")


def test_another_data_type_is_another_finding_under_the_same_theme():
    ps = [practice("P-1", "location.city", "x"), practice("P-2", "location.country", "x")]
    claims = [
        purpose_claim("P-1", "Advertising"),
        purpose_claim("P-2", "Advertising"),
        alternative("P-1", 2),
        alternative("P-2", 2),
    ]
    concerns = [
        minimisation("concern:1", "P-1", 1, ["claim:P-1:2"]),
        minimisation("concern:2", "P-2", 1, ["claim:P-2:2"]),
    ]
    a = ag.aggregate(report(concerns, claims, ps))
    assert len(aggregated_of(a, "data_minimised")) == 2
    [theme] = a["themes"]
    assert len(theme["aggregated_concerns"]) == 2


def test_purposes_on_one_branch_merge_under_the_most_general_when_the_verdict_is_the_same():
    p = practice("P-1", "location.city", "x")
    claims = [
        purpose_claim("P-1", "TargetedAdvertising", 1),
        purpose_claim("P-1", "Advertising", 2),
        alternative("P-1", 3, basis=["claim:P-1:1"]),
        alternative("P-1", 4, basis=["claim:P-1:2"]),
    ]
    concerns = [
        minimisation("concern:1", "P-1", 1, ["claim:P-1:3"]),
        minimisation("concern:2", "P-1", 2, ["claim:P-1:4"]),
    ]
    a = ag.aggregate(report(concerns, claims, [p]))
    [f] = aggregated_of(a, "data_minimised")
    assert f["key"]["purposes"] == ["Advertising"]
    assert sorted(m["purpose"] for m in f["members"]) == ["Advertising", "TargetedAdvertising"]


def test_purposes_on_one_branch_stay_apart_when_the_verdict_differs():
    p = practice("P-1", "location.city", "x")
    claims = [
        purpose_claim("P-1", "TargetedAdvertising", 1),
        purpose_claim("P-1", "Advertising", 2),
        alternative("P-1", 3, status="supported", level="documented"),
        alternative("P-1", 4),
    ]
    concerns = [
        minimisation("concern:1", "P-1", 1, ["claim:P-1:3"], status="supported"),
        minimisation("concern:2", "P-1", 2, ["claim:P-1:4"]),
    ]
    a = ag.aggregate(report(concerns, claims, [p]))
    fs = aggregated_of(a, "data_minimised")
    assert len(fs) == 2
    assert {f["key"]["outcome"] for f in fs} == {"technically_supported", "none_supported"}
    assert {tuple(f["key"]["purposes"]) for f in fs} == {("TargetedAdvertising",), ("Advertising",)}


def test_a_node_with_two_parents_present_is_one_group_labelled_with_both():
    groups = ag._purpose_groups(
        {"PersonalisedAdvertising", "Advertising", "Personalisation"}, ag.vocabulary(ag.PURPOSES)
    )
    assert groups["PersonalisedAdvertising"] == ("Advertising", "Personalisation")
    assert groups["Advertising"] == groups["Personalisation"] == ("Advertising", "Personalisation")


def test_unrelated_and_unknown_purposes_stay_apart():
    groups = ag._purpose_groups({"Advertising", "EnforceSecurity", "?"}, ag.vocabulary(ag.PURPOSES))
    assert groups == {"Advertising": ("Advertising",), "EnforceSecurity": ("EnforceSecurity",), "?": ("?",)}


def test_the_outcome_follows_the_decisive_alternatives():
    claims = {
        "a": {"type": "alternative", "status": "supported", "level": "documented", "component": "P-1.data"},
        "b": {"type": "alternative", "status": "supported", "level": "documented", "component": "P-1.recipient"},
        "c": {"type": "alternative", "status": "supported", "level": "plausible", "component": "P-1.data"},
        "r": {"type": "alternative", "status": "supported", "strength": "run", "component": "P-1.data"},
    }
    assert ag._outcome({"basis": ["a", "b", "c"], "status": "supported"}, claims) == (
        "technically_supported",
        ["data", "recipient"],
    )
    assert ag._outcome({"basis": ["r"], "status": "supported"}, claims) == ("demonstrated", [])
    assert ag._outcome({"basis": ["c"], "status": "not_established"}, claims) == ("none_supported", [])
    assert ag._outcome({"basis": [], "status": "not_assessable"}, claims) == ("not_assessable", [])


def test_declared_purposes_group_by_their_node_without_the_hierarchy():
    ds = [
        {"id": "D-1", "value": "ImproveExistingProductsAndServices"},
        {"id": "D-2", "value": "ImproveExistingProductsAndServices"},
        {"id": "D-3", "value": "Personalisation"},
        {"id": "D-4", "value": "ServicePersonalisation"},
    ]
    concerns = [
        not_specific("concern:1", "D-1", "improve our products"),
        not_specific("concern:2", "D-2", "help us improve them"),
        not_specific("concern:3", "D-3", "personalise your experience"),
        not_specific("concern:4", "D-4", "tailor the service"),
    ]
    a = ag.aggregate(report(concerns, declarations=ds))
    fs = {f["key"]["declared"]: f for f in aggregated_of(a, "purpose_specific")}
    assert set(fs) == {"ImproveExistingProductsAndServices", "Personalisation", "ServicePersonalisation"}
    assert [m["statement"] for m in fs["ImproveExistingProductsAndServices"]["members"]] == [
        "improve our products",
        "help us improve them",
    ]


def test_status_and_tier_never_mix():
    ds = [{"id": "D-1", "value": "Personalisation"}, {"id": "D-2", "value": "Personalisation"}]
    concerns = [
        not_specific("concern:1", "D-1", "x"),
        not_specific("concern:2", "D-2", "y", status="not_established"),
    ]
    a = ag.aggregate(report(concerns, declarations=ds))
    assert sorted(f["status"] for f in a["aggregated_concerns"]) == ["not_established", "supported"]


def test_supported_and_agreeing_findings_come_first():
    ds = [{"id": f"D-{i}", "value": v} for i, v in enumerate(["A", "B", "B", "C"])]
    concerns = [
        not_specific("concern:0", "D-0", "a", status="not_established"),
        not_specific("concern:1", "D-1", "b1"),
        not_specific("concern:2", "D-2", "b2"),
        not_specific("concern:3", "D-3", "c", uncertainty=DISAGREED),
    ]
    a = ag.aggregate(report(concerns, declarations=ds))
    assert [f["key"]["declared"] for f in a["aggregated_concerns"]] == ["B", "C", "A"]
    assert a["aggregated_concerns"][1]["disagreeing"] == 1
    assert a["aggregated_concerns"][1]["uncertainty"]["s"] == "high"


def test_collection_concerns_keep_their_condition_and_open_conditions_group_by_text():
    concerns = [
        {
            "id": "concern:collection:1",
            "subject": "collection",
            "requirement": "dpo_contact",
            "principle": "transparency",
            "provisions": [],
            "step": "information_not_given",
            "tier": "rule",
            "status": "supported",
            "uncertainty": BY_RULE,
            "observability": "E1",
            "condition": ["dpo_designated"],
            "reason": "missing if dpo_designated",
        }
    ]
    opens = [
        {"id": "open:1", "text": "consent", "qualifies": ["relation:1", "relation:2"]},
        {"id": "open:2", "text": "consent", "qualifies": ["relation:3"]},
    ]
    a = ag.aggregate(report(concerns, open_=opens))
    [f] = a["aggregated_concerns"]
    assert f["key"] == {"condition": ["dpo_designated"]} and f["condition"] == ["dpo_designated"]
    [g] = a["open"]
    assert g["members"] == ["open:1", "open:2"] and g["qualifies"] == 3


def test_every_concern_is_in_exactly_one_finding_and_the_schema_holds():
    ps = [practice("P-1", "location.city", "x")]
    claims = [purpose_claim("P-1", "Advertising"), alternative("P-1", 2)]
    concerns = [
        minimisation("concern:1", "P-1", 1, ["claim:P-1:2"]),
        not_specific("concern:2", "D-1", "x"),
        {**not_specific("concern:3", "D-9", "unknown declaration")},
    ]
    a = ag.aggregate(report(concerns, claims, ps, [{"id": "D-1", "value": "Advertising"}]))
    got = sorted(m["concern"] for f in a["aggregated_concerns"] for m in f["members"])
    assert got == ["concern:1", "concern:2", "concern:3"]
    validate("expectation_aggregate", a)


def test_a_lost_concern_is_refused():
    r = report([not_specific("concern:1", "D-1", "x")], declarations=[{"id": "D-1", "value": "A"}])
    a = ag.aggregate(r)
    with pytest.raises(ag.AggregateError):
        ag._check_lossless(
            {**r, "concerns": r["concerns"] + [not_specific("concern:2", "D-1", "y")]},
            a["aggregated_concerns"],
            a["open"],
        )


def test_run_writes_both_files_and_replays(tmp_path: Path):
    r = report([not_specific("concern:1", "D-1", "x")], declarations=[{"id": "D-1", "value": "A"}])
    (tmp_path / "assessment.json").write_text(json.dumps(r), encoding="utf-8")
    first = ag.run(tmp_path)
    second = ag.run(tmp_path)
    assert (tmp_path / "aggregate.json").is_file() and (tmp_path / "aggregate.md").is_file()

    def strip(a):
        return {**a, "report": {k: v for k, v in a["report"].items() if k != "created"}}

    assert strip(first) == strip(second)
    assert first["report"]["assessment"]["sha256"] != "0" * 64


def test_run_without_an_assessment_says_so(tmp_path: Path):
    with pytest.raises(ag.AggregateError, match="run skuld assess first"):
        ag.run(tmp_path)
