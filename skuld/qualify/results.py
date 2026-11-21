"""
The qualified results (plan/archive/QUALIFICATION_PLAN.md §3): for a case, or a row of a section, the steps of the precedence are
taken in order; the first that holds is the result, and every later step that also holds is a secondary reason. Each
step records what made it hold.

    1  externally established discrepancy  an O–D relation is ≠ by rule, under no condition, and is no omission
    2  externally supported concern        a concern is supported under neither a source nor an applicability
                                           condition; an O–D relation is ≠ under a fact condition only; an omission
                                           (≠ on the silence of channels that need not declare every case) under no
                                           source condition
    3  insufficient or conflicting         a symbol is conflict; a concern is conflicted or not established, or
       evidence                            supported only under a source or an applicability condition; an O–D
                                           relation is ≠ under a source condition; a requirement that applies was not
                                           assessed
    4  not externally assessable           a concern is not assessable, or a gap's next step is an audit request
                                           (what only the controller could show; Ratatoskr 0.39.0: a gap carries
                                           no level, its next step says whether an external step remains)
    5  no concern detected within the      none of the above, and the case was assessed for a requirement
       tested scope

Where none of 1–4 holds and no requirement applies to the case (a declaration O does not observe, a requirement of
the collection that does not apply), its result is `not_applicable`: no qualified result, since nothing was assessed,
and counted apart from the five (`CASE_ORDER`). Its reason says why: declared but not observed by O, declared with no
observation of O relating to it, or the requirements that do not apply.

A case holds the concerns of its declared purposes (purpose specificity) `aside`: they are decided in the purposes' rows
(8.8), and the case lists each, last among its secondary reasons, as the result its row gives it.

Concerns with status not_applicable or refuted name no step. The rules read a `View` of the case, so that review
triggers and next steps can test a resolution on a copy (triggers.py, nextsteps.py) and add no rule of their own.
"""

import copy
from dataclasses import dataclass, field

from skuld.qualify import symbols
from skuld.qualify.conditions import APPLICABILITY, FACT, SOURCE

#: 3: a supported concern of minimisation names the strength of its evidence (documented, demonstrated) (18 Nov 2026)
#: 4: an omission (O≠D on the silence of channels that need not declare every case) is an externally supported
#: concern, not a discrepancy; a concern under an applicability condition is insufficient evidence (framework report
#: 0.6, def:qualification; 18 Nov 2026); 5: step 4 reads a gap whose next step is an audit request, not a level
#: (Ratatoskr 0.39.0, OBSERVABILITY_PLAN §9; 21 Nov 2026)
VERSION = "5"
COMPONENT = {"role": "method", "id": "skuld.qualify.results", "version": VERSION}

DISCREPANCY = "externally_established_discrepancy"
CONCERN = "externally_supported_concern"
INSUFFICIENT = "insufficient_or_conflicting_evidence"
NOT_ASSESSABLE = "not_externally_assessable"
NO_CONCERN = "no_concern_detected"
NOT_APPLICABLE = "not_applicable"
ORDER = (DISCREPANCY, CONCERN, INSUFFICIENT, NOT_ASSESSABLE, NO_CONCERN)  # the qualified results
CASE_ORDER = (*ORDER, NOT_APPLICABLE)  # the results of a case or a row
NAMES = {
    DISCREPANCY: "Externally established discrepancy",
    CONCERN: "Externally supported concern",
    INSUFFICIENT: "Insufficient or conflicting evidence",
    NOT_ASSESSABLE: "Not externally assessable",
    NO_CONCERN: "No concern detected within the tested scope",
    NOT_APPLICABLE: "Not applicable",
}


@dataclass
class Rel:
    id: str
    type: str
    outcome: str
    symbol: str
    condition: str | None = None  # fact or source
    aspect: str | None = None
    text: str | None = None  # the condition's text
    high: bool = False  # its uncertainty is high
    partial: str | None = None  # for corresponds_partially: broader, related, root_category
    omission: bool = False  # O≠D that reads only the silence of channels not exhaustive for the predicate


@dataclass
class Con:
    id: str
    requirement: str
    step: str
    status: str
    condition: str | None = None  # fact or source
    conditions: list[str] = field(default_factory=list)
    high: bool = False
    basis: list[str] = field(default_factory=list)
    evidence: str | None = None  # rule, documented or demonstrated (attributes.evidence)


@dataclass
class Gap:
    id: str
    reason: str
    next: str  # the kind of its next step
    of: str | None = None
    held: str | None = None  # for an audit request: what the controller holds that it requests

    @property
    def audit(self) -> bool:
        """Whether only the controller could settle it: its next step is an audit request."""
        return self.next == "audit_request"


@dataclass
class Unassessed:
    requirement: str
    subject: str
    why: str
    gap: str | None = None  # the gap that explains it (S-23)


@dataclass
class View:
    """What the rules read of a case or a row."""

    relations: list[Rel] = field(default_factory=list)
    concerns: list[Con] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    unassessed: list[Unassessed] = field(default_factory=list)
    assessed: list[str] = field(default_factory=list)  # the requirements it was assessed for
    inapplicable: list[str] = field(default_factory=list)  # the requirements that do not apply to it
    aside: list[Con] = field(default_factory=list)  # concerns of its declared purposes, decided in their rows

    def copy(self) -> "View":
        return copy.deepcopy(self)

    def of_type(self, kind: str) -> list[Rel]:
        return [r for r in self.relations if r.type == kind]

    def symbol(self, kind: str) -> tuple[str, bool, list[str]]:
        """The case's symbol for a relation type, whether it is conditional, and the relations it rests on."""
        rels = self.of_type(kind)
        s, conditional = symbols.combine([(r.symbol, r.condition is not None) for r in rels])
        return s, conditional, [r.id for r in rels if r.symbol == s]


@dataclass
class Step:
    result: str
    reason: str
    rests_on: list[str]


def _od(view: View, condition) -> list[Rel]:
    return [r for r in view.of_type("O-D") if r.symbol == symbols.DISAGREE and r.condition == condition]


def _aspect(r: Rel) -> str:
    how = r.outcome.replace("_", " ") + (f", {r.partial.replace('_', ' ')}" if r.partial else "")
    return f"O≠D on {r.aspect or 'the practice'} ({how})"


def _list(parts: list[str], most: int = 4) -> str:
    """Parts in order of first mention, each repeated one counted once (×n)."""
    counts: dict[str, int] = {}
    for x in parts:
        counts[x] = counts.get(x, 0) + 1
    named = [f"{x} (×{n})" if n > 1 else x for x, n in counts.items()]
    shown = named[:most]
    return "; ".join(shown) + (f"; and {len(named) - most} more" if len(named) > most else "")


def steps(view: View) -> list[Step]:
    """Every step of the precedence that holds, in order; if none of 1–4 holds, step 5 where the case was assessed for
    a requirement, else not applicable."""
    out: list[Step] = []
    found = [r for r in _od(view, None) if not r.omission]
    if found:
        out.append(Step(DISCREPANCY, _list([_aspect(r) for r in found]), [r.id for r in found]))
    supported = [c for c in view.concerns if c.status == "supported" and c.condition not in (SOURCE, APPLICABILITY)]
    under_fact = _od(view, FACT)
    omitted = [r for r in _od(view, None) if r.omission]
    if supported or under_fact or omitted:
        parts = [
            f"{c.requirement} ({c.step.replace('_', ' ')}"
            + (f", {c.evidence}" if c.step == "less_invasive_alternative" and c.evidence else "")
            + ")"
            + (" if " + ", ".join(c.conditions) if c.conditions else "")
            for c in supported
        ] + [f"{_aspect(r)} if {r.text or 'a condition holds'}" for r in under_fact]
        parts += [f"{_aspect(r)}: an omission, not a denial" for r in omitted]
        rests = [c.id for c in supported] + [r.id for r in under_fact] + [r.id for r in omitted]
        out.append(Step(CONCERN, _list(parts), rests))
    parts, rests = [], []
    conflicts = [r for r in view.relations if r.symbol == symbols.CONFLICT]
    if conflicts:
        parts.append("conflicting evidence on " + ", ".join(sorted({r.type for r in conflicts})))
        rests += [r.id for r in conflicts]
    for c in view.concerns:
        if c.status in ("conflicted", "not_established"):
            parts.append(f"{c.requirement} {c.status.replace('_', ' ')}")
            rests.append(c.id)
        elif c.status == "supported" and c.condition == SOURCE:
            parts.append(f"{c.requirement} supported only if {', '.join(c.conditions)}")
            rests.append(c.id)
        elif c.status == "supported" and c.condition == APPLICABILITY:
            parts.append(f"{c.requirement} supported only if it applies: {', '.join(c.conditions)}")
            rests.append(c.id)
    for r in _od(view, SOURCE):
        unread = [c.split(":", 1)[-1].replace("_", " ") for c in (r.text or "").split(", ") if c]
        parts.append(f"{_aspect(r)} only if the {' and the '.join(unread) or 'unread source'} declares no more")
        rests.append(r.id)
    if view.unassessed:
        by_why: dict[str, list[str]] = {}
        for u in view.unassessed:
            by_why.setdefault(u.why, [])
            if u.requirement not in by_why[u.why]:
                by_why[u.why].append(u.requirement)
        parts += [f"{', '.join(reqs)} not assessed: {why}" for why, reqs in by_why.items()]
        rests += sorted({u.gap for u in view.unassessed if u.gap})
    if parts:
        out.append(Step(INSUFFICIENT, _list(parts), rests))
    beyond = [c for c in view.concerns if c.status == "not_assessable"]
    external = [g for g in view.gaps if g.audit]
    if beyond or external:
        parts = [f"{c.requirement} not assessable" for c in beyond] + [
            f"{g.reason.replace('_', ' ')} (an audit request: {g.held})" for g in external
        ]
        out.append(Step(NOT_ASSESSABLE, _list(sorted(set(parts))), [c.id for c in beyond] + [g.id for g in external]))
    if not out and view.assessed:
        out.append(Step(NO_CONCERN, f"assessed for {', '.join(sorted(set(view.assessed)))} with no concern", []))
    elif not out:
        out.append(_not_applicable(view))
    return out


def _not_applicable(view: View) -> Step:
    unseen = [r for r in view.of_type("O-D") if r.outcome == "declared_without_observation"]
    if unseen:
        return Step(NOT_APPLICABLE, "declared, not observed by O", [r.id for r in unseen])
    if view.inapplicable:
        reqs = sorted(set(view.inapplicable))
        return Step(NOT_APPLICABLE, f"{', '.join(reqs)} {'does' if len(reqs) == 1 else 'do'} not apply", [])
    return Step(NOT_APPLICABLE, "declared, and nothing O observed relates to it", [])


def result(view: View) -> str:
    return steps(view)[0].result


def qualified(view: View) -> dict:
    """The result with its reason, what it rests on and the secondary reasons."""
    found = steps(view)
    first = found[0]
    return {
        "result": first.result,
        "reason": f"{NAMES[first.result]}: {first.reason}",
        "rests_on": first.rests_on,
        "secondary": [
            {"result": s.result, "reason": f"{NAMES[s.result]}: {s.reason}", "rests_on": s.rests_on} for s in found[1:]
        ]
        + _aside(view),
    }


def _aside(view: View) -> list[dict]:
    """The concerns of the case's declared purposes, each as the result its row gives it (8.8); a refuted one gives
    none."""
    out = []
    for c in view.aside:
        found = steps(View(concerns=[c], assessed=[c.requirement]))[0]
        if found.result == NO_CONCERN:
            continue
        reason = f"{NAMES[found.result]}: {found.reason} of a declared purpose, decided in its row"
        out.append({"result": found.result, "reason": reason, "rests_on": found.rests_on})
    return out
