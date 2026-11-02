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
reviewed: null                    # or {by, time, note}
```

A slot is of kind `text` (texts a screen of the path showed; the oracle's `any`), `screen` (the exact key of a
screen of the path) or `activity` (the activity of a screen of the path). `path_start` and `path_end`, the number
of the recording's actions before the feature's path and up to its last action, are filled by every instantiation.
A slot that is a whole argument is replaced by its value; one within a text is written into it.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from skuld.oracles import METRICS, PREDICATES

SLOT_KINDS = ("text", "screen", "activity")
BUILT_IN = ("path_start", "path_end")
#: The invalid conditions of every generated oracle: a hold at start that changes how the application starts
INVALID = ({"hold_above_ms": 1000},)

_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CatalogueError(Exception):
    """A family that is malformed or does not pass the catalogue's checks."""


@dataclass(frozen=True)
class Family:
    id: str
    version: int
    data: dict
    sha256: str
    path: Path | None = None

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def reviewed(self) -> bool:
        return bool(self.data.get("reviewed"))

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
        """Writes a family as the next version of its id, or as version 1 of a new id; returns it."""
        current = self.get(data["id"])
        data = {**data, "version": current.version + 1 if current else 1}
        check(data)
        folder = self.root / "families"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{data['id']}@{data['version']}.yaml"
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
        path.write_text(text, encoding="utf-8", newline="\n")
        family = Family(data["id"], data["version"], data, _digest(text), path)
        self.families.append(family)
        return family


def load(root: str | Path) -> Catalogue:
    """Reads a catalogue folder; an absent one is empty. Raises CatalogueError for a family that fails the checks."""
    root = Path(root)
    families = []
    for path in sorted((root / "families").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise CatalogueError(f"{path.name}: not a mapping")
        try:
            check(data)
        except CatalogueError as e:
            raise CatalogueError(f"{path.name}: {e}") from e
        if path.stem != f"{data['id']}@{data['version']}":
            raise CatalogueError(f"{path.name}: named otherwise than its id and version")
        families.append(Family(data["id"], int(data["version"]), data, _digest(text), path))
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
