"""
The run's scope, as far as it settles a denial's own scope (D3, plan/archive/OBSERVABILITY_PLAN.md §7): a condition
the run's scope settles is no open question, and gets no open condition and no gap. The rule tier reads the scopes of
O's reports (Verðandi 3.7.0 carries Loki's `locale`, `store` and `persona_age` from run_scope.json into the scope's
`context`, beside `egress`); a report that does not state an indicator settles nothing that needs it.

    a denial limited to    settled by                                         holds                 fails
    a jurisdiction         the egress country, the store country and the      the country they      they agree on a
                           locale's region, only where all three are stated   agree on lies in it   country outside it
                           and agree, in every scope
    a user group           the persona's age, the same in every scope         the age falls in it   it does not
    a product              the application observed                           an app, the mobile    a website, a web
                                                                              application           page, a browser
    the user's prior       the consent state, readable in every scope         no consent recorded   (never: what an
    consent                                                                   in any                accepted consent
                                                                                                    covers is not shown)

A denial whose scope the run's scope settles as failing does not apply to what O observed: it relates to no practice.
A part that holds leaves the relation's condition. Anything the rules cannot read (a jurisdiction they do not know, a
user group without an age, a product they cannot place) stays open, as before.
"""

import re
from dataclasses import dataclass, field

#: The member states of the EEA, where the GDPR applies
EEA = frozenset("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS LI NO".split())
#: Jurisdictions by how D's qualifiers name them, as the countries they cover
NAMED = {
    "eu": EEA,
    "eea": EEA,
    "european union": EEA,
    "european economic area": EEA,
    "europe": EEA,
    "gdpr": EEA,
    "us": frozenset({"US"}),
    "usa": frozenset({"US"}),
    "united states": frozenset({"US"}),
    "united states of america": frozenset({"US"}),
    "canada": frozenset({"CA"}),
    "uk": frozenset({"GB"}),
    "united kingdom": frozenset({"GB"}),
    "great britain": frozenset({"GB"}),
    "germany": frozenset({"DE"}),
    "france": frozenset({"FR"}),
    "switzerland": frozenset({"CH"}),
    "brazil": frozenset({"BR"}),
    "japan": frozenset({"JP"}),
    "australia": frozenset({"AU"}),
    "india": frozenset({"IN"}),
    "china": frozenset({"CN"}),
    "south korea": frozenset({"KR"}),
}
#: Parts of a country, by the country they lie in: the run's indicators place a user in a country only, so a part
#: fails where the country is another and stays open where it is its own
PARTS = {
    "california": "US",
    "virginia": "US",
    "colorado": "US",
    "connecticut": "US",
    "utah": "US",
    "texas": "US",
    "nevada": "US",
    "quebec": "CA",
}
#: A product that is not the application observed, and one that is
NOT_THE_APP = re.compile(r"\b(web ?sites?|web ?pages?|sites?|browsers?|desktop)\b", re.I)
THE_APP = re.compile(r"\b(apps?|applications?|mobile)\b", re.I)
#: A denial's condition about the user's consent
CONSENT = re.compile(r"consent|agree|opt[- ]?in", re.I)


@dataclass(frozen=True)
class RunScope:
    """What the scopes of an assessment's O reports say of where and who the user is.

    Attributes:
        country: The country egress, store and locale agree on in every scope; None where one is not stated or they
            disagree
        age: The persona's age, the same in every scope; None otherwise
        consent_given: Whether the application stored a consent, where every scope's consent state is readable;
            None otherwise
        indicators: What was read, for the reasons a settlement gives
    """

    country: str | None = None
    age: int | None = None
    consent_given: bool | None = None
    indicators: dict = field(default_factory=dict)


def _country_of(context: dict) -> tuple[str | None, dict]:
    egress = context.get("egress") if isinstance(context.get("egress"), dict) else {}
    store = context.get("store") if isinstance(context.get("store"), dict) else {}
    locale = context.get("locale") if isinstance(context.get("locale"), dict) else {}
    tag = str(locale.get("locale") or "")
    region = next((p.upper() for p in re.split(r"[-_]", tag)[1:] if re.fullmatch(r"[A-Za-z]{2}", p)), None)
    stored = store.get("country") or (store["countries"][0] if len(store.get("countries") or ()) == 1 else None)
    read = {"egress": egress.get("country"), "store": stored, "locale": region}
    values = {str(v).upper() for v in read.values() if v}
    agreed = values.pop() if all(read.values()) and len(values) == 1 else None
    return agreed, read


def _consent(series) -> bool | None:
    """Whether a consent was stored, from a scope's consent states; None unless every state is marked readable."""
    if not isinstance(series, list) or not series or not all(isinstance(s, dict) for s in series):
        return None
    if not all(s.get("readable") is True for s in series):
        return None
    for s in series:
        state = s.get("state") if isinstance(s.get("state"), dict) else {}
        for k, v in state.items():
            key, value = str(k).lower(), str(v)
            if key.endswith("tcstring") and value.strip():
                return True
            if "consent" in key and ("1" in value or value.lower() in ("true", "yes", "granted", "accepted")):
                return True
    return False


def of_reports(o_reports: list[dict]) -> RunScope:
    """The run scope of O's reports: what all their scopes agree on."""
    countries, ages, consents, read = set(), set(), set(), []
    scopes = [s for r in o_reports for s in r.get("scopes", [])]
    for s in scopes:
        context = s.get("context") if isinstance(s.get("context"), dict) else {}
        country, indicators = _country_of(context)
        countries.add(country)
        age = context.get("persona_age") if isinstance(context.get("persona_age"), dict) else {}
        ages.add(age.get("years") if isinstance(age.get("years"), int) else None)
        consents.add(_consent(s.get("consent")))
        read.append({**indicators, "age": age.get("years")})
    one = len(scopes) > 0
    return RunScope(
        country=next(iter(countries)) if one and len(countries) == 1 else None,
        age=next(iter(ages)) if one and len(ages) == 1 else None,
        consent_given=next(iter(consents)) if one and len(consents) == 1 else None,
        indicators={"scopes": len(scopes), "read": read},
    )


def _jurisdiction(value: str, scope: RunScope) -> bool | None:
    name = value.strip().lower().replace(".", "")
    if scope.country is None:
        return None
    if name in NAMED:
        return scope.country in NAMED[name]
    if re.fullmatch(r"[a-z]{2}", name):
        return scope.country == name.upper()
    part = PARTS.get(name) or (name[:2].upper() if re.fullmatch(r"[a-z]{2}-[a-z0-9]{1,3}", name) else None)
    if part:
        return False if scope.country != part else None  # in its country the indicators do not tell the part
    return None


def _user_group(value: str, scope: RunScope) -> bool | None:
    if scope.age is None:
        return None
    text = value.lower()
    under = re.search(r"(?:under|younger than|below)(?: the age of)?\s*(\d{1,2})", text)
    if under:
        return scope.age < int(under.group(1))
    over = re.search(
        r"(?:over|older than|above|at least)(?: the age of)?\s*(\d{1,2})|(\d{1,2})\s*(?:\+|or older)", text
    )
    if over:
        n = int(over.group(1) or over.group(2))
        return scope.age > n if "over" in text or "older than" in text or "above" in text else scope.age >= n
    if re.search(r"\b(child|children|kids?|minors?|teens?|teenagers?)\b", text):
        if scope.age < 13:
            return True
        return False if scope.age >= 18 else None
    if re.search(r"\badults?\b", text):
        return scope.age >= 18
    return None


def _product(value: str) -> bool | None:
    if NOT_THE_APP.search(value) and not THE_APP.search(value):
        return False
    if THE_APP.search(value) and not NOT_THE_APP.search(value):
        return True
    return None


def applies(limit: dict, scope: RunScope) -> bool | None:
    """Whether a denial limited to `limit` (D's qualifier applicability, {kind, value}) applies to what O observed:
    True or False where the run's scope settles it, None where it does not."""
    kind, value = limit.get("kind"), str(limit.get("value") or "")
    if not value:
        return None
    if kind == "jurisdiction":
        return _jurisdiction(value, scope)
    if kind == "user_group":
        return _user_group(value, scope)
    if kind == "product":
        return _product(value)
    return None


def condition_held(condition: dict, scope: RunScope) -> bool | None:
    """Whether a denial's condition (D's qualifier condition, {type, text}) held when O observed: settled only for one
    about the user's consent, as holding where the run's consent states are readable and no consent was stored."""
    text = str(condition.get("text") or "")
    if not CONSENT.search(text):
        return None
    return True if scope.consent_given is False else None


def described(scope: RunScope) -> str:
    """The run's scope in words, for a settlement's reason."""
    parts = []
    if scope.country:
        parts.append(f"the user placed in {scope.country} by egress, store and locale alike")
    if scope.age is not None:
        parts.append(f"a persona aged {scope.age}")
    if scope.consent_given is False:
        parts.append("no consent stored")
    return ", ".join(parts) or "nothing settled"
