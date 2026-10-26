"""
The Observation dimension's analysis of a run, a component of E's experimental channel.

Skuld does not read captures for what the application did: it reads Verðandi's observation report of
each run (`verdandi analyse`, called as a command), the same analysis that O's reports are made by.
A run without a report gets one; content inference is not asked for, so the analysis needs no model.
"""

import json
import subprocess
from pathlib import Path

import jsonschema
from ratatoskr.schemas import validate

from skuld.configuration import recipient as recipient_of

REPORT = "observation_report.json"


class ObservationError(Exception):
    """A run whose observation report could not be made or does not conform."""


def report_path(root: Path, run_id: str) -> Path:
    return root / "observation" / run_id / REPORT


def observe(root: Path, run_id: str, run_dir: Path, command: list[str], make: bool = True) -> dict:
    """
    The observation report of a run, made with Verðandi where the workspace has none.

    Raises ObservationError if there is none and `make` is False, if Verðandi fails, or if the
    report does not conform to Ratatoskr's schema.
    """
    path = report_path(root, run_id)
    if not path.is_file():
        if not make:
            raise ObservationError(f"{run_id}: no observation report")
        result = subprocess.run(
            [*command, "analyse", str(run_dir), "--out", str(path.parent)], capture_output=True, text=True
        )
        if result.returncode != 0 or not path.is_file():
            raise ObservationError(f"{run_id}: verdandi analyse failed: {result.stderr.strip()[-300:]}")
    report = json.loads(path.read_text(encoding="utf-8"))
    try:
        validate("observation_report", report)
    except jsonschema.ValidationError as e:
        raise ObservationError(f"{run_id}: the observation report does not conform: {e.message}"[:300]) from e
    return report


def source_reads(report: dict, source: str) -> list[dict]:
    """The evidence items of the reads of one hooked source, with the value the application was handed."""
    return [
        e
        for e in report["evidence"]
        if e["proposition"]["kind"] == "source_read" and e["proposition"].get("source") == source
    ]


def claims(report: dict) -> list[dict]:
    """O's claims of the run, each once: the combined claims and the channels' claims that none of them combines."""
    combined = {i for c in report["claims"] if c.get("combined") for i in c.get("of") or ()}
    return [c for c in report["claims"] if c["id"] not in combined]


def transmissions_to(report: dict, recipient: str) -> list[dict]:
    """The Transmits claims, of any node, to a recipient (a register entity, or 'domain:<domain>')."""
    return [c for c in claims(report) if c["type"] == "transmits" and recipient_of(c) == recipient]
