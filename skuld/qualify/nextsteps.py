"""
Next steps (plan/archive/QUALIFICATION_PLAN.md §4.1; OBSERVABILITY_PLAN §8): every gap, open condition and broader O–D
relation of a case yields a next step with its kind, who would take it, what it would decide and whether it could
change the result of a case it serves. Duplicates across cases are merged and keep every case they serve. The
Investigator takes those the suite can take within its pass; the rest stay in the dossier as recommended follow-up.

A gap's step is the gap's own next step (`next`, gaps.py: kind, and `held` for an audit request), taken by:

    acquire             saga (a channel), skuld (kept samples of a question)
    explore             loki
    experiment          skuld, through loki
    re-analyse          skuld
    extend_corpus       skuld (corpus), then the stage asked again; for fact_missing (a fact the corpus lacks), the
                        target names its node and property, so that the claims lacking one fact share one step
    review              a person
    improve_instrument  verdandi (a decoder, a hook for a payload it could not read), skuld (an oracle)
    audit_request       the provider, for what it holds: a record (an evidence-assisted audit) or its organisation's
                        assessment (a full accountability assessment)

An open condition's steps: a source condition is acquired (saga); a fact condition yields one step per proposition it
bears on (`bears_on`): its external step where its reach is not none, else an audit request with its held
(gaps.condition_step), and a review where none is declared. Further:

    O–D broader                                          re-analyse     verdandi
    a purpose skuld select finds eligible (its           experiment     skuld, through loki
    minimisation undecided, a component Skuld can
    impose on, no experiment tried it)

A gap without a next step is an error. Whether a step could change a result is the test of the review triggers
(§5.2): qualifying the case under each resolution of what the step would decide, with the rules of results.py.
"""

import json

from skuld import gaps as gap_steps
from skuld.qualify import symbols
from skuld.qualify.conditions import SOURCE
from skuld.qualify.conditions import channel as source_channel
from skuld.qualify.results import Con, View, result

#: 6 (21 Nov 2026, P10): a fact_missing gap's step (extend_corpus) targets the fact's node and property, so that the
#: claims lacking one fact share one step; 5 (21 Nov 2026): a gap's step is its own next step (Ratatoskr 0.39.0: kind and held, improve_instrument), an open
#: fact condition's steps follow from the levels of the propositions it bears on, no audit request by a level; 4 (21
#: Nov 2026): the gap reason substitute_more_invasive (Ratatoskr 0.38.0) goes to a person's review; 3 (20 Nov 2026): the
#: gap reason purpose_not_in_vocabulary (Ratatoskr 0.32.0) is re-analysed by Skuld
VERSION = "6"
COMPONENT = {"role": "method", "id": "skuld.qualify.nextsteps", "version": VERSION}

KINDS = gap_steps.KINDS
#: Who takes a step of a kind, where the gap does not say otherwise
BY = {
    "acquire": "saga",
    "explore": "loki",
    "experiment": "skuld",
    "re-analyse": "skuld",
    "extend_corpus": "skuld",
    "review": "person",
    "improve_instrument": "verdandi",
    "audit_request": "provider",
}


class UnknownReason(ValueError):
    """A gap without a next step."""


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
    nxt = g.get("next")
    if not isinstance(nxt, dict) or nxt.get("kind") not in KINDS:
        raise UnknownReason(f"{g['id']}: gap reason {g.get('reason')!r} has no next step")
    reason, of, kind = g["reason"], g.get("of"), nxt["kind"]
    by, target = BY[kind], {}
    concern, claim = index.concerns.get(of or ""), index.claims.get(of or "")
    if reason == "fact_missing":  # a fact the corpus lacks, by its node and property: one step for every claim
        fact = g.get("fact") or {}
        target = {k: fact[k] for k in ("node", "property") if fact.get(k)}
    elif reason == "own_knowledge":
        practice = of if of in index.practices else (claim or {}).get("subject")
        p = index.practices.get(practice or "")
        if p:
            target = {"practice": p["id"], "component": p.get("recipient") or p.get("actor") or "?"}
    elif kind == "acquire":
        if of in index.requirements:
            by, target = "skuld", {"requirement": of}  # the question's samples, kept by skuld judge
        else:
            target = {"channel": g.get("channel") or "all"}
    elif kind == "explore":
        target = {k: v for k, v in (("feature", g.get("feature")), ("case", _subject(g))) if v}
    elif kind == "experiment":
        subject = (concern or claim or {}).get("subject")
        if concern:
            target = {"concern": of}
        if subject in index.practices:
            target["practice"] = subject
        elif not concern and not claim:
            target = {"case": _subject(g)}
    elif kind == "improve_instrument" and reason == "oracle_not_observable":
        by = "skuld"  # an oracle is a case's
        if claim:
            target = {k: v for k, v in (("case", claim.get("case")), ("practice", claim.get("subject"))) if v}
    elif kind == "improve_instrument" and _subject(g) in index.practices:
        target = {"practice": _subject(g)}
    elif kind == "re-analyse" and concern:
        target = {"concern": of}
    step = {"kind": kind, "by": by, "target": target, "decides": g["proposition"], "from": [g["id"]]}
    if kind == "audit_request":
        step["held"] = nxt["held"]
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


def _open_steps(index, o: dict) -> list[dict]:
    """An open condition's steps: a source condition acquired; a fact condition one step per proposition it bears on,
    by its level (gaps.condition_step); a review where it names none."""
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
        return [
            {
                "kind": "acquire",
                "by": "saga",
                "target": {"channel": channels[0]} if len(channels) == 1 else {},
                "decides": o["text"],
                "from": [o["id"]],
            }
        ]
    if not o.get("bears_on"):
        return [{"kind": "review", "by": "person", "target": {}, "decides": o["text"], "from": [o["id"]]}]
    out = []
    for b in o["bears_on"]:
        level = gap_steps.level_of(b["ref"], getattr(index, "frame", None))
        nxt = gap_steps.condition_step(b["ref"], level, b["proposition"])
        step = {
            "kind": nxt["kind"],
            "by": BY[nxt["kind"]],
            "target": {},
            "decides": b["proposition"],
            "from": [o["id"]],
        }
        if nxt.get("held"):
            step["held"] = nxt["held"]
        out.append(step)
    return out


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
        out += [(step, _open_variants(view, o)) for step in _open_steps(index, o)]
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
        key = json.dumps([step["kind"], step["by"], step["target"], step["decides"], step.get("held")], sort_keys=True)
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
        if s.get("held"):
            entry["held"] = s["held"]
        if s["target"]:
            entry["target"] = s["target"]
        entry.update(
            {"cases": sorted(s["cases"]), "decides": s["decides"], "could_change": s["could_change"], "from": s["from"]}
        )
        out.append(entry)
        for h in s["cases"]:
            of_holding.setdefault(h, []).append(sid)
    return out, of_holding
