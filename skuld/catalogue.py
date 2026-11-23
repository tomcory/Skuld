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

A family may declare a control (21 Nov 2026): a condition whose outcome is expected before the runs, which tests the
family's oracles rather than the application. `network` blocks every host the case's baseline runs contacted, so a
purpose that needs the network must break; a control that preserves it is a sensitivity failure of the oracle.

```yaml
control: {intervention: network, expected: breaks}
```

An oracle template may add conditions by the application's store category (Sága's `store_listing.category`, in the
store's language; matched without regard to case), each entry with the category names it applies to, its conditions
of success and, optionally, its own control, which replaces the family's; a category no entry names keeps the
template's own conditions (`launch@3`):

```yaml
oracle:
  success:
    - first_screen_ready: {}
  categories:
    - names: [Weather, Wetter]
      success:
        - text_shown: {any: ["0°", "1°", "2°", "3°", "4°", "5°", "6°", "7°", "8°", "9°"]}
      reach: [R3]
      control: {intervention: network, expected: breaks}
```

A category entry may name requirements of its purpose that its conditions reach (`reach`, 21 Nov 2026: launch@4's R3,
the category's content), added to the template's own for an application of the category.

A slot is `{kind, description}` and nothing else (21 Nov 2026). In a YAML flow mapping a comma ends a plain value, so
`{kind: text, description: the place, as shown}` gives a description cut at the comma and a stray key `as shown`;
`check` refuses such a slot. Families written before with one (current-location-forecast@1 and @2,
questionnaire-onboarding@1) are still read, for the cases that name them, with the problem recorded in the family's
`problems`; they are refused for any new use (`add`, `usable`: the proposer's choice of a family, a merge of
proposals), and a later version fixes them.

A family may be superseded by another (21 Nov 2026: oauth-sign-up by third-party-authentication, which holds both
purposes of the same path). Its next version is its last and says so, `superseded_by: <id>`; the newest versions
(`latest`) leave it out, and a proposal that names it is refused.
"""

import fcntl
import hashlib
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from skuld import yamlio
from skuld.oracles import METRICS, PREDICATES

SLOT_KINDS = ("text", "screen", "activity")
BUILT_IN = ("path_start", "path_end")
#: The invalid conditions of every generated oracle: a hold at start that changes how the application starts
INVALID = ({"hold_above_ms": 1000},)
#: The invalid conditions of the launch families' oracles: also a launch that brought up the launcher or another app
#: first, which says nothing of the application (21 Nov 2026)
LAUNCH_INVALID = (*INVALID, {"launcher_first": {}})
#: The interventions of a control: `network` blocks every host the case's baseline runs contacted
CONTROL_INTERVENTIONS = ("network",)
#: The outcomes a control may expect
EXPECTED = ("breaks", "preserves")

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
    #: What the strict check refuses in a family file written before it (a slot with other keys than kind and
    #: description): the family is read for the cases that name it, never used anew
    problems: tuple[str, ...] = ()

    @property
    def superseded_by(self) -> str | None:
        return self.data.get("superseded_by")

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

    def latest(self, superseded: bool = False) -> list[Family]:
        """The newest version of every family; of a superseded family none, unless `superseded`."""
        newest: dict[str, Family] = {}
        for f in self.families:
            if f.id not in newest or f.version > newest[f.id].version:
                newest[f.id] = f
        return sorted((f for f in newest.values() if superseded or not f.superseded_by), key=lambda f: f.id)

    def get(self, family_id: str, version: int | None = None) -> Family | None:
        found = [f for f in self.families if f.id == family_id and (version is None or f.version == version)]
        return max(found, key=lambda f: f.version) if found else None

    def usable(self, family_id: str, version: int | None = None) -> Family:
        """A family for a new use (a proposer's choice, a merge of proposals): the given version, else the newest.
        Raises CatalogueError for an unknown family, one superseded or one the strict check refuses."""
        family = self.get(family_id, version)
        if family is None:
            raise CatalogueError(f"{family_id!r} is no family of the catalogue")
        if family.superseded_by:
            raise CatalogueError(f"{family.key} is superseded by {family.superseded_by}: choose that family")
        if family.problems:
            raise CatalogueError(f"{family.key} is malformed ({'; '.join(family.problems)}); use a later version")
        return family

    def add(self, data: dict) -> Family:
        """Writes a family as the next version of its id, or as version 1 of a new id; returns it. An empty `reviewed`
        field is dropped: the review is stored beside the family (`review`)."""
        if "reviewed" in data and not data["reviewed"]:
            data = {k: v for k, v in data.items() if k != "reviewed"}
        folder = self.root / "families"
        folder.mkdir(parents=True, exist_ok=True)
        # 23 Nov 2026: processes proposing at once (the re-run's step 8) each read the catalogue when they started, so
        # two that described the same new id both wrote <id>@1 and the later replaced the earlier. Under a lock, the
        # versions on disk decide: a family identical to one there is that one, another is the next version.
        with open(folder / ".lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            current = self.get(data["id"])
            versions = [current.version] if current else []
            for path in folder.glob(f"{data['id']}@*.yaml"):
                if path.stem.rsplit("@", 1)[1].isdigit():
                    version = int(path.stem.rsplit("@", 1)[1])
                    versions.append(version)
                    text = yaml.safe_dump({**data, "version": version}, sort_keys=False, allow_unicode=True, width=120)
                    if path.read_text(encoding="utf-8") == text:
                        known = next((f for f in self.families if f.key == path.stem), None)
                        if known is None:
                            known = Family(data["id"], version, {**data, "version": version}, _digest(text), path)
                            self.families.append(known)
                        return known
            data = {**data, "version": max(versions, default=0) + 1}
            check(data)
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
        reviewed = replace(family, review=record, review_problem=None)
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


def load(root: str | Path, base: str | Path | None = None) -> Catalogue:
    """Reads a catalogue folder; an absent one is empty. Raises CatalogueError for a family that fails the checks, but
    for slot keys (`slot_problems`), which a family written before the strict check may have: it is read with them as
    its `problems`.

    With `base`, the catalogue is layered: the families of `base` (Skuld's committed catalogue, read only) and of
    `root` (a study's catalogue, where `add` writes the families models propose and `review` their reviews). A family
    in both is refused."""
    root = Path(root)
    families = list(load(base).families) if base is not None else []
    below = {f.key for f in families}
    for path in sorted((root / "families").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        data = yamlio.load(text)
        if not isinstance(data, dict):
            raise CatalogueError(f"{path.name}: not a mapping")
        try:
            check(data, strict_slots=False)
        except CatalogueError as e:
            raise CatalogueError(f"{path.name}: {e}") from e
        if path.stem != f"{data['id']}@{data['version']}":
            raise CatalogueError(f"{path.name}: named otherwise than its id and version")
        key, sha256 = f"{data['id']}@{data['version']}", _digest(text)
        review, problem = _review(root, key, sha256, data)
        problems = tuple(slot_problems(data))
        if key in below:
            raise CatalogueError(f"{path.name}: {key} is also in the base catalogue {base}")
        families.append(Family(data["id"], int(data["version"]), data, sha256, path, review, problem, problems))
    return Catalogue(root, families)


def check(data: dict, strict_slots: bool = True) -> None:
    """
    Refuses a family that is malformed: an id that is not lower-case words with hyphens; a purpose without its parts
    or requirements; an oracle that reaches requirements its purpose does not have, names a predicate or metric the
    instance does not know, or uses a slot it does not declare (or declares one it does not use); a slot with keys
    other than `kind` and `description` (`slot_problems`; not with `strict_slots` False, as `load` reads a family
    written before); a `superseded_by` that is no family id.
    """
    missing = [k for k in ("id", "version", "name", "entry", "path", "outcome", "purposes") if k not in data]
    if missing:
        raise CatalogueError(f"missing {', '.join(missing)}")
    if not _ID.match(str(data["id"])):
        raise CatalogueError(f"the id {data['id']!r} is not lower-case words joined by hyphens")
    if not data["purposes"]:
        raise CatalogueError("no purpose")
    if data.get("control") is not None:
        check_control(data["control"], "the family's control")
    if "superseded_by" in data and not _ID.match(str(data["superseded_by"] or "")):
        raise CatalogueError("superseded_by names the id of the family that supersedes it")
    if strict_slots and (found := slot_problems(data)):
        raise CatalogueError("; ".join(found))
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
        by_category = oracle.get("categories") or []
        if not isinstance(by_category, list):
            raise CatalogueError(f"{where}: the oracle's categories are a list of entries")
        for n, entry in enumerate(by_category, 1):
            names = entry.get("names") if isinstance(entry, dict) else None
            if not names or not all(isinstance(x, str) and x.strip() for x in names) or not entry.get("success"):
                raise CatalogueError(f"{where}: category entry {n} needs names and conditions of success")
            if entry.get("control") is not None:
                check_control(entry["control"], f"{where}: category entry {n}'s control")
            if not set(entry.get("reach") or ()) <= requirements:
                raise CatalogueError(f"{where}: category entry {n} reaches {entry['reach']}, not requirements of it")
        for spec in [
            *oracle["success"],
            *(oracle.get("invalid") or ()),
            *(s for e in by_category for s in e["success"]),
        ]:
            if _name(spec) not in PREDICATES:
                raise CatalogueError(f"{where}: unknown predicate {_name(spec)!r}")
        for m in oracle.get("measurements") or ():
            if _name(m.get("metric")) not in METRICS:
                raise CatalogueError(f"{where}: unknown metric in measurement {m.get('name')!r}")
        slots = oracle.get("slots") or {}
        for name, slot in slots.items():
            if slot.get("kind") not in SLOT_KINDS or not slot.get("description"):
                raise CatalogueError(f"{where}: slot {name} needs a kind of {SLOT_KINDS} and a description")
        used = slots_in(
            [
                oracle["success"],
                oracle.get("invalid") or [],
                oracle.get("measurements") or [],
                [e["success"] for e in by_category],
            ]
        )
        if undeclared := used - set(slots) - set(BUILT_IN):
            raise CatalogueError(f"{where}: undeclared slots {sorted(undeclared)}")
        if unused := set(slots) - used:
            raise CatalogueError(f"{where}: slots {sorted(unused)} are declared but not used")


def slot_problems(data: dict) -> list[str]:
    """The slots of a family's oracles with keys other than `kind` and `description`: in a YAML flow mapping a comma
    ends a plain description, and the rest of it becomes a key of its own (21 Nov 2026)."""
    out = []
    for p in data.get("purposes") or ():
        for name, slot in ((p.get("oracle") or {}).get("slots") or {}).items():
            if isinstance(slot, dict) and (other := sorted(map(str, set(slot) - {"kind", "description"}))):
                out.append(f"purpose {p.get('id')}: slot {name} has keys other than kind and description: {other}")
    return out


def check_control(control, where: str) -> None:
    """Refuses a control that names no known intervention or expected outcome."""
    if not isinstance(control, dict) or set(control) != {"intervention", "expected"}:
        raise CatalogueError(f"{where} is {{intervention, expected}}")
    if control["intervention"] not in CONTROL_INTERVENTIONS:
        raise CatalogueError(f"{where}: the intervention is one of {', '.join(CONTROL_INTERVENTIONS)}")
    if control["expected"] not in EXPECTED:
        raise CatalogueError(f"{where}: the expected outcome is one of {', '.join(EXPECTED)}")


def category_entry(oracle: dict, category: str | None) -> dict | None:
    """The entry of an oracle template's category table that names the application's store category, or None."""
    if not category:
        return None
    wanted = " ".join(category.split()).casefold()
    for entry in oracle.get("categories") or ():
        if any(" ".join(n.split()).casefold() == wanted for n in entry["names"]):
            return entry
    return None


def reach(oracle: dict, category: str | None) -> list:
    """An oracle template's requirements reached for an application of the store category: its own, and those the
    category's entry adds."""
    entry = category_entry(oracle, category)
    extra = [r for r in (entry.get("reach") or ()) if r not in oracle["reach"]] if entry else []
    return [*oracle["reach"], *extra]


def success(oracle: dict, category: str | None) -> list:
    """An oracle template's conditions of success for an application of the store category: its own, and those of
    the category's entry where its table has one."""
    entry = category_entry(oracle, category)
    return [*oracle["success"], *(entry["success"] if entry else ())]


def control(family: dict, category: str | None = None) -> dict | None:
    """The control a family declares for an application of the store category: a category entry's (of the first
    oracle whose table names the category), else the family's own; None if it declares none."""
    for p in family.get("purposes") or ():
        entry = category_entry(p.get("oracle") or {}, category)
        if entry is not None:
            return entry.get("control") or family.get("control")
    return family.get("control")


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
