"""
The reasoning channel's corpus: passages of platform documentation and of embedded components' documentation, and
in its folder norms/ the passages of norms and guidelines the assessment stage reads by requirement.

The corpus is a component of the channel type, fixed by digest, not a named input of a case. A passage
is a YAML file:

```yaml
id: android-unique-identifiers
title: Best practices for unique identifiers
source: https://developer.android.com/identity/user-data-ids
retrieved: 2026-10-21
kind: platform            # or component; norm or guideline in norms/
# authority: edpb         # norms/ only: gdpr (a norm), edpb or wp29 (a guideline); orders a requirement's passages
about:
  nodes: [device-or-other-ids.advertising-id]   # data nodes it concerns (and their descendants)
  entities: []                                  # register entities it concerns
  recipient_types: []                           # recipient-type nodes it concerns (and their descendants)
  requirements: []                              # requirements of the frame it concerns (norms/)
text: >-
  …, in our own words where the source's licence asks for it
verified: {by: assessor, date: 2026-10-23, note: checked against the page as retrieved}
facts:                    # optional (P10, 21 Nov 2026): properties the text states, quoted from it
  - about: device-or-other-ids.app-set-id       # a data node of the data vocabulary
    kind: scope                                 # scope, persists or precision_m (FACT_KINDS)
    value: developer                            # one of the kind's values (below)
    quote: shared by all apps of the same developer   # a substring of `text` (whitespace normalised)
```

A fact states one property of a datum, as the passage's text does: its kind, its value and the words it is read from
(`quote`, which must occur in `text` as written there, case included; runs of whitespace compare as one space). The
kinds and their values are those of the minimisation question's typed form (judge.py), by which a rule compares what
a purpose needs with what an alternative gives:

    scope        the apps among which the same value of an identifier links the user, by containment
                 (SCOPES: app ⊂ developer ⊂ device ⊂ cross-app):
                   app          one app alone (one app's own identifier: an installation ID)
                   developer    the apps of one developer account on the device (the App Set ID)
                   device       every app on the device, though it is not made to link the user across apps
                   cross-app    every app on the device, and made to link the user across apps and the parties they
                                share it with (the advertising ID)
    persists     the event that ends an identifier's value, ordered by how much it survives
                 (PERSISTS: session < reinstall < reset < factory-reset):
                   session        the app's session or process ends
                   reinstall      the app is uninstalled or its data cleared (it survives sessions)
                   reset          the user resets it in the system's settings (it survives reinstalls)
                   factory-reset  only the device's factory reset (it survives the user's resets)
    precision_m  a location's precision in metres, a positive number: how far from the user it may place them (the
                 larger, the coarser)

A fact is rendered as a part of its own (F<n>) right after its passage in a minimisation context (judge.py, prompt
version 5 on), with the passage file as its provenance, so that gates (b) and (c) read it as they read the passage.

A passage is tagged (`about`) with each data node it names, or that a rule it states plainly covers, listed one by
one and never through a parent: the rules of Android's guidance on identifiers cover the Android ID although they do
not name it, while a tag on `device-or-other-ids` would also give the passage to the IP address, which no app chooses
as an identifier. A tag says that the passage concerns the datum, which retrieval reads and so does the gate that lets
a documented alternative be supported only by a passage about its component (Expectation report 0.9, `def:status`).

A passage stands in for its source, so each is checked against it by a person before it is relied on (`verified`);
`problems` lists the passages that are not, and `coverage` the components of the Observation dimension's reports that
no passage is about.

Passages are retrieved per processing component, or per requirement, by what they are about; nothing is searched at
analysis time. A component's are capped (PER_ENTITY about its recipient, PER_NODE about its datum); a requirement's
are all given, by authority (`AUTHORITIES`: the Regulation, then the EDPB, then WP29), each in file order. The norms
are a corpus of their own (`load(directory / NORMS)`), so that the expectation stage's corpus and its digest do not
change with them: that stage reads no norm.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from ratatoskr import claims as claim_views
from ratatoskr.vocabularies import Vocabulary

from skuld import yamlio


class CorpusError(Exception):
    """A passage file that cannot be read: no YAML mapping, or without its id, title or text."""


#: Passages about a practice's recipient (its register entity) given at most
PER_ENTITY = 3
#: Passages about a practice's datum (its data node, or a node above or below it) given at most: four since 21 Nov
#: 2026, when the Advertising ID had four (three before, as about the entity)
PER_NODE = 4
#: The authorities of the norms and guidelines (`authority` of a passage in norms/), in the order a requirement's
#: passages are given (`Corpus.on`): the Regulation, then the EDPB's guidelines, then those of the Article 29 Working
#: Party (WP29), which the EDPB endorsed (WP260 rev.01) or did not adopt (WP203)
AUTHORITIES = ("gdpr", "edpb", "wp29")
#: The authority each kind of norms/ passage may have
AUTHORITY_OF_KIND = {"norm": ("gdpr",), "guideline": ("edpb", "wp29")}
#: The folder of the norms and guidelines, inside the corpus folder
NORMS = "norms"
#: The kinds of a fact, and the values of each in their order (see above): a scope by containment, a persistence by the
#: event that ends it; precision_m takes a positive number of metres
SCOPES = ("app", "developer", "device", "cross-app")
PERSISTS = ("session", "reinstall", "reset", "factory-reset")
FACT_KINDS = ("scope", "persists", "precision_m")
ORDERS = {"scope": SCOPES, "persists": PERSISTS}


def valid_value(kind: str, value) -> bool:
    """Whether a value is one of a fact kind's: a scope or persistence of its order, or a positive number of metres."""
    if kind in ORDERS:
        return value in ORDERS[kind]
    if kind == "precision_m":
        return isinstance(value, int | float) and not isinstance(value, bool) and value > 0
    return False


@dataclass(frozen=True)
class Fact:
    """A property of a datum a passage states: the data node it is about, its kind, its value and the words of the
    passage it is read from."""

    about: str
    kind: str
    value: object
    quote: str


@dataclass(frozen=True)
class Passage:
    id: str
    title: str
    source: str
    kind: str
    nodes: tuple[str, ...]
    entities: tuple[str, ...]
    text: str
    path: Path
    retrieved: str | None = None
    verified: dict | None = None
    requirements: tuple[str, ...] = ()
    recipient_types: tuple[str, ...] = ()
    authority: str | None = None
    facts: tuple[Fact, ...] = ()

    @property
    def checked(self) -> bool:
        """Whether a person checked the passage against its source (`verified: {by, date}`)."""
        return isinstance(self.verified, dict) and bool(self.verified.get("by")) and bool(self.verified.get("date"))

    def concerns(self, kind: str, value: str | None, categories=(), data=None, types=None) -> bool:
        """
        Whether the passage is about a processing component (gate b of E's status rule for a documented alternative):
        for a datum (kind D), a data node it is tagged with is the datum's node or one above it, other than the root;
        for a recipient (kind R), it is tagged with the recipient's entity, or with a recipient-type node at or above
        one of the recipient's categories, other than the root.
        """
        if not value:
            return False
        if kind == "D":
            return any(_at_or_above(value, tag, data) for tag in self.nodes)
        return value in self.entities or any(
            _at_or_above(c, tag, types) for tag in self.recipient_types for c in categories
        )


@dataclass(frozen=True)
class Corpus:
    passages: tuple[Passage, ...]
    sha256: str

    def about(self, node: str | None, entity: str | None, vocabulary: Vocabulary) -> list[Passage]:
        """The passages about a datum's node (or a node above or below it) or about an entity, in the corpus's order:
        at most PER_ENTITY about the entity and at most PER_NODE about the node, each capped on its own, so that the
        passages about the datum never push out those about its recipient (18 Nov 2026, three and three, with three in
        all where no more were found, which the separate caps keep). A passage about both counts as about the entity.
        PER_NODE is four since 21 Nov 2026, so that the Advertising ID's fourth passage is given. The vocabulary's
        root matches no node: every node is below it, so it would find every passage about a node, the first PER_NODE
        of them by file order (21 Nov 2026; coverage and the gate leave the root out alike)."""
        if node is not None and node == vocabulary.root:
            node = None
        found, by_entity, by_node = [], [], []
        for p in self.passages:
            if entity and entity in p.entities:
                found.append(p)
                by_entity.append(p)
            elif node and any(_related(node, n, vocabulary) for n in p.nodes):
                found.append(p)
                by_node.append(p)
        kept = {id(p) for p in by_entity[:PER_ENTITY] + by_node[:PER_NODE]}
        return [p for p in found if id(p) in kept]

    def on(self, requirement: str) -> list[Passage]:
        """The passages about a requirement of the frame, by authority (21 Nov 2026): the Regulation's (`gdpr`) first,
        then the EDPB's guidelines (`edpb`), then WP29's (`wp29`), then any other; within each, in the corpus's
        order (by file name). Before, all were in file order, which put the EDPB's guidelines before the GDPR."""
        found = [p for p in self.passages if requirement in p.requirements]
        rank = {a: i for i, a in enumerate(AUTHORITIES)}
        return sorted(found, key=lambda p: rank.get(p.authority or "", len(AUTHORITIES)))  # stable: file order kept


def load(directory: str | Path) -> Corpus:
    """Reads a corpus folder. Its digest covers every passage file, by name and content."""
    directory = Path(directory)
    passages, digest = [], hashlib.sha256()
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yamlio.load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise CorpusError(f"{path}: no YAML ({e})") from None
        if not isinstance(data, dict):
            raise CorpusError(f"{path}: not a mapping")
        lacking = [k for k in ("id", "title", "text") if not data.get(k)]  # a passage without source is a problem
        if lacking:
            raise CorpusError(f"{path}: no {', '.join(lacking)}")
        about = data.get("about") or {}
        facts = data.get("facts") or []
        if not isinstance(facts, list) or not all(isinstance(f, dict) for f in facts):
            raise CorpusError(f"{path}: facts is not a list of mappings ({{about, kind, value, quote}})")
        passages.append(
            Passage(
                id=data["id"],
                title=data["title"],
                source=str(data.get("source") or ""),
                kind=data.get("kind", "platform"),
                nodes=tuple(about.get("nodes") or ()),
                entities=tuple(about.get("entities") or ()),
                text=" ".join(str(data["text"]).split()),
                path=path,
                retrieved=str(data["retrieved"]) if data.get("retrieved") else None,
                verified=data.get("verified") or None,
                requirements=tuple(about.get("requirements") or ()),
                recipient_types=tuple(about.get("recipient_types") or ()),
                authority=str(data["authority"]) if data.get("authority") else None,
                facts=tuple(
                    Fact(str(f.get("about") or ""), str(f.get("kind") or ""), f.get("value"), str(f.get("quote") or ""))
                    for f in facts
                ),
            )
        )
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return Corpus(tuple(passages), digest.hexdigest())


def problems(corpus: Corpus, data: Vocabulary | None = None) -> list[str]:
    """What keeps passages from being relied on: no source, no date retrieved, nothing they are about, an id not
    their file's name, no record that a person checked them against their source, a norm or guideline without its
    authority (`gdpr` for a norm, `edpb` or `wp29` for a guideline; another passage states none), or a fact whose
    quote is not in the passage's text, whose kind is unknown, whose value is not one of its kind's, or which is about
    no node of the data vocabulary (`data`, default the bundled one)."""
    if data is None and any(p.facts for p in corpus.passages):
        from skuld.common import DATA, vocabulary

        data = vocabulary(DATA)
    out = []
    for p in corpus.passages:
        if p.path.stem != p.id:
            out.append(f"{p.path.name}: its id is {p.id}")
        if not p.source.startswith(("http://", "https://")):
            out.append(f"{p.id}: no source to check it against")
        if not p.retrieved:
            out.append(f"{p.id}: no date it was retrieved")
        if not (p.nodes or p.entities or p.requirements):
            out.append(f"{p.id}: about no data node, entity or requirement, so no context retrieves it")
        if p.verified is not None and not isinstance(p.verified, dict):
            out.append(f"{p.id}: verified is not a mapping (verified: {{by, date}})")
        elif not p.checked:
            out.append(f"{p.id}: not verified against its source (verified: {{by, date}})")
        allowed = AUTHORITY_OF_KIND.get(p.kind)
        if allowed and p.authority not in allowed:
            out.append(
                f"{p.id}: a {p.kind} whose authority is {p.authority or 'not stated'} (authority: {' or '.join(allowed)})"
            )
        elif not allowed and p.authority is not None:
            out.append(f"{p.id}: a {p.kind} passage states an authority ({p.authority}); only norms and guidelines do")
        out += fact_problems(p, data)
    return out


def fact_problems(p: Passage, data: Vocabulary | None) -> list[str]:
    """What keeps a passage's facts from being read (see `problems`), each named by its position (facts[k])."""
    out = []
    for k, f in enumerate(p.facts):
        name = f"{p.id}: facts[{k}]"
        if f.kind not in FACT_KINDS:
            out.append(f"{name}: kind {f.kind or '(none)'!r} is not one of {', '.join(FACT_KINDS)}")
        elif not valid_value(f.kind, f.value):
            allowed = " < ".join(ORDERS[f.kind]) if f.kind in ORDERS else "a positive number of metres"
            out.append(f"{name}: value {f.value!r} is not a {f.kind} ({allowed})")
        if data is not None and (not f.about or f.about not in data or f.about == data.root):
            out.append(f"{name}: about {f.about or '(none)'!r} is not a node of the data vocabulary")
        quote = " ".join(f.quote.split())
        if not quote or quote not in p.text:
            out.append(f"{name}: its quote is not in the passage's text")
    return out


def coverage(corpus: Corpus, reports: list[dict], vocabulary: Vocabulary) -> dict[str, dict]:
    """
    The recipients (register entities) and data nodes of the Observation dimension's claims that no passage is about,
    each with the applications and claims that name it, most applications first.
    """
    found: dict[str, dict] = {}
    for report in reports:
        for claim in claim_views.of_report(report):
            entity = (claim.get("recipient") or {}).get("entity")
            keys = [("entity", entity)] if entity and entity != "?" else []
            node = (claim.get("datum") or {}).get("node")
            if node and node != "data":
                keys.append(("node", node))
            for kind, value in keys:
                if kind == "entity" and corpus.about(None, value, vocabulary):
                    continue
                if kind == "node" and corpus.about(value, None, vocabulary):
                    continue
                entry = found.setdefault(f"{kind}:{value}", {"applications": set(), "claims": 0})
                entry["applications"].add(claim.get("application"))
                entry["claims"] += 1
    ordered = sorted(found.items(), key=lambda kv: (-len(kv[1]["applications"]), -kv[1]["claims"], kv[0]))
    return {k: {"applications": sorted(v["applications"]), "claims": v["claims"]} for k, v in ordered}


def _at_or_above(node: str, tag: str, vocabulary: Vocabulary | None) -> bool:
    """Whether tag is node or a node above it, and not the vocabulary's root."""
    if vocabulary is None:
        return node == tag
    if tag == vocabulary.root:
        return False
    return node == tag or (node in vocabulary and tag in vocabulary and vocabulary.is_a(node, tag))


def _related(a: str, b: str, vocabulary: Vocabulary) -> bool:
    if a == b:
        return True
    if a not in vocabulary or b not in vocabulary:
        return False
    return vocabulary.is_a(a, b) or vocabulary.is_a(b, a)
