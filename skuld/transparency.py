"""
The transparency status of the collection, per requirement of the frame that a document addresses (E def:transparency).

    addressed        a declaration of an accessible document bears the requirement's label (either polarity)
    not_applicable   otherwise, if the requirement does not apply
    missing          otherwise, if it applies
    missing_if       otherwise: missing if its undecided conditions hold

The annotations are views of D's derived documents (ratatoskr.tilt.annotations; D's report, schema 4), and every
analysed document is accessible; the applicability is decided from O's and D's claims together (frame.py). The status
is one of the collection, not of a document: information may be layered.

As D's rules do, E reads the silence of a complete, analysed document only: where a document Sága acquired incomplete
is silent, the information may be in the part it did not acquire, and where a document was acquired but D could not
analyse it, or its acquisition failed, the information may be in it; the status is then missing_if, under the condition
`complete:<channel>` or `analysed:<channel>` that it does not give it (INCOMPLETE, UNREAD). A channel without a
document (absent) is no such condition: the provider gives none.
"""

from dataclasses import dataclass, field

from ratatoskr.frames import Frame

from skuld.assessment import Subjects
from skuld.frame import Decision

ADDRESSED, NOT_APPLICABLE, MISSING, MISSING_IF = "addressed", "not_applicable", "missing", "missing_if"
#: The prefix of the condition that an incomplete document's missing part does not give the information
INCOMPLETE = "complete:"
#: The prefix of the condition that a document D could not analyse, or failed to acquire, does not give the information
UNREAD = "analysed:"
#: The channel statuses of a document that exists but was not read
NOT_READ = ("not_analysable", "failed")


@dataclass
class Status:
    requirement: str
    applicability: str
    status: str
    conditions: list[str] = field(default_factory=list)  # for missing_if: the undecided conditions
    addressed_by: list[dict] = field(default_factory=list)  # D's values, <channel>:<JSON Pointer>
    decided_by: dict[str, dict] = field(default_factory=dict)  # condition -> what decided it, by dimension
    silent: list[str] = field(default_factory=list)  # for missing and missing_if: the channels whose silence it reads


def statuses(frame: Frame, subjects: Subjects, decided: dict[str, Decision], d_sha256: str) -> list[Status]:
    """The collection's status for each requirement a document addresses; empty without D."""
    if subjects.collection is None:
        return []
    labelled: dict[str, list[dict]] = {}
    read, incomplete = [], []
    for document in subjects.collection["documents"]:
        if document["status"] in NOT_READ:
            incomplete.append(UNREAD + document["channel"])
        if document["status"] != "analysed":
            continue
        read.append(document["channel"])
        if not document.get("complete", True):
            incomplete.append(INCOMPLETE + document["channel"])
        for a in document.get("annotations", []):
            value = f"{document['channel']}:{a['path']}"
            labelled.setdefault(a["requirement"], []).append({"dimension": "D", "report": d_sha256, "claim": value})
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
        elif app == "applies" and not incomplete:
            out.append(Status(r.id, app, MISSING, decided_by=evidence, silent=sorted(set(read))))
        else:
            conditions = undecided + sorted(set(incomplete))
            out.append(
                Status(r.id, app, MISSING_IF, conditions=conditions, decided_by=evidence, silent=sorted(set(read)))
            )
    return out
