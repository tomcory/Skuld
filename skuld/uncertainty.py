"""
E's uncertainty (Ratatoskr 0.34.0, `ratatoskr.uncertainty`): one level with the reasons that set it, set where a
claim or concern is made, from what it rests on. A result is low unless a reason raises it.

E's reasons, where they are set:

    from_documents           moderate  a model's judgement grounded in cited documents: a stage-1 claim and a
                                       reasoning-tier claim from documents; a reasoning-tier concern
    own_knowledge            high      a model's judgement resting on its own knowledge (a stage-1 or reasoning-tier
                                       claim that cites no document)
    samples_disagree         high      the samples of a judgement disagree (concerns (ii), (iv))
    open_judgement           moderate  a judgement of an open term of the norms: specific, compatible, minimal
                                       (concerns (ii), (iv), (v))
    open_condition           moderate  the result holds under an open condition (concern (i) missing_if; concern (iii)
                                       with a condition)
    silence_not_exhaustive   moderate  a silence read on a channel not exhaustive for it: concern (i) with a silent
                                       channel not exhaustive or a document incomplete or unread; concern (iv) by rule,
                                       which rests on there being no specified purpose; an O–D relation
                                       observed_without_declaration with a silent channel not exhaustive
    o_silence                moderate  an O–D relation declared_without_observation, which reads O's silence
    aligned_above            moderate  an experimental claim combined with a hypothesis purpose aligned at a node above
                                       the case purpose (≈, combine C1)
    purpose_not_from_feature moderate  an experimental premise whose purpose is not its feature's
    unverifiable             moderate  a comparison with a part of its runs unverifiable
    runs_not_alternated      moderate  a comparison whose runs did not alternate
    few_runs                 moderate  a comparison with a side of fewer than MIN_RUNS runs
    not_demonstrated         moderate  concern (v) on an alternative documented, not demonstrated by a run

O's and D's reasons pass through unchanged into practices, declarations, relations and concerns; D's are read
leniently, every one at most D_AT_MOST (assessment.py): D rates a value its model placed high while its analysis is
unmeasured. A report O or D made before Ratatoskr 0.34.0 states factor levels ({f, t, s, n}) and no reason; E reads
its uncertainty as low, with no reason (`read`; a whole report with `converted`, which observe.py applies before it
checks an O report against the schema).

Combination: what a result rests on together is `needs` (the highest level, every reason): a relation over its
practice and declarations, a concern over its premises, a conflicted combined claim over all its members, an
aggregated concern over its members. Alternatives that establish the same are `either` (the alternative of the
lowest level, with its own reasons): a practice over its O claims, a combined claim over the members that agree with
its status.

A claim's uncertainty is a function of its kind and premises, used to set its concerns' and not stored; the
assessment names it (CLAIMS):

    stage-1 and reasoning-tier claims   from_documents where it cites documents, else own_knowledge
    experimental claims                 the comparisons' (unverifiable, runs_not_alternated, few_runs), with
                                        purpose_not_from_feature, and aligned_above where combined with a hypothesis
                                        purpose aligned by a node above it; a combined claim either over its agreeing
                                        members

Until 0.8.0, E stated three factors per result (technical t, semantic s, normative n), each with its own level.
"""

from ratatoskr.uncertainty import (
    HIGH,
    LEVELS,
    LOW,
    MODERATE,
    REASONS,
    capped,
    check,
    either,
    is_high,
    needs,
    of,
    raised,
)

#: The version of the rules above for claims; raise it when they change. 2: one level with its reasons (Ratatoskr
#: 0.34.0), for factor levels {t, s, n}
VERSION = "2"
CLAIMS = {"function": "skuld.uncertainty", "version": VERSION}

__all__ = [
    "CLAIMS",
    "HIGH",
    "LEVELS",
    "LOW",
    "MODERATE",
    "REASONS",
    "capped",
    "check",
    "converted",
    "either",
    "has",
    "is_high",
    "needs",
    "of",
    "raised",
    "read",
    "text",
]


def read(u: dict | None) -> dict:
    """The uncertainty of a claim of O or D as E reads it: as stated, or low with no reason where the report states
    none, or states factor levels (a report made before Ratatoskr 0.34.0), since a factor level names no reason."""
    if not isinstance(u, dict) or "level" not in u:
        return of()
    return needs(u)


def converted(record):
    """A report of O or D with every uncertainty stated as factor levels (made before Ratatoskr 0.34.0) read as low
    with no reason (`read`), so that it conforms to the schema of 0.34.0; a report in the new shape is unchanged."""
    if isinstance(record, list):
        return [converted(x) for x in record]
    if not isinstance(record, dict):
        return record
    return {
        k: read(v) if k == "uncertainty" and isinstance(v, dict) and "level" not in v else converted(v)
        for k, v in record.items()
    }


def has(u: dict | None, reason: str) -> bool:
    """Whether a reason sets part of the uncertainty."""
    return any(r["reason"] == reason for r in (u or {}).get("reasons", ()))


def text(u: dict) -> str:
    """The uncertainty for a reader: its level, and its reasons with their levels ("high: samples disagree, open judgement
    (moderate)")."""
    reasons = [
        r["reason"].replace("_", " ") + (f" ({r['level']})" if r["level"] != u["level"] else "")
        for r in u.get("reasons", ())
    ]
    return u["level"] + (f": {', '.join(reasons)}" if reasons else "")
