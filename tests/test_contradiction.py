"""Concern (iii), declaration contradicted (author, 14 Nov 2026): a declaration that O contradicts."""

from ratatoskr.frames import Frame

from skuld import aggregate as ag
from skuld import concerns
from skuld.correspondence import CONTRADICTS, Relation
from skuld.uncertainty import of

FRAME = Frame.load("gdpr-art5")


def relation(n, practice, pointer, condition=None, u=None):
    return Relation(
        id=f"relation:{practice}:{n}",
        type="O-D",
        tier="rule",
        outcome=CONTRADICTS,
        of={"dimension": "O", "report": "o", "claim": f"c{n}"},
        to=[{"dimension": "D", "report": "d", "claim": pointer}],
        subject=practice,
        aspect="recipient",
        condition=condition,
        uncertainty=u or of("actor_inferred"),
    )


def items(d, rels):
    return [f"item:{rel.of['claim'].removeprefix('c')}" for rel in rels]


def test_one_concern_per_declaration_supported_and_conditional_only_if_every_contradiction_is():
    rels = [
        relation(1, "P-a", "policy:/notDisclosed/0"),
        relation(
            2,
            "P-b",
            "policy:/notDisclosed/0",
            "the recipient is not a service provider",
            of(("model_decision", "moderate")),
        ),
        relation(3, "P-a", "policy:/notDisclosed/1", "the recipient is not a service provider"),
        relation(4, "P-b", "policy:/notDisclosed/1", "the denial applies to the observation (jurisdiction Utah)"),
    ]
    declaration_of = {"policy:/notDisclosed/0": "D-0", "policy:/notDisclosed/1": "D-1"}
    stated, covered = concerns.declaration_contradicted(
        FRAME, rels, declaration_of, items, {}, {"D-0": "We do not share data."}
    )
    by = {c.subject: c for c in stated}
    assert set(by) == {"D-0", "D-1"} and {c.subject for c in covered} == {"D-0", "D-1"}
    unconditional, conditional = by["D-0"], by["D-1"]
    assert (unconditional.requirement, unconditional.step, unconditional.tier) == (
        "declaration_corresponds",
        "declaration_contradicted",
        "rule",
    )
    assert unconditional.principle == "transparency" and not hasattr(unconditional, "observability")
    assert unconditional.status == "supported" and unconditional.condition == []
    # needs over its relations, O's and D's reasons passed through; no open condition
    assert unconditional.uncertainty == {
        "level": "moderate",
        "reasons": [
            {"reason": "actor_inferred", "level": "moderate"},
            {"reason": "model_decision", "level": "moderate"},
        ],
    }
    assert unconditional.reason == '"We do not share data.": contradicted by 2 observed practices'
    assert unconditional.supporting == ["item:1", "item:2"]
    # every contradiction conditional: the concern holds if one of the conditions does
    assert conditional.condition == [
        "the denial applies to the observation (jurisdiction Utah) or the recipient is not a service provider"
    ]
    assert conditional.uncertainty == of("actor_inferred", "open_condition")
    assert conditional.reason.endswith("each under an open condition")


def test_where_the_requirement_does_not_apply_nothing_is_stated():
    rels = [relation(1, "P-a", "policy:/notDisclosed/0")]
    stated, covered = concerns.declaration_contradicted(
        FRAME,
        rels,
        {"policy:/notDisclosed/0": "D-0"},
        items,
        {"declaration_corresponds": {"applicability": "does_not_apply"}},
    )
    assert stated == [] and [(c.subject, c.applies) for c in covered] == [("D-0", False)]


def test_each_contradicted_declaration_is_an_aggregated_concern_of_its_own_with_its_text():
    rels = [relation(1, "P-a", "policy:/notDisclosed/0"), relation(2, "P-a", "policy:/notDisclosed/1")]
    of = {"policy:/notDisclosed/0": "D-0", "policy:/notDisclosed/1": "D-1"}
    stated, _ = concerns.declaration_contradicted(FRAME, rels, of, items, {}, {"D-0": "We never share.", "D-1": "No."})
    concerns.number(stated)
    report = {
        "report": {"created": "2026-11-15T00:00:00+00:00"},
        "application": {"package": "a.b", "version": "1"},
        "concerns": concerns.to_json(stated),
        "subjects": {"practices": [], "declarations": [{"id": "D-0"}, {"id": "D-1"}]},
        "claims": [],
        "open": [],
    }
    out = ag.aggregate(report)
    units = out["aggregated_concerns"]
    assert len(units) == 2 and all(u["step"] == "declaration_contradicted" for u in units)
    assert {u["key"]["subject"] for u in units} == {"D-0", "D-1"}
    assert {u["members"][0]["statement"] for u in units} == {"We never share.", "No."}
    assert any(u["label"].endswith("“We never share.”") for u in units)
