"""
The runs of a workspace, made by Loki: a replay of a recorded run per condition, in rotated order.

For each condition Skuld writes Loki's configuration: the base configuration with every source Loki
can hook set to `pass`, except those the condition's alternative changes, and the hosts it blocks.
It calls Loki's command line (`loki -c <configuration> replay <recorded run> -d <device> --force`),
reads the run folder Loki names in its last line of output, and appends the run to `runs.jsonl`.
For one experimental case (`case`), Loki replays the recording only up to the end of the case's path (`--until-action`):
the runs are runs of that case, and of every experimental case whose path ends no later. For an experimental case
without a path, such as the launch, that is the cold start, with the recording's leading actions on the system's screens
(Android's "Viewing full screen" confirmation, a permission dialog of the package `android`): the system's dialogs over
the app, which no policy answers, are part of starting it. Starting and stopping frida-server is also a command of
Loki's. The inputs must be fixed before the first run, as the runs are judged only by inputs fixed before them.

Before a series, Skuld reads the version of the application installed on the device (`installed_version`, the one
adb call it makes itself: `dumpsys package`, as Loki reads it into a run's record) and compares it with the
recording's and the workspace's (20 Nov 2026; before, runs of another version were made and only the analysis
excluded them, `experiments`). A version that differs stops the series, unless the author states the pair compatible
(`compatible_versions` of `assessment.yaml`, `skuld compat add`): the series is then made, and each of its entries in
`runs.jsonl` carries the drift (`version_drift`). A replay whose record names another version than the one checked
(the application updated during the series) stops the series after it.
"""

import copy
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml

from skuld import yamlio
from skuld.experiments import BASELINE, _compatible
from skuld.inputs import InputError, Workspace, check_frozen, portable, write_atomically
from skuld.verify import SOURCE_NODES

QUALIFICATION = "qualification.json"


class ExecutionError(Exception):
    """
    A condition no experimental case defines, conditions defined differently by two experimental cases, or a run Loki
    did not make.
    """


def interventions(workspace: Workspace) -> dict[str, dict]:
    """The intervention of every condition, as the experimental cases' search spaces define it."""
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


def installed_version(device: str, package: str) -> str | None:
    """
    The version name of the package installed on the device, as `adb shell dumpsys package` gives it (Loki records
    a run's `app.version_name` so); None if the package is not installed. Raises ExecutionError if adb cannot be run.
    """
    try:
        result = subprocess.run(
            ["adb", "-s", device, "shell", "dumpsys", "package", package],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ExecutionError(f"the installed version of {package} cannot be read on {device}: {e}") from e
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip())[-300:]
        raise ExecutionError(f"the installed version of {package} cannot be read on {device}: {detail}")
    found = re.search(r"versionName=(\S+)", result.stdout)
    return found.group(1) if found else None


def recorded_version(recorded: Path) -> str | None:
    """The version of the application a recording was made of, as Loki's record names it (`app.version_name`)."""
    path = recorded / "run.json"
    if not path.is_file():
        return None
    try:
        name = (json.loads(path.read_text(encoding="utf-8")).get("app") or {}).get("version_name")
    except ValueError:
        return None
    return None if name is None else str(name)


def version_drift(workspace: Workspace, recorded: Path, installed: str | None) -> dict | None:
    """
    The version drift of a series: None if the installed version is the recording's and the workspace's; else a
    record of it (installed, recorded and workspace versions, and the statements that make it compatible) if the
    author states the installed version compatible with each of the others (`compatible_versions`). Raises
    ExecutionError otherwise, and if the package is not installed: the analysis would exclude every run.
    """
    package = str(workspace.application.get("package", "?"))
    ours = str(workspace.application.get("version", "?"))
    recording = recorded_version(recorded) or ours
    if installed is None:
        raise ExecutionError(f"{package} is not installed on the device")
    others = sorted({recording, ours} - {installed})
    if not others:
        return None
    stated = _compatible(workspace.root, installed)
    unstated = [v for v in others if v not in stated]
    if unstated:
        raise ExecutionError(
            f"the device has {package} {installed} installed, the recording is of {recording} and the workspace of "
            f"{ours}: install {recording}, or state {installed} compatible with {', '.join(unstated)} "
            f"(skuld compat add); the analysis excludes runs of another version"
        )
    statements = [{k: v for k, v in stated[v].items() if k in ("versions", "reason", "fixed")} for v in others]
    return {"installed": installed, "recorded": recording, "workspace": ours, "stated": statements}


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
    installed: Callable[[str, str], str | None] | None = None,
) -> list[dict]:
    """
    Makes the runs and appends them to runs.jsonl; returns the entries written.

    With `qualify`, one baseline replay comes first; the experimental cases it does not qualify (`qualification`) are
    recorded in `qualification.json`, and the series is made unless it qualifies none. The replay is kept as a baseline
    run.

    Args:
        recorded: The recorded run whose path the replays follow
        base: Loki's base configuration
        loki: The command that runs Loki, e.g. ["../Loki/.venv/bin/loki"] (cli.component)
        cwd: Where Loki is run (its configuration's output folder is relative to it)
        case: Replay only up to the end of this case's path
        keep_going: Loki goes on with an episode's next actions after one it could not replay (`--keep-going`)
        installed: Reads the installed version, (device, package) -> version name or None; `installed_version` if
            None (a test passes its own)

    Raises:
        ExecutionError: Also before the first run, for a version on the device that is neither the recording's nor
            the workspace's and not stated compatible with them (`version_drift`)
    """
    try:
        check_frozen(workspace)
    except InputError as e:
        raise ExecutionError(f"the inputs are not fixed: {e}") from e
    on_device = (installed or installed_version)(device, str(workspace.application.get("package", "")))
    drift = version_drift(workspace, recorded, on_device)
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
                workspace,
                [BASELINE],
                1,
                known,
                base_config,
                folder,
                order,
                recorded,
                device,
                loki,
                cwd,
                until,
                flags,
                on_device,
                drift,
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
            workspace,
            conditions,
            repeat,
            known,
            base_config,
            folder,
            order,
            recorded,
            device,
            loki,
            cwd,
            until,
            flags,
            on_device,
            drift,
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
    """qualification.json: per experimental case, what kept the last qualifying replay that covered it from qualifying
    it, and that replay; a replay of a prefix leaves the cases it did not cover as they were."""
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
    workspace,
    conditions,
    repeat,
    known,
    base_config,
    folder,
    order,
    recorded,
    device,
    loki,
    cwd,
    until=None,
    flags=(),
    version=None,
    drift=None,
) -> list[dict]:
    """The runs of the conditions; stops after a run whose record names another version than `version`, the one
    checked before the series."""
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
            if drift:
                entry["version_drift"] = drift
            with (workspace.root / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as runs:
                runs.write(json.dumps(entry) + "\n")
            # runs.jsonl names the folder relative to the runs base; the caller gets a path it can open
            written.append({**entry, "dir": str(run_dir), "exit": result.returncode})
            ran = recorded_version(run_dir)
            if version is not None and ran is not None and ran != version:
                raise ExecutionError(
                    f"run {order} ({condition}) is of version {ran}, not {version} as installed before the series: "
                    "the application changed during the series, which is stopped"
                )
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
    What keeps a baseline replay from qualifying its recording for an experimental case, by case (the cases it
    qualifies have none): the replay cannot be read, departs from the path of the case's feature, or an observable
    oracle of the case does not decide `met` for it. With `with_covered`, also the cases the replay is a run of (None
    for a replay that cannot be read, which is a run of no case it could show).
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
