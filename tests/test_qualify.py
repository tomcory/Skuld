"""Qualification, the last stage of E (S-25, plan/archive/QUALIFICATION_PLAN.md §7): each rule on constructed assessments, the
tables against the pinned schema, precedence, and the fixtures."""

import json
import random
from pathlib import Path

import pytest
from ratatoskr.schemas import load_schema, validate

from skuld.qualify import nextsteps, qualify, symbols
from skuld.qualify.results import (
    CASE_ORDER,
    CONCERN,
    DISCREPANCY,
    INSUFFICIENT,
    NO_CONCERN,
    NOT_APPLICABLE,
    NOT_ASSESSABLE,
    ORDER,
)
from skuld.uncertainty import of

from .assessment import HIGH, REQUIREMENTS, Assessment

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = [
    "air.nn.mobile.app.main@3.8.96",
    "de.wetteronline.wetterapp@2026.20",
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4",
]
#: The profiles the author reviewed (Q3, 2026-11-02; plan/archive/QUALIFICATION_PLAN.md 8.7-8.10), fixed as expected output: a
#: change of a rule that moves one is a decision, recorded there, and this table changes with it
PROFILES = {
    "air.nn.mobile.app.main@3.8.96": {
        "practice": {CONCERN: 17, INSUFFICIENT: 10},
        "declaration": {NOT_APPLICABLE: 83},
        "declared_purposes": {CONCERN: 78, INSUFFICIENT: 55, NO_CONCERN: 49, NOT_APPLICABLE: 52},
        "collection": {NO_CONCERN: 21},
    },
    "de.wetteronline.wetterapp@2026.20": {  # D without its policy: the missing-source fixture (8.10)
        "practice": {CONCERN: 9, INSUFFICIENT: 17},
        "declaration": {},
        "declared_purposes": {CONCERN: 2, INSUFFICIENT: 63, NOT_APPLICABLE: 1},
        "collection": {INSUFFICIENT: 10, NO_CONCERN: 9, NOT_APPLICABLE: 2},
    },
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4": {
        "practice": {CONCERN: 7, INSUFFICIENT: 1},
        "declaration": {NOT_APPLICABLE: 28},
        "declared_purposes": {CONCERN: 40, INSUFFICIENT: 8, NO_CONCERN: 21, NOT_APPLICABLE: 13},
        "collection": {CONCERN: 4, NO_CONCERN: 17},
    },
}


def qualified(a: Assessment) -> dict:
    report = a.build()
    report["qualification"] = qualify(report, REQUIREMENTS)
    validate("expectation_assessment", report)
    return report["qualification"]


def case(q: dict, subject: str) -> dict:
    return next(c for c in q["cases"] if c["subject"] == subject)


def declared(a: Assessment, pid: str, outcome: str, **fields) -> str:
    """A practice declared in the policy, related by an O–D relation of the outcome."""
    did = a.declaration(f"D-{len(a.report['subjects']['declarations'])}", f"policy:/dataDisclosed/{pid}")
    a.relation("O-D", outcome, pid, to=[did], **fields)
    return did


# -- symbols ---------------------------------------------------------------------------------------------------------


def test_not_established_is_unknown_never_disagreement():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    a.relation("O-E", "no_functional_dependency_established", p)
    a.relation("D-E", "justification_not_established", p)
    c = case(qualified(a), p)
    assert c["pattern"]["O-E"]["symbol"] == "unknown" and c["pattern"]["D-E"]["symbol"] == "unknown"
    assert c["result"] == NO_CONCERN


def test_any_disagreement_wins_within_a_relation_type():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    declared(a, p, "corresponds_partially", partial="related", aspect="recipient")
    c = case(qualified(a), p)
    assert c["pattern"]["O-D"]["symbol"] == "disagree"
    # a correspondence with a sibling node only reads the silence on the observed one: an omission (framework 0.6)
    assert c["result"] == CONCERN


def test_a_denial_establishes_a_discrepancy_and_an_omission_does_not():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "contradicts")
    assert case(qualified(a), p)["result"] == DISCREPANCY


def test_observed_without_declaration_is_established_only_on_an_exhaustive_channels_silence():
    def result(silent: str) -> str:
        a = Assessment()
        p = a.practice()
        a.assessed_for_practice(p)
        for channel in silent.split(", "):
            a.document(channel)
        a.relation("O-D", "observed_without_declaration", p, silence=[f"D: {silent}"])
        c = case(qualified(a), p)
        return c["result"], c["reason"]

    established, _ = result("data_safety, policy")
    assert established == DISCREPANCY
    omitted, why = result("policy")
    assert omitted == CONCERN and "an omission, not a denial" in why


def test_the_silence_of_an_incomplete_document_is_an_omission():
    """An exhaustive channel closes its silence only where its document is complete (def:qualification, 21 Nov 2026)."""

    def result(complete: bool) -> tuple[str, str]:
        a = Assessment()
        p = a.practice()
        a.assessed_for_practice(p)
        a.document("data_safety", complete=complete)
        a.document("policy")
        a.relation("O-D", "observed_without_declaration", p, silence=["D: data_safety, policy"])
        c = case(qualified(a), p)
        return c["result"], c["reason"]

    assert result(True)[0] == DISCREPANCY
    omitted, why = result(False)
    assert omitted == CONCERN and "an omission, not a denial" in why


def test_a_concern_under_an_applicability_condition_is_insufficient_evidence():
    def result(applicability) -> str:
        a = Assessment()
        p = a.practice()
        a.assessed_for_practice(p)
        declared(a, p, "corresponds_exactly")
        a.concern(p, condition=["dpo_designated"])
        report = a.build()
        return case(qualify(report, REQUIREMENTS, applicability=applicability), p)["result"]

    assert result({"dpo_designated"}) == INSUFFICIENT
    # the same condition read as a fact about the processing leaves the concern supported
    assert result(set()) == CONCERN


def test_a_partial_correspondence_is_read_by_its_alignment():
    assert symbols.symbol({"type": "O-D", "outcome": "corresponds_partially", "partial": "root_category"}) == "agree"
    assert symbols.symbol({"type": "O-D", "outcome": "corresponds_partially", "partial": "related"}) == "disagree"
    assert symbols.symbol({"type": "O-D", "outcome": "corresponds_partially", "partial": "broader"}) == "unknown"


def test_an_unknown_outcome_is_an_error():
    with pytest.raises(symbols.UnknownOutcome):
        symbols.symbol({"id": "r", "type": "O-E", "outcome": "probably_fine"})
    with pytest.raises(symbols.UnknownOutcome):
        symbols.symbol({"id": "r", "type": "O-D", "outcome": "corresponds_partially"})


def test_every_outcome_of_the_pinned_schema_has_a_row():
    # a Ratatoskr release that adds an outcome cannot pass silently
    schema = load_schema("expectation_assessment")
    for rule in schema["properties"]["relations"]["items"]["allOf"]:
        kind = rule.get("if", {}).get("properties", {}).get("type", {}).get("const")
        outcomes = rule.get("then", {}).get("properties", {}).get("outcome", {}).get("enum")
        if kind and outcomes:
            for outcome in outcomes:
                if not (kind == "O-D" and outcome == "corresponds_partially"):
                    assert outcome in symbols.TABLES[kind], f"{kind} {outcome} has no row"
    for partial in schema["properties"]["relations"]["items"]["properties"]["partial"]["enum"]:
        assert partial in symbols.PARTIAL


def test_every_gap_reason_of_the_pinned_schema_has_a_next_step():
    schema = load_schema("expectation_assessment")
    for reason in schema["$defs"]["gapReason"]["enum"]:
        a = Assessment()
        p = a.practice()
        a.assessed_for_practice(p)
        a.gap(p, reason, of=p, observability="E3")
        q = qualified(a)
        assert q["next_steps"], reason
    with pytest.raises(nextsteps.UnknownReason):
        a = Assessment()
        p = a.practice()
        a.gap(p, "a_new_reason", of=p)
        qualify(a.build(), REQUIREMENTS)


def test_the_five_results_are_the_schemas():
    defs = load_schema("expectation_assessment")["$defs"]
    assert list(defs["qualifiedResult"]["enum"]) == list(ORDER)
    assert list(defs["caseResult"]["enum"]) == list(CASE_ORDER)


# -- placement --------------------------------------------------------------------------------------------------------


def test_a_purpose_goes_with_the_declaration_it_is_nested_under():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    d = declared(a, p, "corresponds_exactly")
    j = a.declaration("D-9", f"policy:/dataDisclosed/{p}/purposes/0", "justification", "declares_purpose", value="x")
    orphan = a.declaration("D-10", "policy:/notDisclosed/0", "justification", "declares_purpose", value="y")
    a.covered("purpose_specific", [j, orphan])
    c = a.concern(j, "purpose_specific", step="not_specific")
    q = qualified(a)
    held = case(q, p)
    assert j in held["references"]["declarations"] and d in held["references"]["declarations"]
    assert c in held["references"]["concerns"]
    # each purpose is a row too, where its specificity is decided (8.8)
    assert [r["subject"] for r in q["declared_purposes"]["rows"]] == [j, orphan]


def test_a_legal_basis_is_no_declared_purposes_row():
    """209 legal bases per family appeared as purposes "the reasoning tier did not judge" (plan/archive/POST_PAPER_FIXES 3)."""
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    j = a.declaration("D-9", f"policy:/dataDisclosed/{p}/purposes/0", "justification", "declares_purpose", value="x")
    basis = a.declaration("D-10", "policy:/legalBases/0", "justification", "declares_legal_basis", value="consent")
    said = a.declaration("D-11", f"policy:/dataDisclosed/{p}/legalBases/0", "justification", "declares_legal_basis")
    for d in a.report["subjects"]["declarations"]:
        if d["id"] in (j, said):
            d["statement"] = "Q1"  # said in one sentence with the purpose
    a.covered("purpose_specific", [j])
    q = qualified(a)
    assert [r["subject"] for r in q["declared_purposes"]["rows"]] == [j]
    assert basis not in json.dumps(q["declared_purposes"]) and said not in json.dumps(q["declared_purposes"])


def test_a_vague_purpose_is_decided_in_its_statements_row_never_in_the_practice():
    a = Assessment()
    p, other = a.practice(), a.practice()
    for x in (p, other):
        a.assessed_for_practice(x)
        declared(a, x, "corresponds_exactly")
    # one statement said for both practices' data: two declarations, one row
    j1 = a.declaration("D-9", f"policy:/dataDisclosed/{p}/purposes/0", "justification", "declares_purpose", value="x")
    j2 = a.declaration(
        "D-10", f"policy:/dataDisclosed/{other}/purposes/0", "justification", "declares_purpose", value="x"
    )
    for d in a.report["subjects"]["declarations"]:
        if d["id"] in (j1, j2):
            d["statement"] = "Q1"
    a.covered("purpose_specific", [j1, j2])
    c = a.concern(j1, "purpose_specific", step="not_specific")
    a.relation("D-E", "purpose_too_vague", j2, to=[c])
    q = qualified(a)
    for x in (p, other):
        held = case(q, x)
        assert c in held["references"]["concerns"] and held["result"] == NO_CONCERN
        assert [s["result"] for s in held["secondary"]] == [CONCERN]
        assert "of a declared purpose, decided in its row" in held["secondary"][0]["reason"]
    rows = q["declared_purposes"]["rows"]
    assert [(r["subject"], r["result"]) for r in rows] == [(j1, CONCERN)]
    assert q["profile"]["declared_purposes"] == {CONCERN: 1}


def test_a_declaration_no_practice_case_holds_is_a_case_of_its_own():
    a = Assessment()
    d = a.declaration("D-0", "policy:/dataDisclosed/0")
    a.relation("O-D", "declared_without_observation", d, silence=["O: unknown"])
    q = qualified(a)
    c = case(q, d)
    assert c["kind"] == "declaration" and c["pattern"]["O-D"]["symbol"] == "none"
    assert q["profile"]["declaration"] == {NOT_APPLICABLE: 1}
    assert c["result"] == NOT_APPLICABLE and "declared, not observed by O" in c["reason"]


def test_a_declaration_no_observation_relates_to_is_not_applicable_never_no_concern():
    a = Assessment()
    d = a.declaration("D-0", "policy:/dataRetention/0", type_="declares_retention")
    c = case(qualified(a), d)
    assert c["result"] == NOT_APPLICABLE and "nothing O observed relates to it" in c["reason"]


def test_nothing_is_dropped_without_notice():
    a = Assessment()
    a.practice()
    a.concern("P-elsewhere")
    q = qualified(a)
    assert [u["id"] for u in q["unplaced"]] == ["concern:P-elsewhere:1"]


# -- results ----------------------------------------------------------------------------------------------------------


def test_a_conditional_contradiction_never_establishes_a_discrepancy():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "contradicts", condition="the recipient acts as a third party", aspect="recipient")
    c = case(qualified(a), p)
    assert c["result"] == CONCERN and c["pattern"]["O-D"]["conditional"]


def test_a_source_condition_makes_a_concern_insufficient():
    a = Assessment()
    a.transparency("processing_purpose", "missing_if", conditions=["analysed:policy"])
    a.covered("processing_purpose", ["collection"])
    cid = a.concern("collection", "processing_purpose", step="information_not_given", condition=["analysed:policy"])
    a.open("whether the policy, which could not be analysed, gives the information", [cid], kind="source")
    q = qualified(a)
    row = q["collection"]["rows"][0]
    assert row["result"] == INSUFFICIENT
    step = next(s for s in q["next_steps"] if s["id"] in row["next_steps"])
    assert step["kind"] == "acquire" and step["target"] == {"channel": "policy"} and step["could_change"]


def test_a_fact_condition_leaves_a_supported_concern():
    a = Assessment()
    a.transparency("processing_purpose", "missing_if", conditions=["dpo_designated"])
    a.covered("processing_purpose", ["collection"])
    a.concern("collection", "processing_purpose", step="information_not_given", condition=["dpo_designated"])
    assert qualified(a)["collection"]["rows"][0]["result"] == CONCERN


def test_a_practice_without_a_purpose_is_insufficient():
    a = Assessment()
    p = a.practice()
    a.gap(p, "own_knowledge", of=p)
    c = case(qualified(a), p)
    assert c["result"] == INSUFFICIENT and "no purpose" in c["reason"]


def test_without_d_a_minimisation_concern_still_stands():
    a = Assessment(with_d=False)
    p = a.practice()
    a.covered("data_minimised", [p])
    a.concern(p)
    q = qualified(a)
    c = case(q, p)
    assert c["result"] == CONCERN
    assert any("no D report" in s["reason"] for s in c["secondary"])
    assert not q["collection"]["assessed"] and "no D report" in q["collection"]["reason"]


def test_beyond_external_evidence_is_not_externally_assessable():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    a.gap(p, "oracle_not_observable", of=p, observability="E3")
    assert case(qualified(a), p)["result"] == NOT_ASSESSABLE


def test_an_audit_request_carries_its_level():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    a.gap(p, "oracle_not_observable", of=p, observability="E3")
    a.gap(p, "applicability_unknown", of=p, observability="E4")
    levels = {s["level"] for s in qualified(a)["next_steps"] if s["kind"] == "audit_request"}
    assert levels == {"evidence_assisted_audit", "full_accountability_assessment"}


def test_only_minimisation_has_an_experiment():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    m = a.concern(p, status="not_established")
    s = a.concern(p, "purpose_compatible", status="not_established", step="no_specified_purpose")
    a.gap(p, "not_admitted", of=m)
    a.gap(p, "not_admitted", of=s)
    kinds = {tuple(x["from"]): x["kind"] for x in qualified(a)["next_steps"]}
    assert sorted(kinds.values()) == ["experiment", "re-analyse"]


def test_the_attributes_never_set_a_result():
    def result(**practice) -> str:
        a = Assessment()
        p = a.practice(**practice)
        a.assessed_for_practice(p)
        declared(a, p, "corresponds_exactly")
        return case(qualified(a), p)["result"]

    assert result() == result(data="health-fitness.physical-activity", recipient="other", party="own")


# -- triggers ---------------------------------------------------------------------------------------------------------


def test_a_trigger_weighs_only_if_a_resolution_changes_the_result():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    a.concern(p, uncertainty=HIGH)
    c = case(qualified(a), p)
    high = next(t for t in c["triggers"] if t["trigger"] == "high_uncertainty")
    assert high["weighs"]  # read as not established, the case is no longer a supported concern

    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "observed_without_declaration")
    a.concern(p, uncertainty=HIGH)
    c = case(qualified(a), p)
    high = next(t for t in c["triggers"] if t["trigger"] == "high_uncertainty")
    assert not high["weighs"]  # the discrepancy stands whatever the concern


def test_high_uncertainty_reads_the_level_only():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    # many moderate reasons are still moderate: no trigger
    a.concern(p, uncertainty=of("from_documents", "open_judgement", "few_runs", "aligned_above"))
    c = case(qualified(a), p)
    assert not any(t["trigger"] == "high_uncertainty" for t in c["triggers"])


def test_a_concern_resting_on_an_overruled_claim_is_a_model_against_measurement_trigger():
    a = Assessment()
    p = a.practice()
    a.assessed_for_practice(p)
    declared(a, p, "corresponds_exactly")
    measured = {
        "id": f"claim:{p}:1",
        "type": "purpose",
        "stage": "assessment",
        "channels": ["ex:launch", "reasoning:e1/s1"],
        "of": ["ex:launch:1", "e1/s1:1"],
        "subject": p,
        "purpose": {"node": "Advertising"},
        "status": "supported",
        "supporting": ["k"],
        "challenging": [],
        "sufficiency": {"sufficient": True},
        "strength": "run",
        "overruled": [{"claim": "e1/s1:1", "channels": ["reasoning:e1/s1"], "status": "refuted", "strength": "doc"}],
    }
    a.report["claims"].append(measured)
    concern = a.concern(p, basis=[measured["id"]])
    c = case(qualified(a), p)
    trigger = next(t for t in c["triggers"] if t["trigger"] == "model_against_measurement")
    assert trigger["signal"] == [concern] and trigger["weighs"]  # as the model had it, there would be no concern

    a.report["claims"][-1].pop("overruled")
    c = case(qualified(a), p)
    assert not any(t["trigger"] == "model_against_measurement" for t in c["triggers"])


# -- precedence -------------------------------------------------------------------------------------------------------


def test_the_result_is_the_first_step_that_holds_and_lower_evidence_never_changes_it():
    rng = random.Random(7)
    outcomes = ["corresponds_exactly", "observed_without_declaration", "contradicts", "insufficient_evidence"]
    statuses = ["supported", "not_established", "not_assessable", "refuted"]
    for _ in range(150):
        a = Assessment()
        p = a.practice()
        a.assessed_for_practice(p)
        outcome = rng.choice(outcomes)
        declared(a, p, outcome, **({"condition": "a fact"} if outcome == "contradicts" and rng.random() < 0.5 else {}))
        for _ in range(rng.randint(0, 2)):
            a.concern(p, status=rng.choice(statuses))
        first = case(qualified(a), p)
        # adding evidence for a lower step never changes a higher result
        a.gap(p, "oracle_not_observable", of=p, observability="E3")
        after = case(qualified(a), p)
        if ORDER.index(first["result"]) < ORDER.index(NOT_ASSESSABLE):
            assert after["result"] == first["result"]
        held = [first["result"]] + [s["result"] for s in first["secondary"]]
        assert held == sorted(held, key=ORDER.index)


# -- the fixtures -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixtures_are_qualified_whole(name):
    path = ROOT / "workspaces" / name / "assessment.json"
    if not path.is_file():
        pytest.skip("the case study's workspaces are not in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    q = report.get("qualification")
    assert q is not None, "re-run skuld assess"
    assert q["unplaced"] == []
    practices = {p["id"] for p in report["subjects"]["practices"]}
    assert {c["subject"] for c in q["cases"] if c["kind"] == "practice"} == practices
    assert sum(q["profile"]["practice"].values()) == len(practices)
    steps = {s["id"] for s in q["next_steps"]}
    assert all(set(c["next_steps"]) <= steps for c in q["cases"])
    # neutral order: by result down the precedence, then by subject
    keys = [(CASE_ORDER.index(c["result"]), c["subject"]) for c in q["cases"]]
    assert keys == sorted(keys)
    assert {k: v for k, v in q["profile"].items() if k != "o_d_by_channel"} == PROFILES[name]
    # one signal for experiments: a step per purpose skuld select finds eligible, and the listing reads its flag
    from skuld import select

    listed = select.listing(path.parent)
    steps = {s["target"]["purpose"]: s for s in q["next_steps"] if "purpose" in s.get("target", {})}
    assert {c["purpose"] for c in listed if c["eligible"]} == set(steps)
    assert all(c["could_change"] == steps[c["purpose"]]["could_change"] for c in listed if c["eligible"])


def test_a_concerns_evidence_is_rule_documented_or_demonstrated_and_a_minimisation_reason_names_it():
    from skuld.qualify import attributes, results

    claims = {
        "claim:P:doc": {"id": "claim:P:doc", "strength": "doc", "level": "technically_supported"},
        "claim:P:run": {"id": "claim:P:run", "strength": "run", "level": "demonstrated"},
    }
    minimise = {"step": "less_invasive_alternative", "tier": "reasoning"}
    assert attributes.evidence({**minimise, "basis": ["claim:P:doc"]}, claims) == "documented"
    assert attributes.evidence({**minimise, "basis": ["claim:P:doc", "claim:P:run"]}, claims) == "demonstrated"
    assert attributes.evidence({"step": "information_not_given", "tier": "rule"}, claims) == "rule"
    assert attributes.evidence({"step": "not_specific", "tier": "reasoning"}, claims) == "documented"
    con = results.Con("concern:P:1", "data_minimised", "less_invasive_alternative", "supported", evidence="documented")
    found = results.steps(results.View(concerns=[con]))
    assert found[0].result == results.CONCERN
    assert "data_minimised (less invasive alternative, documented)" in found[0].reason
