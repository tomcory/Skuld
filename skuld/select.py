"""
skuld select: the choice of experiments, each choice and each refusal a named input with its reason
(`inputs/selection.json`), made from an assessment report before any run it asks for.

A candidate is a practice and a supported inferred purpose whose minimisation reasoning cannot decide: no concern (v)
is supported for it, and no experiment already decides it (an experimental Alternative claim, ≈ the purpose, that is
supported or refuted). It is refused where Skuld can impose nothing on the practice's components (`space.imposable`),
or where an experiment already ran and could not assess it (no oracle observes the purpose). Of the others, those
`inputs/chosen.yaml` names (concern or practice ids, each with its reason: pursued by the author, or in the calibration
sample) are chosen first, and their device time counts; the rest are chosen in order while their device time fits the
budget (config.json's `experiments`: off at a budget of 0, the default), and refused with the budget as the reason
when it does not.

    chosen:
      - {id: P-22c276a76c, reason: pursue}
      - {id: concern:P-22c276a76c:1, reason: calibrate}

A case's device time is estimated as (1 + its alternatives) × repeats runs, and one qualifying replay, of
`run_seconds` each. A selection is fixed once: making another replaces it only on request, and keeps the one it
replaces.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import yaml

from skuld import combine, config, inputs, space

VERSION = "1"
AUTHOR = {"kind": "rule", "id": "skuld.select", "version": VERSION}
FILE = "inputs/selection.json"
CHOSEN = "inputs/chosen.yaml"
#: Why an entry of `inputs/chosen.yaml` is chosen
REASONS = {"pursue": "pursued by the author", "calibrate": "in the calibration sample"}
CHOICE, REFUSAL = "experiment_choice", "experiment_refusal"
#: The defaults of config.json's `experiments`
DEFAULTS = {"budget_seconds": 0, "repeats": 3, "run_seconds": 240}


class SelectionError(Exception):
    pass


def settings() -> dict:
    return {**DEFAULTS, **(config.load().get("experiments") or {})}


def _chosen(root: Path) -> dict[str, str]:
    """The ids `inputs/chosen.yaml` names, each with its reason."""
    path = root / CHOSEN
    if not path.is_file():
        return {}
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("chosen") or ()
    out = {}
    for e in entries:
        if e.get("reason") not in REASONS:
            raise SelectionError(f"{CHOSEN}: {e.get('id')}: the reason is one of {', '.join(REASONS)}")
        out[str(e["id"])] = e["reason"]
    return out


def candidates(report: dict, practices: list[dict]) -> list[dict]:
    """The practices and supported inferred purposes whose minimisation is undecided, with what Skuld could impose."""
    by_id = {p["id"]: p for p in practices}
    concern = {c["purpose"]: c for c in report["concerns"] if c["step"] == "less_invasive_alternative"}
    tested = [c for c in report["claims"] if c.get("case") and c["type"] == "alternative"]
    decided = {b for c in tested if c["status"] in combine.DECISIVE for b in c["basis"]}
    tried = {b: c for c in tested if c["status"] == "not_assessable" for b in c["basis"]}
    out = []
    for h in report["claims"]:
        if h.get("stage") != "expectation" or h["type"] != "purpose":
            continue
        if h["status"] != "supported" or h["id"] in decided:
            continue
        k = concern.get(h["id"])
        if k is not None and k["status"] == "supported":
            continue
        p = by_id[h["subject"]]
        out.append(
            {
                "practice": p["id"],
                "purpose": h["id"],
                "node": h["purpose"].get("node"),
                "beneficiary": h["purpose"].get("beneficiary"),
                "concern": k["id"] if k else None,
                "concern_status": k["status"] if k else None,
                "episodes": p["episodes"],
                "fields": {f: p.get(f) for f in ("id", "claim_type", "data", "recipient")},
                "components": space.imposable(SimpleNamespace(**{**p, "party": p.get("party")})),
                **(
                    {"tried": f"case {tried[h['id']]['case']}: {tried[h['id']].get('reason', 'not assessable')}"}
                    if h["id"] in tried
                    else {}
                ),
            }
        )
    return out


def select(root: str | Path, replace: bool = False, now: datetime | None = None) -> dict:
    """Writes the selection of an assessment workspace from its report (`skuld assess` first); returns it."""
    root = Path(root)
    path = root / FILE
    report_path = root / "assessment.json"
    if not report_path.is_file():
        raise SelectionError(f"{root}: no assessment.json; run skuld assess first")
    if path.is_file() and not replace:
        raise SelectionError(f"{path} is fixed; select again only with --replace, which keeps it")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    practices = json.loads((root / "subjects.json").read_text(encoding="utf-8"))["practices"]
    s = settings()
    named = _chosen(root)
    spent, entries = 0, []
    found = candidates(report, practices)
    first = [c for c in found if {c["practice"], c["concern"]} & set(named)]
    for c in first + [c for c in found if c not in first]:
        alternatives = sum(len(x["alternatives"]) for x in c["components"])
        cost = ((1 + alternatives) * s["repeats"] + 1) * s["run_seconds"]
        entry = {"id": f"selection:{c['practice']}:{c['purpose'].rsplit(':', 1)[1]}", **c, "cost_seconds": cost}
        marked = next((named[k] for k in (c["concern"], c["practice"]) if k in named), None)
        undecided = f"reasoning does not decide it (concern (v) {c['concern_status'] or 'not stated'})"
        if not c["components"]:
            entry.update(kind=REFUSAL, reason="Skuld can impose nothing on its components")
        elif c.get("tried"):
            entry.update(kind=REFUSAL, reason=f"an experiment could not assess it ({c['tried']})")
        elif marked:
            entry.update(kind=CHOICE, reason=f"{REASONS[marked]}; {undecided}")
        elif spent + cost <= s["budget_seconds"]:
            entry.update(kind=CHOICE, reason=f"{undecided}; within the budget")
        elif not s["budget_seconds"]:
            entry.update(kind=REFUSAL, reason=f"{undecided}; experiments are off (budget 0)")
        else:
            entry.update(
                kind=REFUSAL, reason=f"{undecided}; over the budget ({spent + cost} of {s['budget_seconds']} s)"
            )
        if entry["kind"] == CHOICE:
            spent += cost
        entries.append(entry)
    created = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    selection = {
        "created": created,
        "author": AUTHOR,
        "assessment": {"path": "assessment.json", "sha256": inputs.digest(report_path)},
        "settings": s,
        "device_seconds": spent,
        "entries": entries,
    }
    if path.is_file():
        old = json.loads(path.read_text(encoding="utf-8"))
        path.rename(path.with_name(f"selection-{old['created'].replace(':', '')}.json"))
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(selection, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return selection


def named(root: Path) -> list[dict]:
    """The selection's entries as the report's named inputs, each by the digest of its record."""
    path = root / FILE
    if not path.is_file():
        return []
    selection = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "kind": e["kind"],
            "id": e["id"],
            "sha256": _sha(e),
            "fixed": selection["created"],
            "author": selection["author"],
            "reason": e["reason"],
        }
        for e in selection["entries"]
    ]


def _sha(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def chosen(selection: dict) -> list[dict]:
    return [e for e in selection["entries"] if e["kind"] == CHOICE]


def keeps(selection: dict, data) -> tuple[set[str], Callable[[dict], bool]]:
    """For the generator: the episodes of the chosen practices, and whether a case's component varies a component
    the selection chose."""
    entries = chosen(selection)
    episodes = {e for x in entries for e in x["episodes"]}
    wanted = [(SimpleNamespace(**x["fields"]), {c["component"] for c in x["components"]}) for x in entries]

    def keep(component: dict) -> bool:
        return any(space.varies(component, p, data) in names for p, names in wanted)

    return episodes, keep
