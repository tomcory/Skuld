"""E's combination: one rule for every channel and model question (corroboration, decision by strength and value,
conflict, the reason of a claim that cannot assess), and the claims a purpose's claims rest on."""

from skuld import combine


def claim(cid, status, strength=None, supporting=(), challenging=(), s="low"):
    c = {
        "id": cid,
        "type": "alternative",
        "channels": [cid],
        "subject": "P",
        "purpose": {"node": "ServiceProvision", "beneficiary": "user"},
        "component": "P.data",
        "alternative": "an app-generated identifier",
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


def test_the_strongest_claim_decides_a_disagreement():
    c = combine.combined(
        "C", [claim("rs", "supported", "doc", ["x"]), claim("ex", "refuted", "run", challenging=["k"])]
    )
    assert (c["status"], c["strength"], c["challenging"], c["supporting"]) == ("refuted", "run", ["k"], [])


def test_equally_strong_claims_that_disagree_are_conflicted():
    c = combine.combined("C", [claim("a", "supported", "doc", ["x"]), claim("b", "refuted", "doc", challenging=["y"])])
    assert c["status"] == "conflicted" and c["supporting"] == ["x"] and c["challenging"] == ["y"]


def test_a_claim_without_a_decisive_status_does_not_outweigh_one_with_it():
    c = combine.combined("C", [claim("ex", "not_assessable"), claim("rs", "supported", "doc", ["x"])])
    assert c["status"] == "supported" and c["sufficiency"] == {"sufficient": True}


def test_where_no_channel_can_decide_the_reason_of_one_that_cannot_assess_is_kept():
    cannot = {
        **claim("ex", "not_assessable"),
        "reason": "no oracle",
        "sufficiency": {"sufficient": False, "reason": "oracle_not_observable"},
    }
    c = combine.combined("C", [cannot, claim("rs", "not_established", s="high")])
    assert (c["status"], c["reason"], c["sufficiency"]["reason"]) == (
        "not_assessable",
        "no oracle",
        "oracle_not_observable",
    )
    assert (
        combine.combined("C", [claim("a", "not_established"), claim("b", "not_established")])["status"]
        == "not_established"
    )


def test_a_claim_on_a_purpose_takes_the_purposes_semantic_uncertainty_where_higher():
    purpose = {"uncertainty": {"t": "not_applicable", "s": "high", "n": "not_applicable"}}
    assert combine.on_purpose(claim("a", "supported", "doc", s="moderate"), purpose)["uncertainty"]["s"] == "high"


def test_a_beneficiary_is_the_user_the_provider_or_another_party():
    assert [combine.beneficiary(x) for x in ("user", "PROVIDER", "the app provider", "the user's coach", None)] == [
        "user",
        "provider",
        "provider",
        "user",
        "other",
    ]
