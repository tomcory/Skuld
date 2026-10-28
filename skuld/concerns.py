"""
E's concerns (E def:concern), by four rules:

    (i)   information not given, for the collection and a transparency requirement (rule tier): supported if its
          status is missing, citing what decides that it applies and D's silence on its label; supported under an
          open condition if missing_if. That no document bears the label is D's analysis not finding it, and no
          channel of D is exhaustive for a transparency requirement (assessment.EXHAUSTIVE), so U_s is moderate
    (ii)  not specific, for a declared purpose (reasoning tier): stated where a sample judges it not specific;
          supported if the samples' combined judgement is
    (iii) no specified purpose covers it, for a practice and a supported inferred purpose: stated where no purpose
          specified for the practice's data covers the inferred one; supported by rule if none is specified for its
          data, else by the reasoning tier if the combined judgement is that it is compatible with none of them
    (v)   a less invasive alternative, for a practice and a supported inferred purpose (reasoning tier): supported if a
          combined Alternative claim on one of its components is supported, technically supported by documents or
          demonstrated by an experiment for a case purpose ≈ it; not assessable if every premise is

A sample's judgement is combined across samples like any claim (combine.decide): a supported judgement of strength
doc decides over samples that name no concern, and the disagreement raises the concern's semantic uncertainty.

A concern's uncertainty is set by its step from its premises: U_t a comparison's where an experiment decides it; U_s
its purpose's, moderate for a judgement from documents, high where the samples disagree; U_n low for a requirement
tested by rule, moderate for a judgement of an open term, under an open condition moderate.

A concern never states that a requirement is met: what E assessed and stated no concern for is its coverage
(`coverage`), relative to the documents D acquired and could access.
"""

from dataclasses import asdict, dataclass, field

from ratatoskr.frames import Frame

from skuld import combine
from skuld.assessment import exhaustive
from skuld.transparency import INCOMPLETE, MISSING, MISSING_IF, NOT_APPLICABLE, UNREAD, Status
from skuld.uncertainty import highest

VERSION = "9"
COMPONENT = {"role": "method", "id": "skuld.concerns", "version": VERSION}

#: Of a rule-tier concern of information not given: as certain as D's annotations and O's claims it reads
BY_RULE = {"t": "not_applicable", "s": "low", "n": "low"}
#: Of a reasoning-tier judgement from documents
FROM_DOC = {"t": "not_applicable", "s": "moderate", "n": "moderate"}


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
        uncertainty = {**BY_RULE, "n": "moderate"} if conditional else dict(BY_RULE)
        if open_silence or unread:
            uncertainty["s"] = "moderate"
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
        return [], [Covered(r.id, s.declarations[0], "rule", False) for s in statements]
    concerns, covered = [], []
    for s in statements:
        mine = [j for j in judgements if j["statement"] == s.id]
        if not mine:
            continue
        channels = sorted({ch for j in mine for ch in j["channels"]})
        covered.append(Covered(r.id, s.declarations[0], "reasoning"))
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
                uncertainty=FROM_DOC if agreed else {**FROM_DOC, "s": "high"},
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
    """Concerns (iii) and coverage per practice and supported inferred purpose (judge.Limitation), from the
    compatibility samples' judgements. Both steps rest on D's classification of the specified purposes and their data,
    so a concern takes the semantic uncertainty `declared` gives each of them (D's, read leniently); one that rests on
    there being no specified purpose for the data reads the silence of channels exhaustive for no purpose, so U_s is at
    least moderate."""
    declared = declared or {}

    def of_d(specified) -> str:
        levels = [declared[d]["s"] for s in specified for d in s.declarations if d in declared]
        return highest(*levels) if levels else "not_applicable"

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
        if not case.relevant:
            concerns.append(
                _concern(
                    frame,
                    r.id,
                    **common,
                    tier="rule",
                    status="supported",
                    uncertainty={**BY_RULE, "s": highest(h["uncertainty"]["s"], "moderate")},
                    observability="E2",
                    reason=f"no purpose is specified for {node}'s data",
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
        concerns.append(
            _concern(
                frame,
                r.id,
                **common,
                tier="reasoning",
                status=status,
                uncertainty={
                    "t": "not_applicable",
                    "s": highest(h["uncertainty"]["s"], "moderate" if agreed else "high", of_d(case.relevant)),
                    "n": "moderate",
                },
                observability="E2",
                reason=f"not compatible with {incompatible} of the {len(case.relevant)} purposes specified for its data"
                + (f"; {'; '.join(reasons)}" if reasons else ""),
                channels=sorted({ch for j in mine for ch in j["channels"]}),
                specified=sorted({d for s in case.relevant for d in s.declarations}),
                supporting=sorted(set(supporting)),
            )
        )
    return concerns, covered


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
        purpose_s = h["uncertainty"]["s"]
        if best is not None:
            uncertainty = {
                "t": best["uncertainty"]["t"],
                "s": highest(best["uncertainty"]["s"], purpose_s, "low" if shown else "moderate"),
                "n": "moderate",
            }
        else:
            uncertainty = {**FROM_DOC, "s": highest(purpose_s, "moderate")}
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
