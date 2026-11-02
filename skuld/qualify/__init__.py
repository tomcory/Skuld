"""
Qualification, the last, deterministic stage of `skuld assess` (S-25, QUALIFICATION_PLAN.md, ADR 0002): it reads
what the assessment computed (subjects, relations, concerns, coverage, gaps, open conditions, claims), the frame's
requirements and the data vocabulary, and writes `qualification` into the report:

    placement.py   cases and sections, and what is unplaced (§2.1)
    attributes.py  the case attributes (§2.3)
    symbols.py     relations as ≈, ≠, ?, conflict; a case's pattern and its reading (§2.2)
    conditions.py  source and fact conditions (§2.4)
    results.py     the qualified result with its reason and secondary reasons (§3)
    nextsteps.py   next steps with whether they could change a result (§4.1)
    triggers.py    review triggers with their weight (§5)
    here           the views the rules read, the profile and the scope (§4.2, §6)

It asks no model, adds no evidence and no norm, and orders no applications: the profile counts one application's
cases, and an application has no qualified result of its own. Rebuilding the assessment rebuilds it identically.
"""

from skuld.qualify import attributes, conditions, nextsteps, placement, results, symbols, triggers
from skuld.qualify.placement import Holding, Index
from skuld.qualify.results import Con, Gap, Rel, Unassessed, View

VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.qualify", "version": VERSION}
COMPONENTS = [
    COMPONENT,
    placement.COMPONENT,
    attributes.COMPONENT,
    symbols.COMPONENT,
    conditions.COMPONENT,
    results.COMPONENT,
    nextsteps.COMPONENT,
    triggers.COMPONENT,
]

#: Requirements of practices judged relative to a declared purpose, which an assessment without D cannot assess
NEEDS_D = ("purpose_specified", "purpose_compatible")
NO_PURPOSE = "E established no purpose for this practice, so it was assessed for no requirement of practices"
NO_D = "no D report"
LIMITATION_FLOWS = (
    "Practices stand in for the framework's processing flows: one per claim type, data node, recipient and actor, "
    "aggregated over the version's runs (Q13)."
)


def _high(u: dict | None) -> bool:
    return bool(u) and any(u.get(f) == "high" for f in ("t", "s", "n"))


class _Coverage:
    def __init__(self, report: dict):
        self.assessed = {c["requirement"]: set(c["assessed"]) for c in report["coverage"]}
        self.not_applicable = {c["requirement"]: set(c.get("not_applicable", [])) for c in report["coverage"]}

    def status(self, requirement: str, subject: str) -> str:
        if subject in self.not_applicable.get(requirement, ()):
            return "not_applicable"
        return "assessed" if subject in self.assessed.get(requirement, ()) else "not_assessed"


def _requirements_of(index: Index, coverage: _Coverage, holding: Holding, with_d: bool) -> tuple[list, list, list]:
    """The requirements a holding was assessed for, those that apply to it but were not (with why), and those that do
    not apply to it."""
    kinds = index.requirements
    assessed, missing, inapplicable = [], [], []

    def check(requirement: str, subject: str, why: str, gap: str | None = None) -> None:
        s = coverage.status(requirement, subject)
        if s == "assessed":
            assessed.append(requirement)
        elif s == "not_assessed":
            missing.append(Unassessed(requirement, subject, why, gap))
        else:
            inapplicable.append(requirement)

    if holding.kind == "practice":
        purpose_gap = next(
            (g["id"] for g in index.report["gaps"] if g.get("of") == holding.subject and g["reason"] == "own_knowledge"),
            None,
        )
        for r, kind in kinds.items():
            if kind != "practice":
                continue
            if not with_d and r in NEEDS_D:
                check(r, holding.subject, NO_D)
            elif purpose_gap:
                check(r, holding.subject, NO_PURPOSE, purpose_gap)
            else:
                check(r, holding.subject, "not assessed")
    if holding.kind == "declared_purpose":  # decided in the purpose's row, never in a case (8.8)
        for r, kind in kinds.items():
            if kind == "declaration":
                check(r, holding.subject, "a declared purpose the reasoning tier did not judge")
    if holding.kind == "collection":
        r = holding.id.removeprefix("row:collection:")
        check(r, "collection", "not assessed")
    return assessed, missing, inapplicable


def _view(index: Index, holding: Holding, assessed: list, missing: list, inapplicable: list) -> View:
    rels = []
    for rid in holding.relations:
        r = index.relations[rid]
        rels.append(
            Rel(
                rid,
                r["type"],
                r["outcome"],
                symbols.symbol(r),
                conditions.of_relation(r),
                r.get("aspect"),
                r.get("condition"),
                _high(r.get("uncertainty")),
                r.get("partial"),
            )
        )
    cons, aside = [], []
    for cid in holding.concerns:
        c = index.concerns[cid]
        if c["status"] == "not_applicable":
            continue
        elsewhere = holding.kind != "declared_purpose" and index.requirements.get(c["requirement"]) == "declaration"
        (aside if elsewhere else cons).append(
            Con(
                cid,
                c["requirement"],
                c["step"],
                c["status"],
                conditions.of_concern(c),
                list(c.get("condition") or []),
                c.get("observability", "E2"),
                _high(c.get("uncertainty")),
                list(c.get("basis") or []),
            )
        )
    gaps = [Gap(g, index.gaps[g]["reason"], index.gaps[g]["observability"], index.gaps[g].get("of")) for g in holding.gaps]
    return View(rels, cons, gaps, missing, assessed, inapplicable, aside)


def _references(holding: Holding, missing: list) -> dict:
    out = {
        "relations": holding.relations,
        "concerns": holding.concerns,
        "claims": holding.claims,
        "declarations": holding.declarations,
        "gaps": holding.gaps,
        "open": holding.open,
        "coverage": sorted({u.requirement for u in missing}),
    }
    return {k: v for k, v in out.items() if v}


def _pattern(view: View) -> dict:
    parts = {}
    for kind in ("O-D", "O-E", "D-E"):
        s, conditional, rests = view.symbol(kind)
        parts[kind] = {"symbol": s, **({"conditional": True} if conditional else {}), "relations": rests}
    return {**parts, "reading": symbols.reading(parts["O-D"]["symbol"], parts["O-E"]["symbol"], parts["D-E"]["symbol"])}


def qualify(report: dict, requirements: dict[str, str], data=None, registry=None) -> dict:
    """The qualification of an assessment: `requirements` gives each requirement of the frame the kind of its subject
    (practice, declaration, collection); `data` is the data vocabulary, `registry` the recipient register."""
    index = Index(report, requirements)
    from skuld import select as selection  # select reads qualification's steps; import here, not at module load

    index.experiments = {}
    for c in selection.candidates(report, report["subjects"]["practices"]):
        if selection.refusal(c) is None:
            index.experiments.setdefault(c["practice"], []).append(c)
    coverage = _Coverage(report)
    with_d = report["inputs"]["declaration"] is not None
    cases, purposes, collection = placement.place(index)
    holdings = cases + purposes + collection
    scope = {h.id: _requirements_of(index, coverage, h, with_d) for h in holdings}
    placement.attach(index, holdings, {h: {u.requirement for u in scope[h][1]} for h in scope})
    views = {h.id: _view(index, h, *scope[h.id]) for h in holdings}

    served = []
    for h in holdings:
        for step, variants in nextsteps.candidates(index, h, views[h.id]):
            served.append((h.id, step, nextsteps.changes(views[h.id], variants)))
    steps, of_holding = nextsteps.merge(served)

    def entry(h: Holding) -> dict:
        view = views[h.id]
        q = results.qualified(view)
        return {
            "result": q["result"],
            "reason": q["reason"],
            "secondary": q["secondary"],
            **({"rests_on": q["rests_on"]} if q["rests_on"] else {}),
            "triggers": triggers.triggers(index, h, view),
            "next_steps": of_holding.get(h.id, []),
            "references": _references(h, scope[h.id][1]),
        }

    out_cases = []
    for h in cases:
        e = entry(h)
        out_cases.append(
            {
                "id": h.id,
                "kind": h.kind,
                "subject": h.subject,
                "attributes": attributes.of_case(index, h, data, registry),
                "pattern": _pattern(views[h.id]),
                "result": e["result"],
                "reason": e["reason"],
                "secondary": e["secondary"],
                **({"rests_on": e["rests_on"]} if "rests_on" in e else {}),
                "triggers": e["triggers"],
                "next_steps": e["next_steps"],
                "references": e["references"],
            }
        )
    out_cases.sort(key=lambda c: (results.CASE_ORDER.index(c["result"]), c["subject"]))

    def rows(hs: list[Holding], extra) -> list[dict]:
        out = [{"id": h.id, "subject": h.subject if h.kind != "collection" else h.id.removeprefix("row:collection:"),
                **extra(h), **entry(h)} for h in hs]
        return sorted(out, key=lambda r: (results.CASE_ORDER.index(r["result"]), r["id"]))

    transparency = {
        s["requirement"]: s for s in (report["subjects"].get("collection") or {}).get("transparency", [])
    }

    def collection_extra(h: Holding) -> dict:
        s = transparency[h.id.removeprefix("row:collection:")]
        return {"status": s["status"], "applicability": s["applicability"],
                **({"conditions": s["conditions"]} if s.get("conditions") else {})}

    declared = {"assessed": with_d, "rows": rows(purposes, lambda h: {})}
    collected = {"assessed": with_d and bool(transparency), "rows": rows(collection, collection_extra)}
    if not with_d:
        declared["reason"] = collected["reason"] = f"not assessed: {NO_D}"
    unplaced = placement.unplaced(index, holdings)
    if not with_d:  # D's gap goes with the collection, which is not assessed without D
        unplaced = [u for u in unplaced if index.gaps.get(u["id"], {}).get("of") != "collection"]
    return {
        "header": {"components": COMPONENTS},
        "scope": _scope(report, with_d),
        "profile": _profile(report, out_cases, declared["rows"], collected["rows"], index),
        "cases": out_cases,
        "declared_purposes": declared,
        "collection": collected,
        "next_steps": steps,
        "unplaced": unplaced,
        "limitations": _limitations(scope, cases),
    }


def _count(items: list[dict]) -> dict:
    out: dict[str, int] = {}
    for x in items:
        out[x["result"]] = out.get(x["result"], 0) + 1
    return {k: out[k] for k in results.CASE_ORDER if k in out}


def _profile(report: dict, cases: list, purposes: list, collection: list, index: Index) -> dict:
    by_channel: dict[str, dict[str, int]] = {}
    for r in report["relations"]:
        if r["type"] != "O-D":
            continue
        refs = [t for t in r.get("to", []) if t.get("dimension") == "D"]
        if r["of"].get("dimension") == "D":
            refs.append(r["of"])
        channels = sorted({t["claim"].split(":", 1)[0] for t in refs}) or ["none"]
        for ch in channels:
            by_channel.setdefault(ch, {})
            by_channel[ch][r["outcome"]] = by_channel[ch].get(r["outcome"], 0) + 1
    return {
        "practice": _count([c for c in cases if c["kind"] == "practice"]),
        "declaration": _count([c for c in cases if c["kind"] == "declaration"]),
        "declared_purposes": _count(purposes),
        "collection": _count(collection),
        "o_d_by_channel": {ch: dict(sorted(v.items())) for ch, v in sorted(by_channel.items())},
    }


def _scope(report: dict, with_d: bool) -> dict:
    documents = (report["subjects"].get("collection") or {}).get("documents", [])
    channels = [
        {"channel": d["channel"], "status": "analysed", "complete": d.get("complete", True),
         **({"reason": d["incomplete"]} if d.get("incomplete") else {})}
        for d in documents
    ]
    named = {d["channel"] for d in documents}
    for c in report["concerns"]:
        for x in c.get("condition") or ():
            ch = conditions.channel(x)
            if ch and ch not in named and x.startswith("analysed:"):
                named.add(ch)
                channels.append({"channel": ch, "status": "not_analysed"})
    comparability = report["inputs"].get("comparability") or {}
    return {
        "acquisition": report["sources"]["acquisition"],
        "channels": sorted(channels, key=lambda c: c["channel"]),
        "features": len(report["features"]),
        "practices": len(report["subjects"]["practices"]),
        "declaration": with_d,
        "comparable": comparability.get("comparable") if with_d else None,
        "compatible_versions": [n["id"] for n in report["inputs"]["named"] if n["kind"] == "version_compatibility"],
    }


def _limitations(scope: dict, cases: list[Holding]) -> list[str]:
    out = [LIMITATION_FLOWS]
    unexplained = sorted(
        {h.subject for h in cases if any(u.why == "not assessed" for u in scope[h.id][1])}
    )
    if unexplained:
        out.append(
            f"{len(unexplained)} practices were not assessed for a requirement of practices without a gap saying why: "
            + ", ".join(unexplained)
        )
    return out
