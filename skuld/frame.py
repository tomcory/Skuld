"""
The normative frame (Ratatoskr's `gdpr-art5`) and the decisions of its applicability conditions.

Each condition has an evaluator that says what each dimension's claims establish, that it holds or that it fails,
with the items that do, a provider's denials among them; `Frame.decide` then counts a dimension only in a direction
the frame lets it decide, so that a provider's denial, though recorded, never makes a requirement inapplicable. D's declarations count from any of its documents,
accessible or not: a declaration in a document that is not accessible addresses no requirement but shows that a
condition holds.

    personal_data_collected   holds by O: a practice transmits data; by D: a declaration of collection
                              fails by O: O established that no data is transmitted
    recipients_exist          holds by O: a practice transmits to another organisation (parties.py); by D: a
                              declared recipient
    third_country_transfer    holds by O: a recipient whose jurisdiction is known and outside the EEA; by D: a
                              declared transfer
    not_from_data_subject     holds by D: the documents name sources of data other than the data subject
    basis_*                   holds or fails by D: the legal bases (Art. 6(1)) the documents reference
    dpo_designated, adm_in_use  holds by D: a DPO named, automated decision-making declared in use
    purpose_declared          holds or fails by D: a declared purpose, or none in an analysed report
"""

from dataclasses import asdict, dataclass, field

from ratatoskr.frames import Frame

from skuld.assessment import Subjects

OBS, DEC = "O", "D"
#: The EEA's countries (EU, Iceland, Liechtenstein, Norway), by ISO 3166-1 alpha-2
EEA = frozenset("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS LI NO".split())
#: The letters of Art. 6(1) each basis condition reads
BASES = {"basis_f": {"f"}, "basis_e_or_f": {"e", "f"}, "basis_a_or_b": {"a", "b"}, "basis_a": {"a"}}


@dataclass
class Decision:
    condition: str
    value: str
    holds: dict[str, list] = field(default_factory=dict)  # dimension -> the items that establish it holds
    fails: dict[str, list] = field(default_factory=dict)


@dataclass
class Evidence:
    """What the evaluators read: the subjects, and the parts of O's and D's reports they need."""

    subjects: Subjects
    o_statuses: list[dict]
    d_documents: list[dict]  # D's derived documents, every analysed channel


def evidence(subjects: Subjects, o_reports: list[dict], d_report: dict | None) -> Evidence:
    statuses = [s for r in o_reports for s in r.get("statuses", [])]
    documents = [ch["tilt"] for ch in (d_report or {}).get("channels", []) if ch.get("tilt")]
    return Evidence(subjects, statuses, documents)


def _declared(e: Evidence, claim_type: str, polarity: str = "+") -> list[dict]:
    return [d.claim for d in e.subjects.declarations if d.type == claim_type and d.polarity == polarity]


def _transmits(e: Evidence) -> list:
    return [p for p in e.subjects.practices if p.claim_type == "transmits"]


def _absent(e: Evidence, claim_type: str, node: str = "data") -> list[dict]:
    """O's established absences of a cell, for every recipient: a cell that lists hosts of payloads it could not
    search (`not_found_for`, Observation report 0.7) establishes no absence for those, so it decides no condition."""
    return [
        s
        for s in e.o_statuses
        if (s["claim_type"], s["node"], s["status"]) == (claim_type, node, "absence_established")
        and not s.get("not_found_for")
    ]


def _bases(e: Evidence) -> set[str]:
    return {
        str(b.get("reference", "")).rsplit("-", 1)[1]
        for doc in e.d_documents
        for item in doc.get("dataDisclosed", [])
        for b in item.get("legalBases", [])
        if str(b.get("reference", "")).startswith("GDPR-6-1-")
    }


def _evaluate(condition: str, e: Evidence) -> tuple[dict, dict]:
    holds, fails = {}, {}
    if condition == "personal_data_collected":
        holds[OBS] = [p.id for p in _transmits(e)]
        holds[DEC] = _declared(e, "declares_collection")
        fails[OBS] = _absent(e, "transmits")
        fails[DEC] = _declared(e, "declares_collection", "-")
    elif condition == "recipients_exist":
        holds[OBS] = [p.id for p in _transmits(e) if (p.party or {}).get("relation") == "other"]
        holds[DEC] = _declared(e, "declares_recipient")
        fails[DEC] = _declared(e, "declares_recipient", "-")
    elif condition == "third_country_transfer":
        holds[OBS] = [p.id for p in _transmits(e) if any(j not in EEA for j in p.jurisdictions)]
        holds[DEC] = _declared(e, "declares_transfer")
        fails[DEC] = _declared(e, "declares_transfer", "-")
    elif condition == "not_from_data_subject":
        holds[DEC] = [_document(doc) for doc in e.d_documents if doc.get("sources")]
    elif condition in BASES:
        declared = _bases(e)
        if declared:
            (holds if declared & BASES[condition] else fails)[DEC] = sorted(declared)
    elif condition == "dpo_designated":
        holds[DEC] = [_document(doc) for doc in e.d_documents if doc.get("dataProtectionOfficer")]
    elif condition == "adm_in_use":
        holds[DEC] = [
            _document(doc) for doc in e.d_documents if (doc.get("automatedDecisionMaking") or {}).get("inUse")
        ]
    elif condition == "purpose_declared":
        purposes = _declared(e, "declares_purpose")
        if purposes:
            holds[DEC] = purposes
        elif e.subjects.collection is not None and any(
            d["status"] == "analysed" for d in e.subjects.collection["documents"]
        ):
            fails[DEC] = ["no purpose declared in the analysed documents"]
    return {k: v for k, v in holds.items() if v}, {k: v for k, v in fails.items() if v}


def _document(doc: dict) -> str:
    """A derived document, as a decision cites it: its channel and documents."""
    header = doc.get("_asgard") or {}
    return f"{','.join(header.get('channels', []))}:{','.join(header.get('documents', []))}"


def decisions(frame: Frame, e: Evidence) -> dict[str, Decision]:
    """Every condition's decision, by the dimensions the frame lets decide each direction."""
    out = {}
    for cid in frame.conditions:
        holds, fails = _evaluate(cid, e)
        out[cid] = Decision(cid, frame.decide(cid, tuple(holds), tuple(fails)), holds, fails)
    return out


def applicability(frame: Frame, decided: dict[str, Decision]) -> dict[str, dict]:
    """Every requirement's applicability, with the conditions left undecided."""
    values = {cid: d.value for cid, d in decided.items()}
    return {
        r.id: {
            "applicability": frame.applicability(r, values),
            "undecided": [c.id for c in frame.undecided(r, values)],
        }
        for r in frame.requirements.values()
    }


def to_json(decided: dict[str, Decision]) -> dict:
    return {cid: asdict(d) for cid, d in decided.items()}
