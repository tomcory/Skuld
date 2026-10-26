"""
Processing configurations: the baseline from the Observation dimension's claims, and alternatives.

A configuration assigns each dimension the instance imposes a value: data (the nodes of O's Transmits and Accesses
claims), recipients (their register entities, or the domain where no entity is known) and granularity (a datum's
node is its precision). Each is ordered by "at most as invasive as". An alternative changes its component's
dimension only, so it is compared there: it is a member of the search space if it is less invasive there than the
baseline.
"""

from ratatoskr.vocabularies import Vocabulary

from skuld.inputs import Alternative, Case, Component

UNKNOWN = "?"
#: Dimensions whose value is a set, ordered by inclusion
SETS = ("D", "R")


def recipient(claim: dict) -> str | None:
    """A Transmits claim's recipient: its register entity, else its domain, else its host."""
    r = claim.get("recipient")
    if not r:
        return None
    if r.get("entity") not in (None, UNKNOWN):
        return r["entity"]
    return f"domain:{r.get('domain') or r['endpoint']['host']}"


def baseline(reports: list[dict]) -> dict:
    """The baseline configuration u_0: what O's reports of the baseline runs establish, unioned."""
    data, recipients, precision = set(), set(), {}
    from skuld.observe import claims

    for report in reports:
        for claim in claims(report):
            node = claim["datum"]["node"]
            data.add(node)
            precision[node] = node
            if claim["type"] == "transmits" and (r := recipient(claim)):
                recipients.add(r)
    return {"D": sorted(data), "R": sorted(recipients), "G": dict(sorted(precision.items()))}


def present(component: Component, u0: dict, vocabulary: Vocabulary) -> bool:
    """Whether a component is a component of u_0. A datum is present if u_0 holds it or a node below it."""
    if component.dimension == "R":
        return component.entity in u0["R"]
    return any(n == component.node or (n in vocabulary and vocabulary.is_a(n, component.node)) for n in u0["D"])


def apply(u0: dict, alternative: Alternative, case: Case) -> dict:
    """The configuration u' of an alternative: u_0 with its changes. A value of None removes a datum or recipient."""
    u = {"D": list(u0["D"]), "R": list(u0["R"]), "G": dict(u0["G"])}
    for change in alternative.changes:
        component = case.component(change["component"])
        if component.dimension == "R":
            if change["value"] is None:
                u["R"] = [r for r in u["R"] if r != component.entity]
        elif component.dimension == "D":
            if change["value"] is None:
                # a removed datum's precision is left as it was, so that the removal changes D alone
                u["D"] = [n for n in u["D"] if n != component.node]
        else:
            u["G"][component.node] = change["value"]
    return u


def changed(u0: dict, u: dict) -> list[str]:
    """chg(u_0, u'): the dimensions in which two configurations differ."""
    return [d for d in u0 if u0[d] != u[d]]


def check(alternative: Alternative, case: Case, u0: dict, vocabulary: Vocabulary) -> list[str]:
    """
    What makes an alternative no member of a search space: a change outside its component's dimension, that
    dimension unchanged or made more invasive, or a removal that changes more than its component.
    """
    problems = []
    u = apply(u0, alternative, case)
    chg = changed(u0, u)
    component = case.component(alternative.component)
    dimension = component.dimension
    outside = [d for d in chg if d != dimension]
    if outside:
        problems.append(f"changes {outside} besides its component's dimension {dimension}")
    if dimension not in chg:
        problems.append(f"does not change the dimension {dimension} of its component")
    if alternative.removal and list(alternative.changes) != [{"component": component.id, "value": None}]:
        problems.append("is marked a removal but changes more than its component, or does not remove it")
    if not at_most(u[dimension], u0[dimension], dimension, vocabulary):
        problems.append(f"is not at most as invasive in {dimension}")
    return problems


def at_most(a, b, dimension: str, vocabulary: Vocabulary) -> bool:
    """a ⊴ b in one dimension."""
    if a == b:
        return True
    if dimension in SETS:
        return set(a) <= set(b)
    return all(k in b and coarser(v, b[k], vocabulary) for k, v in a.items())


def coarser(a: str, b: str, vocabulary: Vocabulary) -> bool:
    """
    Whether precision a is at most as fine as b: the same node, a node above it, or a node the vocabulary states is
    coarser than b or than a node above b (`x-coarser-than`; approximate location is coarser than precise location,
    and so are the nodes below it).
    """
    if a == b or (a in vocabulary and b in vocabulary and vocabulary.is_a(b, a)):
        return True
    if a not in vocabulary or b not in vocabulary:
        return False
    for node in (a, *vocabulary.ancestors(a)):
        for finer in vocabulary[node].extra.get("coarser-than") or ():
            if b == finer or vocabulary.is_a(b, finer):
                return True
    return False
