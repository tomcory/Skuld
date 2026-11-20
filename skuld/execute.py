"""
The runs of a workspace, made by Loki: a replay of a recorded run per condition, in rotated order.

For each condition Skuld writes Loki's configuration: the base configuration with every source Loki
can hook set to `pass`, except those the condition's alternative changes, and the hosts it blocks.
It calls Loki's command line (`loki -c <configuration> replay <recorded run> -d <device> --force`),
reads the run folder Loki names in its last line of output, and appends the run to `runs.jsonl`.
For one case (`case`), Loki replays the recording only up to the end of the case's path
(`--until-action`): the runs are runs of that case, and of every case whose path ends no later. For a
case without a path, such as the launch, that is the cold start, with the recording's leading actions
on the system's screens (Android's "Viewing full screen" confirmation, a permission dialog of the
package `android`): the system's dialogs over the app, which no policy answers, are part of starting it.
Skuld runs no adb itself: starting and stopping frida-server is also a command of Loki's. The
inputs must be fixed before the first run, as the runs are judged only by inputs fixed before them.
"""

import copy
import json
import subprocess
from pathlib import Path

import yaml

from skuld import yamlio
from skuld.experiments import BASELINE
from skuld.inputs import InputError, Workspace, check_frozen, portable, write_atomically
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
    config = copy.deepcopy(base)  # not a JSON round trip: YAML values such as a persona's birth date are dates
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
    case: str | None = None,
    keep_going: bool = False,
) -> list[dict]:
    """
    Makes the runs and appends them to runs.jsonl; returns the entries written.

    With `qualify`, one baseline replay comes first; the cases it does not qualify (`qualification`) are recorded in
    `qualification.json`, and the series is made unless it qualifies none. The replay is kept as a baseline run.

    Args:
        recorded: The recorded run whose path the replays follow
        base: Loki's base configuration
        loki: The command that runs Loki, e.g. ["../Loki/.venv/bin/loki"] (cli.component)
        cwd: Where Loki is run (its configuration's output folder is relative to it)
        case: Replay only up to the end of this case's path
        keep_going: Loki goes on with an episode's next actions after one it could not replay (`--keep-going`)
    """
    try:
        check_frozen(workspace)
    except InputError as e:
        raise ExecutionError(f"the inputs are not fixed: {e}") from e
    until = None
    if case is not None:
        chosen = next((c for c in workspace.cases if c.id == case), None)
        if chosen is None:
            raise ExecutionError(f"no case {case}")
        if chosen.feature.path_run not in (None, recorded.name):
            raise ExecutionError(f"case {case} follows the recording {chosen.feature.path_run}, not {recorded.name}")
        until = chosen.feature.actions if chosen.feature.path_run else system_prefix(recorded)
    known = interventions(workspace)
    flags = ["--keep-going"] if keep_going else []
    unknown = [c for c in conditions if c != BASELINE and c not in known]
    if unknown:
        raise ExecutionError(f"no case defines the conditions {unknown}")
    base_config = yamlio.load(base.read_text(encoding="utf-8")) or {}
    folder = workspace.root / "configs"
    folder.mkdir(exist_ok=True)
    order = max((e.order for e in workspace.runs), default=0)
    written = []
    frida = (base_config.get("instrumentation") or {}).get("backend") == "frida"
    if frida:
        started = subprocess.run(
            [*loki, "frida-server", "-d", device, "start"],
            capture_output=True,
            text=True,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
        )
        if started.returncode != 0:
            raise ExecutionError(f"frida-server did not start: {started.stderr.strip()[-300:]}")
    try:
        if qualify:
            written = _series(
                workspace, [BASELINE], 1, known, base_config, folder, order, recorded, device, loki, cwd, until, flags
            )
            order = written[-1]["order"]
            problems, covered = qualification(workspace, Path(written[-1]["dir"]), with_covered=True)
            if covered is None:
                # a replay that cannot be read qualifies none of the cases asked for, and says nothing of the others
                covered = [c.id for c in workspace.cases if case is None or c.id == case]
            _record_qualification(workspace, written[-1]["run"], problems, covered)
            asked = [c for c in covered if case is None or c == case]
            if not asked:
                raise ExecutionError(
                    f"the recording qualified no case: its replay reaches {case or 'no case of the workspace'}"
                    + ("" if case is None else " not")
                )
            if all(problems.get(c) for c in asked):
                raise ExecutionError(
                    "the recording qualified no case: "
                    + "; ".join(f"{c}: {'; '.join(problems.get(c) or ['not replayed'])}" for c in asked)
                )
        written += _series(
            workspace, conditions, repeat, known, base_config, folder, order, recorded, device, loki, cwd, until, flags
        )
    finally:
        if frida:
            subprocess.run(
                [*loki, "frida-server", "-d", device, "stop"],
                capture_output=True,
                text=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
            )
    return written


def system_prefix(recorded: Path) -> int:
    """The number of the recording's leading actions taken on a screen of the system (oracles._system), not the app's."""
    from skuld.oracles import _system

    graph = (
        json.loads((recorded / "graph.json").read_text(encoding="utf-8")) if (recorded / "graph.json").is_file() else {}
    )
    screens = graph.get("screens") or {}
    merged = graph.get("merged_into") or {}
    n = 0
    for line in (
        (recorded / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if (recorded / "events.jsonl").is_file()
        else []
    ):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") != "action":
            continue
        sid = event.get("src")
        while sid in merged:
            sid = merged[sid]
        if not _system(screens.get(sid) or {}):
            break
        n += 1
    return n


def _record_qualification(workspace: Workspace, run: str, problems: dict, covered: list[str]) -> None:
    """qualification.json: per case, what kept the last qualifying replay that covered it from qualifying it, and
    that replay; a replay of a prefix leaves the cases it did not cover as they were."""
    path = workspace.root / QUALIFICATION
    record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"cases": {}}
    record.setdefault("cases", {})
    runs = record.setdefault("runs", {c: record["run"] for c in record["cases"]} if record.get("run") else {})
    for c in covered:
        record["cases"][c] = problems.get(c, [])
        runs[c] = run
    record["run"] = run
    write_atomically(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")


def _series(
    workspace, conditions, repeat, known, base_config, folder, order, recorded, device, loki, cwd, until=None, flags=()
) -> list[dict]:
    written = []
    for condition in schedule(conditions, repeat):
        for attempt in range(1 + RETRIES):
            order += 1
            config_path = folder / f"{order:03d}-{condition}.yaml"
            config = configuration(base_config, {} if condition == BASELINE else known[condition])
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8", newline="\n")
            command = (
                [*loki, "-c", str(config_path.resolve()), "replay", str(recorded.resolve()), "-d", device, "--force"]
                + ([] if until is None else ["--until-action", str(until)])
                + list(flags)
            )
            result = subprocess.run(command, capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL)
            run_dir = _run_dir(result.stdout, cwd)
            if run_dir is None:
                raise ExecutionError(
                    f"run {order} ({condition}): Loki named no run folder; exit {result.returncode}: "
                    + (result.stderr.strip()[-600:] or result.stdout.strip()[-600:])
                )
            base = workspace.runs_base or workspace.root
            entry = {"run": run_dir.name, "dir": portable(run_dir, base), "condition": condition, "order": order}
            if until is not None:
                entry["until_action"] = until
            if "--keep-going" in flags:
                entry["keep_going"] = True
            with (workspace.root / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as runs:
                runs.write(json.dumps(entry) + "\n")
            # runs.jsonl names the folder relative to the runs base; the caller gets a path it can open
            written.append({**entry, "dir": str(run_dir), "exit": result.returncode})
            if not _not_instrumented(result.stdout):
                break
            if attempt < RETRIES:
                written[-1]["retried"] = True  # replaced by the next attempt
    return written


# A replay whose app process Frida did not instrument imposed no condition (Loki stops it: app_not_instrumented); it
# stays in runs.jsonl, the analysis refuses it (runs.load: 'failed'), and the condition is replayed once more. On the
# study's emulators about every second replay failed so, the one after a complete replay (12 Nov 2026).
RETRIES = 1


def _not_instrumented(stdout: str) -> bool:
    lines = [line for line in stdout.splitlines() if line.strip()]
    try:
        stop = json.loads(lines[-1]).get("stop_reason") if lines else None
    except ValueError:
        return False
    return isinstance(stop, str) and stop.startswith("error") and "app_not_instrumented" in stop


def qualification(workspace: Workspace, run_dir: Path, with_covered: bool = False):
    """
    What keeps a baseline replay from qualifying its recording for a case, by case (the cases it qualifies have
    none): the replay cannot be read, departs from the path of the case's feature, or an observable oracle of the
    case does not decide `met` for it. With `with_covered`, also the cases the replay is a run of (None for a
    replay that cannot be read, which is a run of no case it could show).
    """
    from skuld.experiments import RunState, departed, runs_of
    from skuld.oracles import decide
    from skuld.runs import RunRefused, load

    try:
        run = load(run_dir)
    except RunRefused as e:
        unread = {case.id: [f"the replay cannot be read: {e}"] for case in workspace.cases}
        return (unread, None) if with_covered else unread
    problems: dict[str, list[str]] = {}
    covered = []
    for case in workspace.cases:
        if not runs_of(case, RunState(run.run_id, None, run=run)):
            continue
        covered.append(case.id)
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
    return (problems, covered) if with_covered else problems


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
