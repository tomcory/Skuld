from types import SimpleNamespace

from ratatoskr.vocabularies import Vocabulary

from skuld import relations

DATA = Vocabulary.load("asgard-data")
PURPOSES = Vocabulary.load("dpv-purposes")


def claim(cid, type_, status, strength=None, **fields):
    out = {"id": cid, "type": type_, "status": status, **fields}
    if strength:
        out["strength"] = strength
    return out


def outcome(claims, aspect="data"):
    found, best = relations.outcome(aspect, claims)
    return found, (best or {}).get("id")


def test_a_dependency_is_decided_by_the_value_of_the_strongest_claim():
    essential = claim("d1", "dependency", "supported", "doc", relationship="essential")
    independent = claim("d2", "dependency", "supported", "run", relationship="not_dependent")
    assert outcome([essential]) == ("functional_dependency_supported", "d1")
    assert outcome([essential], "recipient")[0] == "recipient_dependency_supported"
    # a run that preserves the purpose without the component decides over documents
    assert outcome([essential, independent]) == ("no_functional_dependency_established", "d2")
    assert outcome([essential, {**independent, "strength": "doc"}])[0] == "conflicting"
    # a run that preserves the purpose with some measurement worse refutes essential
    refuted = claim("d4", "dependency", "refuted", "run", relationship="essential")
    assert outcome([essential, refuted]) == ("no_functional_dependency_established", "d4")
    assert outcome([refuted], "recipient") == ("recipient_dependency_not_established", "d4")
    proposed = claim("d5", "dependency", "not_established", "own", relationship="essential")
    assert outcome([proposed]) == ("no_functional_dependency_established", None)


def test_a_substitutable_dependency_is_a_dependency_on_a_datum_of_its_kind():
    """A run's substitutable is no not_dependent (the purpose needed a datum of the kind) and decides over documents
    by its strength (Ratatoskr 0.37.0, 21 Nov 2026)."""
    essential = claim("d1", "dependency", "supported", "doc", relationship="essential")
    substitutable = claim("d2", "dependency", "supported", "run", relationship="substitutable")
    assert outcome([substitutable]) == ("functional_dependency_supported", "d2")
    assert outcome([essential, substitutable]) == ("functional_dependency_supported", "d2")
    assert outcome([essential, {**substitutable, "strength": "doc"}])[0] == "conflicting"


def test_minimisation_takes_the_deciding_claims_level_and_strength():
    described = claim("a1", "alternative", "supported", "doc", level="technically_supported")
    shown = claim("a2", "alternative", "supported", "run", level="demonstrated")
    assert outcome([described, shown]) == ("alternative_demonstrated", "a2")
    assert outcome([described]) == ("alternative_technically_supported", "a1")
    # a plausible alternative, or one an experiment refutes, has no outcome of its own
    plausible = claim("a3", "alternative", "not_established", level="plausible")
    failed = claim("a4", "alternative", "refuted", "run", level="demonstrated")
    assert outcome([plausible, failed])[0] == "insufficient_evidence"
    assert outcome([{**shown, "status": "conflicted"}])[0] == "conflicting"
    assert outcome([claim("a5", "alternative", "not_assessable", reason="no oracle")])[0] == "not_assessable"


def practice(pid, data="location.coordinates"):
    return SimpleNamespace(id=pid, data=data, claims=[{"dimension": "O", "report": "0" * 64, "claim": f"c-{pid}"}])


def purpose(hid, subject, status="supported", node="ServiceProvision"):
    return {"id": hid, "type": "purpose", "subject": subject, "status": status, "purpose": {"node": node}}


def test_every_practice_e_formed_an_expectation_of_is_related():
    subjects = SimpleNamespace(practices=[practice("P1"), practice("P2"), practice("P3")])
    hypotheses = [
        purpose("claim:P1:1", "P1"),
        claim(
            "claim:P1:2",
            "dependency",
            "supported",
            "doc",
            subject="P1",
            relationship="essential",
            basis=["claim:P1:1"],
            component="P1.data",
        ),
        purpose("claim:P2:1", "P2", "not_established"),
        purpose("claim:P3:1", "P3"),
    ]
    alone = claim(
        "claim:P3:2",
        "alternative",
        "supported",
        "run",
        level="demonstrated",
        subject="P3",
        basis=[],
        of=["ex:forecast:1"],
        case="forecast",
        component="P3.data",
        purpose={"id": "P-F1"},
    )
    out = {(r.subject, tuple(t["claim"] for t in r.to)): r for r in relations.o_e(subjects, hypotheses, [], [alone])}
    assert out[("P1", ("claim:P1:2",))].outcome == "functional_dependency_supported"
    assert out[("P2", ("claim:P2:1",))].outcome == "insufficient_evidence"
    assert out[("P3", ("claim:P3:1",))].reason == "no claim of dependency or alternative names the purpose"
    # reasoning is silent on the case's purpose: the experiment is related for it
    assert out[("P3", ("claim:P3:2",))].outcome == "alternative_demonstrated"
    assert all(t["dimension"] == "E" for r in out.values() for t in r.to)


def declared(did, value, data="location"):
    return SimpleNamespace(
        id=did,
        type="declares_purpose",
        polarity="+",
        value=value,
        data=data,
        claim={"dimension": "D", "report": "1" * 64, "claim": f"/claims/{did}"},
    )


def test_a_declared_purpose_is_supported_by_the_purposes_e_infers_for_the_practices_of_its_data():
    subjects = SimpleNamespace(
        comparability={"comparable": True},
        practices=[practice("P1", "location.coordinates"), practice("P2", "location.city"), practice("P3", "data")],
        declarations=[
            declared("D1", "ServiceProvision"),
            declared("D2", "Advertising"),
            declared("D3", "ServiceProvision", "personal-info.email-address"),
            declared("D4", "NoSuchPurpose"),
            declared("D5", "ServiceProvision"),
        ],
    )
    hypotheses = [
        purpose("claim:P1:1", "P1", node="RequestedServiceProvision"),
        purpose("claim:P2:1", "P2", node="Advertising"),
        purpose("claim:P3:1", "P3", node="Advertising"),
    ]
    out = {r.subject: r for r in relations.d_e(subjects, hypotheses, {"D5": "concern:D-5:1"}, DATA, PURPOSES)}
    # P3's data is above the declared data: no practice of it
    assert (out["D1"].outcome, [t["claim"] for t in out["D1"].to]) == (
        "justification_partially_supported",
        ["claim:P1:1"],
    )
    assert out["D1"].reason == "1 of 2 practices of its data have a supported purpose it covers"
    assert out["D2"].outcome == "justification_partially_supported"
    assert out["D3"].outcome == "not_assessable"
    assert out["D4"].outcome == "not_comparable"
    assert (out["D5"].outcome, out["D5"].to) == ("purpose_too_vague", [{"dimension": "E", "claim": "concern:D-5:1"}])
    assert relations.d_e(subjects, [], {}, DATA, PURPOSES) == []
    subjects.comparability = {"comparable": False}
    assert {r.outcome for r in relations.d_e(subjects, hypotheses, {}, DATA, PURPOSES)} == {"not_comparable"}
