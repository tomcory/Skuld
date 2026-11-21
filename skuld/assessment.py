"""
The assessment of one application version: its subjects, built from O's and D's reports.

    practices     O's claims of processing, aggregated across the version's O reports by claim type, data node,
                  recipient (register entity, else domain; none for Accesses) and actor (Q1). A practice keeps the
                  episodes and contexts it occurred in, the claims it rests on by reference (report digest and claim
                  id), the recipient's party relation (parties.py) and its configuration u0 (configuration.py).
                  Frequency and granularity are qualifiers of a practice, not practices of their own.
    declarations  D's claims of practice and of justification, by reference (report digest and claim id), with what
                  the alignment reads of them. Claims of justification are named inputs of the assessment stage only;
                  the expectation stage reads no declaration.
    collection    D's documents with their requirement annotations and completeness; None without D.

A practice's uncertainty is its O claims' `either` (they corroborate one another: the least uncertain, with its own
reasons); a declaration's is its D claim's, every reason at its own level: a value D's model placed is high
(`model_decision`), and so is what rests on it (until 0.9.0 E read every reason of D's at most moderate; the author
dropped that lenient reading on 21 Nov 2026). O's and D's reasons pass through unchanged; a report made before
Ratatoskr 0.34.0, which states factor levels and no reason, is read as low (`uncertainty.read`). Which of D's channels is exhaustive
for a predicate, so that its silence is closed, is D's, as Ratatoskr states its channel types (ratatoskr.channels).

The design questions Q1 (what one practice is), Q8 (O and D of different versions) and Q9 (which O reports are
subjects: the exploration's and baseline runs', never a run under an intervention, which `skuld describe` refuses,
`inputs.check_subject`) were built as proposed on 24 Oct 2026 and confirmed by the author on 21 Nov 2026.

The assessment records whether O's and D's scopes are comparable (Q8): O's installed version and D's store version
equal, or a pair the assessment states compatible. The relations read it: where they are not, D's claims are passed
on as not comparable, with the reason, and the collection is still a subject of its own.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime

from ratatoskr import align, channels, tilt
from ratatoskr import claims as claim_views
from ratatoskr.registry import Registry

from skuld import parties
from skuld.configuration import baseline, recipient
from skuld.inputs import Assessment, ReportRef
from skuld.observe import claims as o_claims
from skuld.uncertainty import either, read

#: 2: D's marks on the root read from its derived documents (Urda 2.1.0); 3: a practice's recipient is related to the
#: provider by its owner when it was first observed (`observed`), not today's (20 Nov 2026); 4: one level with its
#: reasons (Ratatoskr 0.34.0): a practice's is its O claims' `either`, a declaration's D's every reason capped; 5: a
#: declaration's is its D claim's, every reason at its own level (no lenient reading of D; 21 Nov 2026)
VERSION = "5"
COMPONENT = {"role": "method", "id": "skuld.assessment", "version": VERSION}


@dataclass
class Practice:
    id: str
    claim_type: str
    data: str
    recipient: str | None
    actor: str
    episodes: list[str]
    contexts: list[dict]
    claims: list[dict]
    observations: list[str]
    party: dict | None = None
    recipient_categories: list[str] = field(default_factory=list)
    jurisdictions: list[str] = field(default_factory=list)  # the recipient's, where O states one
    observed: str | None = None  # when it was first observed: the earliest start of its observations' scopes
    u0: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)  # its O claims' either


@dataclass
class Declaration:
    id: str
    kind: str
    type: str
    channel: str
    data: str
    value: object
    polarity: str
    claim: dict
    uncertainty: dict = field(default_factory=dict)  # the D claim's, every reason at its own level
    # D's marks on the root (Urda 2.1.0): the declaration names no data, so it holds of all data as stated (_no_data);
    # the fields that hold the root only because D could not place their value (_unplaced: category, purpose); and
    # whether D's report marks them at all (`marked`: an unmarked root of an earlier report may mean either)
    no_data: bool = False
    unplaced: list[str] = field(default_factory=list)
    marked: bool = False

    def unplaced_data(self, root: str) -> bool:
        """Whether its data is the root only because D could not place the value: undecided, not all data."""
        return self.data == root and "category" in self.unplaced

    def unplaced_purpose(self, root: str) -> bool:
        """Whether its purpose is the root only because D could not place the value: undecided, not every purpose."""
        return self.value == root and "purpose" in self.unplaced


@dataclass
class Subjects:
    application: str
    version: str
    practices: list[Practice]
    declarations: list[Declaration]
    collection: dict | None
    comparability: dict
    controller: dict
    components: list[dict] = field(default_factory=list)

    def practice(self, practice_id: str) -> Practice:
        return next(p for p in self.practices if p.id == practice_id)

    def to_json(self) -> dict:
        return asdict(self)


def actor(claim: dict) -> str:
    """A claim's actor as a key: the component an inventory or call site names, the app itself, or `?`."""
    a = (claim.get("qualifiers") or {}).get("actor")
    if not isinstance(a, dict):
        return "?" if a in (None, "?") else str(a)
    if a.get("kind") == "component":
        return f"component:{a.get('component') or '?'}"
    return a.get("kind") or "?"


def _key(claim: dict) -> tuple[str, str, str | None, str]:
    target = recipient(claim) if claim["type"] == "transmits" else None
    if claim["type"] == "transmits" and target is None:
        target = "?"
    return claim["type"], claim["datum"]["node"], target, actor(claim)


def exhaustive(channel: str, predicate: str) -> bool:
    """Whether D's channel is exhaustive for the predicate, so that the silence of its complete document is closed."""
    return channels.exhaustive(channel, predicate)


def declared_uncertainty(claim: dict) -> dict:
    """A D claim's uncertainty as E reads it: every reason at its own level (`read`)."""
    return read(claim.get("uncertainty"))


def _practice_id(key: tuple) -> str:
    return "P-" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:10]


def _ref(dimension: str, report: ReportRef, claim: str) -> dict:
    return {"dimension": dimension, "report": report.sha256, "claim": claim}


def practices(reports: list[ReportRef], registry: Registry | None, provider: parties.Controller) -> list[Practice]:
    """O's practices, from the top-level claims of every O report of the version (Q1)."""
    grouped: dict[tuple, Practice] = {}
    claims_of: dict[str, list[dict]] = {}
    for ref in reports:
        report = ref.load()
        started = {
            sc.get("observation"): (sc.get("time") or {}).get("start")
            for sc in report.get("scopes", [])
            if isinstance(sc, dict)
        }
        for claim in o_claims(report):
            if claim.get("status") != "supported" or claim.get("polarity", "+") != "+":
                continue
            key = _key(claim)
            p = grouped.get(key)
            if p is None:
                p = grouped[key] = Practice(_practice_id(key), *key, [], [], [], [])
            contexts = (claim.get("qualifiers") or {}).get("contexts") or []
            p.episodes = sorted({*p.episodes, *(str(c.get("episode", "?")) for c in contexts)}, key=_episode_order)
            p.contexts += [{**c, "observation": obs} for c in contexts for obs in claim.get("observations", [None])[:1]]
            p.claims.append(_ref("O", ref, claim["id"]))
            p.observations = sorted({*p.observations, *claim.get("observations", [])})
            times = [started[o] for o in claim.get("observations", []) if started.get(o)]
            if times:
                p.observed = min([*times, *([p.observed] if p.observed else [])], key=_instant)
            r = claim.get("recipient") or {}
            if p.recipient and r.get("categories"):
                p.recipient_categories = sorted({*p.recipient_categories, *r["categories"]})
            if p.recipient and r.get("jurisdiction") not in (None, "?"):
                p.jurisdictions = sorted({*p.jurisdictions, r["jurisdiction"]})
            claims_of.setdefault(p.id, []).append(claim)
    for p in grouped.values():
        p.u0 = baseline([{"claims": claims_of[p.id]}])
        p.uncertainty = either(*(read(c.get("uncertainty")) for c in claims_of[p.id]))
        if p.recipient and p.recipient != "?":
            p.party = asdict(parties.relate(p.recipient, registry, provider, at=at(p.observed)))
    return sorted(grouped.values(), key=lambda p: (p.claim_type, p.data, p.recipient or "", p.actor))


def _instant(text: str):
    """A time as O states it, comparable across offsets ("2026-10-22T21:54:12.192+00:00")."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def at(text: str | None) -> datetime | None:
    """A time as O or D states it, for the register's owners at that time; None if none or unreadable."""
    try:
        return _instant(text) if text else None
    except ValueError:
        return None


def _episode_order(episode: str) -> tuple:
    return (0, int(episode)) if episode.isdigit() else (1, episode)


def declarations(report: ReportRef | None) -> list[Declaration]:
    """D's claims, computed from its derived documents (ratatoskr.claims), by their ids; a recipient claim's value is
    its recipient."""
    if report is None:
        return []
    loaded = report.load()
    documents = {
        ch["channel"]: ch.get("tilt") or {} for ch in loaded.get("channels", []) if ch.get("status") == "analysed"
    }
    marked = _marks_root(loaded, documents)
    out = []
    for n, claim in enumerate(claim_views.of_report(loaded)):
        value = claim.get("recipient") if claim["type"] == "declares_recipient" else claim.get("value")
        document = documents.get(claim["channels"][0]) or {}
        item = _at(document, claim.get("declaration"))
        entry = _at(document, claim["id"].split(":", 1)[1] if ":" in claim["id"] else None)
        unplaced = [*(item.get("_unplaced") or ()), *((entry.get("_unplaced") or ()) if entry is not item else ())]
        out.append(
            Declaration(
                f"D-{n}",
                claim["kind"],
                claim["type"],
                claim["channels"][0],
                claim["datum"]["node"],
                value,
                claim.get("polarity", "+"),
                _ref("D", report, claim["id"]),
                declared_uncertainty(claim),
                no_data=bool(item.get("_no_data")),
                unplaced=sorted(set(unplaced)),
                marked=marked,
            )
        )
    return out


#: The first Urda that marks a root it holds for all data (_no_data) apart from one it could not place (_unplaced)
MARKS_SINCE = (2, 1)


def _marks_root(report: dict, documents: dict[str, dict]) -> bool:
    """Whether D's report marks its roots: written by Urda 2.1.0 or later, or carrying a mark. In an earlier report
    the root stands both for all data and for a value D could not place."""
    named = re.match(r"(\d+)\.(\d+)", str((report.get("report") or {}).get("urda") or ""))
    if named and (int(named.group(1)), int(named.group(2))) >= MARKS_SINCE:
        return True
    text = json.dumps(documents)
    return '"_no_data"' in text or '"_unplaced"' in text


def _at(document: dict, pointer: str | None) -> dict:
    """The object at a JSON Pointer of a derived document, or {} where there is none."""
    node: object = document
    for part in (pointer or "").strip("/").split("/") if pointer else ():
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return {}
    return node if isinstance(node, dict) else {}


def collection(report: ReportRef | None) -> dict | None:
    """D's documents with their requirement annotations (by label and polarity), a view of each analysed document
    (tilt.annotations), and whether Sága acquired it complete (D's `complete`, with the reason where it is not); an
    analysed document is accessible (D's report, schema 4)."""
    if report is None:
        return None
    documents = []
    for ch in report.load()["channels"]:
        entry = {"channel": ch["channel"], "document": ch.get("document"), "status": ch["status"]}
        if ch.get("reason"):
            entry["reason"] = ch["reason"]
        if ch["status"] == "analysed":
            entry["complete"] = ch.get("complete") is not False
            if not entry["complete"]:
                entry["incomplete"] = ch.get("incomplete") or "incomplete as acquired"
            entry["annotations"] = [
                {"requirement": a["requirement"], "path": a["path"], "polarity": a["polarity"]}
                for a in tilt.annotations(ch.get("tilt") or {})
            ]
        documents.append(entry)
    return {"documents": documents}


def comparability(a: Assessment, compatible_versions: set[frozenset[str]] | None = None) -> dict:
    """Whether O's and D's claims may be related: one application, versions equal or stated compatible (Q8), by
    `compatible_versions` or else by the statements of the workspace."""
    if compatible_versions is None:
        compatible_versions = a.compatible_pairs()
    if a.declaration is None:
        return {"comparable": None, "reasons": ["no D report"], "unknown": []}
    d = a.declaration.load()["collection"]
    d_scope = align.Scope(d.get("package", a.package), d.get("store_version") or align.UNKNOWN)
    reasons, unknown = [], set()
    for ref in a.observations:
        for scope in ref.load().get("scopes", []):
            o_scope = align.Scope(scope.get("application", a.package), scope.get("version") or align.UNKNOWN)
            result = align.comparable(o_scope, d_scope, compatible_versions)
            reasons += [f"{scope.get('observation')}: {r}" for r in result.reasons]
            unknown |= set(result.unknown)
    return {"comparable": not reasons, "reasons": reasons, "unknown": sorted(unknown)}


#: The data vocabulary's root: O's node for a datum it could not identify (encrypted, binary or damaged content)
UNIDENTIFIED = "data"


def known_data(subjects: Subjects) -> tuple[Subjects, list[Practice]]:
    """The subjects without the practices whose datum O could not identify, and those practices (author, 13 Nov 2026:
    a contact whose content is not observable is no practice the assessment can judge; config
    `assessment.known_data_only`)."""
    left_out = [p for p in subjects.practices if p.data == UNIDENTIFIED]
    return replace(subjects, practices=[p for p in subjects.practices if p.data != UNIDENTIFIED]), left_out


def build(a: Assessment, registry: Registry | None) -> Subjects:
    """The subjects of an assessment."""
    d_report = a.declaration.load() if a.declaration else None
    provider = parties.controller(d_report, a.package)
    comparable = comparability(a)
    return Subjects(
        a.package,
        a.version,
        practices(a.observations, registry, provider),
        declarations(a.declaration),
        collection(a.declaration),
        comparable,
        {
            "names": sorted(provider.names),
            "domains": sorted(provider.domains),
            "package_domain": provider.package_domain,
        },
        [
            COMPONENT,
            align.COMPONENT,
            channels.COMPONENT,
            *([registry.reference() | {"role": "registry"}] if registry else []),
        ],
    )
