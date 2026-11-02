"""
The symbols of qualification (QUALIFICATION_PLAN.md §2.2): each relation reduced to agree (≈), disagree (≠), unknown
(?) or conflict, by fixed tables over the outcomes of `expectation_assessment`; per relation type, a case's symbol;
and the case's triangulation pattern, read against the framework's table.

"Not established" is unknown, never disagree. An outcome the tables do not know is an error, not a guess: a new
outcome of Skuld needs a row here first.
"""

VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.qualify.symbols", "version": VERSION}

AGREE, DISAGREE, UNKNOWN, CONFLICT, NONE = "agree", "disagree", "unknown", "conflict", "none"
SIGN = {AGREE: "≈", DISAGREE: "≠", UNKNOWN: "?", CONFLICT: "conflict", NONE: "–"}

#: O–D outcomes; corresponds_partially is read by its partial alignment (PARTIAL)
O_D = {
    "corresponds_exactly": AGREE,
    "corresponds_hierarchically": AGREE,
    "contradicts": DISAGREE,
    "observed_without_declaration": DISAGREE,
    "not_comparable": UNKNOWN,
    "insufficient_evidence": UNKNOWN,
    "declared_without_observation": NONE,  # makes a declaration-only case
}
#: corresponds_partially by its alignment: a root-category recipient agrees (its vagueness is E's to raise), siblings
#: disagree, O's node above the declared ones is unknown (a next step re-analyses it)
PARTIAL = {"root_category": AGREE, "related": DISAGREE, "broader": UNKNOWN}
O_E = {
    "functional_dependency_supported": AGREE,
    "recipient_dependency_supported": AGREE,
    "alternative_technically_supported": DISAGREE,
    "alternative_demonstrated": DISAGREE,
    "conflicting": CONFLICT,
    "no_functional_dependency_established": UNKNOWN,
    "recipient_dependency_not_established": UNKNOWN,
    "insufficient_evidence": UNKNOWN,
    "not_assessable": UNKNOWN,
}
D_E = {
    "justification_supported": AGREE,
    "justification_partially_supported": AGREE,
    "declared_necessity_refuted": DISAGREE,
    "justification_conflicted": CONFLICT,
    "justification_not_established": UNKNOWN,
    "purpose_too_vague": UNKNOWN,
    "not_comparable": UNKNOWN,
    "not_assessable": UNKNOWN,
}
TABLES = {"O-D": O_D, "O-E": O_E, "D-E": D_E}

#: The framework's table of triangulation patterns (framework.tex, tab:triangulation), in its order
READINGS = (
    ((AGREE, AGREE, AGREE), "no discrepancy or justificatory challenge identified within the scope"),
    ((DISAGREE, AGREE, None), "behaviour differs from the declaration but is independently supported"),
    ((AGREE, DISAGREE, DISAGREE), "behaviour and declaration correspond, but the justification is independently challenged"),
    ((DISAGREE, DISAGREE, None), "behaviour is inconsistent with the declaration and independently challenged"),
)
E_UNRESOLVED = "the independent justification is unresolved or not externally assessable"


class UnknownOutcome(ValueError):
    """An outcome no table has a row for."""


def symbol(relation: dict) -> str:
    """A relation's symbol by the tables."""
    table = TABLES[relation["type"]]
    outcome = relation["outcome"]
    if relation["type"] == "O-D" and outcome == "corresponds_partially":
        partial = relation.get("partial")
        if partial not in PARTIAL:
            raise UnknownOutcome(f"{relation.get('id')}: corresponds_partially without a known partial ({partial!r})")
        return PARTIAL[partial]
    if outcome not in table:
        raise UnknownOutcome(f"{relation.get('id')}: {relation['type']} outcome {outcome!r} has no row")
    return table[outcome]


def combine(symbols: list[tuple[str, bool]]) -> tuple[str, bool]:
    """A relation type's symbol for a case from its relations' (symbol, conditional): conflict if any is; else ≠ if
    any is (unconditional before conditional); else ≈ if any is; else ?; none without relations."""
    present = [s for s in symbols if s[0] != NONE]
    if not present:
        return NONE, False
    if any(s == CONFLICT for s, _ in present):
        return CONFLICT, False
    disagree = [c for s, c in present if s == DISAGREE]
    if disagree:
        return DISAGREE, all(disagree)
    if any(s == AGREE for s, _ in present):
        return AGREE, False
    return UNKNOWN, False


def reading(od: str, oe: str, de: str) -> str | None:
    """The framework's reading of a pattern, or None for one outside its table."""
    for (a, b, c), text in READINGS:
        if od == a and oe == b and (c is None or de == c):
            return text
    if oe in (UNKNOWN, NONE) and de in (UNKNOWN, NONE):
        return E_UNRESOLVED
    return None
