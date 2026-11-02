"""
The two kinds of condition (QUALIFICATION_PLAN.md §2.4).

    source  that a source was read or acquired in full: a concern's condition `analysed:<channel>` or
            `complete:<channel>`; a relation's condition of kind `source`. A finding under it rests on a missing source:
            insufficient evidence, next step acquire the channel.
    fact    every other condition: a fact about the processing no dimension could establish (a recipient acting as a
            third party, a DPO designated). A finding under it holds qualified by it: at most an externally supported
            concern, next step review.

A finding with both kinds counts by its source condition.
"""

VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.qualify.conditions", "version": VERSION}

SOURCE, FACT = "source", "fact"
#: The prefixes of a concern's source conditions (transparency.py), with what each says of the channel
SOURCE_PREFIXES = {"analysed:": "analysed", "complete:": "acquired complete"}


def kind(condition_id: str) -> str:
    """The kind of a concern's condition, by its id."""
    return SOURCE if any(condition_id.startswith(p) for p in SOURCE_PREFIXES) else FACT


def channel(condition_id: str) -> str | None:
    """The channel a source condition names, or None."""
    for prefix in SOURCE_PREFIXES:
        if condition_id.startswith(prefix):
            return condition_id.removeprefix(prefix)
    return None


def of_concern(concern: dict) -> str | None:
    """The kind a concern's conditions make it: source if any is, fact if any is, else None."""
    kinds = {kind(c) for c in concern.get("condition") or ()}
    return SOURCE if SOURCE in kinds else FACT if kinds else None


def of_relation(relation: dict) -> str | None:
    """The kind of a relation's condition, or None; until every relation states one, a condition is a fact."""
    if not relation.get("condition"):
        return None
    return relation.get("condition_kind") or FACT
