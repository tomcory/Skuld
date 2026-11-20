"""
E's concerns (E def:concern), by five rules:

    (i)   information not given, for the collection and a transparency requirement (rule tier): supported if its
          status is missing, citing what decides that it applies and D's silence on its label; supported under an
          open condition if missing_if. That no document bears the label is D's analysis not finding it, and no
          channel of D is exhaustive for a transparency requirement (ratatoskr.channels), so its uncertainty is
          moderate (`silence_not_exhaustive`)
    (ii)  not specific, for a declared purpose (reasoning tier): stated where a sample judges it not specific;
          supported if the samples' combined judgement is
    (iii) declaration contradicted, for a declaration O contradicts (rule tier; author, 14 Nov 2026): supported where
          correspondence relates an observed practice to it as `contradicts` (a denial of what O observed); one
          concern per declaration, citing the declaration's text and the O claims; under an open condition if every
          contradiction is conditional (e.g., the denial is limited to some jurisdictions, or the recipient might be
          a service provider), the condition being that one of them holds. Transparency (WP260 rev.01 para. 10: the
          data subject cannot determine the scope of the processing in advance), secondarily fairness (EDPB
          Guidelines 4/2019 para. 70)
    (iv)  no specified purpose covers it, for a practice and a supported inferred purpose: stated where no purpose
          specified for the practice's data covers the inferred one; supported by rule if none is specified for its
          data, else by the reasoning tier if the combined judgement is that it is compatible with none of them
    (v)   a less invasive alternative, for a practice and a supported inferred purpose (reasoning tier): supported if a
          combined Alternative claim on one of its components is supported, technically supported by documents or
          demonstrated by an experiment for a case purpose ≈ it; not assessable if every premise is

A sample's judgement is combined across samples like any claim (combine.decide): a supported judgement of strength
doc decides over samples that name no concern, and the disagreement raises the concern's uncertainty to high
(`samples_disagree`).

A concern's uncertainty is set by its step from its premises, `needs` over what it rests on: the purpose's, a
comparison's where an experiment decides it, D's (read leniently) where it reads D's classification, the relations'
for (iii); with its own reasons, `from_documents` for a judgement from documents, `samples_disagree` where the
samples disagree, `open_judgement` for a judgement of an open term (reasoning tier), `open_condition` under an open
condition, `silence_not_exhaustive` where it reads a silence not exhaustive for it, `not_demonstrated` for an
alternative documented, not demonstrated by a run. A requirement tested by rule on no open condition and no silence
is low.

A concern never states that a requirement is met: what E assessed and stated no concern for is its coverage
(`coverage`), relative to the documents D acquired and could access.
"""

from dataclasses import asdict, dataclass, field

from ratatoskr.frames import Frame

from skuld import combine
from skuld.assessment import exhaustive
from skuld.transparency import INCOMPLETE, MISSING, MISSING_IF, NOT_APPLICABLE, UNREAD, Status
from skuld.uncertainty import needs, of, raised

VERSION = "13"  # 13: one level with its reasons (Ratatoskr 0.34.0); 12: (iv) undecided where D specifies purposes for data it could not place (Urda 2.1.0); 11: concern (i) cites every item that decides it applies; 10: rule (iii), declaration contradicted
COMPONENT = {"role": "method", "id": "skuld.concerns", "version": VERSION}

#: Of a rule-tier concern of information not given: as certain as D's annotations and O's claims it reads
BY_RULE = of()
#: Of a reasoning-tier judgement from documents of an open term
FROM_DOC = of("from_documents", "open_judgement")


@dataclass
class Concern:
    subject: str
    requirement: str
    principle: str
    provisions: list[str]
    step: str
    tier: str
    status: str
    uncertainty: dict
    observability: str
    id: str = ""
    condition: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)  # the claims its rule reads
    supporting: list[str] = field(default_factory=list)  # the evidence items it rests on
    silence: list[str] = field(default_factory=list)
    reason: str | None = None
    channels: list[str] = field(default_factory=list)
    purpose: str | None = None  # the combined Purpose claim
    specified: list[str] = field(default_factory=list)  # the declarations of the specified purposes judged
    relations: list[str] = field(default_factory=list)  # the relations its rule reads


@dataclass
class Covered:
    """A subject E assessed against a requirement, by a channel, or found the requirement not to apply to."""

    requirement: str
    subject: str
    channel: str
    applies: bool = True


def _concern(frame: Frame, requirement: str, **fields) -> Concern:
    r = frame.requirement(requirement)
    return Concern(requirement=r.id, principle=r.principle, provisions=list(r.provisions), **fields)


def information_not_given(frame: Frame, statuses: list[Status], evidence_of: dict[str, list[str]]):
    """Concerns (i) and coverage for the collection, from its transparency statuses. `evidence_of` gives, per
    requirement, the evidence items that decide its applicability."""
    concerns, covered = [], []
    for s in statuses:
        r = frame.requirement(s.requirement)
        covered.append(Covered(r.id, "collection", "rule", s.status != NOT_APPLICABLE))
        if s.status not in (MISSING, MISSING_IF):
            continue
        conditional = s.status == MISSING_IF
        # the silence is closed only on a channel exhaustive for the requirement; D has none for one (D's channel types)
        open_silence = [ch for ch in s.silent if not exhaustive(ch, f"information:{r.id}")]
        unread = any(c.startswith((INCOMPLETE, UNREAD)) for c in s.conditions)
        uncertainty = of(
            *(["open_condition"] if conditional else []),
            *(["silence_not_exhaustive"] if open_silence or unread else []),
        )
        concerns.append(
            _concern(
                frame,
                r.id,
                subject="collection",
                step="information_not_given",
                tier="rule",
                status="supported",
                uncertainty=uncertainty,
                observability="E1",
                condition=list(s.conditions),
                supporting=evidence_of.get(r.id, []),
                silence=[f"D: no accessible document bears the label {r.label}"]
                + ([f"D: not exhaustive for it: {', '.join(open_silence)}"] if open_silence else []),
                reason=(
                    f"missing if {', '.join(s.conditions)}, which no dimension decides"
                    if conditional
                    else "applies, and no accessible document gives the information"
                )
                + (
                    "; a silent document was acquired incomplete"
                    if any(c.startswith(INCOMPLETE) for c in s.conditions)
                    else ""
                )
                + ("; a document could not be analysed" if any(c.startswith(UNREAD) for c in s.conditions) else ""),
            )
        )
    return concerns, covered


def _condition(applicability: dict, requirement: str) -> list[str]:
    a = applicability.get(requirement) or {}
    return list(a.get("undecided") or ()) if a.get("applicability") == "?" else []


def _applies(applicability: dict, requirement: str) -> bool:
    return (applicability.get(requirement) or {}).get("applicability", "applies") != "does_not_apply"


def _judged(judgements: list[dict], items) -> tuple[str, list[str], bool]:
    """The combined status of a proposition's judgements across samples, the items its supporting judgements cite,
    and whether the samples agree."""
    status, _ = combine.decide(judgements)
    supporting = sorted({x for j in judgements if j["status"] == "supported" for x in items(j["sample"], j["parts"])})
    return status, supporting, all(j["status"] == status for j in judgements)


def not_specific(frame: Frame, statements, judgements: list[dict], items, applicability: dict):
    """Concerns (ii) and coverage per declared purpose statement, from the specificity samples' judgements."""
    r = frame.requirement("purpose_specific")
    if not _applies(applicability, r.id):
        return [], [Covered(r.id, d, "rule", False) for s in statements for d in s.declarations]
    concerns, covered = [], []
    for s in statements:
        mine = [j for j in judgements if j["statement"] == s.id]
        if not mine:
            continue
        channels = sorted({ch for j in mine for ch in j["channels"]})
        # every declaration of the statement is assessed with it (a concern names the statement's first)
        covered += [Covered(r.id, d, "reasoning") for d in s.declarations]
        flagged = [j for j in mine if not j["specific"]]
        if not flagged:
            continue
        status, supporting, agreed = _judged(mine, items)
        lacking = sorted({x for j in flagged for x in j["lacking"]})
        concerns.append(
            _concern(
                frame,
                r.id,
                subject=s.declarations[0],
                step="not_specific",
                tier="reasoning",
                status=status,
                uncertainty=FROM_DOC if agreed else raised(FROM_DOC, "samples_disagree"),
                observability="E2",
                condition=_condition(applicability, r.id),
                reason=(
                    f'"{s.text}": {len(flagged)} of {len(mine)} samples judge it not specific'
                    + (f" ({', '.join(lacking)} lacking)" if lacking else "")
                    + ("" if status == "supported" else f"; {flagged[0]['reason']}")
                ),
                channels=channels,
                supporting=supporting,
            )
        )
    return concerns, covered


def purpose_limitation(
    frame: Frame, cases, judgements: list[dict], items, applicability: dict, declared: dict[str, dict] | None = None
):
    """Concerns (iv) and coverage per practice and supported inferred purpose (judge.Limitation), from the
    compatibility samples' judgements. Both steps rest on D's classification of the specified purposes and their data,
    so a concern needs the uncertainty `declared` gives each of them (D's, read leniently); one that rests on there
    being no specified purpose for the data reads the silence of channels exhaustive for no purpose, so it is at least
    moderate (`silence_not_exhaustive`)."""
    declared = declared or {}

    def of_d(specified) -> dict:
        return needs(*(declared[d] for s in specified for d in s.declarations if d in declared))

    specified_r, compatible_r = frame.requirement("purpose_specified"), frame.requirement("purpose_compatible")
    concerns, covered = [], []
    for case in cases:
        h, practice = case.purpose, case.practice
        node = h["purpose"]["node"]
        r = compatible_r if case.relevant else specified_r
        covered.append(Covered(specified_r.id, practice, "rule"))
        if case.relevant:
            covered.append(Covered(compatible_r.id, practice, "reasoning"))
        if case.covering:
            continue
        common = {
            "subject": practice,
            "step": "no_specified_purpose",
            "condition": _condition(applicability, r.id),
            "basis": [h["id"]],
            "purpose": h["id"],
            "silence": [f"D: no purpose specified for the practice's data covers {node}"],
        }
        unplaced = getattr(case, "unplaced", None) or []
        if not case.relevant:
            # purposes D specifies for data it could not place could be the practice's: then it is undecided
            concerns.append(
                _concern(
                    frame,
                    r.id,
                    **common,
                    tier="rule",
                    status="not_established" if unplaced else "supported",
                    uncertainty=raised(h["uncertainty"], "silence_not_exhaustive"),
                    observability="E2",
                    reason=f"no purpose is specified for {node}'s data"
                    + (f"; {_unplaced(unplaced)}" if unplaced else ""),
                )
            )
            continue
        mine = [j for j in judgements if j["sample"].split("/")[2] == case.question] if case.question else []
        statuses, supporting, reasons, agreed = [], [], [], True
        for k, s in enumerate(case.relevant, 1):
            pair = [j for j in mine if j["specified"] == f"Q{k}"]
            if not pair:
                statuses.append("not_established")
                reasons.append(f"{s.node}: not judged")
                continue
            status, items_, agree = _judged(pair, items)
            statuses.append(status)
            supporting += items_
            agreed &= agree
            if status != "supported":
                reasons.append(f"{s.node}: " + ", ".join(sorted({j["judgement"] for j in pair})))
        incompatible = statuses.count("supported")
        status = "supported" if incompatible == len(case.relevant) else "not_established"
        covering_unplaced = getattr(case, "unplaced_covering", None) or []
        if covering_unplaced:  # a purpose D specifies for data it could not place covers it: undecided
            status = "not_established"
            reasons.append(_unplaced(covering_unplaced))
        concerns.append(
            _concern(
                frame,
                r.id,
                **common,
                tier="reasoning",
                status=status,
                uncertainty=needs(
                    h["uncertainty"], FROM_DOC if agreed else raised(FROM_DOC, "samples_disagree"), of_d(case.relevant)
                ),
                observability="E2",
                reason=f"not compatible with {incompatible} of the {len(case.relevant)} purposes specified for its data"
                + (f"; {'; '.join(reasons)}" if reasons else ""),
                channels=sorted({ch for j in mine for ch in j["channels"]}),
                specified=sorted({d for s in case.relevant for d in s.declarations}),
                supporting=sorted(set(supporting)),
            )
        )
    return concerns, covered


def _unplaced(specified) -> str:
    """Why purposes specified for data D could not place leave concern (iv) undecided."""
    nodes = ", ".join(sorted({s.node for s in specified}))
    return f"D specifies {nodes} for data it could not place, which could be the practice's"


def less_invasive_alternative(
    frame: Frame,
    hypotheses: list[dict],
    alternatives: list[dict],
    judged: set[str],
    applicability: dict,
    experimental: list[dict] = (),
):
    """Concerns (v) and coverage per practice and supported inferred purpose, from the assessment stage's combined
    Alternative claims and the experiments' (`combine.experimental`) whose basis names the purpose; `judged` names
    the practices whose minimisation samples are kept."""
    r = frame.requirement("data_minimised")
    concerns, covered = [], []
    for h in hypotheses:
        if h["type"] != "purpose" or h["status"] != "supported":
            continue
        docs = [c for c in alternatives if c["basis"] == [h["id"]]]
        runs = [x for x in experimental if h["id"] in x["basis"] and x["type"] == "alternative"]
        if h["subject"] not in judged and not runs:
            continue
        covered.append(Covered(r.id, h["subject"], "reasoning"))
        mine = docs + runs
        if not mine:
            continue
        decisive = [c for c in mine if c["status"] == "supported" and c.get("level") != "plausible"]
        if decisive:
            status = "supported"
        elif all(c["status"] == "not_assessable" for c in mine):
            status = "not_assessable"
        else:
            status = "not_established"
        best = max(decisive, key=lambda c: combine.STRENGTH[c.get("strength", "own")]) if decisive else None
        node = h["purpose"]["node"]
        shown = [x for x in decisive if x.get("strength") == "run"]
        if shown:
            reason = "; ".join(
                f"{x['alternative']} demonstrated for {x['purpose']['id']} ({x['purpose']['node']}) of case {x['case']}"
                for x in shown
            )
        elif decisive:
            components = sorted({c["component"].rsplit(".", 1)[1] for c in decisive})
            reason = f"{len(decisive)} of {len(docs)} alternatives for {node} technically supported ({', '.join(components)})"
        elif status == "not_assessable":
            reason = next((x["reason"] for x in mine if x.get("reason")), "no premise could be assessed")
        else:
            reason = f"{len(docs)} alternatives for {node}, none supported by documents" + (
                f"; experiments: {', '.join(sorted({x['status'] for x in runs}))}" if runs else ""
            )
        if best is not None:
            uncertainty = needs(
                best["uncertainty"], h["uncertainty"], of("open_judgement", *([] if shown else ["not_demonstrated"]))
            )
        else:
            uncertainty = needs(h["uncertainty"], FROM_DOC)
        unobservable = status == "not_assessable" and any(
            x["sufficiency"].get("reason") == "oracle_not_observable" for x in runs
        )
        concerns.append(
            _concern(
                frame,
                r.id,
                subject=h["subject"],
                step="less_invasive_alternative",
                tier="reasoning",
                status=status,
                uncertainty=uncertainty,
                observability="E3" if unobservable else "E2",
                condition=_condition(applicability, r.id),
                basis=[c["id"] for c in decisive or mine],
                reason=reason,
                channels=sorted({ch for c in mine for ch in c["channels"]}),
                purpose=h["id"],
                supporting=sorted({x for c in decisive for x in c["supporting"]}),
            )
        )
    return concerns, covered


def declaration_contradicted(
    frame: Frame,
    contradictions: list,
    declaration_of: dict[str, str],
    items_of,
    applicability: dict,
    text_of: dict[str, str] | None = None,
):
    """
    Concerns (iii) and coverage, one per declaration that an O-D relation `contradicts` (correspondence.Relation).

    Args:
        contradictions: the O-D relations whose outcome is contradicts
        declaration_of: per D claim pointer (`<channel>:/<path>`), the declaration subject's id
        items_of: (declaration id, its relations) -> the evidence items the concern cites
        text_of: per declaration id, its text in the document, for the reason
    A frame without the requirement (gdpr-art5 before 1.1.0) states none: an assessment made with it is read again
    as it was made.
    """
    if "declaration_corresponds" not in frame.requirements:
        return [], []
    r = frame.requirement("declaration_corresponds")
    text_of = text_of or {}
    by_declaration: dict[str, list] = {}
    for rel in contradictions:
        for d in sorted({declaration_of[t["claim"]] for t in rel.to if t["claim"] in declaration_of}):
            by_declaration.setdefault(d, []).append(rel)
    concerns, covered = [], []
    if not _applies(applicability, r.id):
        return concerns, [Covered(r.id, d, "rule", False) for d in sorted(by_declaration)]
    for d, rels in sorted(by_declaration.items()):
        covered.append(Covered(r.id, d, "rule"))
        unconditional = any(not rel.condition for rel in rels)
        open_ = sorted({rel.condition for rel in rels if rel.condition})
        condition = _condition(applicability, r.id) + ([] if unconditional else [" or ".join(open_)])
        practices = sorted({rel.subject for rel in rels if rel.subject})
        said = text_of.get(d)
        reason = (f'"{said}": ' if said else "") + (
            f"contradicted by {len(practices)} observed practice{'s' if len(practices) != 1 else ''}"
            + ("" if unconditional else ", each under an open condition")
        )
        concerns.append(
            _concern(
                frame,
                r.id,
                subject=d,
                step="declaration_contradicted",
                tier="rule",
                status="supported",
                uncertainty=needs(*(rel.uncertainty for rel in rels), of(*(["open_condition"] if condition else []))),
                observability="E1",
                condition=condition,
                supporting=items_of(d, rels),
                reason=reason,
            )
        )
    return concerns, covered


def number(concerns: list[Concern]) -> None:
    """The concerns' ids, `concern:<subject>:<n>`, in order."""
    n: dict[str, int] = {}
    for c in concerns:
        n[c.subject] = n.get(c.subject, 0) + 1
        c.id = f"concern:{c.subject}:{n[c.subject]}"


def coverage(frame: Frame, covered: list[Covered]) -> list[dict]:
    """Per requirement, the subjects E assessed, those it does not apply to, and the channels: E's silence is what of
    the assessed subjects no concern names."""
    out: dict[str, dict] = {}
    for c in covered:
        entry = out.setdefault(
            c.requirement, {"requirement": c.requirement, "assessed": [], "not_applicable": [], "channels": []}
        )
        key = "assessed" if c.applies else "not_applicable"
        if c.subject not in entry[key]:
            entry[key].append(c.subject)
        if c.channel not in entry["channels"]:
            entry["channels"].append(c.channel)
    order = list(frame.requirements)
    return [
        {k: v for k, v in e.items() if v or k == "assessed"}
        for e in sorted(out.values(), key=lambda e: order.index(e["requirement"]) if e["requirement"] in order else 0)
    ]


def to_json(items) -> list[dict]:
    return [{k: v for k, v in asdict(i).items() if v not in (None, [])} for i in items]
