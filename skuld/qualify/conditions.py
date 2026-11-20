"""
The three kinds of condition (QUALIFICATION_PLAN.md §2.4; framework report 0.6, def:qualification).

    source  that a source was read or acquired in full: a concern's condition `analysed:<channel>` or
            `complete:<channel>`; a relation's condition of kind `source`. A finding under it rests on a missing source:
            insufficient evidence, next step acquire the channel.
    applicability  that a requirement applies to its subject: one of the frame's applicability conditions
            (`applies_if`: a DPO designated, automated decision-making in use, a transfer to a third country, data
            obtained elsewhere than from the data subject). A concern under it may concern a requirement that does not
            apply at all: insufficient evidence, next step an audit request to the provider (the gap
            applicability_unknown; since version 2, 18 Nov 2026)
    fact    every other condition: a fact about the processing no dimension could establish (a recipient acting as a
            service provider or a third party). A finding under it holds qualified by it: at most an externally
            supported concern, next step review.

A finding with several kinds counts by the first of source, applicability and fact.
"""

VERSION = "2"
COMPONENT = {"role": "method", "id": "skuld.qualify.conditions", "version": VERSION}

SOURCE, APPLICABILITY, FACT = "source", "applicability", "fact"
#: The prefixes of a concern's source conditions (transparency.py), with what each says of the channel
SOURCE_PREFIXES = {"analysed:": "analysed", "complete:": "acquired complete"}


def kind(condition_id: str, applicability=frozenset()) -> str:
    """The kind of a concern's condition, by its id; `applicability` holds the frame's applicability conditions."""
    if any(condition_id.startswith(p) for p in SOURCE_PREFIXES):
        return SOURCE
    return APPLICABILITY if condition_id in applicability else FACT


def channel(condition_id: str) -> str | None:
    """The channel a source condition names, or None."""
    for prefix in SOURCE_PREFIXES:
        if condition_id.startswith(prefix):
            return condition_id.removeprefix(prefix)
    return None


def of_concern(concern: dict, applicability=frozenset()) -> str | None:
    """The kind a concern's conditions make it: source if any is, else applicability if any is, else fact if any is,
    else None."""
    kinds = {kind(c, applicability) for c in concern.get("condition") or ()}
    for k in (SOURCE, APPLICABILITY, FACT):
        if k in kinds:
            return k
    return None


def of_relation(relation: dict) -> str | None:
    """The kind of a relation's condition, or None; until every relation states one, a condition is a fact."""
    if not relation.get("condition"):
        return None
    return relation.get("condition_kind") or FACT
