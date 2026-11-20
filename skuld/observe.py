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
from ratatoskr import claims as claim_views
from ratatoskr.schemas import validate

from skuld import uncertainty
from skuld.configuration import recipient as recipient_of

REPORT = "observation_report.json"


class ObservationError(Exception):
    """A run whose observation report could not be made or does not conform."""


def report_path(root: Path, run_id: str) -> Path:
    return root / "observation" / run_id / REPORT


#: The methods of O that read a datum from content, and so depend on the annotators an analysis was made with
INFERENCE = ("content_inference", "text_classification")


def annotators(report: dict) -> tuple:
    """The annotation components an observation report was made with: its inference methods, model (and reasoning)
    and classifier (by digest); () for a report made without any."""
    components = report.get("report", {}).get("components") or []
    methods = sorted(c["id"] for c in components if c.get("role") == "method" and c.get("id") in INFERENCE)
    if not methods:
        return ()
    model = next(((c["id"], c.get("reasoning")) for c in components if c.get("role") == "model"), None)
    classifier = next((c.get("sha256") for c in components if c.get("role") == "classifier"), None)
    return tuple(methods), model, classifier


def observe(
    root: Path, run_id: str, run_dir: Path, command: list[str], make: bool = True, options: list[str] | None = None
) -> dict:
    """
    The observation report of a run, made with Verðandi where the workspace has none.

    Raises ObservationError if there is none and `make` is False, if Verðandi fails, or if the
    report does not conform to Ratatoskr's schema. `options` go to `verdandi analyse` (the workspace's
    `verdandi_options`: its annotators).
    """
    path = report_path(root, run_id)
    if not path.is_file():
        if not make:
            raise ObservationError(f"{run_id}: no observation report")
        # from the workspace, which a relative path in the command (Verðandi's project) is relative to
        result = subprocess.run(
            [*command, "analyse", str(Path(run_dir).resolve()), "--out", str(path.parent.resolve()), *(options or [])],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=root,
        )
        if result.returncode != 0 or not path.is_file():
            raise ObservationError(f"{run_id}: verdandi analyse failed: {result.stderr.strip()[-300:]}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ObservationError(
            f"{run_id}: the observation report is no JSON ({e}); delete it to analyse again"
        ) from None
    # a report Verðandi made before Ratatoskr 0.34.0 states factor levels, which name no reason: read as low
    report = uncertainty.converted(report)
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
    found = claim_views.of_report(report)  # with what the report states once (status, application, polarity)
    combined = {i for c in found if c.get("combined") for i in c.get("of") or ()}
    return [c for c in found if c["id"] not in combined]


def transmissions_to(report: dict, recipient: str) -> list[dict]:
    """The Transmits claims, of any node, to a recipient (a register entity, or 'domain:<domain>')."""
    return [c for c in claims(report) if c["type"] == "transmits" and recipient_of(c) == recipient]
