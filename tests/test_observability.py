"""Observability levels on propositions (Ratatoskr 0.39.0, plan/archive/OBSERVABILITY_PLAN.md §4–§9): gaps bear on
propositions and have a structured next step; a complete-reach proposition never ends in an audit request; the run's
scope settles a denial's own scope (D3); where a purpose is achieved (`achieved_on`)."""

import json

import pytest
from ratatoskr.frames import Frame
from ratatoskr.schemas import load_schema, validate

from skuld import assess as assess_
from skuld import assessment, combine, correspondence, gaps, inputs, observe
from skuld import scope as run_scope
from skuld.assess import assess
from skuld.common import PURPOSES, vocabulary
from tests.test_assess import claim, o_report, workspace
from tests.test_assess import d_report as documented
from tests.test_rule_tier import DATA, REGISTRY, TYPES, d_claim, d_report

FRAME = Frame.load("gdpr-art5")
NAME = "personal-info.name"


# -- the next-step table (OBSERVABILITY_PLAN §8), a case per row ------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "fields", "kind", "held"),
    [
        ("own_knowledge", {}, "extend_corpus", None),
        ("own_knowledge", {"exhausted": True}, "audit_request", "organisation"),
        ("not_admitted", {"claim_type": "purpose"}, "re-analyse", None),
        ("not_admitted", {"claim_type": "dependency"}, "experiment", None),
        ("not_admitted", {"claim_type": "alternative"}, "experiment", None),
        ("not_admitted", {"requirement": "data_minimised"}, "experiment", None),
        ("not_admitted", {"requirement": "purpose_compatible"}, "re-analyse", None),
        ("purpose_vague", {}, "review", None),
        ("substitute_more_invasive", {}, "review", None),
        ("purpose_not_in_vocabulary", {}, "re-analyse", None),
        ("oracle_not_observable", {"achieved_on": "device"}, "improve_instrument", None),
        ("oracle_not_observable", {"achieved_on": None}, "improve_instrument", None),
        ("oracle_not_observable", {"achieved_on": "server"}, "audit_request", "record"),
        ("source_not_analysable", {"payloads": ["encrypted_by_application"]}, "improve_instrument", None),
        ("source_not_analysable", {"payloads": ["binary"]}, "improve_instrument", None),
        ("source_not_analysable", {"payloads": ["damaged"]}, "explore", None),
        ("source_not_analysable", {"payloads": ["damaged", "binary"]}, "improve_instrument", None),
        ("source_not_analysable", {}, "improve_instrument", None),  # O states no reason: an instrument
        ("requirements_not_reached", {}, "explore", None),
        ("needs_run", {}, "experiment", None),
        ("search_space_not_run", {}, "experiment", None),
        ("intervention_not_verified", {}, "experiment", None),
        ("substitution_not_verifiable", {}, "experiment", None),
        ("not_covered", {}, "experiment", None),
        ("precondition_failed", {}, "experiment", None),
        ("source_absent", {}, "acquire", None),
        ("not_comparable", {}, "acquire", None),
    ],
)
def test_a_gap_reason_has_the_next_step_of_its_row(reason, fields, kind, held):
    step = gaps.reason_step(reason, "the proposition", **fields)
    assert (step["kind"], step.get("held")) == (kind, held) and step["text"]
    validator_input = {"bears_on": [{"proposition": "p", "ref": "requirement:data_minimised"}], "next": step}
    validate_next(validator_input)


def validate_next(gap: dict) -> None:
    """A gap's bears_on and next against the schema's definitions (an expectation_assessment gap)."""
    import jsonschema

    defs = load_schema("claim")["$defs"]
    for name, value in (("bearsOn", gap["bears_on"]), ("nextStep", gap["next"])):
        jsonschema.validate(value, {"$defs": defs, "$ref": f"#/$defs/{name}"})


@pytest.mark.parametrize(
    ("condition", "kind", "held"),
    [
        ("purpose_declared", "acquire", None),  # E1: complete, never an audit request
        ("dpo_designated", "acquire", None),  # E2: Art. 37(7) makes the DPO's contact public
        ("personal_data_collected", "explore", None),  # E2: absent only within the exploration's coverage
        ("recipients_exist", "explore", None),
        ("not_from_data_subject", "audit_request", "record"),  # E3
        ("adm_in_use", "audit_request", "record"),
        ("third_country_transfer", "audit_request", "record"),
        ("basis_a", "audit_request", "organisation"),  # E4
    ],
)
def test_an_applicability_conditions_step_is_external_where_its_reach_is_not_none(condition, kind, held):
    ref = f"condition:{condition}"
    step = gaps.condition_step(ref, gaps.level_of(ref, FRAME), FRAME.conditions[condition].text)
    assert (step["kind"], step.get("held")) == (kind, held)


def test_the_fact_conditions_of_o_d_relations_take_their_levels_from_ratatoskr_and_skuld():
    definition = gaps.level_of("definition:google-play-data-safety/recipient", FRAME)
    role = gaps.level_of("role:ThirdParty", FRAME)
    reading = gaps.level_of("reading:root-category", FRAME)
    assert (definition["level"], definition["held"]) == ("E3", "record")
    assert (role["level"], role["held"]) == ("E3", "record")
    assert (reading["level"], reading["reach"], reading["held"]) == ("E2", "partial", "organisation")
    assert gaps.condition_step("role:ThirdParty", role, "x")["kind"] == "audit_request"
    assert gaps.condition_step("reading:root-category", reading, "x")["kind"] == "review"
    # the product a denial is limited to is decided by observing the application (complete reach); the other scope
    # conditions are partial, the provider's records holding the rest
    product = gaps.level_of("scope:product", FRAME)
    assert (product["level"], product["reach"], "held" in product) == ("E1", "complete", False)
    assert gaps.level_of("scope:jurisdiction", FRAME)["level"] == "E2"
    # correspondence reads the definitions' texts from Ratatoskr, not a table of its own
    assert correspondence.DEFINITIONS[("google-play-data-safety", "data")].startswith("the processing is not only")


def test_an_old_frame_is_read_with_the_current_frames_levels():
    old = Frame.load("gdpr-art5", "1.1.0")
    assert old.conditions["adm_in_use"].observability is None
    assert gaps.level_of("condition:adm_in_use", old)["level"] == "E3"


# -- the invariant: no audit request for a proposition of complete reach ---------------------------------------------


def _gap(ref, step):
    return {
        "id": "gap:x:1",
        "reason": "applicability_unknown",
        "bears_on": [{"proposition": "p", "ref": ref}],
        "next": step,
    }


def test_no_audit_request_for_a_proposition_of_complete_reach():
    audit = gaps.step("audit_request", "ask", "record")
    for ref in ("condition:purpose_declared", "requirement:controller_name", "requirement:purpose_specific"):
        with pytest.raises(gaps.NextStepError):
            gaps.check(_gap(ref, audit), FRAME)
    # on the device, a dependency's proposition is shown there: complete reach
    claims = {"x": {"id": "x", "type": "dependency", "purpose": {"achieved_on": "device"}}}
    with pytest.raises(gaps.NextStepError):
        gaps.check(_gap("claim:x", audit), FRAME, claims)
    for ref in ("condition:adm_in_use", "requirement:data_minimised", "role:ThirdParty", "reading:root-category"):
        gaps.check(_gap(ref, audit), FRAME)
    # and no condition's step is ever an audit request where its reach is complete
    for cid, c in FRAME.conditions.items():
        step = gaps.condition_step(f"condition:{cid}", c.observability, c.text)
        gaps.check(_gap(f"condition:{cid}", step), FRAME)
        assert (step["kind"] == "audit_request") == (c.observability["reach"] == "none")


# -- a case under an E3 condition, with and without the provider's own evidence ---------------------------------------


def _assessed(tmp_path, documents):
    o = o_report([claim("c1", NAME, "adco", "AdSDK")])
    d = documented([], documents=documents)
    return assess(workspace(tmp_path, [o], d).root, write=False)


def test_an_e3_condition_without_the_providers_evidence_is_an_audit_request_and_with_it_none(tmp_path):
    (tmp_path / "without").mkdir()
    (tmp_path / "with").mkdir()
    without = _assessed(tmp_path / "without", [{"meta": {"name": "policy"}}])
    with_ = _assessed(tmp_path / "with", [{"meta": {"name": "policy"}, "automatedDecisionMaking": {"inUse": True}}])
    # without: whether automated decision-making is in use is the controller's record; an audit request, record
    (g,) = [g for g in without["gaps"] if {b["ref"] for b in g["bears_on"]} == {"condition:adm_in_use"}]
    assert g["reason"] == "applicability_unknown" and (g["next"]["kind"], g["next"]["held"]) == (
        "audit_request",
        "record",
    )
    row = next(r for r in without["qualification"]["collection"]["rows"] if r["subject"] == "automated_decision_making")
    assert any(s["kind"] == "audit_request" and s["held"] == "record" for s in without["qualification"]["next_steps"])
    assert row["result"] == "insufficient_or_conflicting_evidence"
    assert "not externally assessable" in json.dumps(row["secondary"]).lower()
    # with the provider's own declaration the condition holds: no gap, the requirement applies
    assert not [g for g in with_["gaps"] if any(b["ref"] == "condition:adm_in_use" for b in g["bears_on"])]
    status = next(
        t for t in with_["subjects"]["collection"]["transparency"] if t["requirement"] == "automated_decision_making"
    )
    assert status["applicability"] == "applies" and "adm_in_use" not in status.get("conditions", [])
    # every gap of both bears on a proposition, has a next step, and carries no level
    for report in (without, with_):
        for g in report["gaps"]:
            assert g["bears_on"] and g["next"]["kind"] in gaps.KINDS and "observability" not in g
            gaps.check(g, FRAME)
        assert not [c for c in report["concerns"] if "observability" in c]


def test_only_the_frames_applicability_conditions_have_gaps(tmp_path):
    report = _assessed(tmp_path, [{"meta": {"name": "policy"}}])
    for g in report["gaps"]:
        if g["reason"] == "applicability_unknown":
            ((ref,),) = [[b["ref"] for b in g["bears_on"]]]
            assert ref.startswith("condition:") and ref.removeprefix("condition:") in FRAME.conditions


# -- the run's scope (D3) ---------------------------------------------------------------------------------------------


def scoped(egress="DE", store="DE", locale="de-DE", age=None, consent=None):
    context = {"egress": {"country": egress} if egress else "?"}
    if store:
        context["store"] = {"countries": [store], "country": store}
    if locale:
        context["locale"] = {"locale": locale}
    if age is not None:
        context["persona_age"] = {"years": age, "on": "2026-11-21"}
    report = o_report([claim("c1", NAME, "adco", "AdSDK")])
    report["scopes"][0]["context"] = context
    if consent is not None:
        report["scopes"][0]["consent"] = consent
    return report


def test_a_jurisdiction_is_settled_only_where_egress_store_and_locale_agree():
    agree = run_scope.of_reports([scoped()])
    assert agree.country == "DE"
    eu, ca = {"kind": "jurisdiction", "value": "EU"}, {"kind": "jurisdiction", "value": "California"}
    assert run_scope.applies(eu, agree) is True and run_scope.applies(ca, agree) is False
    assert run_scope.applies({"kind": "jurisdiction", "value": "US"}, agree) is False
    for disagreeing in (scoped(store="US"), scoped(locale="en-US"), scoped(egress="US")):
        s = run_scope.of_reports([disagreeing])
        assert s.country is None and run_scope.applies(eu, s) is None and run_scope.applies(ca, s) is None
    # an indicator not recorded (an O report made before Verðandi 3.7.0) settles nothing
    assert run_scope.of_reports([scoped(store=None, locale=None)]).country is None
    # two runs that place the user apart settle nothing
    assert run_scope.of_reports([scoped(), scoped(egress="FR", store="FR", locale="fr-FR")]).country is None


def test_a_user_group_is_settled_by_the_personas_age():
    adult, child = run_scope.of_reports([scoped(age=30)]), run_scope.of_reports([scoped(age=10)])
    under13 = {"kind": "user_group", "value": "children under 13"}
    assert run_scope.applies(under13, adult) is False and run_scope.applies(under13, child) is True
    assert run_scope.applies({"kind": "user_group", "value": "anyone under the age of 16"}, adult) is False
    assert run_scope.applies({"kind": "user_group", "value": "minors"}, adult) is False
    assert run_scope.applies(under13, run_scope.of_reports([scoped()])) is None  # no age recorded


def test_a_product_and_prior_consent_are_settled_by_what_was_observed():
    s = run_scope.of_reports([scoped()])
    assert run_scope.applies({"kind": "product", "value": "website"}, s) is False
    assert run_scope.applies({"kind": "product", "value": "our mobile app"}, s) is True
    assert run_scope.applies({"kind": "product", "value": "Forums"}, s) is None
    none = [{"time": "t", "state": {"IABTCF_gdprApplies": "1"}, "readable": True}]
    given = [{"time": "t", "state": {"IABTCF_TCString": "CQ..."}, "readable": True}]
    consent = {"type": "choice", "text": "unless you consent"}
    assert run_scope.condition_held(consent, run_scope.of_reports([scoped(consent=none)])) is True
    assert run_scope.condition_held(consent, run_scope.of_reports([scoped(consent=given)])) is None
    unreadable = [{"time": "t", "state": {}}]  # not marked readable: settles nothing
    assert run_scope.condition_held(consent, run_scope.of_reports([scoped(consent=unreadable)])) is None
    assert run_scope.condition_held({"type": "user_action", "text": "when you sign up"}, s) is None


def _relations(tmp_path, report, **qualifiers):
    denial = d_claim("declares_collection", NAME, "-", **qualifiers)
    a = workspace(tmp_path, [report], d_report([denial]))
    built = assessment.build(a, REGISTRY)
    settled = []
    scope = run_scope.of_reports([r.load() for r in a.observations])
    rel = correspondence.relate(built, a.declaration.load(), [], REGISTRY, DATA, TYPES, scope, settled)
    return [r for r in rel if r.outcome == "contradicts"], settled


def test_the_run_scope_settles_a_denials_jurisdiction_where_its_indicators_agree(tmp_path):
    eu = {"applicability": [{"kind": "jurisdiction", "value": "EU"}]}
    for name, report, condition in (
        ("agree", scoped(), None),
        ("disagree", scoped(store="US"), "the denial applies to the observation (jurisdiction EU)"),
    ):
        (tmp_path / name).mkdir()
        (r,), settled = _relations(tmp_path / name, report, **eu)
        assert r.condition == condition
        assert bool(settled) == (condition is None)
        if condition:
            assert [p["ref"] for p in r.parts] == ["scope:jurisdiction"]
    # a denial limited to California does not apply to a user placed in Germany: no contradiction
    (tmp_path / "ca").mkdir()
    found, settled = _relations(tmp_path / "ca", scoped(), applicability=[{"kind": "jurisdiction", "value": "US-CA"}])
    assert found == [] and settled[0]["outcome"] == "fails"


def test_the_run_scope_settles_a_denials_user_group_by_the_personas_age(tmp_path):
    children = {"applicability": [{"kind": "user_group", "value": "children under 13"}]}
    (tmp_path / "adult").mkdir()
    (tmp_path / "unknown").mkdir()
    found, _ = _relations(tmp_path / "adult", scoped(age=34), **children)
    assert found == []
    (r,), _ = _relations(tmp_path / "unknown", scoped(), **children)
    assert r.condition and [p["ref"] for p in r.parts] == ["scope:user_group"]


def test_a_settled_condition_leaves_the_case_and_an_unsettled_one_names_its_proposition(tmp_path):
    eu = [{"kind": "jurisdiction", "value": "EU"}]
    for name, report in (("agree", scoped()), ("disagree", scoped(store="US"))):
        (tmp_path / name).mkdir()
        denial = d_claim("declares_collection", NAME, "-", applicability=eu)
        a = workspace(tmp_path / name, [report], d_report([denial]))
        out = assess(a.root, write=False)
        opened = [o for o in out["open"] if "jurisdiction" in o["text"]]
        contradiction = next(r for r in out["relations"] if r["outcome"] == "contradicts")
        if name == "agree":  # no open condition, no gap, an unconditional contradiction
            assert not opened and "condition" not in contradiction
            assert not [b for g in out["gaps"] for b in g["bears_on"] if b["ref"].startswith("scope:")]
        else:
            (o,) = opened
            assert o["bears_on"] == [{"proposition": o["bears_on"][0]["proposition"], "ref": "scope:jurisdiction"}]
            # its step: a run whose indicators agree (its reach is partial), never an audit request
            steps = [s for s in out["qualification"]["next_steps"] if o["id"] in s["from"]]
            assert [s["kind"] for s in steps] == ["explore"]


# -- where a purpose is achieved --------------------------------------------------------------------------------------


def test_a_combined_purpose_says_where_it_is_achieved_only_where_its_members_agree():
    def member(n, where):
        return {
            "id": f"m{n}",
            "type": "purpose",
            "channels": ["r"],
            "subject": "P-1",
            "purpose": {"node": "Advertising", **({"achieved_on": where} if where else {})},
            "status": "supported",
            "supporting": [],
            "challenging": [],
            "uncertainty": {"level": "low", "reasons": []},
            "sufficiency": {"sufficient": True},
            "strength": "doc",
        }

    agreed = combine.combined("c", [member(1, "server"), member(2, "server"), member(3, None)])
    apart = combine.combined("c", [member(1, "server"), member(2, "device")])
    assert agreed["purpose"]["achieved_on"] == "server" and "achieved_on" not in apart["purpose"]


def test_where_a_purpose_is_achieved_comes_from_its_case_else_from_stage_1():
    purposes = vocabulary(PURPOSES)
    hypothesis = {
        "id": "claim:P-1:1",
        "type": "purpose",
        "subject": "P-1",
        "purpose": {"node": "ServiceProvision", "beneficiary": "user", "achieved_on": "server"},
    }
    premise = {"subject": "P-1", "purpose": {"id": "P-W1", "node": "ServiceProvision", "beneficiary": "user"}}
    assert assess_._achieved_on(premise, [hypothesis], purposes) == "server"
    stated = {**premise, "purpose": {**premise["purpose"], "achieved_on": "device"}}
    assert assess_._achieved_on(stated, [hypothesis], purposes) == "device"  # the case's statement wins
    assert assess_._achieved_on(premise, [], purposes) is None


def test_a_case_purpose_may_state_where_it_is_achieved(tmp_path):
    assert inputs._achieved_on("SERVER", "x") == "server" and inputs._achieved_on(None, "x") is None
    with pytest.raises(inputs.InputError):
        inputs._achieved_on("cloud", "x")
    from skuld import rules
    from skuld.inputs import Purpose

    p = Purpose("p", {}, "n", "?", "technical", "sufficient", "ancillary", (), None, achieved_on="server")
    assert rules.precondition(p, True) == (
        "not_assessable",
        "the purpose has no observable oracle (it is achieved on servers)",
        "oracle_not_observable",
    )


# -- old O reports -----------------------------------------------------------------------------------------------------


def test_an_o_report_made_before_ratatoskr_0_39_is_read_in_the_new_shape():
    old = {
        "report": {"claims": {"observability": "E1"}},
        "claims": [{"id": "c1", "observability": "E1"}],
        "gaps": [
            {
                "id": "g1",
                "concerns": {"claim": "c1"},
                "missing": "the category",
                "required": "r",
                "reason": "unread",
                "observability": "E1",
                "next_step": "hook the network calls",
            },
            {
                "id": "g2",
                "concerns": {"claim_type": "accesses", "node": "x"},
                "missing": "m",
                "required": "r",
                "reason": "x",
            },
        ],
    }
    new = observe.levelled(old)
    assert "observability" not in json.dumps(new) and "next_step" not in json.dumps(new)
    assert new["gaps"][0]["next"] == {"kind": "improve_instrument", "text": "hook the network calls"}
    assert new["gaps"][0]["bears_on"] == [{"proposition": "the category", "ref": "claim:c1"}]
    assert new["gaps"][1]["next"]["kind"] == "explore" and new["gaps"][1]["bears_on"][0]["ref"] == "cell:accesses/x"
    assert observe.levelled(new) == new


def test_the_pinned_schema_refuses_a_level_on_a_concern_or_a_gap():
    schema = load_schema("expectation_assessment")
    assert schema["properties"]["gaps"]["items"]["properties"]["observability"] is False
    assert schema["properties"]["concerns"]["items"]["properties"]["observability"] is False
    assert "improve_instrument" in load_schema("claim")["$defs"]["nextStepKind"]["enum"]
    validate  # noqa: B018 - the assessments above validate in assess.build
