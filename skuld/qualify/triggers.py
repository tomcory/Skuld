"""
Review triggers (QUALIFICATION_PLAN.md §5): a mark on a case that one of the framework's review conditions
(F-R-REVIEW) holds, with the signal that raises it. A trigger weighs if qualifying the case under any of its
resolutions gives a different result; the test reuses the rules of results.py on a copy of the case and adds none of
its own. Triggers tell the reader where a result is least certain, and their weight enters the review sample of
calibration (ADR 0004); no decision on them changes this report.

    conflicted_claims              a symbol is conflict, or a concern is conflicted       conflict read as ≈ and as ≠;
                                                                                          the concern supported or not
    high_uncertainty               a relation or concern with t, s or n high              a supported concern read as
                                                                                          not established; a relation
                                                                                          read as ?
    unresolved_entity              a transmission whose recipient is none or a domain,    each conditional ≠ read as
                                   or whose actor is ?                                    holding and as failing
    purpose_too_vague              a D–E relation purpose_too_vague                       read as ≈ and as ≠
    model_against_measurement      a concern resting on a combined claim that overruled   the concern's status flipped
                                   a claim of the other kind of strength (S-22)
    beyond_external_observability  a concern or gap with observability E3 or E4           resolved for and against
"""

from skuld.qualify import symbols
from skuld.qualify.nextsteps import _concern, _relation, _without_gap
from skuld.qualify.results import View, result

VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.qualify.triggers", "version": VERSION}


def _flip(status: str) -> str:
    return "not_established" if status == "supported" else "supported"


def triggers(index, holding, view: View) -> list[dict]:
    now = result(view)
    out = []

    def add(trigger: str, signal: list[str], variants: list[tuple[str, View]]) -> None:
        if not signal:
            return
        found = [{"resolution": name, "result": result(v)} for name, v in variants]
        out.append(
            {
                "trigger": trigger,
                "signal": sorted(set(signal)),
                "weighs": any(f["result"] != now for f in found),
                **({"resolutions": [f for f in found if f["result"] != now]} if found else {}),
            }
        )

    conflicts = [r for r in view.relations if r.symbol == symbols.CONFLICT]
    conflicted = [c for c in view.concerns if c.status == "conflicted"]
    add(
        "conflicted_claims",
        [r.id for r in conflicts] + [c.id for c in conflicted],
        [(f"{r.id} as ≈", _relation(view, r.id, symbols.AGREE)) for r in conflicts]
        + [(f"{r.id} as ≠", _relation(view, r.id, symbols.DISAGREE)) for r in conflicts]
        + [(f"{c.id} supported", _concern(view, c.id, "supported")) for c in conflicted]
        + [(f"{c.id} refuted", _concern(view, c.id, None)) for c in conflicted],
    )
    high_c = [c for c in view.concerns if c.high and c.status == "supported"]
    high_r = [r for r in view.relations if r.high]
    add(
        "high_uncertainty",
        [c.id for c in high_c] + [r.id for r in high_r],
        [(f"{c.id} not established", _concern(view, c.id, "not_established")) for c in high_c]
        + [(f"{r.id} as ?", _relation(view, r.id, symbols.UNKNOWN)) for r in high_r],
    )
    if holding.kind == "practice":
        p = index.practices[holding.subject]
        unresolved = p["claim_type"] == "transmits" and (
            p.get("recipient") in (None, "?") or str(p.get("recipient")).startswith("domain:")
        )
        if unresolved or p.get("actor") in (None, "?"):
            conditional = [r for r in view.of_type("O-D") if r.condition and r.symbol == symbols.DISAGREE]
            add(
                "unresolved_entity",
                [holding.subject],
                [(f"{r.id} holds", _relation(view, r.id, r.symbol, True)) for r in conditional]
                + [(f"{r.id} fails", _relation(view, r.id, None)) for r in conditional],
            )
    vague = [r for r in view.of_type("D-E") if r.outcome == "purpose_too_vague"]
    add(
        "purpose_too_vague",
        [r.id for r in vague],
        [(f"{r.id} as ≈", _relation(view, r.id, symbols.AGREE)) for r in vague]
        + [(f"{r.id} as ≠", _relation(view, r.id, symbols.DISAGREE)) for r in vague],
    )
    overruling = {cid for cid, c in index.claims.items() if c.get("overruled")}
    against = [c for c in view.concerns if set(c.basis) & overruling]
    add(
        "model_against_measurement",
        [c.id for c in against],
        [(f"{c.id} as the overruled claim would have it", _concern(view, c.id, _flip(c.status))) for c in against],
    )
    beyond_c = [c for c in view.concerns if c.observability in ("E3", "E4")]
    beyond_g = [g for g in view.gaps if g.observability in ("E3", "E4")]
    add(
        "beyond_external_observability",
        [c.id for c in beyond_c] + [g.id for g in beyond_g],
        [(f"{g.id} resolved", _without_gap(view, g.id)) for g in beyond_g]
        + [(f"{c.id} supported", _concern(view, c.id, "supported", True)) for c in beyond_c]
        + [(f"{c.id} refuted", _concern(view, c.id, None)) for c in beyond_c],
    )
    return out
