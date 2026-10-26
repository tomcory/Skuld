"""
Functional oracles: the predicates an oracle file combines, over Loki's records of a run.

An oracle file holds no code. It lists conditions of success, conditions under which a run is invalid
and measurements, each by the name of a predicate or metric below with its arguments:

```yaml
success:
  - first_screen: {activity_suffix: ui.guide.GuideFirstActivity}
  - replay_complete: {}
  - screen_reached: {exact_key: 3b169bc8d30a725e}
  - text_shown: {any: [Zürich]}
invalid:
  - hold_above_ms: 1000
measurements:
  - {name: own_messages, metric: {messages_to: [ezhealth.app]}, better: higher, tolerance: 0}
```

A run is `invalid` if any invalid condition holds, `met` if every success condition holds, and
`unmet` otherwise. The predicates read the run's record and events only; the capture is read by
the verification, not by an oracle. The costs a run records (messages, connections, time) are
reported with every comparison and are not part of an oracle.
"""

import builtins
from dataclasses import dataclass, field
from datetime import datetime

from skuld.common import under
from skuld.inputs import Oracle
from skuld.runs import Run

VERSION = "0.2.0"


@dataclass(frozen=True)
class Decision:
    decision: str
    measurements: dict = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


def screens(run: Run) -> list[dict]:
    return [e for e in run.events if e.get("type") == "screen"]


def _first_screen(run: Run, activity_suffix: str | None = None, exact_keys: list[str] | None = None) -> bool:
    shown = screens(run)
    if not shown or shown[0].get("package") != run.package:
        return False
    first = shown[0]
    if activity_suffix and not (first.get("activity") or "").endswith(activity_suffix):
        return False
    return not exact_keys or first.get("exact_key") in exact_keys


def _first_screen_not(run: Run, exact_keys: list[str]) -> bool:
    shown = screens(run)
    return bool(shown) and shown[0].get("exact_key") not in exact_keys


def _replay_complete(run: Run) -> bool:
    replay = run.meta.get("replay") or {}
    return bool(replay) and all(replay.get(k) == 0 for k in ("divergences", "repairs", "skipped_actions"))


def after_actions(run: Run) -> list[tuple[int, dict]]:
    """
    The screens of the app, each with the number of actions taken before it. Loki records the screen an action led to
    (label 'post_action') before the action's own event, so such a screen counts as after the next action.
    """
    taken, out = 0, []
    for event in run.events:
        if event.get("type") == "action":
            taken += 1
        elif event.get("type") == "screen" and event.get("package") == run.package:
            out.append((taken + (1 if event.get("label") == "post_action" else 0), event))
    return out


def _within(after: int, after_action: int, until_action: int | None) -> bool:
    return after >= after_action and (until_action is None or after <= until_action)


def _screen_reached(run: Run, exact_key: str, after_action: int = 0, until_action: int | None = None) -> bool:
    """Whether a screen with the exact key was shown after the given action and, if given, up to the next one after
    `until_action`."""
    return builtins.any(
        s.get("exact_key") == exact_key and _within(after, after_action, until_action)
        for after, s in after_actions(run)
    )


def _text_shown(  # noqa: A002 (`any` is the oracle file's word)
    run: Run, any: list[str], after_action: int = 0, until_action: int | None = None
) -> bool:
    """
    Whether a screen of the app shown after the given action (0: any) and, if given, before the action after
    `until_action` holds one of the texts, as a whole text of the screen or within one. Reads the texts Loki records
    with each screen.
    """
    return builtins.any(
        _within(after, after_action, until_action) and any_of(s.get("texts") or (), any)
        for after, s in after_actions(run)
    )


def any_of(texts, wanted: list[str]) -> bool:
    return builtins.any(w in t for t in texts for w in wanted)


def _hold_above_ms(run: Run, ms: float) -> bool:
    return max((run.instrumentation or {}).get("held_ms") or [0]) > ms


PREDICATES = {
    "first_screen": _first_screen,
    "first_screen_not": _first_screen_not,
    "replay_complete": _replay_complete,
    "screen_reached": _screen_reached,
    "text_shown": _text_shown,
    "hold_above_ms": _hold_above_ms,
}


def _messages_to(run: Run, domains: list[str]) -> int:
    return sum(1 for m in run.messages or () if any(under(m["http_request"]["host"], d) for d in domains))


def duration_s(run: Run) -> float | None:
    start, end = run.meta.get("started_at"), run.meta.get("finished_at")
    if not (start and end):
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)


METRICS = {
    "messages_to": _messages_to,
    "messages": lambda run: len(run.messages or ()),
    "duration_s": duration_s,
}


def _call(table: dict, spec, run: Run):
    """Applies one entry of an oracle file: {name: arguments}, where the arguments are a mapping, a list or a value."""
    (name, arguments), *rest = spec.items() if isinstance(spec, dict) else [(spec, None)]
    if rest or name not in table:
        raise ValueError(f"unknown predicate or metric: {spec!r}")
    if isinstance(arguments, dict):
        return table[name](run, **arguments)
    if arguments is None:
        return table[name](run)
    return table[name](run, arguments)


def decide(oracle: Oracle, run: Run) -> Decision:
    """The oracle's decision on a run, with its measurements."""
    measurements = {m.name: _call(METRICS, m.metric, run) for m in oracle.measurements}
    invalid = [str(spec) for spec in oracle.invalid if _call(PREDICATES, spec, run)]
    if invalid:
        return Decision("invalid", measurements, tuple(invalid))
    failed = [str(spec) for spec in oracle.success if not _call(PREDICATES, spec, run)]
    return Decision("unmet" if failed else "met", measurements, tuple(failed))


def costs(run: Run) -> dict:
    """What a run records of its costs: messages, connections attempted and dropped, time."""
    connections = run.connections or ()
    return {
        "messages": len(run.messages or ()),
        "connections": len(connections),
        "connections_dropped": sum(1 for c in connections if c.get("blocked")),
        "duration_s": duration_s(run),
    }


def worse(value, baseline: list, better: str, tolerance: float) -> bool:
    """Whether a measurement of a run is worse than in each of a set of runs, by more than its tolerance."""
    if value is None or not baseline or any(b is None for b in baseline):
        return False
    if better == "higher":
        return all(b - value > tolerance for b in baseline)
    return all(value - b > tolerance for b in baseline)
