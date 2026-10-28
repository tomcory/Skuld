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

A practice's uncertainty is the least of its O claims' per factor (they corroborate one another); a declaration's is
its D claim's, its semantic part read leniently (D_SEMANTIC_AT_MOST): D rates a value its model placed high while its
analysis is unmeasured (EV-D1), and E reads that as moderate until it is measured. Which of D's channels is exhaustive
for a predicate, so that its silence is closed, is D's (EXHAUSTIVE).

The assessment records whether O's and D's scopes are comparable (Q8): O's installed version and D's store version
equal, or a pair the assessment states compatible. The relations read it: where they are not, D's claims are passed
on as not comparable, with the reason, and the collection is still a subject of its own.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from ratatoskr import align, tilt
from ratatoskr import claims as claim_views
from ratatoskr.registry import Registry

from skuld import parties
from skuld.configuration import baseline, recipient
from skuld.inputs import Assessment, ReportRef
from skuld.observe import claims as o_claims
from skuld.uncertainty import FACTORS, ORDER, highest

VERSION = "1"
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
    u0: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)  # t, s, n: the least of its O claims' per factor


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
    uncertainty: dict = field(default_factory=dict)  # t, s, n of the D claim, U_s read leniently


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


#: D's channel types exhaustive for a predicate (D's report, tab:channels): only the Data safety section, for the
#: collection and the sharing of each of its data types. No channel is exhaustive for a transparency requirement.
EXHAUSTIVE = {"data_safety": frozenset({"collection", "sharing"})}
#: The highest semantic uncertainty E reads of a D claim (the lenient reading of an unmeasured model's placement)
D_SEMANTIC_AT_MOST = "moderate"


def exhaustive(channel: str, predicate: str) -> bool:
    """Whether D's channel is exhaustive for the predicate, so that the silence of its complete document is closed."""
    return predicate in EXHAUSTIVE.get(channel, ())


def _tsn(claim: dict) -> dict:
    u = claim.get("uncertainty") or {}
    return {f: u.get(f, "not_applicable") for f in FACTORS}


def _least(uncertainties: list[dict]) -> dict:
    """Per factor, the least level among corroborating claims where the factor applies to any (framework)."""
    out = {}
    for f in FACTORS:
        applying = [u[f] for u in uncertainties if u[f] != "not_applicable"]
        out[f] = min(applying, key=ORDER.index) if applying else "not_applicable"
    return out


def declared_uncertainty(claim: dict) -> dict:
    """A D claim's uncertainty as E reads it: its semantic part at most D_SEMANTIC_AT_MOST."""
    u = _tsn(claim)
    if u["s"] != "not_applicable" and highest(u["s"], D_SEMANTIC_AT_MOST) == u["s"]:
        u["s"] = D_SEMANTIC_AT_MOST
    return u


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
            r = claim.get("recipient") or {}
            if p.recipient and r.get("categories"):
                p.recipient_categories = sorted({*p.recipient_categories, *r["categories"]})
            if p.recipient and r.get("jurisdiction") not in (None, "?"):
                p.jurisdictions = sorted({*p.jurisdictions, r["jurisdiction"]})
            claims_of.setdefault(p.id, []).append(claim)
    for p in grouped.values():
        p.u0 = baseline([{"claims": claims_of[p.id]}])
        p.uncertainty = _least([_tsn(c) for c in claims_of[p.id]])
        if p.recipient and p.recipient != "?":
            p.party = asdict(parties.relate(p.recipient, registry, provider))
    return sorted(grouped.values(), key=lambda p: (p.claim_type, p.data, p.recipient or "", p.actor))


def _episode_order(episode: str) -> tuple:
    return (0, int(episode)) if episode.isdigit() else (1, episode)


def declarations(report: ReportRef | None) -> list[Declaration]:
    """D's claims, computed from its derived documents (ratatoskr.claims), by their ids; a recipient claim's value is
    its recipient."""
    if report is None:
        return []
    out = []
    for n, claim in enumerate(claim_views.of_report(report.load())):
        value = claim.get("recipient") if claim["type"] == "declares_recipient" else claim.get("value")
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
            )
        )
    return out


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
    """Whether O's and D's claims may be related: one application, versions equal or stated compatible (Q8)."""
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
        [COMPONENT, align.COMPONENT, *([registry.reference() | {"role": "registry"}] if registry else [])],
    )
