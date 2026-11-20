"""
The search space of a generated case, derived by rules from what the Observation dimension establishes during the
feature's path and the interventions Skuld can impose.

Per datum read from a source Loki hooks, a removal: the source hands the application a constant value instead
(`REPLACEMENTS`), which changes D. Per read of the location, coarser precision: coordinates rounded to one and to no
decimal, which changes G. Per recipient of a transmission that the registry resolves to an entity other than the
application's provider, a removal: every domain the recording saw it on blocked, which changes R. Whether a
recipient is the provider's is decided as for the assessment's practices (parties.py): by the register entity, or by
the domain where the register has none, so that a selection never asks for a removal the generator does not derive.

Conditions are named by their intervention, and an intervention depends on the recording only, never on the
episode, so that the cases that impose it share its runs.

For the assessment, the same rules per practice (`imposable`), and the practice component a case's component varies
(`varies`): a datum's removal or precision varies the data of every practice of that datum or a datum below it, a
recipient's removal the recipient of every transmission to that entity.
"""

from collections.abc import Callable

from skuld import parties
from skuld.common import DATA, vocabulary
from skuld.configuration import UNKNOWN
from skuld.observe import claims
from skuld.verify import NODE_SOURCES

#: The constant each identifier source hands the application instead of its value
REPLACEMENTS = {
    "advertising_id": "00000000-0000-0000-0000-000000000000",
    "android_id": "0000000000000000",
    "app_set_id": "00000000-0000-0000-0000-000000000000",
    "drm_id": "00" * 32,
    "gsf_id": "0000000000000000",
    "sim_id": "000000000000000",
}
#: The decimals coarser location is rounded to, with the node its precision is
ROUNDINGS = ((1, "location.approximate-location"), (0, "location.approximate-location"))
LOCATION = "location.coordinates"


def in_episode(claim: dict, episodes: set[str]) -> bool:
    """Whether a claim occurred in one of the episodes ('?' and '0': before the first episode)."""
    return any(str(c.get("episode")) in episodes for c in claim["qualifiers"].get("contexts") or ())


def provider_own(registry, provider: parties.Controller) -> Callable[[dict], bool]:
    """Whether a recipient of O's claims is the provider's: by its register entity, else by its domain."""

    def own(recipient: dict) -> bool:
        party = parties.relate(recipient["entity"], registry, provider)
        if party.relation == parties.UNKNOWN and recipient.get("domain"):
            party = parties.relate(f"domain:{recipient['domain']}", registry, provider)
        return party.relation == parties.OWN

    return own


def derive(report: dict, episodes: set[str], package: str, keep=None, own=None) -> tuple[list[dict], list[dict]]:
    """The components and alternatives of a case whose path is the given episodes of the recording; with `keep`,
    only the components it keeps (a selection's) and their alternatives. `own` decides whether a recipient is the
    provider's (default: by the package alone, without the register)."""
    own = own or provider_own(None, parties.controller(None, package))
    components: dict[str, dict] = {}
    alternatives: list[dict] = []
    sources: set[str] = set()
    location = False
    recipients: set[str] = set()
    domains: dict[str, set[str]] = {}
    for claim in claims(report):
        r = claim.get("recipient") or {}
        if claim["type"] == "transmits" and r.get("entity") not in (None, UNKNOWN) and r.get("domain"):
            domains.setdefault(r["entity"], set()).add(r["domain"])
        if not in_episode(claim, episodes):
            continue
        node = claim["datum"]["node"]
        identity = claim["datum"].get("value_identity") or ""
        source = identity.removeprefix("source:") if identity.startswith("source:") else NODE_SOURCES.get(node)
        if source in REPLACEMENTS:
            sources.add(source)
        elif source == "location" or node == LOCATION:
            location = True
        if claim["type"] == "transmits" and r.get("entity") not in (None, UNKNOWN) and r.get("domain"):
            if not own(r):
                recipients.add(r["entity"])
    for source in sorted(sources):
        cid = f"x-{source.replace('_', '-')}"
        components[cid] = {"id": cid, "dimension": "D", "node": _node(source), "name": source.replace("_", " ")}
        alternatives.append(
            {
                "id": f"D-{source}",
                "component": cid,
                "removal": True,
                "changes": [{"component": cid, "value": None}],
                "intervention": {"sources": {source: f"replace:{REPLACEMENTS[source]}"}},
            }
        )
    if location:
        components["x-loc"] = {
            "id": "x-loc",
            "dimension": "G",
            "node": LOCATION,
            "value": LOCATION,
            "name": "the precision of the device's location",
        }
        for decimals, node in ROUNDINGS:
            alternatives.append(
                {
                    "id": f"G-round{decimals}",
                    "component": "x-loc",
                    "changes": [{"component": "x-loc", "value": node}],
                    "intervention": {"sources": {"location": f"round:{decimals}"}},
                }
            )
    for entity in sorted(recipients):
        cid = f"x-{entity}"
        components[cid] = {"id": cid, "dimension": "R", "entity": entity, "name": entity}
        alternatives.append(
            {
                "id": f"R-{entity}",
                "component": cid,
                "removal": True,
                "changes": [{"component": cid, "value": None}],
                "intervention": {"block_hosts": sorted(domains[entity])},
            }
        )
    if keep is not None:
        components = {k: c for k, c in components.items() if keep(c)}
        alternatives = [a for a in alternatives if a["component"] in components]
    return list(components.values()), alternatives


def _node(source: str) -> str:
    return next(node for node, s in NODE_SOURCES.items() if s == source)


def varies(component: dict, practice, data) -> str | None:
    """The component of a practice (`<practice>.data` or `<practice>.recipient`) that a case's component varies, or
    None."""
    if component["dimension"] in ("D", "G"):
        node = component.get("node")
        if node and practice.data in data and data.is_a(practice.data, node):
            return f"{practice.id}.data"
    elif component["dimension"] == "R" and component.get("entity") == practice.recipient:
        return f"{practice.id}.recipient"
    return None


def imposable(practice) -> list[dict]:
    """What Skuld can impose on a practice, by the rules of `derive`: {component, dimension, alternatives}. Its party
    relation reads D's controller too, so a recipient `derive` takes for the provider's is never one it imposes."""
    out = []
    data = vocabulary(DATA)
    known = practice.data in data
    # as `varies` reads a case's components: a datum at or below a source's node, or below location
    source = NODE_SOURCES.get(practice.data) or next(
        (s for node, s in NODE_SOURCES.items() if known and node in data and data.is_a(practice.data, node)), None
    )
    if source in REPLACEMENTS:
        out.append({"component": f"{practice.id}.data", "dimension": "D", "alternatives": [f"D-{source}"]})
    elif practice.data == LOCATION or (known and LOCATION in data and data.is_a(practice.data, LOCATION)):
        alternatives = [f"G-round{d}" for d, _ in ROUNDINGS]
        out.append({"component": f"{practice.id}.data", "dimension": "G", "alternatives": alternatives})
    party = (practice.party or {}).get("relation")
    if practice.claim_type == "transmits" and practice.recipient not in (None, UNKNOWN) and party != "own":
        if not practice.recipient.startswith("domain:"):
            out.append(
                {"component": f"{practice.id}.recipient", "dimension": "R", "alternatives": [f"R-{practice.recipient}"]}
            )
    return out
