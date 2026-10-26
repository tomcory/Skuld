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
about:
  nodes: [device-or-other-ids.advertising-id]   # data nodes it concerns (and their descendants)
  entities: []                                  # register entities it concerns
  requirements: []                              # requirements of the frame it concerns (norms/)
text: >-
  …, in our own words where the source's licence asks for it
verified: {by: assessor, date: 2026-10-23, note: checked against the page as retrieved}
```

A passage stands in for its source, so each is checked against it by a person before it is relied on (`verified`);
`problems` lists the passages that are not, and `coverage` the components of the Observation dimension's reports that
no passage is about.

Passages are retrieved per processing component, or per requirement, by what they are about; nothing is searched at
analysis time. The norms are a corpus of their own (`load(directory / NORMS)`), so that the expectation stage's corpus
and its digest do not change with them: that stage reads no norm.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from ratatoskr.vocabularies import Vocabulary

#: Passages given per component at most
PER_COMPONENT = 3
#: The folder of the norms and guidelines, inside the corpus folder
NORMS = "norms"


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


@dataclass(frozen=True)
class Corpus:
    passages: tuple[Passage, ...]
    sha256: str

    def about(self, node: str | None, entity: str | None, vocabulary: Vocabulary) -> list[Passage]:
        """The passages about a datum's node (or a node above or below it) or about an entity, at most PER_COMPONENT."""
        found = []
        for p in self.passages:
            if entity and entity in p.entities:
                found.append(p)
            elif node and any(_related(node, n, vocabulary) for n in p.nodes):
                found.append(p)
        return found[:PER_COMPONENT]

    def on(self, requirement: str) -> list[Passage]:
        """The passages about a requirement of the frame, in the corpus's order."""
        return [p for p in self.passages if requirement in p.requirements]


def load(directory: str | Path) -> Corpus:
    """Reads a corpus folder. Its digest covers every passage file, by name and content."""
    directory = Path(directory)
    passages, digest = [], hashlib.sha256()
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        about = data.get("about") or {}
        passages.append(
            Passage(
                id=data["id"],
                title=data["title"],
                source=data["source"],
                kind=data.get("kind", "platform"),
                nodes=tuple(about.get("nodes") or ()),
                entities=tuple(about.get("entities") or ()),
                text=" ".join(str(data["text"]).split()),
                path=path,
                retrieved=str(data["retrieved"]) if data.get("retrieved") else None,
                verified=data.get("verified") or None,
                requirements=tuple(about.get("requirements") or ()),
            )
        )
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return Corpus(tuple(passages), digest.hexdigest())


def problems(corpus: Corpus) -> list[str]:
    """What keeps passages from being relied on: no source, no date retrieved, nothing they are about, an id not
    their file's name, or no record that a person checked them against their source."""
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
        elif not (p.verified and p.verified.get("by") and p.verified.get("date")):
            out.append(f"{p.id}: not verified against its source (verified: {{by, date}})")
    return out


def coverage(corpus: Corpus, reports: list[dict], vocabulary: Vocabulary) -> dict[str, dict]:
    """
    The recipients (register entities) and data nodes of the Observation dimension's claims that no passage is about,
    each with the applications and claims that name it, most applications first.
    """
    found: dict[str, dict] = {}
    for report in reports:
        for claim in report.get("claims") or ():
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


def _related(a: str, b: str, vocabulary: Vocabulary) -> bool:
    if a == b:
        return True
    if a not in vocabulary or b not in vocabulary:
        return False
    return vocabulary.is_a(a, b) or vocabulary.is_a(b, a)
