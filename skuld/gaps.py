"""
What E could not establish, the propositions it bears on, and its next step (plan/archive/OBSERVABILITY_PLAN.md §4,
§8; Ratatoskr 0.39.0). A gap carries no observability level: it names the propositions it bears on (`bears_on`, each
in words and by reference), which carry theirs, declared where the propositions are:

    requirement:<id>                     the frame's, per requirement (a concern's level and a silence's)
    condition:<id>                       the frame's, per applicability condition
    definition:<definitions id>/<aspect> ratatoskr.channels.DEFINITIONS (Google Play's sharing, ephemeral processing)
    role:<node>                          recipient-roles' x-observability (ThirdParty: not a processor)
    reading:root-category                here, beside correspondence's rule (READINGS)
    scope:<kind>                         here: a denial limited to a jurisdiction, a user group or a product, or under
                                         a condition of its own (READINGS), which the run's scope settles where it can
    claim:<id>                           E's claims: a Purpose E2 (what the controller pursues), a Dependency or an
                                         Alternative of a purpose achieved on servers E3 (record), on the device E1

A frame that declares no levels (gdpr-art5 before 1.4.0) is read with the levels the current frame declares for the
same requirement or condition: a level belongs to the proposition, not to the frame's version.

A gap's next step (`next`: kind, text, and `held` for an audit request) is the external step that could still change
it, if there is one; otherwise an audit request to the controller for what it holds (`held`, the held of the
proposition). The level does not choose the step; it bounds it: a proposition of complete reach never ends in an
audit request (`check`, which refuses it).

    own_knowledge                  extend_corpus; with gaps.own_knowledge_exhausted (config.json, default off: D4,
                                   measured first), an audit_request (organisation: the purposes pursued, Arts.
                                   13(1)(c), 30) where the corpus holds the recipient's or actor's documentation
    not_admitted                   experiment for a minimisation concern or a Dependency or Alternative claim (repeat
                                   the comparison), else re-analyse (the reasoning tier asked again)
    purpose_vague                  review
    substitute_more_invasive       review
    purpose_not_in_vocabulary      re-analyse
    oracle_not_observable          improve_instrument where the purpose is achieved on the device (or where it is not
                                   known where); audit_request (record) where on servers
    source_not_analysable          improve_instrument (encrypted, binary: a decoder, a hook), explore (damaged,
                                   truncated: another run), by O's reason for the practice's payloads
    requirements_not_reached       explore
    needs_run, search_space_not_run, intervention_not_verified, substitution_not_verifiable, not_covered,
    precondition_failed            experiment
    source_absent, not_comparable  acquire
    applicability_unknown          only for the frame's applicability conditions: the condition's external step
                                   where its reach is not none (CONDITION_STEPS), else audit_request with its held

A concern's other conditions are no gaps: a source condition (a document not analysed or acquired incomplete) and a
fact condition of an O–D relation (a channel's definition, a role, the root-category reading, the denial's own scope
or condition) are open conditions that name the propositions they bear on (`bears_on`), whose steps qualification
takes by the same rule (`condition_step`). The run's scope settles a denial's scope and condition first (scope.py): a
condition it settles is no open condition and has no step.
"""

import functools
import re

from ratatoskr import channels
from ratatoskr.frames import Frame
from ratatoskr.observability import COMPLETE, NONE, ORGANISATION, PARTIAL, RECORD, declare
from ratatoskr.observability import check as check_level

#: 1 (21 Nov 2026): gaps bear on propositions and have a structured next step (Ratatoskr 0.39.0)
VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.gaps", "version": VERSION}

ACQUIRE, EXPLORE, EXPERIMENT, REANALYSE, EXTEND, REVIEW, INSTRUMENT, AUDIT = (
    "acquire",
    "explore",
    "experiment",
    "re-analyse",
    "extend_corpus",
    "review",
    "improve_instrument",
    "audit_request",
)
KINDS = (ACQUIRE, EXPLORE, EXPERIMENT, REANALYSE, EXTEND, REVIEW, INSTRUMENT, AUDIT)

#: The propositions Skuld names beside its rules, with their levels: the reading of a denial labelled only with the
#: root category (correspondence), and a denial's own scope and condition, which the run's scope settles where it can
READINGS = {
    "reading:root-category": {
        "proposition": "a denial labelled only with the root category of data means the data observed",
        "observability": declare(
            PARTIAL, ORGANISATION, "the text, read by a person; what the provider meant, beyond it"
        ),
    },
    "scope:jurisdiction": {
        "proposition": "the denial's jurisdiction is the user's",
        "observability": declare(
            PARTIAL,
            RECORD,
            "the indicators by which the application places its user (egress country, store country, locale), where "
            "they agree; how it places them is its configuration",
        ),
    },
    "scope:user_group": {
        "proposition": "the persona belongs to the user group the denial is limited to",
        "observability": declare(
            PARTIAL, RECORD, "the persona's age; how the application tells the group, its records"
        ),
    },
    "scope:product": {
        "proposition": "the product the denial is limited to is the application observed",
        "observability": declare(PARTIAL, RECORD, "what was observed; which products the provider means, its records"),
    },
    "scope:condition": {
        "proposition": "the denial's own condition held when the data were sent",
        "observability": declare(
            PARTIAL, RECORD, "the consent state and what the persona did in the run; the rest, the provider's records"
        ),
    },
}
#: The external step of a proposition whose reach is not none: (kind, text)
CONDITION_STEPS = {
    "personal_data_collected": (EXPLORE, "a run that reaches the processing (its absence holds only within coverage)"),
    "recipients_exist": (EXPLORE, "a run that reaches a transmission (their absence holds only within coverage)"),
    "dpo_designated": (ACQUIRE, "the provider's published documents (Art. 37(7): the DPO's contact is published)"),
    "purpose_declared": (ACQUIRE, "the provider's documents, analysed in full"),
    "reading:root-category": (REVIEW, "a person reads the denial's text and decides whether it means the data"),
    "scope:jurisdiction": (EXPLORE, "a run whose egress country, store country and locale agree"),
    "scope:user_group": (EXPLORE, "a run with a persona of a recorded age"),
    "scope:product": (REVIEW, "a person decides whether the product the denial names is the application"),
    "scope:condition": (REVIEW, "a person decides from the run whether the denial's condition held"),
}
#: O's reasons a payload could not be read for which another run is the step (damaged in capture, cut off); every
#: other reason (encrypted by the application, binary, an unsupported format, a connection not intercepted) asks for
#: an instrument
DAMAGED = ("damaged", "truncated", "truncated_record")
#: The reasons whose next step is an experiment
EXPERIMENTS = (
    "needs_run",
    "search_space_not_run",
    "intervention_not_verified",
    "substitution_not_verifiable",
    "not_covered",
    "precondition_failed",
)
#: Of a claim of E's: what the controller holds about it
PURPOSE_CLAIM = declare(PARTIAL, ORGANISATION, "what the controller pursues with the data is its own")
ON_SERVERS = declare(NONE, RECORD, "a purpose achieved on servers: their configuration and logs")
ON_DEVICE = declare(COMPLETE, None, "a purpose achieved on the device: what the device shows")


class NextStepError(AssertionError):
    """A gap whose next step is an audit request for a proposition the observer's evidence settles completely."""


def step(kind: str, text: str, held: str | None = None) -> dict:
    """A next step: {kind, text, held (only for an audit request)}."""
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is no next-step kind")
    if (kind == AUDIT) != (held is not None):
        raise ValueError("an audit request, and only one, names what the controller holds (held)")
    return {"kind": kind, "text": text, **({"held": held} if held else {})}


def bearing(ref: str, proposition: str) -> dict:
    return {"proposition": proposition, "ref": ref}


@functools.cache
def _current(frame_id: str) -> Frame | None:
    try:
        return Frame.load(frame_id)
    except Exception:  # noqa: BLE001 - a frame that is not bundled has no current version to read levels from
        return None


def frame_level(frame: Frame, kind: str, pid: str, which: str = "concern") -> dict | None:
    """A requirement's (its concern's or silence's) or a condition's declared level, from the frame, else from the
    current version of the frame where the frame declares none (gdpr-art5 before 1.4.0)."""
    for f in (frame, _current(frame.id) if frame is not None else None):
        if f is None:
            continue
        if kind == "requirement" and pid in f.requirements and f.requirements[pid].observability:
            return f.requirements[pid].observability.get(which)
        if kind == "condition" and pid in f.conditions and f.conditions[pid].observability:
            return f.conditions[pid].observability
    return None


def role_level(node: str) -> tuple[str, dict] | None:
    """The proposition a denial's naming of a recipient role adds, with its level, from recipient-roles'
    x-observability; None for a role without one."""
    from skuld.common import vocabulary

    try:
        found = vocabulary("recipient-roles").nodes.get(node)
    except Exception:  # noqa: BLE001 - a vocabulary that is not bundled declares nothing
        return None
    entry = dict((found.extra or {}).get("observability") or {}) if found is not None else {}
    if not entry:
        return None
    proposition = entry.pop("proposition", node)
    check_level(entry)
    return proposition, entry


def level_of(ref: str, frame: Frame | None, claims: dict[str, dict] | None = None) -> dict | None:
    """The declared level of a proposition by its reference; None where none is declared."""
    kind, _, pid = ref.partition(":")
    if kind in ("requirement", "condition"):
        return frame_level(frame, kind, pid) if frame is not None else None
    if kind == "definition":
        definitions, _, aspect = pid.rpartition("/")
        found = channels.definition(definitions, aspect)
        return found["observability"] if found else None
    if kind == "role":
        found = role_level(pid)
        return found[1] if found else None
    if ref in READINGS:
        return READINGS[ref]["observability"]
    if kind == "claim" and claims is not None and pid in claims:
        return claim_level(claims[pid])
    return None


def claim_level(claim: dict, achieved_on: str | None = None) -> dict | None:
    """The level of an E claim's proposition (OBSERVABILITY_PLAN §4): a Purpose's E2; a Dependency's or an
    Alternative's by where its purpose is achieved, E3 on servers, E1 on the device; None where that is not known."""
    if claim.get("type") == "purpose":
        return PURPOSE_CLAIM
    where = achieved_on or (claim.get("purpose") or {}).get("achieved_on")
    return {"server": ON_SERVERS, "device": ON_DEVICE}.get(where)


def condition_step(ref: str, level: dict | None, what: str) -> dict:
    """The next step of a condition, a definition, a role or a reading that no dimension decided: its external step
    where its reach is not none, else an audit request for what the controller holds. A proposition without a declared
    level has no audit request: a person reviews it."""
    key = ref.split(":", 1)[1] if ref.startswith("condition:") else ref
    if level is not None and level["reach"] != NONE:
        kind, text = CONDITION_STEPS.get(key, (REVIEW, "a person decides it from what was observed and published"))
        return step(kind, f"{text}: {what}")
    if level is None:
        return step(REVIEW, f"a person decides whether {what}")
    source = level.get("source") or "the controller's records"
    return step(AUDIT, f"ask the controller for {source}: {what}", level["held"])


def payload_step(reasons: list[str], what: str) -> dict:
    """The next step of a practice whose content O could not read, by O's reasons for its payloads: another run where
    every one was damaged in capture, else an instrument (a decoder, a hook)."""
    if reasons and all(r in DAMAGED for r in reasons):
        return step(EXPLORE, f"another run, whose capture of {what} is whole")
    named = ", ".join(sorted({r.replace("_", " ") for r in reasons})) or "encrypted or binary"
    return step(INSTRUMENT, f"decode or hook what {what} carries ({named}), then observe again")


def oracle_step(achieved_on: str | None, what: str) -> dict:
    """oracle_not_observable: an oracle on the device where the purpose is achieved there (or where it is not known
    where), an audit request for the servers' records where it is achieved on servers."""
    if achieved_on == "server":
        return step(AUDIT, f"ask the controller for the records of its servers that show whether {what}", RECORD)
    where = "on the device" if achieved_on == "device" else "on the device, if it shows there (where is not known)"
    return step(INSTRUMENT, f"an oracle that observes {what} {where}")


def reason_step(
    reason: str,
    what: str,
    *,
    claim_type: str | None = None,
    requirement: str | None = None,
    achieved_on: str | None = None,
    payloads: list[str] | None = None,
    exhausted: bool = False,
) -> dict:
    """The next step of a gap by its reason (the table above), for a gap about `what`. `claim_type` and `requirement`
    say what a not_admitted gap is of (a claim's type, a concern's requirement), `achieved_on` where the purpose of an
    oracle_not_observable gap is achieved, `payloads` O's reasons for an unread practice's payloads, `exhausted` that
    the corpus holds the documentation an own_knowledge gap asks for and gaps.own_knowledge_exhausted is on (D4).
    applicability_unknown's step is the condition's (`condition_step`)."""
    if reason == "own_knowledge":
        if exhausted:
            return step(
                AUDIT,
                f"ask the controller for {what} it pursues (Arts. 13(1)(c), 30): the corpus documents the recipient or "
                "actor, and the purpose stays unestablished",
                ORGANISATION,
            )
        return step(EXTEND, f"documentation for {what} in the corpus, and the stage asked again")
    if reason == "not_admitted":
        if claim_type in ("dependency", "alternative") or requirement == "data_minimised":
            return step(EXPERIMENT, f"repeat the comparison, or an experiment that decides {what}")
        return step(REANALYSE, f"ask the reasoning tier again: {what}")
    if reason == "purpose_vague":
        return step(REVIEW, f"a person states the purpose's action, object and outcome: {what}")
    if reason == "substitute_more_invasive":
        return step(REVIEW, f"a person judges what the fallback to a datum at least as invasive means: {what}")
    if reason == "purpose_not_in_vocabulary":
        return step(REANALYSE, f"place the node in the purpose map (skuld purposes map), or ask again: {what}")
    if reason == "oracle_not_observable":
        return oracle_step(achieved_on, what)
    if reason == "source_not_analysable":
        return payload_step(payloads or [], what)
    if reason == "requirements_not_reached":
        return step(EXPLORE, f"a goal-directed run that reaches what {what} needs")
    if reason in EXPERIMENTS:
        return step(EXPERIMENT, f"an experiment that decides {what}")
    if reason in ("source_absent", "not_comparable"):
        return step(ACQUIRE, f"the source that {what} needs")
    raise ValueError(f"the gap reason {reason!r} has no next step here")


def check(gap: dict, frame: Frame | None, claims: dict[str, dict] | None = None) -> None:
    """Refuses a gap whose next step is an audit request although a proposition it bears on is of complete reach."""
    if gap["next"]["kind"] != AUDIT:
        return
    for b in gap["bears_on"]:
        level = level_of(b["ref"], frame, claims)
        if level is not None and level["reach"] == COMPLETE:
            raise NextStepError(f"{gap['id']}: an audit request for {b['ref']}, of complete reach")


def unit(gap: dict) -> str:
    """What a gap is counted by: a condition of a concern, a claim, a practice, a requirement, a comparison or case,
    the collection."""
    if gap["reason"] == "applicability_unknown":
        return "a condition of a concern"
    of = str(gap.get("of") or "")
    if of.startswith("claim:"):
        return "a claim"
    if of.startswith("concern:"):
        return "a concern"
    if of == "collection":
        return "the collection"
    if re.match(r"^P-", of) or re.match(r"^gap:P-", gap["id"]):
        return "a practice"
    if of:
        return "a requirement"
    return "a case"
