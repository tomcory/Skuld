"""A builder of minimal valid assessments (expectation_assessment) for qualification's unit tests: a practice, its
declarations, chosen outcomes, concerns, gaps and conditions."""

import copy

O = "a" * 64  # noqa: E741 (the Observation dimension)
D = "b" * 64
LOW = {"level": "low", "reasons": []}
#: A gap reason's next step by default (OBSERVABILITY_PLAN §8)
KIND = {
    "own_knowledge": "extend_corpus",
    "not_admitted": "re-analyse",
    "purpose_vague": "review",
    "substitute_more_invasive": "review",
    "purpose_not_in_vocabulary": "re-analyse",
    "oracle_not_observable": "improve_instrument",
    "source_not_analysable": "improve_instrument",
    "requirements_not_reached": "explore",
    "source_absent": "acquire",
    "not_comparable": "acquire",
    "applicability_unknown": "audit_request",
}
HIGH = {"level": "high", "reasons": [{"reason": "samples_disagree", "level": "high"}]}

#: The frame's requirements by the kind of their subject, as qualification reads them
REQUIREMENTS = {
    "purpose_specified": "practice",
    "purpose_compatible": "practice",
    "data_minimised": "practice",
    "purpose_specific": "declaration",
    "processing_purpose": "collection",
}


class Assessment:
    def __init__(self, with_d: bool = True):
        self.report = {
            "report": {
                "created": "2026-11-01T12:00:00Z",
                "skuld": "0",
                "components": [],
                "claims": {
                    "attributes": {"polarity": "+"},
                    "determined": {"uncertainty": {"function": "x", "version": "1"}},
                },
            },
            "application": {"package": "app.example", "version": "1"},
            "frame": {"id": "gdpr-art5", "version": "1", "sha256": "c" * 64},
            "inputs": {
                "observation": [{"path": "o.json", "sha256": O}],
                "declaration": {"path": "d.json", "sha256": D} if with_d else None,
                "named": [],
                **({"comparability": {"comparable": True}} if with_d else {}),
            },
            "sources": {"items": [], "acquisition": {"observation_report": "acquired"}},
            "subjects": {
                "practices": [],
                "declarations": [],
                "collection": {"documents": [], "transparency": []} if with_d else None,
            },
            "features": [],
            "evidence": [],
            "relations": [],
            "claims": [],
            "concerns": [],
            "coverage": [],
            "passed_on": [],
            "cases": [],
            "open": [],
            "gaps": [],
        }
        self.n = 0

    def practice(
        self,
        pid="P-1",
        data="device-or-other-ids.advertising-id",
        recipient="adco",
        claim_type="transmits",
        actor="component:adco",
        party="other",
    ) -> str:
        self.report["subjects"]["practices"].append(
            {
                "id": pid,
                "claim_type": claim_type,
                "data": data,
                "recipient": recipient,
                "actor": actor,
                "party": {"relation": party, "basis": ["test"]} if party else None,
                "claims": [{"dimension": "O", "report": O, "claim": f"c-{pid}"}],
            }
        )
        return pid

    def declaration(
        self, did, claim, kind="practice", type_="declares_collection", data="device-or-other-ids", value=None
    ) -> str:
        d = {
            "id": did,
            "claim": {"dimension": "D", "report": D, "claim": claim},
            "kind": kind,
            "type": type_,
            "channel": claim.split(":", 1)[0],
            "polarity": "+",
            "data": data,
        }
        if value is not None:
            d["value"] = value
        self.report["subjects"]["declarations"].append(d)
        return did

    def relation(self, type_, outcome, subject, to=(), aspect="data", **fields) -> str:
        self.n += 1
        rid = f"relation:{subject}:{self.n}"
        of = {"dimension": "O", "report": O, "claim": f"c-{subject}"}
        if subject.startswith("D-"):
            d = next(x for x in self.report["subjects"]["declarations"] if x["id"] == subject)
            of = d["claim"]
        refs = []
        for t in to:
            d = next((x for x in self.report["subjects"]["declarations"] if x["id"] == t), None)
            refs.append(d["claim"] if d else {"dimension": "E", "claim": t})
        r = {
            "id": rid,
            "type": type_,
            "tier": "rule",
            "outcome": outcome,
            "of": of,
            "to": refs,
            "subject": subject,
            "aspect": aspect,
            "uncertainty": LOW,
            **fields,
        }
        if r.get("condition") and "condition_kind" not in r:
            r["condition_kind"] = "fact"
        self.report["relations"].append(r)
        return rid

    def concern(
        self,
        subject,
        requirement="data_minimised",
        status="supported",
        step="less_invasive_alternative",
        condition=(),
        uncertainty=LOW,
        basis=(),
    ) -> str:
        self.n += 1
        cid = f"concern:{subject}:{self.n}"
        self.report["concerns"].append(
            {
                "id": cid,
                "subject": subject,
                "requirement": requirement,
                "principle": "p",
                "provisions": ["x"],
                "step": step,
                "tier": "reasoning",
                "status": status,
                "uncertainty": uncertainty,
                **({"condition": list(condition)} if condition else {}),
                "basis": list(basis),
            }
        )
        return cid

    def gap(self, subject, reason, of=None, kind=None, held=None, **fields) -> str:
        """A gap with its next step: `kind` (and `held` for an audit request), else the kind its reason has by default
        (OBSERVABILITY_PLAN §8)."""
        self.n += 1
        gid = f"gap:{subject}:{self.n}"
        kind = kind or KIND.get(reason, "experiment")
        if kind == "audit_request":
            held = held or "record"
        self.report["gaps"].append(
            {
                "id": gid,
                **({"of": of} if of else {}),
                "proposition": f"p {gid}",
                "required": "r",
                "reason": reason,
                "bears_on": [{"proposition": f"p {gid}", "ref": f"requirement:{subject}"}],
                "next": {"kind": kind, "text": "t", **({"held": held} if held else {})},
                **fields,
            }
        )
        return gid

    def open(self, text, qualifies, kind="fact") -> str:
        oid = f"open:{len(self.report['open']) + 1}"
        self.report["open"].append({"id": oid, "text": text, "qualifies": list(qualifies), "kind": kind, "from": "E"})
        return oid

    def covered(self, requirement, assessed=(), not_applicable=()) -> None:
        entry = next((c for c in self.report["coverage"] if c["requirement"] == requirement), None)
        if entry is None:
            entry = {"requirement": requirement, "assessed": []}
            self.report["coverage"].append(entry)
        entry["assessed"] += list(assessed)
        if not_applicable:
            entry.setdefault("not_applicable", []).extend(not_applicable)

    def assessed_for_practice(self, pid) -> None:
        for r, kind in REQUIREMENTS.items():
            if kind == "practice":
                self.covered(r, [pid])

    def transparency(self, requirement, status, applicability="applies", conditions=()) -> None:
        self.report["subjects"]["collection"]["transparency"].append(
            {
                "requirement": requirement,
                "applicability": applicability,
                "status": status,
                **({"conditions": list(conditions)} if conditions else {}),
            }
        )

    def document(self, channel, complete=True) -> None:
        """An analysed document of D's, acquired complete or not."""
        self.report["subjects"]["collection"]["documents"].append(
            {
                "channel": channel,
                "document": f"{channel}.json",
                "status": "analysed",
                "complete": complete,
                **({} if complete else {"incomplete": "incomplete as acquired"}),
            }
        )

    def build(self) -> dict:
        return copy.deepcopy(self.report)
