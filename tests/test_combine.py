"""E's combination: one rule for every channel and model question (corroboration, decision by strength and value,
conflict, the reason of a claim that cannot assess), and the claims a purpose's claims rest on."""

from skuld import combine
from skuld.uncertainty import of


def claim(cid, status, strength=None, supporting=(), challenging=(), u=None, value="essential"):
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
        "uncertainty": u or of(),
        "sufficiency": {"sufficient": status in ("supported", "refuted")},
    }
    if strength:
        c["strength"] = strength
    return c


def test_agreeing_claims_are_corroborated_at_the_lowest_uncertainty():
    c = combine.combined(
        "C",
        [
            claim("a", "supported", "doc", ["x"], u=of("own_knowledge", "few_runs")),
            claim("b", "supported", "doc", ["y"], u=of("from_documents")),
        ],
    )
    assert c["status"] == "supported" and c["of"] == ["a", "b"] and c["supporting"] == ["x", "y"]
    # either: the least uncertain alternative, with its own reasons only
    assert c["uncertainty"] == {"level": "moderate", "reasons": [{"reason": "from_documents", "level": "moderate"}]}


def test_a_conflicted_claim_needs_every_members_uncertainty():
    c = combine.combined(
        "C",
        [
            claim("a", "supported", "doc", ["x"], u=of("from_documents")),
            claim("b", "refuted", "doc", challenging=["y"], u=of("samples_disagree")),
        ],
    )
    assert c["status"] == "conflicted"
    assert c["uncertainty"] == of("samples_disagree", "from_documents")
    assert c["uncertainty"]["level"] == "high" and [r["reason"] for r in c["uncertainty"]["reasons"]] == [
        "samples_disagree",
        "from_documents",
    ]


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


def test_a_runs_substitutable_overrules_a_documented_essential_and_names_its_substitute():
    shown = {
        **claim("ex", "supported", "run", ["k"], value="substitutable"),
        "reason": "the application fell back to the substitute device-or-other-ids.app-set-id",
    }
    c = combine.combined("C", [claim("rs", "supported", "doc", ["x"]), shown])
    assert (c["status"], c["relationship"], c["strength"]) == ("supported", "substitutable", "run")
    assert [m["claim"] for m in c["overruled"]] == ["rs"]
    assert "app-set-id" in c["reason"]
    # a decisive claim of another value keeps no reason of its own, as before
    assert "reason" not in combine.combined("C", [{**claim("rs", "supported", "doc", ["x"]), "reason": "r"}])


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
        **claim("rs", "not_established", u=of("own_knowledge")),
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
        "uncertainty": of("from_documents"),
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


def test_gate_d_an_alternative_it_demotes_takes_the_uncertainty_of_the_members_not_established():
    asked = {"P-1": {"m/P-1/s1", "m/P-1/s2", "m/P-1/s3"}}
    supported, held = _alternative("m/P-1/s1", "supported"), _alternative("m/P-1/s2", "not_established")
    supported["uncertainty"] = of()
    held["uncertainty"] = of("own_knowledge")
    claim = combine.alternatives([supported, held], combine.Numbers(), asked)[0]
    assert claim["status"] == "not_established" and claim["uncertainty"] == {
        "level": "high",
        "reasons": [{"reason": "own_knowledge", "level": "high"}],
    }
    # with no member not established, needs over all of them, never the supporting members' either
    other = {**supported, "id": "m/P-1/s2:a0", "uncertainty": of("from_documents")}
    asked = {"P-1": {"m/P-1/s1", "m/P-1/s2", "m/P-1/s3", "m/P-1/s4", "m/P-1/s5"}}
    claim = combine.alternatives([supported, other], combine.Numbers(), asked)[0]
    assert claim["status"] == "not_established" and claim["uncertainty"] == {
        "level": "moderate",
        "reasons": [{"reason": "from_documents", "level": "moderate"}],
    }


def test_gate_d_counts_the_samples_that_propose_the_same_change_from_reading_5():
    """P10 fix 2: two samples supporting different changes of one component are no majority of three; two supporting
    the same change are. Claims of an earlier reading name no change and combine per component as before."""
    from skuld import combine

    asked = {"P-1": {"m/P-1/s1", "m/P-1/s2", "m/P-1/s3"}}

    def keyed(sample, status, key):
        return {**_alternative(sample, status), "change_key": key}

    different = [
        keyed("m/P-1/s1", "supported", "replace:device-or-other-ids.installation-id"),
        keyed("m/P-1/s2", "supported", "remove"),
        keyed("m/P-1/s3", "not_established", "other"),
    ]
    out = combine.alternatives(different, combine.Numbers(), asked)
    assert [c["change_key"] for c in out] == ["replace:device-or-other-ids.installation-id", "remove", "other"]
    assert all(c["status"] == "not_established" for c in out)
    assert all("(1 of 3)" in c["reason"] for c in out[:2])
    same = [
        keyed("m/P-1/s1", "supported", "remove"),
        keyed("m/P-1/s2", "supported", "remove"),
        keyed("m/P-1/s3", "not_established", "other"),
    ]
    out = combine.alternatives(same, combine.Numbers(), asked)
    assert [(c["change_key"], c["status"], len(c["of"])) for c in out] == [
        ("remove", "supported", 2),
        ("other", "not_established", 1),
    ]
    # without change keys (reading 4), the two supporting samples agree per component, as before
    unkeyed = [{k: v for k, v in c.items() if k != "change_key"} for c in different]
    (one,) = combine.alternatives(unkeyed, combine.Numbers(), asked)
    assert one["status"] == "supported" and "change_key" not in one
