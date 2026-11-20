"""
Parties: whether a recipient is the provider itself or another organisation.

O and D each hand this to E as an open condition, since whether a recipient is a third party is a relation between
its owner and the application's provider that no single dimension establishes (framework, recipient). E decides what
the register and D's documents decide together, and passes the rest on:

    own     the recipient's register owner is the controller D's documents name (by name, after the register's
            normalisation), or its domain is the controller's e-mail domain or the package's domain read backwards
            (de.wetteronline.wetterapp: wetteronline.de), which is all there is to go by without D
    other   the recipient's register owner is a known organisation that is not the controller
    ?       neither: an open condition for the Investigator

Legal roles (processor, joint controller, third party) are not inferred from technical identity: `other` says only
that the recipient belongs to another organisation.
"""

from dataclasses import dataclass, field
from pathlib import Path

from ratatoskr.errors import ConfigError
from ratatoskr.registry import Registry, default_path, normalise_name, registrable_domain

OWN, OTHER, UNKNOWN = "own", "other", "?"


@dataclass(frozen=True)
class Controller:
    """The provider, as D's documents name it: names, and the domains of its e-mail addresses."""

    names: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()
    package_domain: str | None = None


@dataclass
class Party:
    recipient: str  # a register entity, or 'domain:<domain>'
    relation: str
    basis: list[str] = field(default_factory=list)
    owner: str | None = None


def load_registry(path=None) -> Registry | None:
    """The recipient register: `path`, else the one config.json's `registry.path` names, else Ratatoskr's built one;
    None without it. Where the configuration pins a build (`registry.sha256`, Ratatoskr 0.32.0's
    Registry.from_config), a register of other content is refused, never read in its place."""
    from skuld import config

    section = config.load().get("registry") or {}
    location = Path(path) if path else Path(section["path"]) if section.get("path") else default_path()
    if not location.is_file():
        if section.get("sha256"):
            raise ConfigError(
                f"No recipient registry at {location}, but the configuration pins the build {section['sha256']}: "
                "build it (python -m ratatoskr.registry.build --offline) from the sources it was built from"
            )
        return None  # without the register, recipients are domains and their parties open
    return Registry.load(location, section.get("sha256"))


def controller(declaration: dict | None, package: str) -> Controller:
    """The controller from the derived documents of D's report (any channel, accessible or not), and the package."""
    names, domains = set(), set()
    for channel in (declaration or {}).get("channels", []):
        c = (channel.get("tilt") or {}).get("controller") or {}
        for name in [c.get("name"), *(c.get("_names") or [])]:
            if name and normalise_name(name):
                names.add(normalise_name(name))
        if c.get("email") and "@" in c["email"]:
            domains.add(registrable_domain(c["email"].split("@", 1)[1]))
    labels = package.split(".")
    package_domain = f"{labels[1]}.{labels[0]}" if len(labels) >= 2 else None
    return Controller(frozenset(names), frozenset(domains), package_domain)


def relate(recipient: str, registry: Registry | None, provider: Controller, at=None) -> Party:
    """Whether a recipient is the provider or another organisation, with the basis of the decision; `at` is when the
    recipient was observed or declared, and the owner is the register's owner then (an acquisition after it does not
    count), else today's."""
    domain = recipient.removeprefix("domain:") if recipient.startswith("domain:") else None
    entity = registry.entities.get(recipient) if registry is not None and domain is None else None
    if entity is not None:
        owner = registry.owner(entity.id, at=at)
        owner_names = {normalise_name(n) for n in (owner.name, *owner.aliases, entity.name)}
        if owner_names & provider.names:
            return Party(recipient, OWN, [f"register owner {owner.name} is the controller D names"], owner.id)
        entity_domains = {registrable_domain(d) for d in entity.domains + owner.domains}
        if entity_domains & provider.domains:
            return Party(
                recipient, OWN, ["a domain of the register entity is the controller's e-mail domain"], owner.id
            )
        if provider.package_domain in entity_domains:
            return Party(recipient, OWN, ["a domain of the register entity is the package's domain"], owner.id)
        return Party(recipient, OTHER, [f"register owner {owner.name}, not the controller"], owner.id)
    if domain is not None:
        base = registrable_domain(domain)
        if base in provider.domains:
            return Party(recipient, OWN, [f"{base} is the controller's e-mail domain"])
        if provider.package_domain and base == provider.package_domain:
            return Party(recipient, OWN, [f"{base} is the package's domain"])
    return Party(recipient, UNKNOWN, ["neither the register nor D's documents decide whose it is"])
