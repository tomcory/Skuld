"""
A Loki run folder, as Skuld reads it: Skuld's only window on a device.

Loki drives the app, controls the capture and instruments the app; what it did and saw is in the run
folder it writes: `run.json` (the run's record, with the blocks `capture` and `instrumentation`),
`events.jsonl` (everything that happened, in order) and the capture's export below `capture/`, with
the scans of the apps (their permissions and tracker libraries) if the run asked for them.
`load` reads such a folder and refuses one that Skuld cannot rely on: a run that did not end in
order, a capture export that Loki did not validate or that is not complete, and an instrumentation
record that does not conform to Ratatoskr's schemas, which Skuld checks again itself.

Whether an intervention held is not decided here. `Run.verification` is Loki's answer to "was the
app handed what the settings say"; Skuld's own verifier adds the traffic and the device state.

A goal-directed run (Loki's regime goal, `loki crawl --goal … --goal-id <case>`, 21 Nov 2026) also has its episodes
(`episodes.json`) and its scope (`run_scope.json`, whose `goal` names the goal and where Loki's agent said it reached
it). Its `window` is the goal episode: from the episode's start to its end, with the screens Loki records as it closes
(the agent states the goal from its own screenshot, before Loki records that screen). That the feature was reached
is the agent's statement only; an oracle decides it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema
from ratatoskr.schemas import validate

#: Versions of Loki's run record that this module reads
SCHEMA_VERSIONS = (2,)

#: Exported files of a capture, by the name of their count in `run.json → capture.records`
CAPTURE_FILES = {"messages": "messages.jsonl", "connections": "connections.jsonl"}

#: The apps' scans, exported only if the run asked for them (`capture.export: [..., scans]`)
SCANS_FILE = "scans.jsonl"
#: Loki's periodic snapshots of the capture (`capture` events of state snapshot), the latest of which stands for the
#: final export where that failed
SNAPSHOTS = "capture-snapshot"


class RunRefused(Exception):
    """
    A run folder that Skuld does not use.

    Attributes:
        reason: A short identifier: 'not_a_run', 'unsupported_version', 'unfinished', 'failed', 'no_capture',
            'capture_failed', 'export_not_validated', 'incomplete_export' or 'invalid_record'
        detail: Further information
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SettingChange:
    """
    A source setting changed during the run (a plan step, or its replay).

    Attributes:
        seq: Position in the run's events
        ts: The host's time of the change, ISO 8601 in UTC; `device_uptime_s` places it on the device
        applied: False if the run had no instrumentation session to apply it in
    """

    seq: int
    ts: str
    device_uptime_s: float | None
    settings: tuple[str, ...]
    origin: str
    applied: bool = True


@dataclass(frozen=True)
class Window:
    """
    The goal episode of a goal-directed run, which its oracles judge.

    Attributes:
        episode: The goal episode (the one the agent said it reached the goal in, else the last that sought it)
        start: The run's actions before the episode's first
        end: The run's actions up to the episode's end
        first: The index in the run's events of the episode's start
        last: The index of the last event before the next episode's start (the events after it are outside the window)
        reached: Whether the agent said it reached the goal
    """

    episode: int | None
    start: int
    end: int
    first: int
    last: int
    reached: bool


@dataclass(frozen=True)
class Run:
    """
    What a run folder holds, as far as Skuld uses it. Records are the dicts Loki wrote.

    Attributes:
        meta: The whole of `run.json`
        events: Every event of `events.jsonl`, in order
        actions: The events of type 'action': what was done to the app
        source_reads: The events of type 'source_read': what the app read of an instrumented source
        changes: Setting changes during the run, in order
        messages: The captured HTTP messages (`captured_http_message`); None if the capture was not read
        connections: The captured connections (`captured_connection`); None if the capture was not read
        instrumentation: The block `instrumentation` of `run.json` (`run_instrumentation`); None if the
            run was not instrumented
        scans: The scans of the apps (`app_scan`) by package: the permissions each requests and the
            tracker libraries it contains; None if the capture was not read or the run exported no scans
        episodes: The records of `episodes.json` (an exploration's or a goal-directed run's), in order
        scope: The run's `run_scope.json`; None if it has none
        traffic: Where the run's traffic is read from if not its final export, and why: {source: 'snapshot',
            folder, why}; None for a run whose final export holds it
    """

    directory: Path
    meta: dict
    events: tuple[dict, ...]
    actions: tuple[dict, ...]
    source_reads: tuple[dict, ...]
    changes: tuple[SettingChange, ...]
    messages: tuple[dict, ...] | None
    connections: tuple[dict, ...] | None
    instrumentation: dict | None
    scans: dict[str, dict] | None = None
    episodes: tuple[dict, ...] = ()
    scope: dict | None = None
    traffic: dict | None = None

    @property
    def run_id(self) -> str:
        return self.meta["run_id"]

    @property
    def package(self) -> str:
        return self.meta["package"]

    @property
    def verification(self) -> dict | None:
        """Loki's verification of the instrumentation record; None if there is none (no session, or it failed)."""
        return (self.instrumentation or {}).get("verification")

    @property
    def verified(self) -> bool:
        """Whether Loki verified the intervention. A run without a verification is not verified."""
        return bool((self.verification or {}).get("verified"))

    @property
    def regime(self) -> str | None:
        """How Loki made the run: 'goal', 'replay', or its crawl regime; None if its record does not say."""
        if self.meta.get("regime"):
            return str(self.meta["regime"])
        return "replay" if self.meta.get("replay_of") else None

    @property
    def goal(self) -> dict | None:
        """A goal-directed run's goal as Loki records it (run_scope.json, else run.json's regime summary): feature, id,
        reached, where, unreachable, attempts, episodes, method; None for another run."""
        return goal_of(self.meta, self.scope)

    @property
    def goal_id(self) -> str | None:
        goal = self.goal or {}
        if goal.get("id"):
            return str(goal["id"])
        started = next((e for e in self.events if e.get("type") == "episode_start" and e.get("kind") == "goal"), None)
        return None if started is None or not started.get("item_id") else str(started["item_id"])

    @property
    def goal_reached(self) -> bool:
        """Whether Loki's agent said it reached the goal: a `goal_reached` event. The statement alone; an oracle
        decides whether the feature was reached."""
        return any(e.get("type") == "goal_reached" for e in self.events)

    @property
    def window(self) -> Window | None:
        """The goal episode of a goal-directed run; None for another run, or one with no goal episode."""
        if self.regime != "goal":
            return None
        return goal_window(self.events)


def goal_of(meta: dict, scope: dict | None) -> dict | None:
    """The goal of a goal-directed run's record: run_scope.json's `goal`, else run.json's `regime_summary.goal`."""
    goal = (scope or {}).get("goal") or ((meta.get("regime_summary") or {}).get("goal"))
    return goal if isinstance(goal, dict) else None


def goal_window(events: tuple[dict, ...] | list[dict]) -> Window | None:
    """
    The goal episode of a goal-directed run's events: the episode of its `goal_reached` event, else the last episode
    of kind goal; from that episode's start to its end, with the screens Loki records as it closes (up to the next
    episode's start, or the run's end). Not up to the agent's statement: the agent states it from its own screenshot,
    and Loki records the screen it saw only when the episode closes (live check of 21 Nov 2026: the statement named
    the search screen, and the forecast was recorded after the episode's end). The goal regime ends the episode at the
    statement, so the window holds nothing the agent did after it.
    """
    reached = next((e for e in events if e.get("type") == "goal_reached"), None)
    goals = [e.get("episode") for e in events if e.get("type") == "episode_start" and e.get("kind") == "goal"]
    episode = reached.get("episode") if reached is not None else (goals[-1] if goals else None)
    if episode is None:
        return None
    taken, first, start = 0, None, 0
    for i, event in enumerate(events):
        kind = event.get("type")
        if first is None and kind == "episode_start" and event.get("episode") == episode:
            first, start = i, taken
        elif first is not None and kind == "episode_start" and event.get("episode") != episode:
            return Window(episode, start, taken, first, i - 1, reached is not None)
        if kind == "action":
            taken += 1
    if first is None:
        return None
    return Window(episode, start, taken, first, len(events), reached is not None)


def load(run_dir: str | Path, capture: bool = True, errored: bool = False) -> Run:
    """
    Reads a Loki run folder.

    Args:
        capture: Whether the run's capture is read. A run without a complete, validated capture
            export is then refused; with False the capture is not looked at.
        errored: Whether a run Loki stopped on an error is read, if its traffic is usable (`capture_source`): its
            final export, else its latest snapshot, which `Run.traffic` then names with the reason. Without it such a
            run is refused ('failed'), as a replay that did not impose its condition must be.

    Raises RunRefused if the folder is not one Skuld can rely on.
    """
    directory = Path(run_dir)
    meta = _json(directory / "run.json")
    if not isinstance(meta, dict) or not (directory / "events.jsonl").is_file():
        raise RunRefused("not_a_run", f"{directory} has no run.json or no events.jsonl")
    if meta.get("schema_version") not in SCHEMA_VERSIONS:
        raise RunRefused(
            "unsupported_version", f"run record version {meta.get('schema_version')}, read: {SCHEMA_VERSIONS}"
        )
    if meta.get("status") != "finished":
        raise RunRefused("unfinished", f"status {meta.get('status')!r}: the run did not end in order")

    events = tuple(_lines(directory / "events.jsonl"))
    ended = next((e for e in reversed(events) if e.get("type") == "run_end"), None)
    traffic = None
    if ended is not None and str(ended.get("stop_reason") or "").startswith("error"):
        # Loki stopped the run on an error (exit 1), e.g. the app was not instrumented: what the run shows is not the
        # condition it was asked to impose (12 Nov 2026: 'no process of <app> started within 30 s' in replays)
        stopped = f"Loki stopped the run: {ended['stop_reason']}"[:300]
        # An exploration that lost its emulator at the end still shows what it explored, with the traffic of its final
        # export or its latest snapshot, which O annotated (22 Nov 2026: com.gamma.scan, AdbError at the run's end, was
        # skipped and its stage-1 contexts had no screens); the caller asks for it (`errored`)
        source = capture_source(directory, meta.get("capture"), events) if errored else None
        if source is None:
            raise RunRefused("failed", stopped + ("; no usable capture" if errored else ""))
        if source["source"] == "snapshot":
            traffic = {**source, "why": f"{stopped}; {source['why']}"[:600]}
    instrumentation = meta.get("instrumentation")
    source_reads = tuple(e for e in events if e.get("type") == "source_read")
    _check_instrumentation(instrumentation, source_reads)

    messages = connections = scans = None
    if capture and traffic is not None:
        messages, connections = _read_snapshot(directory / traffic["folder"])
    elif capture:
        messages, connections, scans = _read_capture(directory, meta.get("capture"))
    episodes = _json(directory / "episodes.json")
    scope = _json(directory / "run_scope.json")

    return Run(
        directory=directory,
        meta=meta,
        events=events,
        actions=tuple(e for e in events if e.get("type") == "action"),
        source_reads=source_reads,
        changes=tuple(_change(e) for e in events if e.get("type") == "setting_change"),
        messages=messages,
        connections=connections,
        instrumentation=instrumentation,
        scans=scans,
        episodes=tuple(e for e in episodes if isinstance(e, dict)) if isinstance(episodes, list) else (),
        scope=scope if isinstance(scope, dict) else None,
        traffic=traffic,
    )


def capture_source(directory: str | Path, block: dict | None, events=()) -> dict | None:
    """
    Where a run's traffic can be read: its final export (`capture.export`) if its messages are there, as {source:
    'export', folder}; else its latest snapshot (the folder `capture.snapshot` names, else that of the latest snapshot
    event, else the last folder below capture-snapshot/) with its messages, as {source: 'snapshot', folder, why}; None
    if there is neither.
    """
    directory, block = Path(directory), block or {}
    messages = CAPTURE_FILES["messages"]
    if block.get("export") and (directory / block["export"] / messages).is_file():
        return {"source": "export", "folder": block["export"]}
    named = [block.get("snapshot")]
    named += [
        e.get("snapshot") for e in reversed(events) if e.get("type") == "capture" and e.get("state") == "snapshot"
    ]
    if (directory / SNAPSHOTS).is_dir():
        named += [f"{SNAPSHOTS}/{p.name}" for p in sorted((directory / SNAPSHOTS).iterdir(), reverse=True)]
    folder = next((f for f in named if f and (directory / f / messages).is_file()), None)
    if folder is None:
        return None
    why = f"no final export ({block.get('error') or 'none recorded'}): the traffic is the capture's latest snapshot"
    return {"source": "snapshot", "folder": folder, "why": why}


def _read_snapshot(folder: Path) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """The captured messages and connections of a snapshot, which Loki does not validate."""
    read = {}
    for name, file in CAPTURE_FILES.items():
        if not (folder / file).is_file():
            raise RunRefused("incomplete_export", f"{folder / file} is missing")
        read[name] = tuple(_lines(folder / file))
    return read["messages"], read["connections"]


def _check_instrumentation(block: dict | None, source_reads: tuple[dict, ...]) -> None:
    if block is None:
        if source_reads:
            raise RunRefused("invalid_record", "source reads without an instrumentation block")
        return
    validated = block.get("validated")
    if validated is not None and not validated.get("conforming"):
        raise RunRefused(
            "invalid_record", f"Loki found its instrumentation record not conforming: {validated.get('detail')}"
        )
    try:
        validate("run_instrumentation", block)
        for event in source_reads:
            validate("source_read", event)
    except jsonschema.ValidationError as e:
        path = "/".join(map(str, e.absolute_path))
        raise RunRefused("invalid_record", f"{path}: {e.message}"[:300]) from e


def _read_capture(
    directory: Path, block: dict | None
) -> tuple[tuple[dict, ...], tuple[dict, ...], dict[str, dict] | None]:
    """The captured messages, connections and scans, once the export is known to be validated and complete."""
    if not block:
        raise RunRefused("no_capture", "the run was not captured")
    validated = block.get("validated")
    if validated is not None and not validated.get("conforming"):
        raise RunRefused(
            "export_not_validated",
            f"Loki found the export not conforming: {block.get('error')} {block.get('detail') or ''}".strip(),
        )
    if not block.get("export"):
        raise RunRefused(
            "capture_failed", f"no export: {block.get('error') or 'none recorded'} {block.get('detail') or ''}".strip()
        )
    if validated is None:
        raise RunRefused("export_not_validated", "Loki did not record a validation of the export")
    export = directory / block["export"]
    records = block.get("records") or {}
    read = {}
    for name, file in CAPTURE_FILES.items():
        path = export / file
        if not path.is_file():
            raise RunRefused("incomplete_export", f"{path} is missing")
        read[name] = tuple(_lines(path))
        if name in records and records[name] != len(read[name]):
            raise RunRefused(
                "incomplete_export", f"{file} has {len(read[name])} records, run.json says {records[name]}"
            )
    scans = None
    if "scans" in records:
        path = export / SCANS_FILE
        if not path.is_file():
            raise RunRefused("incomplete_export", f"{path} is missing")
        lines = _lines(path)
        if len(lines) != records["scans"]:
            raise RunRefused(
                "incomplete_export", f"{SCANS_FILE} has {len(lines)} records, run.json says {records['scans']}"
            )
        try:
            for scan in lines:
                validate("app_scan", scan)
        except jsonschema.ValidationError as e:
            raise RunRefused("invalid_record", f"{SCANS_FILE}: {e.message}"[:300]) from e
        scans = {scan["app"]["package"]: scan for scan in lines}
    return read["messages"], read["connections"], scans


def _change(event: dict) -> SettingChange:
    return SettingChange(
        seq=event["seq"],
        ts=event["ts"],
        device_uptime_s=event.get("device_uptime_s"),
        settings=tuple(event.get("settings") or ()),
        origin=event.get("origin", ""),
        applied=event.get("applied", True),
    )


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _lines(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]
