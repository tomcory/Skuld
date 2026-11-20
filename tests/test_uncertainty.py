"""E's uncertainty (skuld.uncertainty, Ratatoskr 0.34.0): one level with the reasons that set it, by E's rules."""

from types import SimpleNamespace

from ratatoskr.frames import Frame

from skuld import concerns, correspondence, uncertainty
from skuld.assessment import declared_uncertainty
from skuld.comparison import Comparison
from skuld.correspondence import DECLARED_ONLY, EXACTLY, OBSERVED_ONLY, Relation
from skuld.uncertainty import of

FRAME = Frame.load("gdpr-art5")


def reasons(u: dict) -> list[str]:
    return [r["reason"] for r in u["reasons"]]


def comparison(baseline=3, alternative=3, unverifiable=(), alternating=True) -> Comparison:
    return Comparison(
        "k",
        "c",
        "P1",
        "A1",
        [f"b{i}" for i in range(baseline)],
        [f"a{i}" for i in range(alternative)],
        "preserves",
        unverifiable=list(unverifiable),
        alternating=alternating,
    )


def test_a_comparisons_uncertainty_names_every_reason_its_technique_is_raised():
    assert comparison().technical() == {"level": "low", "reasons": []}
    u = comparison(alternative=2, unverifiable=["android-id"], alternating=False).technical()
    assert u["level"] == "moderate"
    assert reasons(u) == ["few_runs", "runs_not_alternated", "unverifiable"]


def test_a_d_claim_is_read_leniently_and_an_old_one_as_low():
    claim = {"uncertainty": of("model_decision", "mapping_fit")}
    assert declared_uncertainty(claim) == {
        "level": "moderate",
        "reasons": [{"reason": "mapping_fit", "level": "moderate"}, {"reason": "model_decision", "level": "moderate"}],
    }
    assert declared_uncertainty({"uncertainty": {"f": "low", "t": "low", "s": "high", "n": "low"}}) == of()
    assert declared_uncertainty({}) == of()


def test_a_relation_reads_os_silence_and_ds_silence_on_a_channel_not_exhaustive():
    practice = SimpleNamespace(id="P-1", uncertainty=of("actor_inferred"))
    declaration = SimpleNamespace(
        id="D-1", claim={"claim": "policy:/x"}, uncertainty=of(("model_decision", "moderate"))
    )
    subjects = SimpleNamespace(practices=[practice], declarations=[declaration])
    declared_only = Relation("r1", "O-D", "rule", DECLARED_ONLY, {}, subject="D-1", aspect="data")
    observed_only = Relation(
        "r2", "O-D", "rule", OBSERVED_ONLY, {}, subject="P-1", aspect="recipient", silence=["D: policy"]
    )
    exact = Relation("r3", "O-D", "rule", EXACTLY, {}, to=[{"claim": "policy:/x"}], subject="P-1", aspect="data")
    correspondence._uncertainty([declared_only, observed_only, exact], subjects)
    assert declared_only.uncertainty == of(("model_decision", "moderate"), "o_silence")
    assert observed_only.uncertainty == of("actor_inferred", "silence_not_exhaustive")
    assert exact.uncertainty == of("actor_inferred", ("model_decision", "moderate"))


def purpose(u: dict) -> dict:
    return {
        "id": "claim:P-1:1",
        "type": "purpose",
        "subject": "P-1",
        "status": "supported",
        "purpose": {"node": "Advertising"},
        "uncertainty": u,
    }


def test_concern_iv_by_rule_rests_on_a_silence_and_by_reasoning_on_its_judgements():
    h = purpose(of("own_knowledge"))
    unspecified = SimpleNamespace(purpose=h, practice="P-1", relevant=[], covering=[], question=None)
    [rule], _ = concerns.purpose_limitation(FRAME, [unspecified], [], lambda s, p: [], {})
    assert rule.tier == "rule"
    assert rule.uncertainty == of("own_knowledge", "silence_not_exhaustive")

    specified = SimpleNamespace(node="ServiceProvision", declarations=["D-1"])
    judged = SimpleNamespace(purpose=h, practice="P-1", relevant=[specified], covering=[], question="q1")
    judgements = [
        {
            "sample": f"c/P-1/q1/s{i}",
            "specified": "Q1",
            "status": status,
            "strength": "doc",
            "parts": [],
            "channels": [],
        }
        for i, status in enumerate(("supported", "not_established"))
    ]
    for j in judgements:
        j["judgement"] = "not_compatible" if j["status"] == "supported" else "compatible"
    declared = {"D-1": of(("model_decision", "moderate"))}
    [reasoned], _ = concerns.purpose_limitation(FRAME, [judged], judgements, lambda s, p: [], {}, declared)
    assert reasoned.tier == "reasoning"
    assert reasoned.uncertainty["level"] == "high"
    assert reasons(reasoned.uncertainty) == [
        "own_knowledge",
        "samples_disagree",
        "from_documents",
        "model_decision",
        "open_judgement",
    ]


def alternative(u: dict, strength: str = "doc") -> dict:
    return {
        "id": "claim:P-1:2",
        "type": "alternative",
        "subject": "P-1",
        "basis": ["claim:P-1:1"],
        "component": "P-1.data",
        "status": "supported",
        "level": "technically_supported",
        "strength": strength,
        "supporting": ["item:1"],
        "channels": ["reasoning:m/P-1/s1"],
        "uncertainty": u,
        "sufficiency": {"sufficient": True},
    }


def test_concern_v_on_a_documented_alternative_is_not_demonstrated():
    h = purpose(of("from_documents"))
    [c], _ = concerns.less_invasive_alternative(FRAME, [h], [alternative(of("from_documents"))], {"P-1"}, {})
    assert c.status == "supported"
    assert c.uncertainty == of("from_documents", "not_demonstrated", "open_judgement")
    # none supported: the purpose's, and a judgement from documents of an open term
    held = {**alternative(of("from_documents")), "status": "not_established", "level": "plausible"}
    [c], _ = concerns.less_invasive_alternative(FRAME, [purpose(of("own_knowledge"))], [held], {"P-1"}, {})
    assert c.status == "not_established"
    assert c.uncertainty == of("own_knowledge", "from_documents", "open_judgement")


def test_concern_ii_where_the_samples_disagree_is_high():
    statement = SimpleNamespace(id="S1", declarations=["D-1"], text="to improve our services")
    judgements = [
        {"statement": "S1", "sample": f"s/D/S1/s{i}", "status": status, "strength": "doc", "specific": specific}
        | {"parts": [], "channels": [f"reasoning:s{i}"], "lacking": ["action"], "reason": "vague"}
        for i, (status, specific) in enumerate((("supported", False), ("not_established", True)))
    ]
    [c], _ = concerns.not_specific(FRAME, [statement], judgements, lambda s, p: [], {})
    assert c.uncertainty == {
        "level": "high",
        "reasons": [
            {"reason": "samples_disagree", "level": "high"},
            {"reason": "from_documents", "level": "moderate"},
            {"reason": "open_judgement", "level": "moderate"},
        ],
    }


def test_the_text_for_a_reader_and_an_old_report_converted():
    u = of("samples_disagree", "open_judgement")
    assert uncertainty.text(u) == "high: samples disagree, open judgement (moderate)"
    assert uncertainty.text(of()) == "low"
    old = {"claims": [{"uncertainty": {"f": "low", "t": "moderate", "s": "low", "n": "not_applicable"}}]}
    assert uncertainty.converted(old) == {"claims": [{"uncertainty": {"level": "low", "reasons": []}}]}
    assert uncertainty.read(u) == u and uncertainty.read(None) == of()
