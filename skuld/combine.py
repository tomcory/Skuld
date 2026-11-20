"""
E's combination (E def:combination), one rule for every channel and every model question: claims are related if
they are of one type, about aligned purposes and the same subject and component (for an alternative of an
experiment, the same alternative); related claims that agree in status are corroborated into one combined claim that
cites them; where they disagree, the claim of greatest strength decides if it is supported or refuted, and the
combined claim takes its status and its value; otherwise the combined claim is conflicted if its claims speak both
for and against it. Where none decides, a claim that could not be assessed abstains: the claims that were judged give
the status (their common one, else not established), and the combined claim is not assessable, with the reason, only
if every claim is (author, 13 Nov 2026; before, one claim not assessable made the combination not assessable, so that
a sample with a vague purpose outweighed samples that judged the dependency). One sample of a model that supports a
claim by documents therefore decides over samples that do not.

A combined claim cites the evidence of its claims that agree with its status, and its uncertainty is their `either`
(alternatives that establish the same: the least uncertain, with its own reasons), or `needs` over all of them where
none agrees (conflicted: every reason of every member). The combination calls no
model and yields no finding: the claims it combines are kept, in the samples and the case report they are read from.

    hypotheses    the expectation stage's claims across its samples: purposes aligned by node and beneficiary within a
                  practice (E's ≈), and the dependencies of each combined purpose by component; they enter the
                  assessment stage as its hypotheses, and nothing of the assessment stage passes back into them
    alternatives  the reasoning tier's Alternative claims across its samples, by purpose and component; from reading 2
                  a documented alternative stays supported only with a majority of its question's samples (gate (d),
                  MAJORITY), else it is not established
    experimental  the experimental channel's claims with the hypotheses of aligned purposes: a hypothesis purpose of a
                  practice is aligned with the case purpose of the same beneficiary at its own node, and, where the
                  experiment broke the case purpose, also with one at the nearest node above it (≈), which raises its
                  uncertainty to moderate (`aligned_above`) (C1, author 14 Nov 2026: that a function survives without the data
                  shows nothing for a narrower purpose, while that it breaks holds for every purpose it includes); an
                  experiment's Dependency
                  claim is combined with the hypotheses' on the same component. Where no hypothesis aligns, reasoning
                  is silent on the experimental case's purpose, and the experiment's claim stands combined alone.

A combined claim's uncertainty is used here, to set its concerns', and not stored: the assessment names this function
(`uncertainty.CLAIMS`). A concern resting on a purpose `needs` the purpose's uncertainty with its own.
"""

from skuld.uncertainty import either, needs, raised

#: The strength of a sample's or an experiment's claim, by which the combination decides; a combined claim states it
#: only if supported or refuted, and then it is doc or run, since no rule lets own knowledge decide
STRENGTH = {"own": 0, "doc": 1, "run": 2}
DECISIVE = ("supported", "refuted")
#: The combination as a named method of the report: 2 since claims that could not be assessed abstain (13 Nov 2026);
#: 3 since an alternative demoted by gate (d) takes the uncertainty of the members that agree with it, not of those
#: that support it (20 Nov 2026); 4: one level with its reasons (Ratatoskr 0.34.0): either over the agreeing members,
#: needs over all where none agrees, aligned_above for C1
VERSION = "4"
COMPONENT = {"role": "method", "id": "skuld.combine", "version": VERSION}
#: What a combined claim carries over from the claim that decides it
CARRIED = ("stage", "tier", "case", "scope", "component", "relationship", "alternative", "level")


def decide(members: list[dict]) -> tuple[str, dict | None]:
    """The status of related claims, and the claim that decides it: the strongest supported or refuted claims if
    they agree in status and value, else conflicted; without one, the claims that were assessed decide (their common
    status, else not established), and only if none was is the status not assessable."""
    decisive = [m for m in members if m["status"] in DECISIVE]
    if not decisive:
        judged = [m for m in members if m["status"] != "not_assessable"] or members
        statuses = {m["status"] for m in judged}
        if len(statuses) == 1:
            return statuses.pop(), _strongest(judged) or judged[0]
        return "not_established", None
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
        # the members of lesser strength it decided over: a model's sample overruled by a measurement, or the reverse
        overruled = [
            {
                "claim": m["id"],
                "channels": m["channels"],
                **({"stage": m["stage"]} if m.get("stage") else {}),
                **({"tier": m["tier"]} if m.get("tier") else {}),
                "status": m["status"],
                "strength": m.get("strength", "own"),
            }
            for m in members
            if m["status"] in DECISIVE and (m["status"], m.get("relationship")) != (status, first.get("relationship"))
        ]
        if overruled:
            claim["overruled"] = overruled
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
    """The members as alternatives that establish the same (`either`) where they agree, else what all of them rest on
    together (`needs`)."""
    uncertainties = [m["uncertainty"] for m in members]
    return either(*uncertainties) if minimum else needs(*uncertainties)


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
        out.append(combined(number(subject), members, purpose=p["purpose"], basis=[pid]))
    return out


#: Gate (d) of E's status rule for a documented alternative (Expectation report 0.9, def:combination): a majority of
#: the samples of its question must support it, since one sample of three decided 40-60 % of the study's
#: documented alternatives. It applies from the reasoning tier's reading 2 (judge.READING) on.
MAJORITY = "gate (d): no majority of the samples of its question supports the alternative"


def alternatives(claims: list[dict], number: Numbers, asked: dict[str, set[str]] | None = None) -> list[dict]:
    """The reasoning tier's Alternative claims combined across its samples, per practice, purpose and component.
    With `asked` (the samples of each practice's minimisation question, by sample name), a supported combined claim
    must be supported by more than half of them (gate d), and is otherwise not established."""
    groups: dict[tuple, list[dict]] = {}
    for c in claims:
        groups.setdefault((c["subject"], c["basis"][0], c["component"]), []).append(c)
    out = []
    for (subject, pid, _), members in groups.items():
        claim = combined(number(subject), members, basis=[pid])
        if asked is not None and claim["status"] == "supported" and claim.get("tier") == "reasoning":
            samples = asked.get(subject) or set()
            supporting = {
                ch.removeprefix("reasoning:") for m in members if m["status"] == "supported" for ch in m["channels"]
            }
            if samples and 2 * len(supporting & samples) <= len(samples):
                claim = _without_majority(claim, members, len(supporting & samples), len(samples))
        out.append(claim)
    return out


def _without_majority(claim: dict, members: list[dict], supporting: int, samples: int) -> dict:
    """A supported alternative that too few samples support: plausible and not established, with gate (d) as reason.
    Its uncertainty is a not-established claim's: `either` over the members not established, else `needs` over all
    (`combined`), not the supporting members' it would keep otherwise."""
    claim = {k: v for k, v in claim.items() if k not in ("strength", "overruled")}
    agreeing = [m for m in members if m["status"] == "not_established"]
    claim.update(
        uncertainty=_uncertainty(agreeing or members, minimum=bool(agreeing)),
        status="not_established",
        level="plausible",
        supporting=[],
        sufficiency={"sufficient": False, "reason": "not_admitted"},
        reason=f"{MAJORITY} ({supporting} of {samples})",
    )
    return claim


def aligned(hypotheses: list[dict], case_purposes: list[dict], vocabulary, same_node: bool = False) -> dict[str, dict]:
    """Per hypothesis purpose id, the case purpose it aligns with (≈): the same beneficiary, and the case purpose's
    node its own or the nearest above it; with `same_node`, its own only."""
    out = {}
    for h in hypotheses:
        if h["type"] != "purpose":
            continue
        node = h["purpose"].get("node")
        if not node or node not in vocabulary:
            continue
        lineage = [node] if same_node else [node, *vocabulary.ancestors(node)]
        who = beneficiary(h["purpose"].get("beneficiary"))
        candidates = [
            (lineage.index(q["node"]), n)
            for n, q in enumerate(case_purposes)
            if q.get("node") in lineage and beneficiary(q.get("beneficiary")) == who
        ]
        if candidates:
            out[h["id"]] = case_purposes[min(candidates)[1]]
    return out


#: The statuses of an experimental premise that an experiment decided
DECIDED = ("supported", "refuted")


def experimental(hypotheses: list[dict], premises: list[dict], vocabulary, number: Numbers) -> list[dict]:
    """
    The experimental premises combined with the hypotheses of aligned purposes, per practice: one combined claim per
    (case purpose, type, component, and alternative), whose `basis` names the aligned hypothesis purposes, so that a
    concern of a hypothesis purpose reads it.

    Only a premise an experiment decided (supported or refuted) is combined so. One that decided nothing (its
    purpose has no oracle: not_assessable; the comparison was undecided: not_established) stays a claim of its own
    with an empty basis: the experiment is reported, but it neither merges the hypotheses aligned to its purpose
    into one claim nor gives a concern of theirs a premise (author, 12 Nov 2026).
    """
    out: list[dict] = []
    for x in premises:
        if x["status"] not in DECIDED:
            out.append(
                combined(
                    number(x["subject"]),
                    [x],
                    stage="assessment",
                    purpose=x["purpose"],
                    case=x["case"],
                    scope=x["scope"],
                    component=x["component"],
                    basis=[],
                )
            )
    premises = [x for x in premises if x["status"] in DECIDED]
    for subject in sorted({x["subject"] for x in premises}):
        mine = [x for x in premises if x["subject"] == subject]
        purposes = {(x["case"], x["purpose"]["id"]): x["purpose"] for x in mine}
        keys = list(purposes)
        own = [h for h in hypotheses if h["subject"] == subject]
        by_id = {h["id"]: h for h in own}
        # C1: a preserved purpose reaches hypotheses at its own node only; a broken one also those below it
        by_reach: dict[bool, dict[tuple, list[str]]] = {}
        for same_node in (True, False):
            by_case_purpose: dict[tuple, list[str]] = {}
            for hid, q in aligned(own, [purposes[k] for k in keys], vocabulary, same_node).items():
                k = next(k for k in keys if purposes[k] is q)
                by_case_purpose.setdefault(k, []).append(hid)
            by_reach[same_node] = by_case_purpose
        groups: dict[tuple, list[dict]] = {}
        for x in mine:
            k = (x["case"], x["purpose"]["id"])
            groups.setdefault((k, x["type"], x["component"], x.get("alternative")), []).append(x)

        def reach(members: list[dict], by_reach=by_reach) -> dict[tuple, list[str]]:
            return by_reach[not any(m.get("broke") for m in members if m["stage"] == "assessment")]

        for h in own:
            if h["type"] != "dependency" or not h.get("basis"):
                continue
            for key, members in groups.items():
                k, kind, component, _ = key
                if kind == "dependency" and component == h["component"] and h["basis"][0] in reach(members).get(k, []):
                    members.append(h)
        for (k, _, _, _), members in groups.items():
            x = next(m for m in members if m["stage"] == "assessment")
            basis = sorted(reach(members).get(k, []))
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
                claim["uncertainty"] = raised(claim["uncertainty"], "aligned_above")
            out.append(claim)
    return out
