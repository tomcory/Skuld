"""E's combination: one rule for every channel and model question (corroboration, decision by strength and value,
conflict, the reason of a claim that cannot assess), and the claims a purpose's claims rest on."""

from skuld import combine


def claim(cid, status, strength=None, supporting=(), challenging=(), s="low", value="essential"):
    c = {
        "id": cid,
        "type": "dependency",
        "channels": [cid],
        "subject": "P",
        "purpose": {"node": "ServiceProvision", "beneficiary": "user"},
        "component": "P.data",
        "relationship": value,
        "status": status,
        "supporting": list(supporting),
        "challenging": list(challenging),
        "uncertainty": {"t": "low", "s": s, "n": "not_applicable"},
        "sufficiency": {"sufficient": status in ("supported", "refuted")},
    }
    if strength:
        c["strength"] = strength
    return c


def test_agreeing_claims_are_corroborated_at_the_lowest_uncertainty():
    c = combine.combined(
        "C", [claim("a", "supported", "doc", ["x"], s="high"), claim("b", "supported", "doc", ["y"], s="moderate")]
    )
    assert c["status"] == "supported" and c["of"] == ["a", "b"] and c["supporting"] == ["x", "y"]
    assert c["uncertainty"]["s"] == "moderate"


def test_the_strongest_claim_decides_a_disagreement_and_its_value():
    c = combine.combined(
        "C", [claim("rs", "supported", "doc", ["x"]), claim("ex", "refuted", "run", challenging=["k"])]
    )
    assert (c["status"], c["strength"], c["challenging"], c["supporting"]) == ("refuted", "run", ["k"], [])
    shown = claim("ex", "supported", "run", ["k"], value="not_dependent")
    c = combine.combined("C", [claim("rs", "supported", "doc", ["x"]), shown])
    assert (c["status"], c["relationship"]) == ("supported", "not_dependent")


def test_a_combined_claim_records_the_members_it_overruled():
    model = {**claim("rs", "supported", "doc", ["x"]), "stage": "assessment"}
    c = combine.combined("C", [model, claim("ex", "refuted", "run", challenging=["k"]), claim("ex2", "refuted", "run")])
    assert c["overruled"] == [
        {"claim": "rs", "channels": ["rs"], "stage": "assessment", "status": "supported", "strength": "doc"}
    ]
    # a disagreement in value is overruled too; members that agree, or cannot decide, are not
    shown = claim("ex", "supported", "run", ["k"], value="not_dependent")
    c = combine.combined("C", [claim("rs", "supported", "doc", ["x"]), shown, claim("na", "not_assessable")])
    assert [m["claim"] for m in c["overruled"]] == ["rs"]
    agreeing = combine.combined("C", [claim("rs", "supported", "doc", ["x"]), claim("ex", "supported", "run", ["k"])])
    assert "overruled" not in agreeing


def test_equally_strong_claims_that_disagree_in_status_or_value_are_conflicted():
    c = combine.combined("C", [claim("a", "supported", "doc", ["x"]), claim("b", "refuted", "doc", challenging=["y"])])
    assert c["status"] == "conflicted" and c["supporting"] == ["x"] and c["challenging"] == ["y"]
    other = claim("b", "supported", "doc", ["y"], value="quality_dependent")
    assert combine.combined("C", [claim("a", "supported", "doc", ["x"]), other])["status"] == "conflicted"


def test_a_claim_without_a_decisive_status_does_not_outweigh_one_with_it():
    c = combine.combined("C", [claim("ex", "not_assessable"), claim("rs", "supported", "doc", ["x"])])
    assert c["status"] == "supported" and c["sufficiency"] == {"sufficient": True}


def test_a_claim_that_could_not_be_assessed_abstains_where_none_decides():
    cannot = {
        **claim("ex", "not_assessable"),
        "reason": "the purpose is too vague",
        "sufficiency": {"sufficient": False, "reason": "purpose_vague"},
    }
    judged = {
        **claim("rs", "not_established", s="high"),
        "reason": "a step does not cite the context",
        "sufficiency": {"sufficient": False, "reason": "own_knowledge"},
    }
    # one sample with a vague purpose does not outweigh one that judged the dependency (author, 13 Nov 2026)
    c = combine.combined("C", [cannot, cannot, judged])
    assert (c["status"], c["reason"], c["sufficiency"]["reason"]) == (
        "not_established",
        "a step does not cite the context",
        "own_knowledge",
    )
    # only where every claim could not be assessed is the combination not assessable, with the reason
    alone = combine.combined("C", [cannot, {**cannot, "id": "ex2"}])
    assert (alone["status"], alone["reason"], alone["sufficiency"]["reason"]) == (
        "not_assessable",
        "the purpose is too vague",
        "purpose_vague",
    )
    assert (
        combine.combined("C", [claim("a", "not_established"), claim("b", "not_established")])["status"]
        == "not_established"
    )


def test_a_beneficiary_is_the_user_the_provider_or_another_party():
    assert [combine.beneficiary(x) for x in ("user", "PROVIDER", "the app provider", "the user's coach", None)] == [
        "user",
        "provider",
        "provider",
        "user",
        "other",
    ]


def _alternative(sample: str, status: str) -> dict:
    return {
        "id": f"{sample}:a0",
        "type": "alternative",
        "stage": "assessment",
        "tier": "reasoning",
        "channels": [f"reasoning:{sample}"],
        "subject": "P-1",
        "component": "P-1.data",
        "alternative": "an app-generated installation ID",
        "level": "technically_supported" if status == "supported" else "plausible",
        "purpose": {"node": "Advertising"},
        "basis": ["claim:P-1:1"],
        "status": status,
        "supporting": ["item:1"] if status == "supported" else [],
        "challenging": [],
        "strength": "doc",
        "uncertainty": {"t": "not_applicable", "s": "moderate", "n": "moderate"},
        "sufficiency": {"sufficient": status == "supported"},
    }


def test_gate_d_a_documented_alternative_needs_a_majority_of_its_questions_samples():
    from skuld import combine

    asked = {"P-1": {"m/P-1/s1", "m/P-1/s2", "m/P-1/s3"}}
    one = [_alternative("m/P-1/s1", "supported"), _alternative("m/P-1/s2", "not_established")]
    held = combine.alternatives(one, combine.Numbers(), asked)[0]
    assert (held["status"], held["level"], held["supporting"]) == ("not_established", "plausible", [])
    assert held["reason"].startswith("gate (d)") and "(1 of 3)" in held["reason"] and "strength" not in held
    two = one + [_alternative("m/P-1/s3", "supported")]
    assert combine.alternatives(two, combine.Numbers(), asked)[0]["status"] == "supported"
    # reading 1 has no gate (d): one sample decides
    assert combine.alternatives(one, combine.Numbers())[0]["status"] == "supported"
