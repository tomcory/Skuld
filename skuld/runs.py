"""
A Loki run folder, as Skuld reads it: Skuld's only window on a device.

Loki drives the app, controls the capture and instruments the app; what it did and saw is in the run
folder it writes: `run.json` (the run's record, with the blocks `capture` and `instrumentation`),
`events.jsonl` (everything that happened, in order) and the capture's export below `capture/`.
`load` reads such a folder and refuses one that Skuld cannot rely on: a run that did not end in
order, a capture export that Loki did not validate or that is not complete, and an instrumentation
record that does not conform to Ratatoskr's schemas, which Skuld checks again itself.

Whether an intervention held is not decided here. `Run.verification` is Loki's answer to "was the
app handed what the settings say"; Skuld's own verifier adds the traffic and the device state.
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


class RunRefused(Exception):
    """
    A run folder that Skuld does not use.

    Attributes:
        reason: A short identifier: 'not_a_run', 'unsupported_version', 'unfinished', 'no_capture',
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


def load(run_dir: str | Path, capture: bool = True) -> Run:
    """
    Reads a Loki run folder.

    Args:
        capture: Whether the run's capture is read. A run without a complete, validated capture
            export is then refused; with False the capture is not looked at.

    Raises RunRefused if the folder is not one Skuld can rely on.
    """
    directory = Path(run_dir)
    meta = _json(directory / "run.json")
    if not isinstance(meta, dict) or not (directory / "events.jsonl").is_file():
        raise RunRefused("not_a_run", f"{directory} has no run.json and events.jsonl")
    if meta.get("schema_version") not in SCHEMA_VERSIONS:
        raise RunRefused(
            "unsupported_version", f"run record version {meta.get('schema_version')}, read: {SCHEMA_VERSIONS}"
        )
    if meta.get("status") != "finished":
        raise RunRefused("unfinished", f"status {meta.get('status')!r}: the run did not end in order")

    events = tuple(_lines(directory / "events.jsonl"))
    instrumentation = meta.get("instrumentation")
    source_reads = tuple(e for e in events if e.get("type") == "source_read")
    _check_instrumentation(instrumentation, source_reads)

    messages = connections = None
    if capture:
        messages, connections = _read_capture(directory, meta.get("capture"))

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
    )


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


def _read_capture(directory: Path, block: dict | None) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """The captured messages and connections, once the export is known to be validated and complete."""
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
    return read["messages"], read["connections"]


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
