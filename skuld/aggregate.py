"""
E's aggregate (author, 12 Nov 2026): the assessment's concerns compressed into aggregated concerns a reader can work
through, written as aggregate.json (Ratatoskr's `expectation_aggregate`) and aggregate.md beside assessment.json. An
aggregated concern is a group of concerns, not a new judgment: it states nothing its members do not.

The aggregate reads the assessment and never changes it. Concerns merge into one aggregated concern only where
requirement, step, tier and status are the same and the keys below are equal; every key is a field the assessment
already carries, so no model, embedding or threshold decides membership:

    data_minimised      the practice's data type, the outcome of its alternatives (demonstrated by an experiment,
                        technically supported and on which components, none supported, not assessable), and its
                        purpose, merged along the purpose hierarchy: purposes on one branch of dpv-purposes
                        (TargetedAdvertising, PersonalisedAdvertising, Advertising) are one aggregated concern when
                        everything else is equal, labelled with the most general of them (author: unit app × data
                        type × purpose, option c). Recipients are members: the alternatives concern the data and the
                        purpose (Art. 5(1)(c)), never the recipient
    purpose_compatible, the practice's data type and purpose, merged along the hierarchy as above
    purpose_specified
    purpose_specific    the purpose node D assigned to the declaration (author: app × declared purpose node); no
                        merge along the hierarchy, as whether one purpose is vague says nothing of another
    the collection      requirement and condition (one aggregated concern per requirement in practice)
    declaration_        the declaration (one aggregated concern per declaration contradicted, concern (iii)): whether
    corresponds         one denial is contradicted says nothing of another
    anything else       its subject (an aggregated concern of its own)

Open conditions are grouped by their text. Every concern and open condition is a member of exactly one aggregated
concern or group, and the aggregate checks this before it writes (lossless).

Aggregated concerns are ordered: supported first, then not established, then the rest; the rule tier before the
reasoning tier; those whose samples all agreed first; more members first; then by label. The order is a presentation
aid and makes no claim about severity.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import ratatoskr
from ratatoskr.schemas import validate

import skuld
from skuld import inputs
from skuld.common import PURPOSES, vocabulary
from skuld.uncertainty import highest

VERSION = "1"
COMPONENT = {"role": "method", "id": "skuld.aggregate", "version": VERSION}
REPORT = "aggregate.json"
MARKDOWN = "aggregate.md"
ASSESSMENT = "assessment.json"

PRACTICE = {"data_minimised", "purpose_compatible", "purpose_specified"}
STATUS_ORDER = ("supported", "not_established", "not_assessable")
TIER_ORDER = ("rule", "reasoning")
ORDER = (
    "status (supported, not established, other), tier (rule, reasoning), samples agreeing before disagreeing, "
    "more members first, label; a presentation aid, no claim about severity"
)
OUTCOME_TEXT = {
    "demonstrated": "a less invasive alternative demonstrated by an experiment",
    "technically_supported": "a less invasive alternative technically supported by documents",
    "none_supported": "alternatives proposed, none supported by documents",
    "not_assessable": "not assessable",
}


class AggregateError(inputs.InputError):
    """An assessment that cannot be aggregated, or an aggregate that would lose a concern."""


# -- keys -----------------------------------------------------------------------------------------------------------


def _outcome(concern: dict, claims: dict) -> tuple[str, list[str]]:
    """The outcome of a minimisation concern's alternatives and the components the decisive ones change, as
    concerns.less_invasive_alternative decides it."""
    alternatives = [claims[b] for b in concern.get("basis", []) if claims.get(b, {}).get("type") == "alternative"]
    decisive = [c for c in alternatives if c["status"] == "supported" and c.get("level") != "plausible"]
    if any(c.get("strength") == "run" for c in decisive):
        return "demonstrated", []
    if decisive:
        return "technically_supported", sorted(
            {c["component"].rsplit(".", 1)[1] for c in decisive if c.get("component")}
        )
    if concern["status"] == "not_assessable":
        return "not_assessable", []
    return "none_supported", []


def _purpose_groups(nodes: set[str], purposes) -> dict[str, tuple[str, ...]]:
    """Per purpose node, the most general nodes of its group: nodes of which one is an ancestor of another are one
    group (transitively); a node outside the vocabulary is a group of its own."""
    nodes = sorted(nodes)
    known = {n: set(purposes.ancestors(n)) if n in purposes.nodes else set() for n in nodes}
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for a in nodes:
        for b in nodes:
            if a != b and b in known[a]:
                parent[find(a)] = find(b)
    members = defaultdict(list)
    for n in nodes:
        members[find(n)].append(n)
    out = {}
    for group in members.values():
        tops = tuple(sorted(n for n in group if not (known[n] & set(group))))
        for n in group:
            out[n] = tops
    return out


def _practice_view(concern, practices, claims) -> dict:
    p = practices.get(concern["subject"], {})
    purpose = claims.get(concern.get("purpose") or "", {}).get("purpose") or {}
    return {
        "data": p.get("data") or "?",
        "recipient": (p.get("party") or {}).get("owner") or p.get("recipient"),
        "purpose": purpose.get("node"),
    }


def aggregate(report: dict, assessment_meta: dict | None = None) -> dict:
    """The aggregate of an assessment report (assessment.json's content)."""
    purposes = vocabulary(PURPOSES)
    claims = {c["id"]: c for c in report.get("claims", [])}
    practices = {p["id"]: p for p in report.get("subjects", {}).get("practices", [])}
    declarations = {d["id"]: d for d in report.get("subjects", {}).get("declarations", [])}

    # first pass: each concern's member view and its key before the hierarchy merge
    rows = []
    for c in report["concerns"]:
        base = (c["requirement"], c["step"], c["tier"], c["status"])
        member = {
            "concern": c["id"],
            "subject": c["subject"],
            "reason": c.get("reason", ""),
            "uncertainty": c["uncertainty"],
        }
        key: dict = {}
        if c["requirement"] in PRACTICE and c["subject"] in practices:
            view = _practice_view(c, practices, claims)
            member.update(view)
            key["data"] = view["data"]
            if c["requirement"] == "data_minimised":
                outcome, components = _outcome(c, claims)
                key["outcome"] = outcome
                if components:
                    key["components"] = components
                alts = [claims[b]["alternative"] for b in c.get("basis", []) if claims.get(b, {}).get("alternative")]
                if alts:
                    member["alternatives"] = sorted(set(alts))
            group = "practice"
        elif c["requirement"] == "purpose_specific" and c["subject"] in declarations:
            d = declarations[c["subject"]]
            member["declared"] = d.get("value")
            text = c.get("reason", "")
            if text.startswith('"') and '": ' in text:
                member["statement"] = text[1 : text.index('": ')]
            key["declared"] = d.get("value")
            group = "declared"
        elif c["requirement"] == "declaration_corresponds" and c["subject"] in declarations:
            text = c.get("reason", "")
            if text.startswith('"') and '": ' in text:
                member["statement"] = text[1 : text.index('": ')]
            key["subject"] = c["subject"]
            group = "contradicted"
        elif c["subject"] == "collection":
            if c.get("condition"):
                key["condition"] = sorted(c["condition"])
            group = "collection"
        else:
            key["subject"] = c["subject"]
            group = "other"
        rows.append((c, base, group, key, member))

    # the purpose hierarchy, per practice key without the purpose (option c: only identical keys merge)
    by_rest = defaultdict(set)
    for _, base, group, key, member in rows:
        if group == "practice":
            by_rest[(base, json.dumps(key, sort_keys=True))].add(member.get("purpose") or "?")
    tops = {rest: _purpose_groups(nodes, purposes) for rest, nodes in by_rest.items()}

    aggregated: dict[tuple, dict] = {}
    for c, base, group, key, member in rows:
        if group == "practice":
            rest = (base, json.dumps(key, sort_keys=True))
            key = {**key, "purposes": list(tops[rest][member.get("purpose") or "?"])}
        fkey = (base, json.dumps(key, sort_keys=True))
        f = aggregated.setdefault(
            fkey,
            {
                "requirement": c["requirement"],
                "principle": c["principle"],
                "provisions": list(c.get("provisions", [])),
                "step": c["step"],
                "tier": c["tier"],
                "status": c["status"],
                "key": key,
                "condition": set(),
                "members": [],
                "_group": group,
            },
        )
        f["condition"].update(c.get("condition", []))
        f["members"].append(member)

    out = []
    for f in aggregated.values():
        f["members"].sort(
            key=lambda m: (m.get("data", ""), m.get("recipient") or "", m.get("purpose") or "", m["concern"])
        )
        f["uncertainty"] = {d: highest(*(m["uncertainty"][d] for m in f["members"])) for d in ("t", "s", "n")}
        f["disagreeing"] = sum(m["uncertainty"]["s"] == "high" for m in f["members"])
        f["condition"] = sorted(f["condition"])
        f["label"] = _label(f)
        out.append(f)
    out.sort(key=_order)

    themes: dict[tuple, dict] = {}
    for i, f in enumerate(out, 1):
        f["id"] = f"aggregated:{i}"
        tkey, tlabel = _theme(f)
        t = themes.setdefault(
            tkey, {"requirement": f["requirement"], "status": f["status"], "label": tlabel, "aggregated_concerns": []}
        )
        t["aggregated_concerns"].append(f["id"])
    theme_list = []
    for i, t in enumerate(themes.values(), 1):
        t = {"id": f"theme:{i}", **t}
        theme_list.append(t)
        for fid in t["aggregated_concerns"]:
            out[int(fid.split(":")[1]) - 1]["theme"] = t["id"]
    for f in out:
        del f["_group"]
        if not f["condition"]:
            del f["condition"]

    open_groups: dict[str, dict] = {}
    for o in report.get("open", []):
        g = open_groups.setdefault(o["text"], {"text": o["text"], "kind": o.get("kind"), "members": [], "qualifies": 0})
        g["members"].append(o["id"])
        g["qualifies"] += len(o.get("qualifies", []))
    opens = [{"id": f"open-group:{i}", **g} for i, g in enumerate(open_groups.values(), 1)]

    _check_lossless(report, out, opens)

    kinds = defaultdict(lambda: [0, 0])
    for f in out:
        k = (f["requirement"], f["step"], f["status"])
        kinds[k][0] += len(f["members"])
        kinds[k][1] += 1
    result = {
        "report": {
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "skuld": skuld.__version__,
            "ratatoskr": ratatoskr.__version__,
            "components": [COMPONENT],
            "assessment": assessment_meta
            or {"path": ASSESSMENT, "sha256": "0" * 64, "created": report["report"]["created"]},
            "order": ORDER,
        },
        "application": report["application"],
        "counts": {
            "concerns": len(report["concerns"]),
            "aggregated_concerns": len(out),
            "themes": len(theme_list),
            "open": len(report.get("open", [])),
            "open_groups": len(opens),
            "by_kind": [
                {"requirement": r, "step": s, "status": st, "concerns": n, "aggregated_concerns": m}
                for (r, s, st), (n, m) in sorted(kinds.items())
            ],
        },
        "themes": theme_list,
        "aggregated_concerns": out,
        "open": opens,
    }
    return result


def _order(f: dict):
    status = STATUS_ORDER.index(f["status"]) if f["status"] in STATUS_ORDER else len(STATUS_ORDER)
    tier = TIER_ORDER.index(f["tier"]) if f["tier"] in TIER_ORDER else len(TIER_ORDER)
    return (status, tier, f["disagreeing"] > 0, -len(f["members"]), f["label"], json.dumps(f["key"], sort_keys=True))


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _label(f: dict) -> str:
    k, members = f["key"], f["members"]
    if f["_group"] == "practice":
        purposes = ", ".join(k["purposes"])
        own = sorted({m.get("purpose") or "?" for m in members} - set(k["purposes"]))
        purpose = purposes + (f" (also {', '.join(own)})" if own else "")
        recipients = len({m.get("recipient") for m in members})
        head = f"{k['data']} for {purpose}"
        if f["requirement"] == "data_minimised":
            what = OUTCOME_TEXT[k["outcome"]] + (f" ({', '.join(k['components'])})" if k.get("components") else "")
        else:
            what = "no specified purpose covers it"
        return f"{head}: {what}; {_count(recipients, 'recipient', 'recipients')}"
    if f["_group"] == "declared":
        return f"{k['declared'] or 'no node'}: {_count(len(members), 'declared purpose', 'declared purposes')} judged not specific"
    if f["_group"] == "contradicted":
        said = next((m.get("statement") for m in members if m.get("statement")), None)
        short = (said[:77] + "…") if said and len(said) > 78 else said
        return f"declaration {k['subject']} contradicted by the processing observed" + (f": “{short}”" if short else "")
    if f["_group"] == "collection":
        cond = f" (if {', '.join(k['condition'])})" if k.get("condition") else ""
        return f"{f['requirement']}: {f['step'].replace('_', ' ')}{cond}"
    return f"{f['requirement']} on {k['subject']}: {f['step'].replace('_', ' ')}"


def _theme(f: dict) -> tuple[tuple, str]:
    status = f["status"].replace("_", " ")
    if f["key"].get("purposes") is not None:
        purposes = ", ".join(f["key"]["purposes"])
        return (f["requirement"], f["status"], purposes), f"{f['requirement']}, {status}: {purposes}"
    if f["requirement"] == "purpose_specific":
        return (f["requirement"], f["status"]), f"declared purposes not specific, {status}"
    if f["principle"] and f["key"].get("subject") is None and f["tier"] == "rule":
        return ("collection", f["status"]), f"information not given, {status}"
    return (f["requirement"], f["status"]), f"{f['requirement']}, {status}"


def _check_lossless(report: dict, aggregated: list[dict], opens: list[dict]) -> None:
    want = [c["id"] for c in report["concerns"]]
    got = [m["concern"] for f in aggregated for m in f["members"]]
    if sorted(want) != sorted(got):
        missing, extra = set(want) - set(got), set(got) - set(want)
        raise AggregateError(
            f"aggregate would lose or repeat concerns: missing {sorted(missing)[:5]}, extra {sorted(extra)[:5]}"
        )
    want = [o["id"] for o in report.get("open", [])]
    got = [m for g in opens for m in g["members"]]
    if sorted(want) != sorted(got):
        raise AggregateError("aggregate would lose or repeat open conditions")
    concerns = {c["id"]: c for c in report["concerns"]}
    for f in aggregated:
        for m in f["members"]:
            c = concerns[m["concern"]]
            if any(c[x] != f[x] for x in ("requirement", "step", "tier", "status")):
                raise AggregateError(f"{f['label']}: {m['concern']} differs in requirement, step, tier or status")


# -- files ----------------------------------------------------------------------------------------------------------


def run(root: str | Path, write: bool = True) -> dict:
    """Aggregates the workspace's assessment.json; writes aggregate.json and aggregate.md unless `write` is False."""
    root = Path(root)
    path = root / ASSESSMENT
    if not path.is_file():
        raise AggregateError(f"{root}: no {ASSESSMENT}; run skuld assess first")
    report = json.loads(path.read_text(encoding="utf-8"))
    meta = {"path": ASSESSMENT, "sha256": inputs.digest(path), "created": report["report"]["created"]}
    result = aggregate(report, meta)
    validate("expectation_aggregate", result)
    if write:
        (root / REPORT).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        (root / MARKDOWN).write_text(markdown(result), encoding="utf-8", newline="\n")
    return result


def markdown(a: dict, shown: int = 12) -> str:
    app, c = a["application"], a["counts"]
    lines = [
        f"# Aggregate: {app['package']} {app['version']}",
        "",
        f"Skuld {a['report']['skuld']}, {a['report']['created']}; assessment {a['report']['assessment']['sha256'][:12]}. "
        f"{c['concerns']} concerns in {c['aggregated_concerns']} aggregated concerns and {c['themes']} themes; "
        f"{c['open']} open conditions in {c['open_groups']} groups. Order: {a['report']['order']}.",
        "",
        "| requirement | step | status | concerns | aggregated concerns |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {k['requirement']} | {k['step']} | {k['status']} | {k['concerns']} | {k['aggregated_concerns']} |"
        for k in c["by_kind"]
    ]
    aggregated = {f["id"]: f for f in a["aggregated_concerns"]}
    status = None
    for t in a["themes"]:
        if t["status"] != status:
            status = t["status"]
            lines += ["", f"## {status.replace('_', ' ').capitalize()}"]
        lines += ["", f"### {t['label']}", ""]
        for fid in t["aggregated_concerns"]:
            f = aggregated[fid]
            u = f["uncertainty"]
            note = f"; samples disagreed on {f['disagreeing']}" if f["disagreeing"] else ""
            lines.append(f"- **{f['label']}** ({f['tier']}; U s {u['s']}, n {u['n']}{note}; {fid})")
            rows = _rows(f["members"])
            lines += [f"  - {r}" for r in rows[:shown]]
            if len(rows) > shown:
                lines.append(f"  - … and {len(rows) - shown} more (aggregate.json)")
    if a["open"]:
        lines += ["", "## Open conditions", ""]
        lines += [f"- {g['text']} ({_count(g['qualifies'], 'qualified item', 'qualified items')})" for g in a["open"]]
    return "\n".join(lines) + "\n"


def _rows(members: list[dict]) -> list[str]:
    """The members as the Markdown lists them: a practice once, with every purpose it is a member under."""
    order: list = []  # a statement's or other member's line, or a practice's subject
    practices: dict[str, dict] = {}
    for m in members:
        if "statement" in m:
            order.append(f'"{m["statement"]}" ({m["subject"]})')
        elif "data" in m:
            if m["subject"] not in practices:
                practices[m["subject"]] = {"recipient": m.get("recipient"), "purposes": [], "alternatives": []}
                order.append(("practice", m["subject"]))
            p = practices[m["subject"]]
            p["purposes"].append(m.get("purpose") or "?")
            p["alternatives"] += [a for a in m.get("alternatives", []) if a not in p["alternatives"]]
        else:
            order.append(f"{m['subject']}: {m['reason']}")
    out = []
    for row in order:
        if isinstance(row, str):
            out.append(row)
            continue
        p = practices[row[1]]
        alts = f"; alternatives: {'; '.join(p['alternatives'])}" if p["alternatives"] else ""
        out.append(f"{p['recipient'] or '?'} ({row[1]}): {', '.join(p['purposes'])}{alts}")
    return out
