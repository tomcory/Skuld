"""
O–D correspondence: how each practice relates to D's declarations, by rule (the framework's O–D relation).

Two aspects per practice, each a relation:

    data       the practice's data node against D's declarations of collection: equal (corresponds exactly), below a
               declared node (hierarchically), above it or beside it under a common node (partially)
    recipient  for a transmission to another organisation (parties.py), its recipient against D's declared recipients:
               the same entity (exactly), an entity of the same owner or a declared category the entity's register
               types fall under (hierarchically); a transmission to the provider itself has no recipient aspect

A positive declaration aligned with the practice corresponds, the best alignment deciding the outcome among those it
relates; a denial aligned with it contradicts it if the practice transmits the data (Google Play counts only data that
leaves the device as collected, so an access on the device contradicts no denial). D's root category of data holds
of all data where D's report marks the declaration as naming no data (`_no_data`, Urda 2.1.0) or places the root
itself; where it marks the root as a value it could not place (`_unplaced`), the declaration relates to no practice by
it, and a relation only such declarations could decide is insufficient evidence; in an earlier report, which marks
neither, a denial labelled with the root alone contradicts under a condition (that it meant the data observed). A
denial contradicts under a
condition where what the denial means depends on what O cannot observe: a channel's own definitions (Google Play's
Data safety section does not count a transfer to a service provider as sharing) or the legal role a denial names
(that the recipient is a third party, not a processor). Denials of a sale are not related: O observes no
consideration. Without an aligned declaration in an analysed channel, a practice is observed without matching
declaration; without an analysed channel that declares practices, the relation is insufficient evidence. D's
declarations of practice that no practice aligns with are declared without observation, citing O's silence status of
their node. Where O's and D's scopes are not comparable, every relation is not comparable.

`covered` decides whether a purpose is covered by a specified one (purpose limitation's rule part): the same node or
one above it (D's purposes name no beneficiary, so none is compared).
"""

from dataclasses import asdict, dataclass, field

from ratatoskr import align
from ratatoskr import claims as claim_views
from ratatoskr.registry import Registry
from ratatoskr.vocabularies import Vocabulary

from skuld.assessment import Declaration, Practice, Subjects, at, exhaustive
from skuld.uncertainty import needs, raised

#: 10: a silence is closed only on an exhaustive channel whose document was acquired complete (21 Nov 2026); 9: one
#: level with its reasons (Ratatoskr 0.34.0): needs over the claims related, o_silence and
#: silence_not_exhaustive where a relation reads a silence; 8: a practice's recipient and a declared one are compared by
#: their owners when the practice was observed (20 Nov 2026); 7: D's marks on the root (Urda 2.1.0): a denial of no data in particular contradicts under no condition of
#: its own, a value D could not place leaves the relation undecided; 6: a denial naming a recipient contradicts only a
#: transmission to it; 5: denials relate to transmissions only; a root-category denial contradicts under a condition
VERSION = "10"
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
    partial: str | None = None  # for corresponds_partially: broader, related or root_category (S-17)
    condition: str | None = None
    condition_kind: str | None = None  # fact or source (S-21): source where a mismatch reads D's silence and a
    # channel of D's that declares practices was not analysed (`analysed:<channel>, ...`, 8.9)
    condition_open: str | None = None  # the open condition that states it
    silence: list[str] = field(default_factory=list)
    reason: str | None = None  # where no claim it relates explains its outcome
    uncertainty: dict | None = None  # of the claims it relates, or of the claim and the silence it reads


def _data_outcome(kind: str) -> str | None:
    return {
        align.EQUAL: EXACTLY,
        align.NARROWER: HIERARCHICALLY,
        align.BROADER: PARTIALLY,
        align.RELATED: PARTIALLY,
    }.get(kind)


def _partial(outcome: str, how: str | None) -> str | None:
    """Which partial alignment a corresponds_partially is: O's node above the declared ones, beside them, or a
    recipient declared only by the root category; qualification reads them as ?, ≠ and ≈."""
    if outcome != PARTIALLY:
        return None
    if how == align.BROADER:
        return "broader"
    if how == align.RELATED:
        return "related"
    if how == ROOT_CATEGORY:
        return "root_category"
    raise ValueError(f"a partial correspondence aligned by {how!r}")


#: How a recipient declared only by the root category of the recipient types aligns
ROOT_CATEGORY = "by the root category only"


def _recipient_outcome(practice: Practice, value: dict, registry: Registry | None, types: Vocabulary) -> tuple | None:
    """How a practice's recipient aligns with a declared one: (outcome, alignment), or None."""
    entity = practice.recipient
    if not isinstance(value, dict) or registry is None or entity is None or entity.startswith("domain:"):
        return None
    declared = value.get("entity") or value.get("_entity")
    if declared:
        r = align.recipients(entity, declared, registry, at=at(practice.observed))
        if r.kind == align.SAME_ENTITY:
            return EXACTLY, "same entity"
        if r.kind == align.SAME_OWNER:
            return HIERARCHICALLY, f"same owner ({r.common})"
        return None
    category = value.get("category") or next(iter(value.get("categories") or ()), None)
    if category:
        if category == types.root:
            return PARTIALLY, ROOT_CATEGORY  # 'recipients' says only that someone receives
        try:
            r = align.recipient_category(entity, category, registry, types, at=at(practice.observed))
        except KeyError:  # a category the vocabulary does not know relates to no recipient
            return None
        if r.kind in (align.EQUAL, align.NARROWER):
            return HIERARCHICALLY, f"by category ({category})"
    return None


def _names_recipient(value, types: Vocabulary) -> bool:
    """Whether a declaration's value names a recipient: an entity, or a category of recipients below the root."""
    if not isinstance(value, dict):
        return False
    if value.get("entity") or value.get("_entity"):
        return True
    category = value.get("category") or next(iter(value.get("categories") or ()), None)
    return bool(category) and category != types.root


def _condition(
    declaration: Declaration,
    qualifiers: dict,
    aspect: str,
    channel_definitions: dict[str, str | None],
    data: Vocabulary | None = None,
) -> str | None:
    """What O cannot observe but a contradiction needs: a channel's definitions, the legal role a denial names, the
    denial's own condition and applicability, and, for a denial D labelled only with the root category of data, that
    it meant the data observed (plan/archive/POST_PAPER_FIXES 3: "we never collect or store those informations")."""
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
    if data is not None and declaration.data == data.root and not (declaration.no_data or declaration.marked):
        # an earlier report's root stands both for all data and for a value D could not place (Urda before 2.1.0)
        parts.append(f"the denial, labelled only {data.root}, means the data observed")
    return "; and ".join(parts) or None


#: Why a relation that only declarations of unplaced data could decide is insufficient evidence
UNPLACED = "D could not place the data of the declarations that could relate ({})"


def _unplaced_words(declarations: list[Declaration]) -> str:
    return ", ".join(sorted({d.claim["claim"] for d in declarations}))


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
    d_claims = claim_views.of_report(d_report)
    definitions = {c["channels"][0]: c.get("definitions") for c in d_claims}
    qualifiers = {c["id"]: c.get("qualifiers") or {} for c in d_claims}
    analysed = {d["channel"] for d in subjects.collection["documents"] if d["status"] == "analysed"} & set(
        PRACTICE_CHANNELS
    )
    # a mismatch that reads D's silence holds only if D's unread channels say no more (8.9): a source condition
    unread = sorted(
        {d["channel"] for d in subjects.collection["documents"] if d["status"] != "analysed"} & set(PRACTICE_CHANNELS)
    )
    silent_if = {"condition": ", ".join(f"analysed:{c}" for c in unread), "condition_kind": "source"} if unread else {}
    comparable = subjects.comparability.get("comparable") is not False
    why_not = "O's and D's scopes are not comparable" + (
        ": " + "; ".join(subjects.comparability.get("reasons") or []) if subjects.comparability.get("reasons") else ""
    )
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
                add(outcome=NOT_COMPARABLE, of=of, subject=p.id, aspect=aspect, reason=why_not)
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
            found, contradicting, unplaced = [], [], []
            for d in declarations:
                d_data = align.data(p.data, d.data, data)
                if not d_data.aligned:
                    continue
                if d.unplaced_data(data.root):
                    # the root of a value D could not place says nothing of all data: it could relate, or not
                    if d.polarity == "-" and (
                        p.claim_type != "transmits" or (isinstance(d.value, dict) and d.value.get("sale"))
                    ):
                        continue
                    if (
                        aspect == "recipient"
                        and d.polarity == "+"
                        and _recipient_outcome(p, d.value, registry, types) is None
                    ):
                        continue
                    if aspect == "recipient" and d.polarity == "-" and _names_recipient(d.value, types):
                        pair = _recipient_outcome(p, d.value, registry, types)
                        if pair is None or pair[0] == PARTIALLY:
                            continue
                    unplaced.append(d)
                    continue
                if d.polarity == "-":
                    # a denial contradicts only a transmission of what falls under it; O observes no sale's consideration
                    if p.claim_type != "transmits":
                        continue
                    if d_data.kind in (align.EQUAL, align.NARROWER) and not (
                        isinstance(d.value, dict) and d.value.get("sale")
                    ):
                        # a denial that names a recipient (an entity, or a category below the root) contradicts
                        # only a transmission to that recipient
                        if aspect == "recipient" and _names_recipient(d.value, types):
                            pair = _recipient_outcome(p, d.value, registry, types)
                            if pair is None or pair[0] == PARTIALLY:
                                continue
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
            denied = [d for d in unplaced if d.polarity == "-"]
            if denied:  # a denial of data D could not place may or may not deny the practice: undecided
                add(
                    outcome=INSUFFICIENT,
                    of=of,
                    to=[d.claim for d in denied],
                    subject=p.id,
                    aspect=aspect,
                    alignment=UNPLACED.format(_unplaced_words(denied)),
                )
            for d in contradicting:
                matched.add(d.id)
                condition = _condition(d, qualifiers[d.claim["claim"]], aspect, definitions, data)
                add(
                    outcome=CONTRADICTS,
                    of=of,
                    to=[d.claim],
                    subject=p.id,
                    aspect=aspect,
                    condition=condition,
                    condition_kind="fact" if condition else None,
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
                    partial=_partial(chosen[0][1], chosen[0][2]),
                    **(silent_if if _partial(chosen[0][1], chosen[0][2]) == "related" else {}),
                )
            elif not contradicting and [d for d in unplaced if d.polarity == "+"]:
                positive = [d for d in unplaced if d.polarity == "+"]
                matched.update(d.id for d in positive)
                add(
                    outcome=INSUFFICIENT,
                    of=of,
                    to=[d.claim for d in positive],
                    subject=p.id,
                    aspect=aspect,
                    alignment=UNPLACED.format(_unplaced_words(positive)),
                )
            elif not contradicting:
                if analysed:
                    add(
                        outcome=OBSERVED_ONLY,
                        of=of,
                        subject=p.id,
                        aspect=aspect,
                        silence=[f"D: {', '.join(sorted(analysed))}"],
                        **silent_if,
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
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id, reason=why_not)
            continue
        if d.unplaced_data(data.root):  # O's silence on the root says nothing of data D could not place
            add(
                outcome=INSUFFICIENT,
                of=d.claim,
                subject=d.id,
                aspect="data" if d.type == "declares_collection" else "recipient",
                alignment=UNPLACED.format(d.claim["claim"]),
            )
            continue
        silence = [
            f"O {s['claim_type']} {s['node']}: {s['status']}"
            + (f" (not_found for {', '.join(s['not_found_for'])})" if s.get("not_found_for") else "")
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
    _uncertainty(relations, subjects)
    return relations


def covered(purpose: str, specified: list[str], vocabulary: Vocabulary) -> list[str]:
    """The specified purposes that cover a purpose: the same node, or one above it (purpose limitation, by rule)."""
    return [s for s in specified if align.purposes(purpose, s, vocabulary).kind in (align.EQUAL, align.NARROWER)]


#: The predicate a relation's aspect reads of D: whether the data is collected, whether it goes to the recipient
PREDICATE = {"data": "collection", "recipient": "sharing"}


def _uncertainty(relations: list[Relation], subjects) -> None:
    """The uncertainty of each O–D relation that relates claims: `needs` over the practice's and the D claims' it names
    (D's at their own level); where it reads D's silence, at least moderate (`silence_not_exhaustive`) unless every silent
    channel is exhaustive for the aspect's predicate (ratatoskr.channels) and its document was acquired complete; where it reads O's silence, at least moderate
    (`o_silence`). A relation that relates nothing (not comparable, insufficient evidence) has none."""
    practices = {p.id: p for p in subjects.practices}
    declared = {d.claim["claim"]: d for d in subjects.declarations}
    documents = (getattr(subjects, "collection", None) or {}).get("documents", [])
    complete = {d["channel"] for d in documents if d.get("status") == "analysed" and d.get("complete", True)}
    by_id = {d.id: d for d in subjects.declarations}
    for r in relations:
        if r.outcome == DECLARED_ONLY and r.subject in by_id:
            # O's silence about a declared practice holds relative to what the exploration reached
            r.uncertainty = raised(by_id[r.subject].uncertainty, "o_silence")
            continue
        p = practices.get(r.subject)
        if p is None or not p.uncertainty:
            continue
        if r.to:
            r.uncertainty = needs(
                p.uncertainty, *(declared[t["claim"]].uncertainty for t in r.to if t["claim"] in declared)
            )
        elif r.outcome == OBSERVED_ONLY:
            silent = [c for line in r.silence for c in line.removeprefix("D: ").split(", ")]
            closed = silent and all(exhaustive(c, PREDICATE[r.aspect]) and c in complete for c in silent)
            r.uncertainty = needs(p.uncertainty) if closed else raised(p.uncertainty, "silence_not_exhaustive")


def number(relations: list[Relation]) -> None:
    """The relations' ids, `relation:<subject>:<n>`, in order."""
    n: dict[str, int] = {}
    for r in relations:
        n[r.subject] = n.get(r.subject, 0) + 1
        r.id = f"relation:{r.subject}:{n[r.subject]}"


def to_json(relations: list[Relation]) -> list[dict]:
    return [{k: v for k, v in asdict(r).items() if k == "to" or v not in (None, [])} for r in relations]
