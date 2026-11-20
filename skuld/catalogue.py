"""
The catalogue of feature families: kinds of features that applications share, with their purposes and oracle templates.

A family is a YAML file `families/<id>@<version>.yaml` in the catalogue folder. It is never changed: a change is
its next version. An oracle template is an oracle whose arguments may name slots, `"{name}"`, which a feature of
the family fills from the recording of its path:

```yaml
id: current-location-forecast
version: 1
name: forecast for the current location
entry: the app open, the device at a known location
path: open the forecast for the place the device is at
outcome: the forecast for the place the app found for the device
purposes:
  - id: P1
    action: determine and display
    object: the weather forecast
    beneficiary: user
    context: the device's current location
    outcome: the forecast for the area the user is in
    node: ServiceProvision
    fit: broader
    specificity: sufficient
    role: functional
    requirements:
      - {id: R1, statement: determine an area relevant to the user}
    oracle:                       # or null: no observable oracle
      reach: [R1]
      success:
        - text_shown: {any: "{place}", after_action: "{path_start}"}
      invalid:
        - hold_above_ms: 1000
      measurements: []
      slots:
        place: {kind: text, description: the name of the place the forecast is shown for}
author: {kind: model, name: gemma4:31b, prompt: <sha256>}
created: 2026-10-23
derived_from: {application: de.wetteronline.wetterapp@2026.20, run: <run id>, episode: 1}
```

A slot is of kind `text` (texts a screen of the path showed; the oracle's `any`), `screen` (the exact key of a
screen of the path) or `activity` (the activity of a screen of the path). `path_start` and `path_end`, the number
of the recording's actions before the feature's path and up to its last action, are filled by every instantiation.
A slot that is a whole argument is replaced by its value; one within a text is written into it.

A family's review is stored beside it, `reviews/<id>@<version>.yaml` in the catalogue folder, outside the family's
digest and the catalogue's, so that reviewing a family changes neither (20 Nov 2026; before, `reviewed` was a field of
the family file, and a review changed its digest):

```yaml
family: current-location-forecast@1
sha256: <the digest of the family file reviewed>
by: <a person's id>
time: 2026-11-20T10:00:00+00:00
note: <what the reviewer found, or empty>
```

A review names the digest of the family file it read; a review of another text than the family's is no review of it.
A `reviewed: {by, time, note}` field in a family file, as families written before carry it, is still read as its
review where no review file is stored (deprecated: record a review with `skuld catalogue --review`).
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from skuld import yamlio
from skuld.oracles import METRICS, PREDICATES

SLOT_KINDS = ("text", "screen", "activity")
BUILT_IN = ("path_start", "path_end")
#: The invalid conditions of every generated oracle: a hold at start that changes how the application starts
INVALID = ({"hold_above_ms": 1000},)

_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: The folder of the families' reviews, beside `families/`
REVIEWS = "reviews"


class CatalogueError(Exception):
    """A family that is malformed or does not pass the catalogue's checks."""


@dataclass(frozen=True)
class Family:
    id: str
    version: int
    data: dict
    sha256: str
    path: Path | None = None
    #: The family's review (by, time, note; `legacy` if read from the family file's `reviewed` field), or None
    review: dict | None = None
    #: Why a stored review is no review of the family (it names another digest), or None
    review_problem: str | None = None

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def reviewed(self) -> bool:
        return self.review is not None and self.review_problem is None

    def review_state(self) -> str:
        """How `skuld catalogue` shows the review: who reviewed the family and when, or why it counts as not reviewed."""
        if self.review_problem:
            return f"not reviewed ({self.review_problem})"
        if self.review is None:
            return "not reviewed"
        r = self.review
        state = f"reviewed by {r.get('by') or '?'} {str(r.get('time') or '?')[:10]}"
        return state + " (in the family file; deprecated)" if r.get("legacy") else state

    def summary(self) -> dict:
        """What a model is shown of the family: its description, purposes and the slots it asks for."""
        return {
            "id": self.id,
            "name": self.data["name"],
            "entry": self.data["entry"],
            "path": self.data["path"],
            "outcome": self.data["outcome"],
            "purposes": [f"{p['action']} {p['object']} ({p['beneficiary']})" for p in self.data["purposes"]],
            "slots": {
                name: f"{slot['kind']}: {slot['description']}"
                for p in self.data["purposes"]
                if p.get("oracle")
                for name, slot in (p["oracle"].get("slots") or {}).items()
            },
        }


class Catalogue:
    def __init__(self, root: Path, families: list[Family]):
        self.root = root
        self.families = families

    @property
    def sha256(self) -> str:
        """The catalogue's digest: of its families' keys and digests, in order."""
        listing = "\n".join(f"{f.key} {f.sha256}" for f in sorted(self.families, key=lambda f: f.key))
        return hashlib.sha256(listing.encode("utf-8")).hexdigest()

    def latest(self) -> list[Family]:
        """The newest version of every family."""
        newest: dict[str, Family] = {}
        for f in self.families:
            if f.id not in newest or f.version > newest[f.id].version:
                newest[f.id] = f
        return sorted(newest.values(), key=lambda f: f.id)

    def get(self, family_id: str, version: int | None = None) -> Family | None:
        found = [f for f in self.families if f.id == family_id and (version is None or f.version == version)]
        return max(found, key=lambda f: f.version) if found else None

    def add(self, data: dict) -> Family:
        """Writes a family as the next version of its id, or as version 1 of a new id; returns it. An empty `reviewed`
        field is dropped: the review is stored beside the family (`review`)."""
        current = self.get(data["id"])
        data = {**data, "version": current.version + 1 if current else 1}
        if "reviewed" in data and not data["reviewed"]:
            del data["reviewed"]
        check(data)
        folder = self.root / "families"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{data['id']}@{data['version']}.yaml"
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
        path.write_text(text, encoding="utf-8", newline="\n")
        family = Family(data["id"], data["version"], data, _digest(text), path)
        self.families.append(family)
        return family

    def review(self, key: str, by: str, note: str = "", time: datetime | None = None) -> Family:
        """
        Records a person's review of a family (`<id>@<version>`) in `reviews/<key>.yaml`, with the digest of the
        family file reviewed; returns the family with its review. A family reviewed already, in either place, is
        refused: a review is recorded once.
        """
        family_id, _, version = key.partition("@")
        family = self.get(family_id, int(version)) if version.isdigit() else None
        if family is None:
            raise CatalogueError(f"no family {key} in the catalogue (give <id>@<version>)")
        if not by.strip():
            raise CatalogueError("a review names its reviewer")
        path = review_path(self.root, family.key)
        if path.exists() or family.review is not None:
            raise CatalogueError(f"{family.key} is reviewed already ({family.review_state()})")
        record = {
            "family": family.key,
            "sha256": family.sha256,
            "by": by.strip(),
            "time": (time or datetime.now(UTC)).isoformat(timespec="seconds"),
            "note": note.strip(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=120)
        path.write_text(text, encoding="utf-8", newline="\n")
        reviewed = Family(family.id, family.version, family.data, family.sha256, family.path, record)
        self.families[self.families.index(family)] = reviewed
        return reviewed


def review_path(root: Path, key: str) -> Path:
    """Where the review of a family is stored."""
    return Path(root) / REVIEWS / f"{key}.yaml"


def _review(root: Path, key: str, sha256: str, data: dict) -> tuple[dict | None, str | None]:
    """A family's review and why it is none of the family's: the review file, else the family file's deprecated
    `reviewed` field."""
    path = review_path(root, key)
    if path.is_file():
        record = yamlio.load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not record.get("by"):
            raise CatalogueError(f"{REVIEWS}/{path.name}: not a review (family, sha256, by, time, note)")
        if record.get("family") not in (None, key):
            raise CatalogueError(f"{REVIEWS}/{path.name}: a review of {record.get('family')}, not of {key}")
        if record.get("sha256") != sha256:
            return record, "the review read another text of the family"
        return record, None
    legacy = data.get("reviewed")
    if not legacy:
        return None, None
    return {**(legacy if isinstance(legacy, dict) else {"note": str(legacy)}), "legacy": True}, None


def load(root: str | Path) -> Catalogue:
    """Reads a catalogue folder; an absent one is empty. Raises CatalogueError for a family that fails the checks."""
    root = Path(root)
    families = []
    for path in sorted((root / "families").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        data = yamlio.load(text)
        if not isinstance(data, dict):
            raise CatalogueError(f"{path.name}: not a mapping")
        try:
            check(data)
        except CatalogueError as e:
            raise CatalogueError(f"{path.name}: {e}") from e
        if path.stem != f"{data['id']}@{data['version']}":
            raise CatalogueError(f"{path.name}: named otherwise than its id and version")
        key, sha256 = f"{data['id']}@{data['version']}", _digest(text)
        review, problem = _review(root, key, sha256, data)
        families.append(Family(data["id"], int(data["version"]), data, sha256, path, review, problem))
    return Catalogue(root, families)


def check(data: dict) -> None:
    """
    Refuses a family that is malformed: an id that is not lower-case words with hyphens; a purpose without its parts
    or requirements; an oracle that reaches requirements its purpose does not have, names a predicate or metric the
    instance does not know, or uses a slot it does not declare (or declares one it does not use).
    """
    missing = [k for k in ("id", "version", "name", "entry", "path", "outcome", "purposes") if k not in data]
    if missing:
        raise CatalogueError(f"missing {', '.join(missing)}")
    if not _ID.match(str(data["id"])):
        raise CatalogueError(f"the id {data['id']!r} is not lower-case words joined by hyphens")
    if not data["purposes"]:
        raise CatalogueError("no purpose")
    for p in data["purposes"]:
        where = f"purpose {p.get('id')}"
        parts = ("id", "action", "object", "beneficiary", "context", "outcome", "node", "specificity", "role")
        if any(k not in p for k in parts) or not p.get("requirements"):
            raise CatalogueError(f"{where}: missing parts or requirements")
        oracle = p.get("oracle")
        if oracle is None:
            continue
        requirements = {r["id"] for r in p["requirements"]}
        if not oracle.get("reach") or not set(oracle["reach"]) <= requirements:
            raise CatalogueError(f"{where}: the oracle reaches {oracle.get('reach')}, not requirements of the purpose")
        if not oracle.get("success"):
            raise CatalogueError(f"{where}: the oracle has no condition of success")
        for spec in [*oracle["success"], *(oracle.get("invalid") or ())]:
            if _name(spec) not in PREDICATES:
                raise CatalogueError(f"{where}: unknown predicate {_name(spec)!r}")
        for m in oracle.get("measurements") or ():
            if _name(m.get("metric")) not in METRICS:
                raise CatalogueError(f"{where}: unknown metric in measurement {m.get('name')!r}")
        slots = oracle.get("slots") or {}
        for name, slot in slots.items():
            if slot.get("kind") not in SLOT_KINDS or not slot.get("description"):
                raise CatalogueError(f"{where}: slot {name} needs a kind of {SLOT_KINDS} and a description")
        used = slots_in([oracle["success"], oracle.get("invalid") or [], oracle.get("measurements") or []])
        if undeclared := used - set(slots) - set(BUILT_IN):
            raise CatalogueError(f"{where}: undeclared slots {sorted(undeclared)}")
        if unused := set(slots) - used:
            raise CatalogueError(f"{where}: slots {sorted(unused)} are declared but not used")


def slots_in(value) -> set[str]:
    """The slot names a template value uses."""
    if isinstance(value, str):
        return set(_SLOT.findall(value))
    if isinstance(value, dict):
        return set().union(*(slots_in(v) for v in value.values())) if value else set()
    if isinstance(value, list | tuple):
        return set().union(*(slots_in(v) for v in value)) if value else set()
    return set()


def fill(value, bindings: dict):
    """A template value with its slots filled: a whole-argument slot by the value itself, others written into texts."""
    if isinstance(value, str):
        whole = _SLOT.fullmatch(value)
        if whole:
            return bindings[whole.group(1)]
        return _SLOT.sub(lambda m: str(bindings[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: fill(v, bindings) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [fill(v, bindings) for v in value]
    return value


def _name(spec) -> str | None:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict) and len(spec) == 1:
        return next(iter(spec))
    return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
