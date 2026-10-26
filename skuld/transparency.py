"""
The transparency status of the collection, per requirement of the frame that a document addresses (E def:transparency).

    addressed        a declaration of an accessible document bears the requirement's label (either polarity)
    not_applicable   otherwise, if the requirement does not apply
    missing          otherwise, if it applies
    missing_if       otherwise: missing if its undecided conditions hold

The annotations and the accessibility are D's (its report, schema 3); the applicability is decided from O's and D's
claims together (frame.py). The status is one of the collection, not of a document: information may be layered.
"""

from dataclasses import dataclass, field

from ratatoskr.frames import Frame

from skuld.assessment import Subjects
from skuld.frame import Decision

ADDRESSED, NOT_APPLICABLE, MISSING, MISSING_IF = "addressed", "not_applicable", "missing", "missing_if"


@dataclass
class Status:
    requirement: str
    applicability: str
    status: str
    conditions: list[str] = field(default_factory=list)  # for missing_if: the undecided conditions
    addressed_by: list[dict] = field(default_factory=list)  # pointers into D's report
    decided_by: dict[str, dict] = field(default_factory=dict)  # condition -> what decided it, by dimension


def statuses(frame: Frame, subjects: Subjects, decided: dict[str, Decision], d_sha256: str) -> list[Status]:
    """The collection's status for each requirement a document addresses; empty without D."""
    if subjects.collection is None:
        return []
    labelled: dict[str, list[dict]] = {}
    for n, document in enumerate(subjects.collection["documents"]):
        if document["status"] != "analysed" or not document.get("accessible"):
            continue
        for m, a in enumerate(document.get("annotations", [])):
            pointer = f"/channels/{n}/annotations/{m}"
            labelled.setdefault(a["requirement"], []).append({"dimension": "D", "report": d_sha256, "claim": pointer})
    values = {cid: d.value for cid, d in decided.items()}
    out = []
    for r in frame.labelled():
        app = frame.applicability(r, values)
        undecided = [c.id for c in frame.undecided(r, values)]
        evidence = {cid: {"holds": decided[cid].holds, "fails": decided[cid].fails} for cid in r.applies_if}
        if labelled.get(r.label):
            out.append(Status(r.id, app, ADDRESSED, addressed_by=labelled[r.label], decided_by=evidence))
        elif app == "does_not_apply":
            out.append(Status(r.id, app, NOT_APPLICABLE, decided_by=evidence))
        elif app == "applies":
            out.append(Status(r.id, app, MISSING, decided_by=evidence))
        else:
            out.append(Status(r.id, app, MISSING_IF, conditions=undecided, decided_by=evidence))
    return out
