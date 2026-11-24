"""
The experiments a review of concerns shows (0.12.33, 24 Nov 2026; author: "show the reviewers the experiments that were
used as evidence"). An evidence item of an `ex:` channel names a comparison of the workspace's case report
(`report.json`, its `premises`): one alternative against the baseline, for one purpose of one case, judged by the
purpose's oracle. The reviewer is shown, per comparison, in words:

- the feature the case replays (its name and intended outcome; the launch for the case `launch`) and the purpose tested,
  with its requirements;
- what the alternative changed (`intervention`: hosts blocked, a source replaced or rounded);
- the success check (the oracle's `success`), with the screen it waits for where it waits for one (`screen_reached`:
  the recording's first screen of that structure key, its texts and screenshot);
- per side, each run's decision and its messages and connections (the case report's `runs`), the outcome, and how many
  runs with the change departed from the recorded steps (`divergence`);
- per side, the screen the check was met at in the first run that met it, with its screenshot (Loki takes one per
  visit: a screen without one is shown with its visit's first, as review_screens does).

The screen a check was met at is found as the oracle reads a run (`oracles.after_actions`, the window left out): for
`screen_reached` the first screen of the app with the structure key, else with the recording's content key of it; for
`first_screen_ready` the first screen of the app past the system's; for `text_shown` the first screen of the app
holding one of the texts. It is shown for orientation; the decision is the case report's.
"""

import json
from pathlib import Path

from skuld import inputs
from skuld.calibrate import read_json

#: The case report (skuld analyse)
REPORT = "report.json"


def comparison_of(e: dict) -> str | None:
    """The comparison an assessment's evidence item of an experiment names, if it is one."""
    if e.get("kind") != "run" or not str(e.get("channel") or "").startswith("ex:"):
        return None
    premises = e.get("premises") or []
    return premises[0] if premises else None


def _screens(directory: Path) -> list[dict]:
    path = Path(directory) / "events.jsonl"
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if '"screen"' in line:
                e = json.loads(line)
                if e.get("type") == "screen":
                    out.append(e)
    return out


def _system(screen: dict) -> bool:
    return screen.get("package") == "android" or ".permissioncontroller." in (screen.get("activity") or "")


def _shot(directory: Path, screens: list[dict], screen: dict) -> tuple | None:
    """(path in the run, digest) of the screen's screenshot, else of its visit's first (review_screens._visits)."""
    from skuld import images
    from skuld.review_screens import _visits

    record = screen.get("screenshot")
    if not record:
        first = _visits(directory).get(screen.get("seq"))
        record = first.get("screenshot") if first else None
    if record and (Path(directory) / record).is_file():
        return (record, images.digest(Path(directory) / record))
    return None


def met_at(screens: list[dict], package: str, condition: dict, content_keys: dict) -> dict | None:
    """The screen a run met one success condition at (see the module's docstring); None if none is found."""
    (name, args), *_ = condition.items() if isinstance(condition, dict) else [(condition, None)]
    args = args if isinstance(args, dict) else {}
    mine = [s for s in screens if s.get("package") == package]
    if name == "screen_reached":
        key = args.get("exact_key")
        content = args.get("content_key") or content_keys.get(key)
        return next((s for s in mine if s.get("exact_key") == key), None) or next(
            (s for s in mine if content and s.get("content_key") == content), None
        )
    if name == "first_screen_ready":
        first = next((s for s in screens if not _system(s)), None)
        return first if first and first.get("package") == package else None
    if name == "text_shown":
        wanted = args.get("any") or []
        return next((s for s in mine if any(w in t for t in s.get("texts") or () for w in wanted)), None)
    return None


def _check(condition: dict, recording_screens: list[dict]) -> dict:
    """A success condition in words, with the recorded screen it waits for, if it waits for one."""
    (name, args), *_ = condition.items() if isinstance(condition, dict) else [(condition, None)]
    args = args if isinstance(args, dict) else {}
    if name == "screen_reached":
        target = next((s for s in recording_screens if s.get("exact_key") == args.get("exact_key")), None)
        until = args.get("until_action")
        return {
            "kind": name,
            "text": "the app shows the screen below, which the exploration reached at the end of this feature"
            + (f" (by the feature's last step, action {until} of the exploration)" if until is not None else ""),
            "_target": target,
        }
    if name == "first_screen_ready":
        return {
            "kind": name,
            "text": "after a cold start, the app's first screen comes up ready for input (not a blank or loading "
            "screen, not the launcher)",
        }
    if name == "text_shown":
        wanted = args.get("any") or []
        return {
            "kind": name,
            "text": "a screen of the app shows "
            + (" or ".join(f"“{w}”" for w in wanted) if wanted else "the expected text"),
            "texts": list(wanted),
        }
    return {"kind": str(name), "text": json.dumps(condition, ensure_ascii=False)}


def change_text(alternative, component_name: str | None) -> str:
    """What an alternative changed, in words."""
    intervention = alternative.intervention or {}
    parts = []
    hosts = intervention.get("block_hosts") or []
    if hosts:
        parts.append("every request to " + ", ".join(hosts) + " blocked")
    for source, how in (intervention.get("sources") or {}).items():
        label = source.replace("_", " ")
        how = str(how)
        if how.startswith("replace:"):
            parts.append(f"the {label} the app reads replaced by {how.split(':', 1)[1]}")
        elif how.startswith("round:"):
            n = how.split(":", 1)[1]
            parts.append(f"the {label} the app reads rounded to {n} decimal{'' if n == '1' else 's'}")
        else:
            parts.append(f"the {label} the app reads: {how}")
    if not parts:
        parts.append(f"{component_name or alternative.component} removed" if alternative.removal else alternative.id)
    return "; ".join(parts)


def _run(record: dict | None, oracle: str) -> dict:
    record = record or {}
    decision = next((d["decision"] for d in record.get("decisions") or [] if d.get("oracle") == oracle), None)
    costs = record.get("costs") or {}
    out = {
        "decision": decision,
        "messages": costs.get("messages"),
        "connections": costs.get("connections"),
        "blocked": costs.get("connections_dropped"),
    }
    status = (record.get("verification") or {}).get("status")
    if status and status != "not_applicable":
        out["verified"] = status
    return out


def index(root: Path) -> dict[str, dict]:
    """Per comparison of the workspace's case report, what a review shows of it (see the module's docstring), with
    `_shots`: the screenshots it shows, as review_screens entries for copy_screenshots; {} for a workspace without a
    case report."""
    from skuld.review_screens import SCREENSHOTS

    root = Path(root)
    if not (root / REPORT).is_file() or not (root / "workspace.yaml").is_file():
        return {}
    report = read_json(root / REPORT)
    ws = inputs.load(root)
    package = (ws.application or {}).get("package")
    cases = {c.id: c for c in ws.cases}
    features = {f["id"]: f for f in report.get("features") or []}
    runs = {r["id"]: r for r in report.get("runs") or []}
    dirs = {r.id: r.directory for r in ws.runs}
    recording = _screens(ws.recording) if ws.recording else []
    content_keys = {s["exact_key"]: s["content_key"] for s in recording if s.get("exact_key") and s.get("content_key")}
    loaded: dict[str, list[dict]] = {}

    def screens_of(run: str) -> list[dict]:
        if run not in loaded:
            loaded[run] = _screens(dirs[run]) if run in dirs else []
        return loaded[run]

    def shown(directory: Path | None, screens: list[dict], screen: dict | None) -> dict | None:
        if screen is None or directory is None:
            return None
        shot = _shot(directory, screens, screen)
        out = {"texts": list(screen.get("texts") or ())}
        if shot:
            out["_entry"] = {"screenshot": shot, "directory": directory, "empty": set()}
            out["screenshot"] = f"{SCREENSHOTS}/{shot[1]}{Path(shot[0]).suffix or '.png'}"
        return out

    out = {}
    for c in report.get("comparisons") or []:
        case = cases.get(c["case"])
        if case is None:
            continue
        purpose = next((p for p in case.purposes if p.id == c["purpose"]), None)
        alternative = next((a for a in case.alternatives if a.id == c["alternative"]), None)
        oracle = ws.oracles.get(c["oracle"])
        if purpose is None or alternative is None or oracle is None:
            continue
        component = next((x.name for x in case.components if x.id == alternative.component), None)
        feature = features.get(case.feature.id) or {}
        checks = [_check(s, recording) for s in oracle.success]
        for check in checks:
            target = check.pop("_target", None)
            if target is not None and ws.recording is not None:
                check["screen"] = shown(ws.recording, recording, target)
        sides = {}
        for side, ids in (("baseline", c.get("baseline_runs") or []), ("alternative", c.get("alternative_runs") or [])):
            listed = [_run(runs.get(r), c["oracle"]) for r in ids]
            first = next((r for r, x in zip(ids, listed, strict=True) if x["decision"] == "met"), None)
            screen = None
            if first is not None and oracle.success:
                screens = screens_of(first)
                screen = shown(dirs.get(first), screens, met_at(screens, package, oracle.success[0], content_keys))
            sides[side] = {"runs": listed, "met_at": screen}
        parts = purpose.parts or {}
        out[c["id"]] = {
            "comparison": c["id"],
            "case": case.id,
            "feature": {
                "launch": case.id == "launch",
                "name": feature.get("name") or case.feature.name,
                "outcome": feature.get("outcome") or case.feature.outcome,
            },
            "purpose": {
                "text": " ".join(str(parts[k]) for k in ("action", "object") if parts.get(k)),
                "outcome": parts.get("outcome"),
                "requirements": [r.get("statement") for r in purpose.requirements if r.get("statement")],
            },
            "change": {
                "alternative": alternative.id,
                "component": component,
                "text": change_text(alternative, component),
            },
            "checks": checks,
            "outcome": c.get("outcome"),
            # a launch has no recorded steps to depart from
            "departed": 0 if case.id == "launch" else len(c.get("divergence") or []),
            **sides,
        }
    return out


def shots(card: dict) -> list[dict]:
    """The screenshots a card shows, as review_screens entries (for copy_screenshots)."""
    found = [check.get("screen") for check in card.get("checks", [])]
    found += [card.get(side, {}).get("met_at") for side in ("baseline", "alternative")]
    return [s["_entry"] for s in found if s and "_entry" in s]


def view(card: dict | None) -> dict | None:
    """A card as a sample holds it: without the screenshots' entries."""
    if card is None:
        return None

    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if not k.startswith("_")}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x

    return clean(card)
