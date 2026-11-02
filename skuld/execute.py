"""
The runs of a workspace, made by Loki: a replay of a recorded run per condition, in rotated order.

For each condition Skuld writes Loki's configuration: the base configuration with every source Loki
can hook set to `pass`, except those the condition's alternative changes, and the hosts it blocks.
It calls Loki's command line (`loki -c <configuration> replay <recorded run> -d <device> --force`),
reads the run folder Loki names in its last line of output, and appends the run to `runs.jsonl`.
Skuld runs no adb itself: starting and stopping frida-server is also a command of Loki's. The
inputs must be fixed before the first run, as the runs are judged only by inputs fixed before them.
"""

import json
import subprocess
from pathlib import Path

import yaml

from skuld.experiments import BASELINE
from skuld.inputs import InputError, Workspace, check_frozen, portable
from skuld.verify import SOURCE_NODES

QUALIFICATION = "qualification.json"


class ExecutionError(Exception):
    """A condition no case defines, conditions defined differently by two cases, or a run Loki did not make."""


def interventions(workspace: Workspace) -> dict[str, dict]:
    """The intervention of every condition, as the cases' search spaces define it."""
    found: dict[str, dict] = {}
    for case in workspace.cases:
        for alternative in case.alternatives:
            known = found.setdefault(alternative.condition, alternative.intervention)
            if known != alternative.intervention:
                raise ExecutionError(f"condition {alternative.condition} is imposed differently by two cases")
    return found


def configuration(base: dict, intervention: dict) -> dict:
    """Loki's configuration of a condition: every source hooked, those of the intervention set, its hosts blocked;
    the sinks the base configuration records are recorded in every condition."""
    config = json.loads(json.dumps(base))
    base_sources = (config.get("instrumentation") or {}).get("sources") or {}
    sources = {name: setting for name, setting in base_sources.items() if setting == "record"}
    sources.update({name: "pass" for name in SOURCE_NODES})
    sources.update(intervention.get("sources") or {})
    config.setdefault("instrumentation", {})["sources"] = sources
    config.setdefault("capture", {})["block_hosts"] = list(intervention.get("block_hosts") or ())
    return config


def schedule(conditions: list[str], repeat: int) -> list[str]:
    """The conditions in rotated order: ABC, BCA, CAB, …, so that each comes first, last and between."""
    return [conditions[(i + r) % len(conditions)] for r in range(repeat) for i in range(len(conditions))]


def run(
    workspace: Workspace,
    recorded: Path,
    base: Path,
    device: str,
    conditions: list[str],
    repeat: int,
    loki: list[str],
    cwd: Path | None = None,
    qualify: bool = False,
) -> list[dict]:
    """
    Makes the runs and appends them to runs.jsonl; returns the entries written.

    With `qualify`, one baseline replay comes first; the cases it does not qualify (`qualification`) are recorded in
    `qualification.json`, and the series is made unless it qualifies none. The replay is kept as a baseline run.

    Args:
        recorded: The recorded run whose path the replays follow
        base: Loki's base configuration
        loki: The command that runs Loki, e.g. ["uv", "run", "--project", "../Loki", "loki"]
        cwd: Where Loki is run (its configuration's output folder is relative to it)
    """
    try:
        check_frozen(workspace)
    except InputError as e:
        raise ExecutionError(f"the inputs are not fixed: {e}") from e
    known = interventions(workspace)
    unknown = [c for c in conditions if c != BASELINE and c not in known]
    if unknown:
        raise ExecutionError(f"no case defines the conditions {unknown}")
    base_config = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
    folder = workspace.root / "configs"
    folder.mkdir(exist_ok=True)
    order = max((e.order for e in workspace.runs), default=0)
    written = []
    frida = (base_config.get("instrumentation") or {}).get("backend") == "frida"
    if frida:
        started = subprocess.run(
            [*loki, "frida-server", "-d", device, "start"], capture_output=True, text=True, cwd=cwd
        )
        if started.returncode != 0:
            raise ExecutionError(f"frida-server did not start: {started.stderr.strip()[-300:]}")
    try:
        if qualify:
            written = _series(workspace, [BASELINE], 1, known, base_config, folder, order, recorded, device, loki, cwd)
            order += 1
            problems = qualification(workspace, Path(written[0]["dir"]))
            record = {"run": written[0]["run"], "cases": {c.id: problems.get(c.id, []) for c in workspace.cases}}
            (workspace.root / QUALIFICATION).write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
            )
            if all(problems.get(c.id) for c in workspace.cases):
                raise ExecutionError(
                    "the recording qualified no case: " + "; ".join(f"{c}: {'; '.join(p)}" for c, p in problems.items())
                )
        written += _series(
            workspace, conditions, repeat, known, base_config, folder, order, recorded, device, loki, cwd
        )
    finally:
        if frida:
            subprocess.run([*loki, "frida-server", "-d", device, "stop"], capture_output=True, text=True, cwd=cwd)
    return written


def _series(
    workspace, conditions, repeat, known, base_config, folder, order, recorded, device, loki, cwd
) -> list[dict]:
    written = []
    for condition in schedule(conditions, repeat):
        order += 1
        config_path = folder / f"{order:03d}-{condition}.yaml"
        config = configuration(base_config, {} if condition == BASELINE else known[condition])
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8", newline="\n")
        command = [*loki, "-c", str(config_path.resolve()), "replay", str(recorded.resolve()), "-d", device, "--force"]
        result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
        run_dir = _run_dir(result.stdout, cwd)
        if run_dir is None:
            raise ExecutionError(f"run {order} ({condition}): Loki named no run folder; exit {result.returncode}")
        base = workspace.runs_base or workspace.root
        entry = {"run": run_dir.name, "dir": portable(run_dir, base), "condition": condition, "order": order}
        with (workspace.root / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as runs:
            runs.write(json.dumps(entry) + "\n")
        # runs.jsonl names the folder relative to the runs base; the caller gets a path it can open
        written.append({**entry, "dir": str(run_dir), "exit": result.returncode})
    return written


def qualification(workspace: Workspace, run_dir: Path) -> dict[str, list[str]]:
    """
    What keeps a baseline replay from qualifying its recording for a case, by case (the cases it qualifies have
    none): the replay cannot be read, departs from the path of the case's feature, or an observable oracle of the
    case does not decide `met` for it.
    """
    from skuld.experiments import RunState, departed, runs_of
    from skuld.oracles import decide
    from skuld.runs import RunRefused, load

    try:
        run = load(run_dir)
    except RunRefused as e:
        return {case.id: [f"the replay cannot be read: {e}"] for case in workspace.cases}
    problems: dict[str, list[str]] = {}
    for case in workspace.cases:
        if not runs_of(case, RunState(run.run_id, None, run=run)):
            continue
        if departure := departed(case, run):
            problems.setdefault(case.id, []).append(departure)
            continue
        for purpose in case.purposes:
            if purpose.oracle is not None:
                decision = decide(workspace.oracles[purpose.oracle], run)
                if decision.decision != "met":
                    problems.setdefault(case.id, []).append(
                        f"{purpose.oracle} decides {decision.decision} ({'; '.join(decision.reasons)})"
                    )
    return problems


def _run_dir(stdout: str, cwd: Path | None) -> Path | None:
    lines = [line for line in stdout.splitlines() if line.strip()]
    try:
        named = json.loads(lines[-1]).get("run_dir") if lines else None
    except ValueError:
        return None
    if not named:
        return None
    path = Path(named)
    return (path if path.is_absolute() else (cwd or Path.cwd()) / path).resolve()
