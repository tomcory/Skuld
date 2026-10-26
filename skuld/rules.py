"""
The experimental channel's status rule: claims read from a case's comparisons, by rule, without a model. For a purpose
p and a component ε of the baseline u_0:

- Dependency(ε, p) reads the comparison of the removal u_0 \\ ε: one claim with its value. If the removal breaks p,
  essential is supported; if it preserves p, not_dependent is supported if no measurement of the oracle is worse in
  any run under the removal, quality_dependent if one is worse in every run, and otherwise essential is refuted (p
  survives without ε, its quality undecided). An undecided comparison establishes no value. A component without a
  removal in the search space has no Dependency claim.
- Alternative(u', u_0, p, demonstrated) is supported by a comparison of u' that preserves p and refuted by one that
  breaks it.

A claim is not applicable if ε is not a component of u_0, and not assessable if p is vague or has no observable
oracle. A comparison is in the supporting evidence of the claim it makes supported and in the challenging evidence
of the claim it makes refuted. Without a comparison, the claim is not established, with the reason none was made.
"""

from dataclasses import dataclass, field

from skuld.comparison import Comparison
from skuld.inputs import Alternative, Case, Component, Purpose


@dataclass
class Claim:
    """A claim of the experimental channel of a case. `missing` and `why` (a gap reason) say what would settle it."""

    type: str
    purpose: str
    component: str
    status: str
    relationship: str | None = None
    alternative: str | None = None
    supporting: list[str] = field(default_factory=list)
    challenging: list[str] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    reason: str | None = None
    missing: list[str] = field(default_factory=list)
    why: str | None = None


def precondition(purpose: Purpose, component: Component, present: bool) -> tuple[str, str, str] | None:
    """(status, reason, gap reason) for a claim no comparison can decide, or None."""
    if not present:
        return "not_applicable", "not a component of the baseline configuration", "not_covered"
    if purpose.specificity == "vague":
        return "not_assessable", "the purpose is too vague", "purpose_vague"
    if purpose.oracle is None:
        return "not_assessable", "the purpose has no observable oracle", "oracle_not_observable"
    return None


def _read(claim: Claim, comparison: Comparison, status: str) -> None:
    claim.status = status
    claim.comparisons = [comparison]
    (claim.supporting if status == "supported" else claim.challenging).append(comparison.evidence)


def dependency(purpose: Purpose, component: Component, comparison: Comparison | None, missing_why: str) -> Claim:
    """The Dependency claim a comparison of the removal reads."""
    claim = Claim("dependency", purpose.id, component.id, "not_established")
    if comparison is None:
        claim.missing, claim.why = [f"a comparison of the removal of {component.id}"], missing_why
        claim.reason = "the removal was not compared"
        return claim
    worse = set(comparison.worse.values())
    if comparison.outcome == "breaks":
        claim.relationship = "essential"
        _read(claim, comparison, "supported")
    elif comparison.outcome == "preserves" and worse <= {"none"}:
        claim.relationship = "not_dependent"
        _read(claim, comparison, "supported")
    elif comparison.outcome == "preserves" and "all" in worse:
        claim.relationship = "quality_dependent"
        _read(claim, comparison, "supported")
    elif comparison.outcome == "preserves":
        claim.relationship = "essential"
        _read(claim, comparison, "refuted")
    else:
        claim.comparisons = [comparison]
        claim.missing, claim.why = ["a comparison that preserves or breaks the purpose"], "not_admitted"
        claim.reason = "the comparison of the removal is undecided"
    return claim


def alternative(purpose: Purpose, alt: Alternative, comparison: Comparison | None, missing_why: str) -> Claim:
    claim = Claim("alternative", purpose.id, alt.component, "not_established", alternative=alt.id)
    if comparison is None:
        claim.missing, claim.why = [f"a comparison of {alt.id}"], missing_why
        claim.reason = f"{alt.id} was not compared"
    elif comparison.outcome == "preserves":
        _read(claim, comparison, "supported")
    elif comparison.outcome == "breaks":
        _read(claim, comparison, "refuted")
    else:
        claim.comparisons = [comparison]
        claim.missing, claim.why = ["a comparison that preserves or breaks the purpose"], "not_admitted"
        claim.reason = f"the comparison of {alt.id} is undecided"
    return claim


def claims(
    case: Case,
    present: dict[str, bool],
    comparisons: dict[tuple[str, str], Comparison],
    missing_why: dict[tuple[str, str], str],
    invalid: set[str] = frozenset(),
) -> list[Claim]:
    """
    Every claim of the experimental channel of a case.

    Args:
        present: Per component, whether it is a component of u_0
        comparisons: By (purpose, alternative)
        missing_why: By (purpose, alternative) without a comparison, the gap reason: 'search_space_not_run',
            'intervention_not_verified' or 'precondition_failed'
        invalid: Alternatives that are no members of the search space (not less invasive than u_0 in their
            component's dimension); they have no claims
    """
    out = []
    for purpose in case.purposes:
        for component in case.components:
            alternatives = [a for a in case.alternatives if a.component == component.id and a.id not in invalid]
            removal = next((a for a in alternatives if a.removal), None)
            pre = precondition(purpose, component, present[component.id])
            if pre:
                status, reason, why = pre
                made = [Claim("dependency", purpose.id, component.id, status)] if removal else []
                made += [Claim("alternative", purpose.id, a.component, status, alternative=a.id) for a in alternatives]
                for c in made:
                    c.reason, c.why, c.missing = reason, why, [reason]
                out += made
                continue

            def why(a: Alternative, purpose=purpose) -> str:
                return missing_why.get((purpose.id, a.id), "search_space_not_run")

            if removal is not None:
                out.append(dependency(purpose, component, comparisons.get((purpose.id, removal.id)), why(removal)))
            out += [alternative(purpose, a, comparisons.get((purpose.id, a.id)), why(a)) for a in alternatives]
    return out
