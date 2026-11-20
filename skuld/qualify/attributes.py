"""
Case attributes (plan/archive/QUALIFICATION_PLAN.md §2.3): the facts of a case that triage selects on, stated in full so that it
can select from reports alone. They describe a case; no rule of qualification reads them to set a result.

    claim_type        the practice's, or the declaration's (declares_collection, declares_recipient)
    data              the data node with its label
    special_category  the node at or above the data that the data vocabulary marks a special category (Art. 9)
    recipient         the register entity or domain with its name, or the declared recipient; null if none
    party             own, other or ?, with its basis (never a legal role); practices only
    actor             the component that sent or accessed, or ?; practices only
    declared_in       per declaration of practice the case holds: its channel and the O–D outcome relating it
    o_d               the case's O–D outcomes by aspect, with their conditions
    concerns          per concern of the case: its step, status and the strength of its evidence: `rule` for the rule
                      tier (O's and D's reports), `documented` for the reasoning tier, and for a concern of
                      minimisation `demonstrated` where an alternative it rests on was measured by a run (Expectation
                      report 0.9, option C); since version 2
"""

VERSION = "2"
COMPONENT = {"role": "method", "id": "skuld.qualify.attributes", "version": VERSION}

SPECIAL = "special-category"


def _data(node: str | None, data) -> tuple[dict, dict | None]:
    if not node:
        return {"node": "?"}, None
    if data is None or node not in data:
        return {"node": node}, None
    out = {"node": node, "label": data[node].title}
    for n in (node, *data.ancestors(node)):
        if data[n].extra.get("gdpr") == SPECIAL:
            return out, {"node": n, "label": data[n].title}
    return out, None


def _recipient(recipient, registry) -> dict | None:
    if recipient in (None, "?"):
        return None
    if isinstance(recipient, dict):  # a declared recipient: an entity or a category
        entity = recipient.get("entity") or recipient.get("_entity")
        category = recipient.get("category") or next(iter(recipient.get("categories") or ()), None)
        if entity:
            return {"id": entity, **_name(entity, registry), **({"category": category} if category else {})}
        return {"id": category or "?", **({"category": category} if category else {})}
    return {"id": recipient, **_name(recipient, registry)}


def _name(entity: str, registry) -> dict:
    if entity.startswith("domain:"):
        return {"name": entity.removeprefix("domain:")}
    e = registry.entities.get(entity) if registry is not None else None
    return {"name": e.name} if e is not None else {}


def of_case(index, holding, data, registry) -> dict:
    """The attributes of a practice case or a declaration-only case."""
    od = [index.relations[r] for r in holding.relations if index.relations[r]["type"] == "O-D"]
    if holding.kind == "practice":
        p = index.practices[holding.subject]
        node, special = _data(p["data"], data)
        party = p.get("party")
        out = {
            "claim_type": p["claim_type"],
            "data": node,
            "special_category": special,
            "recipient": _recipient(p.get("recipient"), registry),
            "party": {"relation": party["relation"], "basis": party.get("basis", [])} if party else None,
            "actor": p.get("actor"),
        }
        declared_in = []
        for r in od:
            for t in r.get("to", []):
                d = index.declaration_of(t)
                if d:
                    declared_in.append(_declared(index.declarations[d], r))
        out["declared_in"] = sorted(declared_in, key=lambda x: (x["declaration"], x.get("relation", "")))
    else:
        d = index.declarations[holding.subject]
        node, special = _data(d.get("data"), data)
        out = {
            "claim_type": d.get("type", "?"),
            "data": node,
            "special_category": special,
            "recipient": _recipient(d.get("recipient"), registry),
            "party": None,
            "actor": None,
            "declared_in": [_declared(d, r) for r in od]
            or [{"declaration": d["id"], "channel": d.get("channel", "?")}],
        }
    out["o_d"] = [
        {
            "relation": r["id"],
            "outcome": r["outcome"],
            **({"aspect": r["aspect"]} if r.get("aspect") else {}),
            **({"partial": r["partial"]} if r.get("partial") else {}),
            **({"condition": r["condition"]} if r.get("condition") else {}),
        }
        for r in od
    ]
    out["concerns"] = _concerns(index, holding)
    return out


def evidence(concern: dict, claims: dict) -> str:
    """The strength of a concern's evidence: rule, documented, or demonstrated by a run."""
    if concern.get("tier") == "rule":
        return "rule"
    if concern.get("step") == "less_invasive_alternative":
        premises = [claims[b] for b in concern.get("basis") or () if b in claims]
        if any(p.get("strength") == "run" or p.get("level") == "demonstrated" for p in premises):
            return "demonstrated"
    return "documented"


def _concerns(index, holding) -> list[dict]:
    out = []
    for cid in holding.concerns:
        c = index.concerns[cid]
        if c["status"] == "not_applicable":
            continue
        out.append({"concern": cid, "step": c["step"], "status": c["status"], "evidence": evidence(c, index.claims)})
    return out


def _declared(d: dict, r: dict) -> dict:
    return {
        "declaration": d["id"],
        "channel": d.get("channel") or d["claim"]["claim"].split(":", 1)[0],
        "outcome": r["outcome"],
        "relation": r["id"],
        **({"aspect": r["aspect"]} if r.get("aspect") else {}),
        **({"alignment": r["alignment"]} if r.get("alignment") else {}),
    }
