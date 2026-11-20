"""What several modules read alike: how an answer names the context's ids, a host under a domain, the vocabularies."""

from functools import cache

from ratatoskr.vocabularies import Vocabulary

#: How an answer names a step or part that rests on no part of the context
OWN = "own knowledge"
DATA, PURPOSES, RECIPIENT_TYPES = "asgard-data", "dpv-purposes", "recipient-types"


def ref(text) -> str:
    """An id as the answer wrote it, without the brackets the context shows ids in: '[x-loc]' is 'x-loc'."""
    return str(text or "").strip().strip("[]").strip()


def cited(cites: list[str], ids: set[str]) -> bool:
    """Whether a step or part rests on the context alone: it cites parts, all of them in the context, and no own
    knowledge."""
    cites = [ref(c) for c in cites]
    return bool(cites) and OWN not in [c.lower() for c in cites] and set(cites) <= ids


def under(host: str, domain: str) -> bool:
    """Whether a host is the domain or below it."""
    return host == domain or host.endswith("." + domain)


def vocabulary(name: str) -> Vocabulary:
    """A bundled vocabulary, loaded once, in the version config.json's (or the profile's) `vocabularies` names, else
    the one Ratatoskr bundles. The purpose vocabulary's nodes are part of the stage-1 prompt, so samples asked under
    one version are found only under it (dpv-purposes 2.3.1 added a node on 20 Nov 2026; the fixtures and the study's
    runs were asked under 2.3)."""
    from skuld import config

    return _vocabulary(name, (config.load().get("vocabularies") or {}).get(name))


@cache
def _vocabulary(name: str, version: str | None) -> Vocabulary:
    return Vocabulary.load(name, version=version)
