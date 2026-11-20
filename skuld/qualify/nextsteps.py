"""
Next steps (plan/archive/QUALIFICATION_PLAN.md §4.1): every gap, open condition and broader O–D relation of a case yields one next
step with its kind, who would take it, what it would decide and whether it could change the result of a case it
serves. Duplicates across cases are merged and keep every case they serve. The Investigator takes those the suite can
take within its pass; the rest stay in the dossier as recommended follow-up.

    gap own_knowledge                                    extend_corpus  skuld (corpus), then the stage asked again
    gap source_absent of the collection, a source        acquire        saga, then urda
    condition, gap source_not_analysable
    gap source_absent of a requirement (samples absent)  re-analyse     skuld, the question asked
    gap not_comparable                                   acquire        saga (D of the observed version)
    gap requirements_not_reached, not_covered            explore        loki
    O–D broader                                          re-analyse     verdandi
    gap needs_run, search_space_not_run,                 experiment     skuld, through loki
    intervention_not_verified, substitution_not_
    verifiable, precondition_failed; not_admitted of a
    minimisation concern or of a dependency or
    alternative claim
    a purpose skuld select finds eligible (its           experiment     skuld, through loki
    minimisation undecided, a component Skuld can
    impose on, no experiment tried it)
    gap not_admitted of any other concern or claim       re-analyse     skuld, the reasoning tier asked again
                                                                        (only minimisation has an experiment)
    gap purpose_vague, substitute_more_invasive; an      review         a person
    open fact condition
    gap purpose_not_in_vocabulary                        re-analyse     skuld, the purpose map extended or the
                                                                        stage asked again
    gap oracle_not_observable, applicability_unknown,    audit_request  the provider: an evidence-assisted audit
    observability                                                       (E3), a full accountability assessment (E4)

An unknown reason is an error. Whether a step could change a result is the test of the review triggers (§5.2):
qualifying the case under each resolution of what the step would decide, with the rules of results.py.
"""

import json

from skuld.qualify import symbols
from skuld.qualify.conditions import SOURCE
from skuld.qualify.conditions import channel as source_channel
from skuld.qualify.results import Con, View, result

#: 4 (21 Nov 2026): the gap reason substitute_more_invasive (Ratatoskr 0.38.0) goes to a person's review; 3 (20 Nov
#: 2026): the gap reason purpose_not_in_vocabulary (Ratatoskr 0.32.0) is re-analysed by Skuld
VERSION = "4"
COMPONENT = {"role": "method", "id": "skuld.qualify.nextsteps", "version": VERSION}

EXPERIMENT = (
    "needs_run",
    "search_space_not_run",
    "intervention_not_verified",
    "substitution_not_verifiable",
    "precondition_failed",
    "not_admitted",
)
AUDIT = ("oracle_not_observable", "applicability_unknown", "observability")
#: The requirements an experiment can decide (the experimental channel supplies minimisation's premises)
EXPERIMENTAL = ("data_minimised",)
LEVEL = {"E3": "evidence_assisted_audit", "E4": "full_accountability_assessment"}
KINDS = ("acquire", "explore", "experiment", "re-analyse", "extend_corpus", "review", "audit_request")


class UnknownReason(ValueError):
    """A gap reason no row of the table names."""


# -- resolutions: copies of a view with what a step would decide, decided one way or the other ------------------------


def _without_gap(view: View, gid: str) -> View:
    v = view.copy()
    v.gaps = [g for g in v.gaps if g.id != gid]
    return v


def _concern(view: View, cid: str, status: str | None, unconditioned: bool = False) -> View:
    """The view with a concern set to a status (None removes it), its conditions dropped if `unconditioned`."""
    v = view.copy()
    out = []
    for c in v.concerns:
        if c.id == cid:
            if status is None:
                continue
            c.status = status
            if unconditioned:
                c.condition, c.conditions = None, []
        out.append(c)
    v.concerns = out
    return v


def _relation(view: View, rid: str, symbol: str | None, unconditioned: bool = False) -> View:
    v = view.copy()
    out = []
    for r in v.relations:
        if r.id == rid:
            if symbol is None:
                continue
            r.symbol = symbol
            if unconditioned:
                r.condition = None
        out.append(r)
    v.relations = out
    return v


def _assessed(view: View, requirement: str | None = None) -> View:
    v = view.copy()
    v.unassessed = [u for u in v.unassessed if requirement is not None and u.requirement != requirement]
    return v


def resolutions_of_concerns(view: View, concerns: list[Con]) -> list[View]:
    """A concern decided for (supported, unconditioned) and against (removed)."""
    return [x for c in concerns for x in (_concern(view, c.id, "supported", True), _concern(view, c.id, None))]


def changes(view: View, variants: list[View]) -> bool:
    now = result(view)
    return any(result(v) != now for v in variants)


# -- candidates per holding -------------------------------------------------------------------------------------------


def _gap_step(index, g: dict) -> dict:
    reason, of = g["reason"], g.get("of")
    target: dict = {}
    if reason == "own_knowledge":
        kind, by = "extend_corpus", "skuld"
        practice = of if of in index.practices else (index.claims.get(of) or {}).get("subject")
        p = index.practices.get(practice or "")
        if p:
            target = {"practice": p["id"], "component": p.get("recipient") or p.get("actor") or "?"}
    elif reason in ("source_absent", "source_not_analysable"):
        if of in index.requirements:
            kind, by, target = "re-analyse", "skuld", {"requirement": of}
        else:
            kind, by = "acquire", "saga"
            target = {"channel": g.get("channel") or "all"}
    elif reason == "not_comparable":
        kind, by = "acquire", "saga"
    elif reason in ("requirements_not_reached", "not_covered"):
        kind, by = "explore", "loki"
        target = {k: v for k, v in (("feature", g.get("feature")), ("case", _subject(g))) if v}
    elif reason in EXPERIMENT:
        kind, by = "experiment", "skuld"
        concern, claim = index.concerns.get(of or ""), index.claims.get(of or "")
        if reason == "not_admitted" and not (
            (concern and concern["requirement"] in EXPERIMENTAL)
            or (claim and claim["type"] in ("dependency", "alternative"))
        ):
            kind = "re-analyse"  # no experiment decides a purpose's specificity or compatibility
        subject = (concern or claim or {}).get("subject")
        if concern:
            target = {"concern": of}
        if subject in index.practices:
            target["practice"] = subject
        elif not concern and not claim:
            target = {"case": _subject(g)}
    elif reason in ("purpose_vague", "substitute_more_invasive"):
        kind, by = "review", "person"
    elif reason == "purpose_not_in_vocabulary":
        kind, by = "re-analyse", "skuld"
    elif reason in AUDIT:
        kind, by = "audit_request", "provider"
    else:
        raise UnknownReason(f"{g['id']}: gap reason {reason!r} has no next step")
    step = {"kind": kind, "by": by, "target": target, "decides": g["proposition"], "from": [g["id"]]}
    if kind == "audit_request":
        step["level"] = LEVEL.get(g["observability"], "evidence_assisted_audit")
    return step


def _subject(g: dict) -> str:
    return g["id"].split(":", 1)[1].rsplit(":", 1)[0]


def _gap_variants(index, holding, view: View, g: dict) -> list[View]:
    of = g.get("of")
    variants = [_without_gap(view, g["id"])]
    concerned = [c for c in view.concerns if c.id == of or (of and of in c.basis)]
    variants += resolutions_of_concerns(_without_gap(view, g["id"]), concerned)
    if of == holding.subject or of in index.requirements:
        variants.append(_assessed(_without_gap(view, g["id"]), of if of in index.requirements else None))
    return variants


def _open_step(index, o: dict) -> dict:
    source = o.get("kind") == SOURCE
    if source:
        channels = sorted(
            {
                ch
                for q in o["qualifies"]
                for x in [
                    *(index.concerns.get(q, {}).get("condition") or []),
                    *(index.relations.get(q, {}).get("condition") or "").split(", "),
                ]
                if (ch := source_channel(x))
            }
        )
        return {
            "kind": "acquire",
            "by": "saga",
            "target": {"channel": channels[0]} if len(channels) == 1 else {},
            "decides": o["text"],
            "from": [o["id"]],
        }
    return {"kind": "review", "by": "person", "target": {}, "decides": o["text"], "from": [o["id"]]}


def _open_variants(view: View, o: dict) -> list[View]:
    qualified = set(o["qualifies"])
    variants = []
    for r in view.relations:
        if r.id in qualified and r.condition:
            variants += [_relation(view, r.id, r.symbol, True), _relation(view, r.id, None)]
    for c in view.concerns:
        if c.id in qualified:
            variants += [_concern(view, c.id, c.status, True), _concern(view, c.id, None)]
    return variants


def _experiment_step(view: View, c: dict) -> tuple[dict, list[View]]:
    """The experiment `skuld select` would choose for an eligible purpose, with its outcomes: minimisation assessed,
    the concern supported or not raised."""
    alternatives = [a for comp in c["components"] for a in comp["alternatives"]]
    step = {
        "kind": "experiment",
        "by": "skuld",
        "target": {
            "practice": c["practice"],
            "purpose": c["purpose"],
            **({"concern": c["concern"]} if c["concern"] else {}),
        },
        "decides": f"whether {c['node'] or 'the purpose'} is achieved with less ({', '.join(alternatives)})",
        "from": [c["concern"] or c["purpose"]],
    }
    base = _assessed(view, "data_minimised")
    held = [x for x in base.concerns if x.id == c["concern"]]
    if held:
        variants = resolutions_of_concerns(base, held)
    else:
        added = base.copy()
        added.concerns.append(Con(c["purpose"], "data_minimised", "less_invasive_alternative", "supported"))
        variants = [added, base]
    return step, variants


def candidates(index, holding, view: View) -> list[tuple[dict, list[View]]]:
    """A holding's next steps, each with the resolutions that test whether it could change the holding's result."""
    out = []
    for gid in holding.gaps:
        g = index.gaps[gid]
        out.append((_gap_step(index, g), _gap_variants(index, holding, view, g)))
    if holding.kind == "practice":
        for c in getattr(index, "experiments", {}).get(holding.subject, []):
            out.append(_experiment_step(view, c))
    for oid in holding.open:
        o = index.open[oid]
        out.append((_open_step(index, o), _open_variants(view, o)))
    for r in view.relations:
        if r.type == "O-D" and index.relations[r.id].get("partial") == "broader":
            step = {
                "kind": "re-analyse",
                "by": "verdandi",
                "target": {"practice": holding.subject},
                "decides": "which node of the data vocabulary O's data is, against the declared ones",
                "from": [r.id],
            }
            variants = [_relation(view, r.id, symbols.AGREE), _relation(view, r.id, symbols.DISAGREE, True)]
            out.append((step, variants))
    return out


def merge(served: list[tuple[str, dict, bool]]) -> tuple[list[dict], dict[str, list[str]]]:
    """The next steps from every holding's candidates (holding id, step, could change its result), merged by what they
    are, ordered: those that could change a result first, then those that serve more cases, then by kind and what
    they decide; and per holding the ids of its steps."""
    merged: dict[str, dict] = {}
    for holding, step, could in served:
        key = json.dumps([step["kind"], step["by"], step["target"], step["decides"]], sort_keys=True)
        m = merged.setdefault(key, {**step, "cases": [], "from": [], "could_change": False})
        if holding not in m["cases"]:
            m["cases"].append(holding)
        m["from"] = sorted(set(m["from"]) | set(step["from"]))
        m["could_change"] = m["could_change"] or could
    ordered = sorted(
        merged.values(),
        key=lambda s: (not s["could_change"], -len(s["cases"]), KINDS.index(s["kind"]), s["decides"], s["from"]),
    )
    of_holding: dict[str, list[str]] = {}
    out = []
    for n, s in enumerate(ordered, 1):
        sid = f"step:{n}"
        entry = {"id": sid, "kind": s["kind"], "by": s["by"]}
        if s.get("level"):
            entry["level"] = s["level"]
        if s["target"]:
            entry["target"] = s["target"]
        entry.update(
            {"cases": sorted(s["cases"]), "decides": s["decides"], "could_change": s["could_change"], "from": s["from"]}
        )
        out.append(entry)
        for h in s["cases"]:
            of_holding.setdefault(h, []).append(sid)
    return out, of_holding
