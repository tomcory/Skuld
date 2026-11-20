"""
skuld select: the choice of experiments, each choice and each refusal a named input with its reason
(`inputs/selection.json`), made from an assessment report before any run it asks for.

A candidate is a practice and a supported inferred purpose whose minimisation reasoning cannot decide: no concern (v)
is supported for it, and no experiment already decides it (an experimental Alternative claim, ≈ the purpose, that is
supported or refuted). It is refused where Skuld can impose nothing on the practice's components (`space.imposable`),
or where an experiment already ran and could not assess it (no oracle observes the purpose), or where no experiment
could observe the purpose at all: no family of Skuld's catalogue has a purpose with an oracle that the candidate's
purpose would align with (`combine.aligned`: the same beneficiary, the family's node its own or one above it). Such a
purpose is served, if at all, where no run shows it (an advertising network matching a profile, an analytics backend
counting a use), so an experiment could only test another purpose of its experimental case (author, 12 Nov 2026, after
15 of 18 groups of the gemma run had no oracle for their purpose). Of the others, those
`inputs/chosen.yaml` names (concern or practice ids, each with its reason: pursued by the author, or in the calibration
sample) are chosen first, and their device time counts; the rest are chosen in order while their device time fits the
budget (config.json's `experiments`: off at a budget of 0, the default), and refused with the budget as the reason
when it does not.

    chosen:
      - {id: P-22c276a76c, reason: pursue}
      - {id: concern:P-22c276a76c:1, reason: calibrate}

The Investigator (Odin) passes its order and budget the same way (S-26): entries with the reason `investigate` carry a
rank, and are taken in rank order while their device time fits the budget, given by `--budget-seconds` over
config.json's; the candidates no entry names follow in Skuld's order. Which candidates are eligible stays Skuld's.

    chosen:
      - {id: P-22c276a76c, reason: investigate, rank: 1}

`skuld select --list` writes nothing and prints the candidates as JSON lines, each with its estimated device time,
whether it is eligible, and whether an experiment could change a case's qualified result. That is qualification's
experiment step for the purpose (`qualify/nextsteps.py`), which qualifies the case under each outcome of the
experiment; qualification proposes one per eligible candidate, by `refusal` here, so the two never disagree.

Candidates are decided in groups (author, 12 Nov 2026): one per data type and purpose node of the application, the
unit of the aggregated concerns (`skuld aggregate`). A group's eligible candidates are chosen or refused together, its
ineligible ones are refused each with its own reason, as before. The runs an alternative needs are shared by every
experimental case that imposes it (`space`: a condition depends on the recording only), so the device time counts each
intervention once: one baseline per selection, (repeats + 1) runs with its qualifying replay, and repeats runs per
intervention not yet counted, of `run_seconds` each. A candidate's `cost_seconds` in a selection is what it adds; in
the listing, what it would cost alone ((1 + its alternatives) × repeats runs and one replay), as Odin reads it. A selection is fixed once: making another replaces it only on request (`--replace`), and keeps the
one it replaces. Within one investigation it may be extended (`--extend`), which keeps every earlier choice and
refusal that does not depend on the budget, counts the device time already chosen, and decides the others again:
the candidates it did not yet hold and those an earlier budget refused (the Investigator gives each batch just the
device time of its choice, so its next batch may choose what the earlier one refused).
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from skuld import catalogue, combine, config, inputs, space, yamlio

VERSION = (
    "4"  # 4: a datum below a hooked source's node is imposable, as experimental cases vary it;
    # 3: unobservable purposes refused
)
AUTHOR = {"kind": "rule", "id": "skuld.select", "version": VERSION}
FILE = "inputs/selection.json"
CHOSEN = "inputs/chosen.yaml"
#: Why an entry of `inputs/chosen.yaml` is chosen
REASONS = {
    "pursue": "pursued by the author",
    "calibrate": "in the calibration sample",
    "investigate": "in the Investigator's order",
}
#: Reasons whose entries are chosen whatever the budget; an investigation's are taken within it, by rank
UNBUDGETED = ("pursue", "calibrate")
#: Qualified results an experiment cannot change: a minimisation concern adds nothing to a higher result
CHOICE, REFUSAL = "experiment_choice", "experiment_refusal"
#: The defaults of config.json's `experiments`
DEFAULTS = {"budget_seconds": 0, "repeats": 3, "run_seconds": 240}


class SelectionError(Exception):
    pass


def settings() -> dict:
    return {**DEFAULTS, **(config.load().get("experiments") or {})}


def _chosen(root: Path) -> dict[str, tuple[str, int]]:
    """The ids `inputs/chosen.yaml` names, each with its reason and rank (0 where it has none)."""
    path = root / CHOSEN
    if not path.is_file():
        return {}
    entries = (yamlio.load(path.read_text(encoding="utf-8")) or {}).get("chosen") or ()
    out = {}
    for e in entries:
        if e.get("reason") not in REASONS:
            raise SelectionError(f"{CHOSEN}: {e.get('id')}: the reason is one of {', '.join(REASONS)}")
        rank = e.get("rank", 0)
        if e["reason"] == "investigate" and (not isinstance(rank, int) or rank < 1):
            raise SelectionError(f"{CHOSEN}: {e.get('id')}: an investigation's entry has a rank of 1 or more")
        out[str(e["id"])] = (e["reason"], rank)
    return out


def _cost(c: dict, s: dict) -> int:
    alternatives = sum(len(x["alternatives"]) for x in c["components"])
    return ((1 + alternatives) * s["repeats"] + 1) * s["run_seconds"]


def _entry_id(c: dict) -> str:
    return f"selection:{c['practice']}:{c['purpose'].rsplit(':', 1)[1]}"


def group_id(c: dict) -> str:
    """A candidate's group: its data type and purpose node (the aggregated concerns' unit)."""
    return f"group:{c['fields'].get('data') or '?'}:{c.get('node') or '?'}"


def _alternatives(c: dict) -> set[str]:
    return {a for x in c["components"] for a in x["alternatives"]}


def _added(c: dict, counted: set[str], baseline: bool, s: dict) -> int:
    """The device time a candidate adds to what is counted: the baseline if none is yet, and its interventions not
    yet counted."""
    new = _alternatives(c) - counted
    return ((0 if baseline else s["repeats"] + 1) + len(new) * s["repeats"]) * s["run_seconds"]


def _grouped(found: list[dict]) -> list[list[dict]]:
    """The candidates in groups, in the order of each group's first candidate."""
    groups: dict[str, list[dict]] = {}
    for c in found:
        groups.setdefault(group_id(c), []).append(c)
    return list(groups.values())


def refusal(candidate: dict) -> str | None:
    """Why no experiment is chosen for a candidate, or None where it is eligible."""
    if not candidate["components"]:
        return "Skuld can impose nothing on its components"
    if candidate.get("unobservable"):
        return candidate["unobservable"]
    if candidate.get("tried"):
        return f"an experiment could not assess it ({candidate['tried']})"
    return None


def _could_change(report: dict) -> dict[str, bool]:
    """Per purpose, whether its experiment could change a case's qualified result: qualification's experiment step
    for it (qualify/nextsteps.py), which tests each outcome of the experiment on the case."""
    steps = (report.get("qualification") or {}).get("next_steps") or []
    out: dict[str, bool] = {}
    for s in steps:
        purpose = (s.get("target") or {}).get("purpose")
        if s["kind"] == "experiment" and purpose:
            out[purpose] = out.get(purpose, False) or s["could_change"]
    return out


def listing(root: str | Path) -> list[dict]:
    """The candidates of an assessment workspace with their device time, eligibility and whether an experiment could
    change their case's result; writes nothing."""
    root = Path(root)
    report = json.loads((root / "assessment.json").read_text(encoding="utf-8"))
    practices = json.loads((root / "subjects.json").read_text(encoding="utf-8"))["practices"]
    s = settings()  # a candidate's device time; the budget is select's, not the listing's
    change = _could_change(report)
    out = []
    for c in candidates(report, practices):
        refused = refusal(c)
        out.append(
            {
                "id": _entry_id(c),
                "group": group_id(c),
                "practice": c["practice"],
                "purpose": c["purpose"],
                "concern": c["concern"],
                "cost_seconds": _cost(c, s),
                "eligible": refused is None,
                **({"refusal": refused} if refused else {}),
                # an ineligible candidate has no experiment step, so it could change nothing
                "could_change": refused is None and change.get(c["purpose"], False),
            }
        )
    return out


def group_listing(root: str | Path) -> list[dict]:
    """The candidates' groups (data type and purpose node): each with its members, its distinct interventions, what
    it would cost alone with its runs shared (a baseline and repeats runs per intervention), whether any member is
    eligible and whether any could change a case's result; writes nothing."""
    root = Path(root)
    report = json.loads((root / "assessment.json").read_text(encoding="utf-8"))
    practices = json.loads((root / "subjects.json").read_text(encoding="utf-8"))["practices"]
    s = settings()
    listed = {x["id"]: x for x in listing(root)}
    out = []
    for members in _grouped(candidates(report, practices)):
        eligible = [c for c in members if refusal(c) is None]
        interventions = sorted({a for c in eligible for a in _alternatives(c)})
        first = members[0]
        out.append(
            {
                "id": group_id(first),
                "data": first["fields"].get("data"),
                "node": first.get("node"),
                "members": [_entry_id(c) for c in members],
                "eligible_members": [_entry_id(c) for c in eligible],
                "interventions": interventions,
                "cost_seconds": (s["repeats"] + 1 + len(interventions) * s["repeats"]) * s["run_seconds"]
                if eligible
                else 0,
                "eligible": bool(eligible),
                "could_change": any(listed[_entry_id(c)]["could_change"] for c in eligible),
            }
        )
    return out


#: Skuld's catalogue of case families
CATALOGUE = Path(__file__).resolve().parents[1] / "catalogue"


def observed_purposes(folder: Path = CATALOGUE) -> list[tuple[str, str]]:
    """The (node, beneficiary) of every purpose with an oracle in the newest version of each family of the catalogue."""
    return sorted(
        {
            (p["node"], combine.beneficiary(p.get("beneficiary")))
            for f in catalogue.load(folder).latest()
            for p in f.data.get("purposes") or ()
            if p.get("oracle") and p.get("node")
        }
    )


def unobservable(node: str | None, who: str | None, observed: list[tuple[str, str]], vocabulary) -> str | None:
    """Why no experiment could observe a purpose, or None: no observed purpose of the same beneficiary at its node or
    above it (the alignment of a case purpose with a hypothesis purpose, `combine.aligned`)."""
    if not node or node not in vocabulary:
        return None  # an unknown node is left to the experimental cases, as before
    lineage = {node, *vocabulary.ancestors(node)}
    whom = combine.beneficiary(who)
    if any(n in lineage and b == whom for n, b in observed):
        return None
    return (
        f"no experiment could observe its purpose: no case family of the catalogue has an oracle for a purpose of the "
        f"{whom} at {node} or above it"
    )


def candidates(report: dict, practices: list[dict]) -> list[dict]:
    """The practices and supported inferred purposes whose minimisation is undecided, with what Skuld could impose."""
    from skuld.common import PURPOSES, vocabulary

    purposes = vocabulary(PURPOSES)
    observed = observed_purposes()
    by_id = {p["id"]: p for p in practices}
    concern = {c.get("purpose"): c for c in report["concerns"] if c["step"] == "less_invasive_alternative"}
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
                "episodes": p.get("episodes") or [],
                "fields": {f: p.get(f) for f in ("id", "claim_type", "data", "recipient")},
                "components": space.imposable(SimpleNamespace(**{**p, "party": p.get("party")})),
                **(
                    {"tried": f"case {tried[h['id']]['case']}: {tried[h['id']].get('reason', 'not assessable')}"}
                    if h["id"] in tried
                    else {}
                ),
                **(
                    {"unobservable": why}
                    if (
                        why := unobservable(
                            h["purpose"].get("node"), h["purpose"].get("beneficiary"), observed, purposes
                        )
                    )
                    else {}
                ),
            }
        )
    return out


def select(
    root: str | Path,
    replace: bool = False,
    now: datetime | None = None,
    budget_seconds: int | None = None,
    extend: bool = False,
) -> dict:
    """Writes the selection of an assessment workspace from its report (`skuld assess` first); returns it.
    `budget_seconds` overrides config.json's budget; `extend` keeps an existing selection and adds to it."""
    root = Path(root)
    path = root / FILE
    report_path = root / "assessment.json"
    if not report_path.is_file():
        raise SelectionError(f"{root}: no assessment.json; run skuld assess first")
    if path.is_file() and not (replace or extend):
        raise SelectionError(f"{path} is fixed; select again only with --replace, which keeps it, or --extend")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    practices = json.loads((root / "subjects.json").read_text(encoding="utf-8"))["practices"]
    s = {**settings(), **({"budget_seconds": budget_seconds} if budget_seconds is not None else {})}
    named = _chosen(root)
    spent, entries = 0, []
    if extend and path.is_file():
        earlier = json.loads(path.read_text(encoding="utf-8"))
        # a refusal for the budget alone (eligible, so `refusal` finds nothing) is decided again under the new budget
        entries = [e for e in earlier["entries"] if e["kind"] == CHOICE or refusal(e) is not None]
        spent = earlier["device_seconds"]
    held = {e["id"] for e in entries}
    found = [c for c in candidates(report, practices) if _entry_id(c) not in held]
    # what earlier choices of an extended selection already count: their interventions, and the baseline
    chosen_before = [e for e in entries if e["kind"] == CHOICE]
    counted = {a for e in chosen_before for a in _alternatives(e)}
    baseline = bool(chosen_before)

    def mark(c: dict) -> tuple[str, int] | None:
        return next((named[k] for k in (c["concern"], c["practice"]) if k in named), None)

    def group_mark(members: list[dict]) -> tuple[str, int] | None:
        marks = [m for m in map(mark, members) if m]
        # a reason that is chosen whatever the budget comes first, then the best rank
        return min(marks, key=lambda m: (m[0] not in UNBUDGETED, m[1])) if marks else None

    groups = _grouped(found)
    first = sorted(
        (g for g in groups if group_mark(g)), key=lambda g: (group_mark(g)[0] == "investigate", group_mark(g)[1])
    )
    for members in first + [g for g in groups if g not in first]:
        gid = group_id(members[0])
        eligible = [c for c in members if refusal(c) is None]
        for c in members:
            if c in eligible:
                continue
            entry = {"id": _entry_id(c), **c, "group": gid, "cost_seconds": 0, "kind": REFUSAL, "reason": refusal(c)}
            entries.append(entry)
        if not eligible:
            continue
        # the group's device time: what its eligible members add together, each counting what the one before added
        adds, seen, has_baseline = [], set(counted), baseline
        for c in eligible:
            adds.append(_added(c, seen, has_baseline, s))
            seen |= _alternatives(c)
            has_baseline = True
        cost = sum(adds)
        marked = group_mark(eligible)
        statuses = sorted({c["concern_status"] or "not stated" for c in eligible})
        undecided = f"reasoning does not decide it (concern (v) {', '.join(statuses)})"
        together = f"with its group {gid} ({len(eligible)} candidate{'s' if len(eligible) > 1 else ''})"
        if marked and marked[0] in UNBUDGETED:
            kind, reason = CHOICE, f"{REASONS[marked[0]]}; {undecided}; {together}"
        elif marked and spent + cost <= s["budget_seconds"]:
            kind, reason = (
                CHOICE,
                f"{REASONS[marked[0]]} (rank {marked[1]}); {undecided}; {together}; within the budget",
            )
        elif spent + cost <= s["budget_seconds"]:
            kind, reason = CHOICE, f"{undecided}; {together}; within the budget"
        elif not s["budget_seconds"]:
            kind, reason = REFUSAL, f"{undecided}; {together}; experiments are off (budget 0)"
        else:
            kind, reason = (
                REFUSAL,
                f"{undecided}; {together}; over the budget ({spent + cost} of {s['budget_seconds']} s)",
            )
        for c, add in zip(eligible, adds, strict=True):
            entries.append({"id": _entry_id(c), **c, "group": gid, "cost_seconds": add, "kind": kind, "reason": reason})
        if kind == CHOICE:
            spent += cost
            counted |= seen
            baseline = True
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
        archived = path.with_name(f"selection-{old['created'].replace(':', '')}.json")
        n = 1
        while archived.exists():  # two selections fixed within one second keep both
            n += 1
            archived = path.with_name(f"selection-{old['created'].replace(':', '')}-{n}.json")
        path.rename(archived)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(selection, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
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
    """For the generator: the episodes of the chosen practices, and whether an experimental case's component varies a
    component the selection chose."""
    entries = chosen(selection)
    episodes = {e for x in entries for e in x["episodes"]}
    wanted = [(SimpleNamespace(**x["fields"]), {c["component"] for c in x["components"]}) for x in entries]

    def keep(component: dict) -> bool:
        return any(space.varies(component, p, data) in names for p, names in wanted)

    return episodes, keep
