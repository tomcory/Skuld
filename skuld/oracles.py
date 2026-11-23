"""
Functional oracles: the predicates an oracle file combines, over Loki's records of a run.

An oracle file holds no code. It lists conditions of success, conditions under which a run is invalid
and measurements, each by the name of a predicate or metric below with its arguments:

```yaml
success:
  - first_screen: {activity_suffix: ui.guide.GuideFirstActivity}
  - first_screen_ready: {}
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

`launcher_first` (0.4.0, 21 Nov 2026) holds where the first screen after a cold start, past the system's, is not the
app's: the launcher, or another app. Such a launch says nothing of the app, so the launch families count the run
invalid (it is dropped from both sides of a comparison, and `skuld run` makes it once more), not unmet.

The window of `text_shown` and `screen_reached` is given in actions of a replay of the recording (`after_action`,
`until_action`, filled from the feature's path: `{path_start}`, `{path_end}`). A goal-directed run follows no
recording: its window is its goal episode (`runs.Window`), from the episode's start to its end, with the screens Loki
records as the episode closes. `decide` reads the oracle's window against the case's path there: a
bound at or before the path's start is the episode's start, a bound at or after the path's end is the statement,
and one between them widens to the episode (21 Nov 2026).

`screen_reached` names the recorded screen by its exact key, a digest over every text on it. A goal-directed run
reaches the feature by its own way, with live content, the system's banners and its own choices, so the same screen
rarely recurs with the same texts (23 Nov 2026, the re-run: Weather's notification settings reached with a banner and
other preferences chosen, rejected). Since 0.5.0 it is also met by a screen with the recorded screen's content key
(Loki's key of the screen's structure, its texts aside), read from the workspace's recording (`screen_keys`); the
outcome's texts stay with `text_shown`.
"""

import builtins
import json
from dataclasses import dataclass, field
from datetime import datetime

from skuld.common import under
from skuld.inputs import Oracle
from skuld.runs import Run

#: 0.5.0: screen_reached is also met by the recorded screen's content key; 0.4.0: launcher_first, and a goal-directed
#: run's window is its goal episode; 0.3.0: first_screen_ready; 0.2.1: first_screen skips the system's screens
#: (permission dialog, starting window)
VERSION = "0.5.0"


@dataclass(frozen=True)
class Decision:
    decision: str
    measurements: dict = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


def screens(run: Run) -> list[dict]:
    return [e for e in run.events if e.get("type") == "screen"]


def _system(screen: dict) -> bool:
    """A screen of the system over or before the app: Android's runtime permission dialog (API 33+ asks for
    notifications at the first launch) or a window of the package 'android' (the starting window of a cold start
    is reported so, with the app's activity and no text). Not a screen of the app, nor of another app."""
    return screen.get("package") == "android" or ".permissioncontroller." in (screen.get("activity") or "")


def _launched(run: Run) -> list[dict]:
    """The run's screens from the first that is not the system's on."""
    shown = screens(run)
    start = next((i for i, s in enumerate(shown) if not _system(s)), len(shown))
    return shown[start:]


def _first_screen(run: Run, activity_suffix: str | None = None, exact_keys: list[str] | None = None) -> bool:
    shown = _launched(run)
    if not shown or shown[0].get("package") != run.package:
        return False
    first = shown[0]
    if activity_suffix and not (first.get("activity") or "").endswith(activity_suffix):
        return False
    return not exact_keys or first.get("exact_key") in exact_keys


def _first_screen_ready(run: Run) -> bool:
    """
    Whether the app's first screen after a cold start, past the system's, is ready for input: a screen of the app
    with at least one element Loki could act on (graph.json). Any such screen counts, not only the recorded one: an
    app that shows its tour, a notice or an ad before its entry screen has started. A launcher or another app first,
    or a screen with nothing to act on (a starting window, a blank screen), does not.
    """
    shown = _launched(run)
    if not shown or shown[0].get("package") != run.package:
        return False
    return _actions(run).get(shown[0].get("screen_id"), 0) > 0


def _actions(run: Run) -> dict[str, int]:
    """The number of elements Loki found to act on, per screen id of the run's graph, merged screens included."""
    path = run.directory / "graph.json"
    if not path.is_file():
        return {}
    graph = json.loads(path.read_text(encoding="utf-8"))
    counts = {sid: len(s.get("actions") or ()) for sid, s in (graph.get("screens") or {}).items()}
    merged = graph.get("merged_into") or {}
    for sid in merged:
        target, seen = sid, set()
        while target in merged and target not in seen:
            seen.add(target)
            target = merged[target]
        counts[sid] = counts.get(target, 0)
    return counts


def _launcher_first(run: Run) -> bool:
    """Whether the first screen after a cold start, past the system's, is the launcher's or another app's, not the
    app's (Weather's baseline, 13 Nov 2026): the launch did not bring the app up, which says nothing of it."""
    shown = _launched(run)
    return bool(shown) and shown[0].get("package") != run.package


def _first_screen_not(run: Run, exact_keys: list[str]) -> bool:
    shown = _launched(run)
    return bool(shown) and shown[0].get("exact_key") not in exact_keys


def _replay_complete(run: Run) -> bool:
    replay = run.meta.get("replay") or {}
    return bool(replay) and all(replay.get(k) == 0 for k in ("divergences", "repairs", "skipped_actions"))


def after_actions(run: Run) -> list[tuple[int, dict]]:
    """
    The screens of the app, each with the number of actions taken before it. Loki records the screen an action led to
    (label 'post_action') before the action's own event, so such a screen counts as after the next action. Of a
    goal-directed run, only the screens of its goal episode (`Run.window`).
    """
    window = getattr(run, "window", None)
    taken, out = 0, []
    for i, event in enumerate(run.events):
        if event.get("type") == "action":
            taken += 1
        elif event.get("type") == "screen" and event.get("package") == run.package:
            if window is not None and not window.first <= i <= window.last:
                continue
            out.append((taken + (1 if event.get("label") == "post_action" else 0), event))
    return out


def _within(after: int, after_action: int, until_action: int | None) -> bool:
    return after >= after_action and (until_action is None or after <= until_action)


def _screen_reached(
    run: Run, exact_key: str, after_action: int = 0, until_action: int | None = None, content_key: str | None = None
) -> bool:
    """Whether a screen with the exact key, or with the recorded screen's content key (given by `decide` from the
    recording), was shown after the given action and, if given, up to the next one after `until_action`."""
    return builtins.any(
        (s.get("exact_key") == exact_key or (content_key is not None and s.get("content_key") == content_key))
        and _within(after, after_action, until_action)
        for after, s in after_actions(run)
    )


_KEYS: dict = {}


def screen_keys(recording) -> dict[str, str]:
    """The content key of each exact key among a recording's screens (its events.jsonl); empty where it cannot be
    read. Kept per folder."""
    if recording is None:
        return {}
    folder = str(recording)
    if folder not in _KEYS:
        keys = {}
        try:
            with open(f"{folder}/events.jsonl", encoding="utf-8") as f:
                for line in f:
                    if '"screen"' not in line:
                        continue
                    e = json.loads(line)
                    if e.get("type") == "screen" and e.get("exact_key") and e.get("content_key"):
                        keys.setdefault(e["exact_key"], e["content_key"])
        except OSError:
            pass
        _KEYS[folder] = keys
    return _KEYS[folder]


def _with_content_key(spec, keys: dict[str, str] | None):
    if not keys or not isinstance(spec, dict) or len(spec) != 1:
        return spec
    (name, arguments), *_ = spec.items()
    if name != "screen_reached" or not isinstance(arguments, dict) or "content_key" in arguments:
        return spec
    content = keys.get(arguments.get("exact_key"))
    return {name: {**arguments, "content_key": content}} if content else spec


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
    "first_screen_ready": _first_screen_ready,
    "replay_complete": _replay_complete,
    "screen_reached": _screen_reached,
    "text_shown": _text_shown,
    "hold_above_ms": _hold_above_ms,
    "launcher_first": _launcher_first,
}

#: The predicates whose window is given in actions (`after_action`, `until_action`)
WINDOWED = ("screen_reached", "text_shown")


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


def decide(
    oracle: Oracle, run: Run, path: tuple[int, int] | None = None, screen_keys: dict[str, str] | None = None
) -> Decision:
    """
    The oracle's decision on a run, with its measurements. `path`: the case's path in actions of the recording (its
    start and end), by which a goal-directed run's window is read (`rebased`). `screen_keys`: the recording's content
    key per exact key (`screen_keys`), by which `screen_reached` is met by the recorded screen's structure too.
    """
    window = getattr(run, "window", None)
    measurements = {m.name: _call(METRICS, m.metric, run) for m in oracle.measurements}

    def holds(spec) -> bool:
        return _call(PREDICATES, _with_content_key(rebased(spec, window, path), screen_keys), run)

    invalid = [str(spec) for spec in oracle.invalid if holds(spec)]
    if invalid:
        return Decision("invalid", measurements, tuple(invalid))
    failed = [str(spec) for spec in oracle.success if not holds(spec)]
    return Decision("unmet" if failed else "met", measurements, tuple(failed))


def rebased(spec, window, path: tuple[int, int] | None):
    """
    An oracle's condition with its window in actions of a goal-directed run: a bound at or before the path's start is
    the goal episode's start, one at or after the path's end its end, one between them widens
    to the episode; without a bound, the episode's. A condition of a replay, or without a window, is left as it is.
    """
    if window is None or not isinstance(spec, dict) or len(spec) != 1:
        return spec
    (name, arguments), *_ = spec.items()
    if name not in WINDOWED or not isinstance(arguments, dict):
        return spec
    start, end = path if path is not None else (None, None)
    low, high = arguments.get("after_action", 0), arguments.get("until_action")
    after = window.end if end is not None and low >= end and end > (start or 0) else window.start
    until = window.start if high is not None and start is not None and high <= start < end else window.end
    return {name: {**arguments, "after_action": after, "until_action": until}}


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
