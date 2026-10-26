"""
E's combination (E def:combination), one rule for every channel and every model question: claims are related if
they are of one type, about aligned purposes and the same subject and component (for an alternative of an
experiment, the same alternative); related claims that agree in status are corroborated into one combined claim that
cites them; where they disagree, the claim of greatest strength decides if it is supported or refuted, and the
combined claim takes its status and its value; otherwise the combined claim is conflicted if its claims speak both
for and against it, else not assessable, with the reason, if one of them is, and not established if not. One sample
of a model that supports a claim by documents therefore decides over samples that do not.

A combined claim cites the evidence of its claims that agree with its status, and its uncertainty is, per factor, the
least over them where the factor applies, or the highest over all of them where none agrees. The combination calls no
model and yields no finding: the claims it combines are kept, in the samples and the case report they are read from.

    hypotheses    the expectation stage's claims across its samples: purposes aligned by node and beneficiary within a
                  practice (E's ≈), and the dependencies of each combined purpose by component; they enter the
                  assessment stage as its hypotheses, and nothing of the assessment stage passes back into them
    alternatives  the reasoning tier's Alternative claims across its samples, by purpose and component
    experimental  the experimental channel's claims with the hypotheses of aligned purposes: a hypothesis purpose of a
                  practice is aligned with the case purpose of the same beneficiary whose node is its own or the
                  nearest above it (≈), which raises its semantic uncertainty to moderate; an experiment's Dependency
                  claim is combined with the hypotheses' on the same component. Where no hypothesis aligns, reasoning
                  is silent on the case's purpose, and the experiment's claim stands combined alone.

A claim that rests on a purpose takes the purpose's semantic uncertainty where it is higher than its own.
"""

from skuld.uncertainty import FACTORS, ORDER, highest

#: The strength of a sample's or an experiment's claim, by which the combination decides; a combined claim states it
#: only if supported or refuted, and then it is doc or run, since no rule lets own knowledge decide
STRENGTH = {"own": 0, "doc": 1, "run": 2}
DECISIVE = ("supported", "refuted")
#: What a combined claim carries over from the claim that decides it
CARRIED = ("stage", "tier", "case", "scope", "component", "relationship", "alternative", "level")


def decide(members: list[dict]) -> tuple[str, dict | None]:
    """The status of related claims, and the claim that decides it: the strongest supported or refuted claims if
    they agree in status and value, else conflicted; without one, their common status, else not assessable if one
    is, else not established."""
    decisive = [m for m in members if m["status"] in DECISIVE]
    if not decisive:
        statuses = {m["status"] for m in members}
        if len(statuses) == 1:
            return statuses.pop(), _strongest(members) or members[0]
        return ("not_assessable" if "not_assessable" in statuses else "not_established"), None
    top = _top(decisive)
    if len({(m["status"], m.get("relationship")) for m in top}) == 1:
        return top[0]["status"], top[0]
    return "conflicted", None


def combined(cid: str, members: list[dict], **fields) -> dict:
    """The combined claim of related claims: its status by `decide`, the evidence and uncertainty of the claims that
    agree with it, and what the deciding claim carries."""
    status, decider = decide(members)
    first = decider or members[0]
    agreeing = [m for m in members if m["status"] == status]
    claim = {
        "id": cid,
        "type": first["type"],
        "channels": sorted({ch for m in members for ch in m["channels"]}),
        "of": [m["id"] for m in members],
        "subject": first["subject"],
        "purpose": first["purpose"],
        "status": status,
        "supporting": sorted({i for m in members if m["status"] == "supported" for i in m["supporting"]})
        if status in ("supported", "conflicted")
        else [],
        "challenging": sorted({i for m in members if m["status"] == "refuted" for i in m["challenging"]})
        if status in ("refuted", "conflicted")
        else [],
        "uncertainty": _uncertainty(agreeing or members, minimum=bool(agreeing)),
    }
    for k in CARRIED:
        if k in first:
            claim[k] = first[k]
    if status in DECISIVE:
        claim["strength"] = first.get("strength", "own")
        claim["sufficiency"] = {"sufficient": True}
    else:
        why = next((m["sufficiency"].get("reason") for m in agreeing if m["sufficiency"].get("reason")), None)
        missing = sorted({x for m in members for x in m["sufficiency"].get("missing", [])})
        claim["sufficiency"] = {
            "sufficient": False,
            **({"reason": why} if why else {}),
            **({"missing": missing} if missing else {}),
        }
        if reason := next((m["reason"] for m in agreeing if m.get("reason")), first.get("reason")):
            claim["reason"] = reason
    claim.update(fields)
    return claim


def _strongest(members: list[dict]) -> dict | None:
    rated = [m for m in members if "strength" in m]
    return max(rated, key=lambda m: STRENGTH[m["strength"]]) if rated else None


def _top(decisive: list[dict]) -> list[dict]:
    if not decisive:
        return []
    best = max(STRENGTH[m.get("strength", "own")] for m in decisive)
    return [m for m in decisive if STRENGTH[m.get("strength", "own")] == best]


def _uncertainty(members: list[dict], minimum: bool) -> dict:
    """Per factor, the least level among the members where it applies to any, or the highest."""
    out = {}
    for f in FACTORS:
        levels = [m["uncertainty"][f] for m in members]
        applying = [x for x in levels if x != "not_applicable"]
        out[f] = min(applying, key=ORDER.index) if minimum and applying else highest(*levels)
    return out


def on_purpose(claim: dict, purpose: dict) -> dict:
    """A claim that rests on a purpose, with the purpose's semantic uncertainty where it is higher."""
    claim["uncertainty"] = {
        **claim["uncertainty"],
        "s": highest(claim["uncertainty"]["s"], purpose["uncertainty"]["s"]),
    }
    return claim


def beneficiary(text: str | None) -> str:
    """A purpose's beneficiary as the alignment compares it: the user, the provider, or another party."""
    t = str(text or "").lower()
    if t in ("user", "provider", "other"):
        return t
    return "provider" if "provider" in t else "user" if "user" in t else "other"


class Numbers:
    """The numbers of a report's claims per subject: `claim:<subject>:<n>`."""

    def __init__(self):
        self.n: dict[str, int] = {}

    def __call__(self, subject: str) -> str:
        self.n[subject] = self.n.get(subject, 0) + 1
        return f"claim:{subject}:{self.n[subject]}"


def hypotheses(claims: list[dict], number: Numbers) -> list[dict]:
    """
    The expectation stage's claims combined across its samples: per practice, purposes aligned by node and beneficiary
    (E's ≈), and the dependencies of each combined purpose by component. Each combined claim cites the sample claims
    it combines (`of`) and takes the purpose of the claim that decides it; dependencies name the combined purpose in
    `basis`.
    """
    purposes: dict[tuple, list[dict]] = {}
    for c in claims:
        if c["type"] == "purpose":
            key = (c["subject"], c["purpose"]["node"], beneficiary(c["purpose"]["beneficiary"]))
            purposes.setdefault(key, []).append(c)
    out, of_purpose = [], {}
    for (subject, _, _), members in purposes.items():
        p = combined(number(subject), members)
        out.append(p)
        for m in members:
            of_purpose[m["id"]] = p
    dependencies: dict[tuple, list[dict]] = {}
    for c in claims:
        if c["type"] == "dependency" and c.get("basis") and c["basis"][0] in of_purpose:
            p = of_purpose[c["basis"][0]]
            dependencies.setdefault((c["subject"], p["id"], c["component"]), []).append(c)
    by_id = {p["id"]: p for p in out}
    for (subject, pid, _), members in dependencies.items():
        p = by_id[pid]
        out.append(on_purpose(combined(number(subject), members, purpose=p["purpose"], basis=[pid]), p))
    return out


def alternatives(claims: list[dict], hypotheses: list[dict], number: Numbers) -> list[dict]:
    """The reasoning tier's Alternative claims combined across its samples, per practice, purpose and component."""
    by_id = {h["id"]: h for h in hypotheses}
    groups: dict[tuple, list[dict]] = {}
    for c in claims:
        groups.setdefault((c["subject"], c["basis"][0], c["component"]), []).append(c)
    return [
        on_purpose(combined(number(subject), members, basis=[pid]), by_id[pid])
        for (subject, pid, _), members in groups.items()
    ]


def aligned(hypotheses: list[dict], case_purposes: list[dict], vocabulary) -> dict[str, dict]:
    """Per hypothesis purpose id, the case purpose it aligns with (≈): the same beneficiary, and the case purpose's
    node its own or the nearest above it."""
    out = {}
    for h in hypotheses:
        if h["type"] != "purpose":
            continue
        node = h["purpose"].get("node")
        if not node or node not in vocabulary:
            continue
        lineage = [node, *vocabulary.ancestors(node)]
        who = beneficiary(h["purpose"].get("beneficiary"))
        candidates = [
            (lineage.index(q["node"]), n)
            for n, q in enumerate(case_purposes)
            if q.get("node") in lineage and beneficiary(q.get("beneficiary")) == who
        ]
        if candidates:
            out[h["id"]] = case_purposes[min(candidates)[1]]
    return out


def experimental(hypotheses: list[dict], premises: list[dict], vocabulary, number: Numbers) -> list[dict]:
    """
    The experimental premises combined with the hypotheses of aligned purposes, per practice: one combined claim per
    (case purpose, type, component, and alternative), whose `basis` names the aligned hypothesis purposes, so that a
    concern of a hypothesis purpose reads it.
    """
    out: list[dict] = []
    for subject in sorted({x["subject"] for x in premises}):
        mine = [x for x in premises if x["subject"] == subject]
        purposes = {(x["case"], x["purpose"]["id"]): x["purpose"] for x in mine}
        keys = list(purposes)
        own = [h for h in hypotheses if h["subject"] == subject]
        by_id = {h["id"]: h for h in own}
        to = aligned(own, [purposes[k] for k in keys], vocabulary)
        by_case_purpose: dict[tuple, list[str]] = {}
        for hid, q in to.items():
            k = next(k for k in keys if purposes[k] is q)
            by_case_purpose.setdefault(k, []).append(hid)
        groups: dict[tuple, list[dict]] = {}
        for x in mine:
            k = (x["case"], x["purpose"]["id"])
            groups.setdefault((k, x["type"], x["component"], x.get("alternative")), []).append(x)
        for h in own:
            if h["type"] != "dependency" or not h.get("basis"):
                continue
            for k, hids in by_case_purpose.items():
                if h["basis"][0] in hids and (key := (k, "dependency", h["component"], None)) in groups:
                    groups[key].append(h)
        for (k, _, _, _), members in groups.items():
            x = next(m for m in members if m["stage"] == "assessment")
            basis = sorted(by_case_purpose.get(k, []))
            claim = combined(
                number(subject),
                members,
                stage="assessment",
                purpose=purposes[k],
                case=x["case"],
                scope=x["scope"],
                component=x["component"],
                basis=basis,
            )
            if any(by_id[h]["purpose"].get("node") != purposes[k].get("node") for h in basis):
                claim["uncertainty"]["s"] = highest(claim["uncertainty"]["s"], "moderate")
            out.append(claim)
    return out
