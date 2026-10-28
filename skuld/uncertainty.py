"""
E's uncertainty: per factor a level, set where a claim or concern is made, from what it rests on.

    U_t  technique: of a comparison, low only if no part of its verification is unverifiable, its runs alternated and
         each side has enough runs; not applicable where no run is read
    U_s  purposes and alignment: low for a case's purpose from its feature, moderate from documents or a component, or
         for an alignment by the nearest node above; high from the model's own knowledge
    U_n  norms: low for a requirement tested by rule; moderate for a judgement of an open term (specific, compatible,
         minimal) citing the norms; not applicable for a premise claim, which reads no norm

A claim's uncertainty is a function of its kind and premises, used to set its concerns' and not stored; the
assessment names it (CLAIMS):

    stage-1 and reasoning-tier claims   U_t not applicable; U_s moderate where an agreeing sample cites documents,
                                        else high; U_n not applicable
    experimental claims                 U_t the comparison's; U_s low for the case's purpose, moderate where combined
                                        with a hypothesis purpose aligned by a node above it (≈) or decided by one
                                        from documents; U_n not applicable

The framework's factual uncertainty U_f is not stated: no record E reads is damaged or extracted by a heuristic, so it
would be low throughout. `not_applicable` is below `low`: a factor that applies to a premise applies to what rests on
it.
"""

#: The version of the rules above for claims; raise it when they change
VERSION = "1"
CLAIMS = {"function": "skuld.uncertainty", "version": VERSION}

ORDER = ("not_applicable", "low", "moderate", "high")
FACTORS = ("t", "s", "n")


def highest(*levels: str) -> str:
    return max(levels, key=ORDER.index)


def joined(*uncertainties: dict) -> dict:
    """Per factor, the highest level of the uncertainties."""
    return {f: highest(*(u[f] for u in uncertainties)) for f in FACTORS}
