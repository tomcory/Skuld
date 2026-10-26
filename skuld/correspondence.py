"""
O–D correspondence: how each practice relates to D's declarations, by rule (the framework's O–D relation).

Two aspects per practice, each a relation:

    data       the practice's data node against D's declarations of collection: equal (corresponds exactly), below a
               declared node (hierarchically), above it or beside it under a common node (partially)
    recipient  for a transmission to another organisation (parties.py), its recipient against D's declared recipients:
               the same entity (exactly), an entity of the same owner or a declared category the entity's register
               types fall under (hierarchically); a transmission to the provider itself has no recipient aspect

A positive declaration aligned with the practice corresponds, the best alignment deciding the outcome among those it
relates; a denial aligned with it contradicts it, under a
condition where what the denial means depends on what O cannot observe: a channel's own definitions (Google Play's
Data safety section does not count a transfer to a service provider as sharing) or the legal role a denial names
(that the recipient is a third party, not a processor). Denials of a sale are not related: O observes no
consideration. Without an aligned declaration in an analysed channel, a practice is observed without matching
declaration; without an analysed channel that declares practices, the relation is insufficient evidence. D's
declarations of practice that no practice aligns with are declared without observation, citing O's silence status of
their node. Where O's and D's scopes are not comparable, every relation is not comparable.

`covered` decides whether a purpose is covered by a specified one (purpose limitation's rule part): the same node or
one below it, of the same beneficiary.
"""

from dataclasses import asdict, dataclass, field

from ratatoskr import align
from ratatoskr.registry import Registry
from ratatoskr.vocabularies import Vocabulary

from skuld.assessment import Declaration, Practice, Subjects

VERSION = "2"
COMPONENT = {"role": "method", "id": "skuld.correspondence", "version": VERSION}

EXACTLY, HIERARCHICALLY, PARTIALLY = "corresponds_exactly", "corresponds_hierarchically", "corresponds_partially"
CONTRADICTS, OBSERVED_ONLY, DECLARED_ONLY = (
    "contradicts",
    "observed_without_declaration",
    "declared_without_observation",
)
NOT_COMPARABLE, INSUFFICIENT = "not_comparable", "insufficient_evidence"

#: Channels whose definitions narrow what a declaration means, by aspect
DEFINITIONS = {
    ("google-play-data-safety", "recipient"): (
        "the recipient is not a service provider (Google Play does not count a transfer to one as sharing)"
    ),
    ("google-play-data-safety", "data"): (
        "the processing is not only ephemeral (Google Play does not count ephemeral processing as collection)"
    ),
}
#: The legal roles a denial may name, and what O would have to know for it to contradict an observation
ROLES = {"ThirdParty": "the recipient acts as a third party, not as a processor"}
#: The order of outcomes, best first, among the declarations a practice aligns with
ORDER = (EXACTLY, HIERARCHICALLY, PARTIALLY)
PRACTICE_CHANNELS = ("policy", "data_safety", "in_app")


@dataclass
class Relation:
    id: str
    type: str
    tier: str
    outcome: str
    of: dict
    to: list[dict] = field(default_factory=list)
    subject: str | None = None  # the practice or declaration it is about
    aspect: str | None = None  # data or recipient
    alignment: str | None = None
    condition: str | None = None
    silence: list[str] = field(default_factory=list)
    question: str | None = None  # O–E: dependency or minimisation, which its outcome answers
    reason: str | None = None  # where no claim it relates explains its outcome


def _data_outcome(kind: str) -> str | None:
    return {
        align.EQUAL: EXACTLY,
        align.NARROWER: HIERARCHICALLY,
        align.BROADER: PARTIALLY,
        align.RELATED: PARTIALLY,
    }.get(kind)


def _recipient_outcome(practice: Practice, value: dict, registry: Registry | None, types: Vocabulary) -> tuple | None:
    """How a practice's recipient aligns with a declared one: (outcome, alignment), or None."""
    entity = practice.recipient
    if not isinstance(value, dict) or registry is None or entity is None or entity.startswith("domain:"):
        return None
    declared = value.get("entity") or value.get("_entity")
    if declared:
        r = align.recipients(entity, declared, registry)
        if r.kind == align.SAME_ENTITY:
            return EXACTLY, "same entity"
        if r.kind == align.SAME_OWNER:
            return HIERARCHICALLY, f"same owner ({r.common})"
        return None
    if value.get("category"):
        if value["category"] == types.root:
            return PARTIALLY, "by the root category only"  # 'recipients' says only that someone receives
        r = align.recipient_category(entity, value["category"], registry, types)
        if r.kind in (align.EQUAL, align.NARROWER):
            return HIERARCHICALLY, f"by category ({value['category']})"
    return None


def _condition(
    declaration: Declaration, qualifiers: dict, aspect: str, channel_definitions: dict[str, str | None]
) -> str | None:
    """What O cannot observe but a contradiction needs: a channel's definitions, the legal role a denial names, and
    the denial's own condition and applicability."""
    parts = []
    definitions = channel_definitions.get(declaration.channel)
    if (definitions, aspect) in DEFINITIONS:
        parts.append(DEFINITIONS[(definitions, aspect)])
    role = declaration.value.get("role") if isinstance(declaration.value, dict) else None
    if role in ROLES and not parts:  # a channel's definitions already say what its role means
        parts.append(ROLES[role])
    if (qualifiers.get("condition") or {}).get("text"):
        parts.append(f"the denial's condition held when the data were sent ({qualifiers['condition']['text']})")
    if qualifiers.get("applicability"):
        limits = ", ".join(f"{a.get('kind')} {a.get('value')}" for a in qualifiers["applicability"])
        parts.append(f"the denial applies to the observation ({limits})")
    return "; and ".join(parts) or None


def relate(
    subjects: Subjects,
    d_report: dict | None,
    o_statuses: list[dict],
    registry: Registry | None,
    data: Vocabulary,
    types: Vocabulary,
) -> list[Relation]:
    """The O–D relations of an assessment's practices and D's declarations of practice."""
    if d_report is None:
        return []
    definitions = {c["channel"]: c.get("definitions") for c in d_report["claims"]}
    qualifiers = {f"/claims/{n}": c.get("qualifiers") or {} for n, c in enumerate(d_report["claims"])}
    analysed = {d["channel"] for d in subjects.collection["documents"] if d["status"] == "analysed"} & set(
        PRACTICE_CHANNELS
    )
    comparable = subjects.comparability.get("comparable") is not False
    practice_declarations = [d for d in subjects.declarations if d.kind == "practice"]
    collection = [d for d in practice_declarations if d.type == "declares_collection"]
    recipients = [d for d in practice_declarations if d.type == "declares_recipient"]
    relations: list[Relation] = []
    matched: set[str] = set()

    def add(**kwargs) -> Relation:
        relation = Relation(id=f"r{len(relations) + 1}", type="O-D", tier="rule", **kwargs)
        relations.append(relation)
        return relation

    for p in subjects.practices:
        of = p.claims[0]
        aspects = [("data", collection)]
        if p.claim_type == "transmits" and (p.party or {}).get("relation") != "own":
            aspects.append(("recipient", recipients))
        for aspect, declarations in aspects:
            if not comparable:
                add(outcome=NOT_COMPARABLE, of=of, subject=p.id, aspect=aspect)
                continue
            if aspect == "recipient" and (p.recipient in (None, "?") or (p.party or {}).get("relation") == "?"):
                add(
                    outcome=INSUFFICIENT,
                    of=of,
                    subject=p.id,
                    aspect=aspect,
                    alignment="recipient unknown or of an undecided party",
                )
                continue
            found, contradicting = [], []
            for d in declarations:
                d_data = align.data(p.data, d.data, data)
                if not d_data.aligned:
                    continue
                if d.polarity == "-":
                    # a denial contradicts only what falls under it; O observes no sale's consideration
                    if d_data.kind in (align.EQUAL, align.NARROWER) and not (
                        isinstance(d.value, dict) and d.value.get("sale")
                    ):
                        contradicting.append(d)
                    continue
                if aspect == "data":
                    outcome, how = _data_outcome(d_data.kind), d_data.kind
                else:
                    pair = _recipient_outcome(p, d.value, registry, types)
                    if pair is None:
                        continue
                    outcome, how = pair
                    if d_data.kind != align.EQUAL and outcome == EXACTLY:
                        outcome = HIERARCHICALLY
                if outcome:
                    found.append((ORDER.index(outcome), outcome, how, d))
            for d in contradicting:
                matched.add(d.id)
                add(
                    outcome=CONTRADICTS,
                    of=of,
                    to=[d.claim],
                    subject=p.id,
                    aspect=aspect,
                    condition=_condition(d, qualifiers[d.claim["claim"]], aspect, definitions),
                )
            if found:
                found.sort(key=lambda f: f[0])
                best = found[0][0]
                chosen = [f for f in found if f[0] == best]
                matched.update(f[3].id for f in found)
                add(
                    outcome=chosen[0][1],
                    of=of,
                    to=[f[3].claim for f in found],
                    subject=p.id,
                    aspect=aspect,
                    alignment=chosen[0][2],
                )
            elif not contradicting:
                if analysed:
                    add(
                        outcome=OBSERVED_ONLY,
                        of=of,
                        subject=p.id,
                        aspect=aspect,
                        silence=[f"D: {', '.join(sorted(analysed))}"],
                    )
                else:
                    add(
                        outcome=INSUFFICIENT,
                        of=of,
                        subject=p.id,
                        aspect=aspect,
                        alignment="no analysed channel declares practices",
                    )

    for d in practice_declarations:
        if d.id in matched or d.polarity != "+" or d.type not in ("declares_collection", "declares_recipient"):
            continue
        if not comparable:
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id)
            continue
        silence = [
            f"O {s['claim_type']} {s['node']}: {s['status']}"
            for s in o_statuses
            if s.get("node") == d.data and s.get("claim_type") == "transmits"
        ]
        add(
            outcome=DECLARED_ONLY,
            of=d.claim,
            subject=d.id,
            aspect="data" if d.type == "declares_collection" else "recipient",
            silence=silence or ["O: unknown"],
        )
    return relations


def covered(purpose: str, specified: list[str], vocabulary: Vocabulary) -> list[str]:
    """The specified purposes that cover a purpose: the same node, or one above it (purpose limitation, by rule)."""
    return [s for s in specified if align.purposes(purpose, s, vocabulary).kind in (align.EQUAL, align.NARROWER)]


def number(relations: list[Relation]) -> None:
    """The relations' ids, `relation:<subject>:<n>`, in order."""
    n: dict[str, int] = {}
    for r in relations:
        n[r.subject] = n.get(r.subject, 0) + 1
        r.id = f"relation:{r.subject}:{n[r.subject]}"


def to_json(relations: list[Relation]) -> list[dict]:
    return [{k: v for k, v in asdict(r).items() if k == "to" or v not in (None, [])} for r in relations]
