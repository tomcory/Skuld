"""
The experimental channel's status rule: claims read from an experimental case's comparisons, by rule, without a model.
For a purpose p and a component ε of the baseline u_0:

- Dependency(ε, p) reads the comparison of the removal u_0 \\ ε: one claim with its value. If the removal breaks p,
  essential is supported; if it preserves p while the application fell back to a substitute (another datum of its
  kind, `Comparison.substitutes`), substitutable is supported, naming the substitutes: p needs a datum of that kind,
  not ε (21 Nov 2026; before, such a comparison read as not_dependent); if it preserves p without a substitute,
  not_dependent is supported if no measurement of the oracle is worse in any run under the removal,
  quality_dependent if one is worse in every run, and otherwise essential is refuted (p survives without ε, its
  quality undecided). An undecided comparison establishes no value. A component without a removal in the search
  space has no Dependency claim.
- Alternative(u', u_0, p, demonstrated) is supported by a comparison of u' that preserves p and refuted by one that
  breaks it. Where the application fell back to substitutes under u', u' achieved p with them, so the claim is
  supported only if every substitute is at most as invasive as the component's datum by the data vocabulary's order
  (⊴, `configuration.coarser`: the App Set ID is coarser than the advertising ID); otherwise it is not established,
  with the reason naming the substitute.

A claim is not applicable if ε is not a component of u_0, and not assessable if p is vague or has no observable
oracle. A comparison is in the supporting evidence of the claim it makes supported and in the challenging evidence
of the claim it makes refuted. Without a comparison, the claim is not established, with the reason none was made.
"""

from dataclasses import dataclass, field

from ratatoskr.vocabularies import Vocabulary

from skuld.comparison import Comparison
from skuld.configuration import coarser
from skuld.inputs import Alternative, Case, Component, Purpose

#: The status rule as a named method of the report: 2 since a removal the application survived by a substitute is
#: substitutable, and an alternative survived by a substitute more invasive than its datum is not demonstrated
#: (21 Nov 2026); 1 was recorded as Skuld's version
VERSION = "2"
COMPONENT = {"role": "method", "id": "skuld.rules", "version": VERSION}


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


def precondition(purpose: Purpose, present: bool) -> tuple[str, str, str] | None:
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
    elif comparison.outcome == "preserves" and comparison.substitutes:
        claim.relationship = "substitutable"
        _read(claim, comparison, "supported")
        claim.reason = f"the application fell back to {_named(comparison.substitutes)}"
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


def _named(substitutes: list[str]) -> str:
    return ("the substitute " if len(substitutes) == 1 else "the substitutes ") + ", ".join(substitutes)


def more_invasive(substitutes: list[str], node: str | None, data: Vocabulary | None) -> list[str]:
    """The substitutes not at most as invasive as the datum `node` by the data vocabulary's order (⊴); every one where
    the datum or the vocabulary is unknown, since then none is shown to be."""
    if node is None or data is None:
        return list(substitutes)
    return [s for s in substitutes if not coarser(s, node, data)]


def alternative(
    purpose: Purpose,
    alt: Alternative,
    comparison: Comparison | None,
    missing_why: str,
    component: Component | None = None,
    data: Vocabulary | None = None,
) -> Claim:
    """The Alternative claim a comparison of u' reads; `component` is the alternative's component and `data` the data
    vocabulary, by which its substitutes are ordered against the component's datum."""
    claim = Claim("alternative", purpose.id, alt.component, "not_established", alternative=alt.id)
    worse = more_invasive(comparison.substitutes, component.node if component else None, data) if comparison else []
    if comparison is None:
        claim.missing, claim.why = [f"a comparison of {alt.id}"], missing_why
        claim.reason = f"{alt.id} was not compared"
    elif comparison.outcome == "preserves" and worse:
        claim.comparisons = [comparison]
        claim.missing = [f"a comparison of an alternative to {alt.id} that also withholds {', '.join(worse)}"]
        claim.why = "not_admitted"
        claim.reason = (
            f"under {alt.id} the application fell back to {_named(worse)}, not at most as invasive as "
            f"{(component.node if component else None) or 'its datum'}"
        )
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
    data: Vocabulary | None = None,
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
        data: The data vocabulary, which orders a comparison's substitutes against the component's datum
    """
    out = []
    for purpose in case.purposes:
        for component in case.components:
            alternatives = [a for a in case.alternatives if a.component == component.id and a.id not in invalid]
            removal = next((a for a in alternatives if a.removal), None)
            pre = precondition(purpose, present[component.id])
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
            out += [
                alternative(purpose, a, comparisons.get((purpose.id, a.id)), why(a), component, data)
                for a in alternatives
            ]
    return out
