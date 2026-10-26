"""
A workspace: the cases of one application version, their named inputs and the runs they read.

```text
<workspace>/
  workspace.yaml          application, where the runs are, how Verðandi is called
  cases/<case>.yaml       a case's feature, purposes, components and search space
  oracles/<id>@<v>.yaml   an oracle: success and invalid conditions, measurements
  frozen.json             every input's digest, the time it was fixed, its author and its later changes
  runs.jsonl              the runs: id, folder, condition, position in the sequence
  observation/<run>/      Verðandi's observation report of each run
  report.json, report.md  the expectation report
```

A case file and an oracle file are named inputs. They are fixed by `freeze` before the runs they
judge; a later change is recorded with its reason, never made silently (`check_frozen`).
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

#: The processing dimensions the instance imposes: data, granularity (precision), recipients
DIMENSIONS = ("D", "G", "R")
FROZEN = "frozen.json"


class InputError(Exception):
    """A named input that is malformed, not frozen, or changed without a record."""


@dataclass(frozen=True)
class Feature:
    """
    An entry point, a path of user actions and an observable outcome.

    Attributes:
        path_run: The recorded run whose actions the path is; None for the empty path
        actions: The number of the recorded run's actions up to the path's last one
        start: The number of the recorded run's actions before the path: those that lead to the entry point (0: the
            path starts at a cold start)
        contains: The features whose path begins this one's
    """

    id: str
    name: str
    entry: str
    path_run: str | None
    actions: int
    outcome: str
    contains: tuple[str, ...] = ()
    start: int = 0


@dataclass(frozen=True)
class Purpose:
    """The framework's purpose with its functional requirements and its oracle (None: not observable)."""

    id: str
    parts: dict
    node: str
    fit: str
    provenance: str
    specificity: str
    role: str
    requirements: tuple[dict, ...]
    oracle: str | None


@dataclass(frozen=True)
class Component:
    """A datum (D), a recipient (R) or the value of another dimension for a datum."""

    id: str
    dimension: str
    node: str | None = None
    entity: str | None = None
    value: object = None
    name: str = ""


@dataclass(frozen=True)
class Alternative:
    """
    A configuration of the search space, given by the components it changes; it is compared in its component's
    dimension, the only one it changes.

    Attributes:
        condition: The run condition that imposes it (its id unless stated)
        intervention: The instruments' settings: `sources` (Loki's instrumentation) and `block_hosts`
    """

    id: str
    component: str
    removal: bool
    changes: tuple[dict, ...]
    intervention: dict
    condition: str


@dataclass(frozen=True)
class Measurement:
    name: str
    metric: dict
    better: str
    tolerance: float


@dataclass(frozen=True)
class Oracle:
    """
    A functional oracle as data: the predicates of success and of an invalid run over Loki's records.

    Attributes:
        reach: The requirements whose achievement it decides
    """

    id: str
    version: str
    purpose: str
    reach: tuple[str, ...]
    success: tuple[dict, ...]
    invalid: tuple[dict, ...]
    measurements: tuple[Measurement, ...]
    path: Path

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True)
class Case:
    """A case: a feature, its purposes, the components considered and their search space."""

    id: str
    feature: Feature
    purposes: tuple[Purpose, ...]
    components: tuple[Component, ...]
    alternatives: tuple[Alternative, ...]
    path: Path

    def purpose(self, purpose_id: str) -> Purpose:
        return next(p for p in self.purposes if p.id == purpose_id)

    def component(self, component_id: str) -> Component:
        return next(c for c in self.components if c.id == component_id)


@dataclass(frozen=True)
class RunEntry:
    """
    A run of the workspace: its condition ('baseline' or an alternative's condition) and its position.

    Attributes:
        excluded: Why the assessor excluded the run (an interference from outside the experiment), or None
    """

    id: str
    directory: Path
    condition: str
    order: int
    excluded: str | None = None


@dataclass
class Workspace:
    root: Path
    application: dict
    cases: list[Case]
    oracles: dict[str, Oracle]
    runs: list[RunEntry]
    verdandi: list[str] = field(default_factory=lambda: ["verdandi"])

    def file(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def load(root: str | Path) -> Workspace:
    """Reads a workspace. Raises InputError if an input is malformed."""
    root = Path(root)
    settings = _yaml(root / "workspace.yaml")
    oracles = {}
    for path in sorted((root / "oracles").glob("*.yaml")):
        oracle = _oracle(path)
        oracles[oracle.key] = oracle
    cases = [_case(path) for path in sorted((root / "cases").glob("*.yaml"))]
    for case in cases:
        for purpose in case.purposes:
            if purpose.oracle is not None and purpose.oracle not in oracles:
                raise InputError(f"{case.id}: purpose {purpose.id} names the unknown oracle {purpose.oracle}")
    return Workspace(
        root=root,
        application=settings.get("application") or {},
        cases=cases,
        oracles=oracles,
        runs=_runs(root, settings),
        verdandi=list(settings.get("verdandi") or ["verdandi"]),
    )


def input_files(root: Path) -> list[Path]:
    """The named inputs of a workspace: its case and oracle files."""
    return sorted((root / "cases").glob("*.yaml")) + sorted((root / "oracles").glob("*.yaml"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen(root: Path) -> dict:
    path = root / FROZEN
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"inputs": {}}


def freeze(root: str | Path, author: dict, now: datetime | None = None, authors: dict | None = None) -> list[str]:
    """
    Fixes every input not fixed yet, with its digest, the time and its author (from `authors` by the input's name
    where it names one).

    Returns the inputs fixed. Raises InputError for an input whose digest differs from the one
    recorded: such a change is recorded with `change`, never by freezing again.
    """
    root = Path(root)
    record = frozen(root)
    changed = [p for p in input_files(root) if (e := record["inputs"].get(_name(root, p))) and _current(e) != digest(p)]
    if changed:
        raise InputError(
            "changed after they were fixed (record the change with its reason): "
            + ", ".join(_name(root, p) for p in changed)
        )
    when = _time(now)
    added = []
    for path in input_files(root):
        name = _name(root, path)
        if name not in record["inputs"]:
            who = (authors or {}).get(name, author)
            record["inputs"][name] = {"sha256": digest(path), "fixed": when, "author": who, "changes": []}
            added.append(name)
    _write(root, record)
    return added


def change(root: str | Path, name: str, reason: str, now: datetime | None = None) -> None:
    """Records a change of a fixed input with its reason. The time from which it was fixed stays."""
    root = Path(root)
    record = frozen(root)
    entry = record["inputs"].get(name)
    if entry is None:
        raise InputError(f"{name} was never fixed")
    current = digest(root / name)
    if current == _current(entry):
        raise InputError(f"{name} has not changed")
    entry["changes"].append({"time": _time(now), "sha256": current, "reason": reason})
    _write(root, record)


def check_frozen(workspace: Workspace) -> dict[str, dict]:
    """
    The frozen record of every input, checked: each is fixed, and its digest is the one last recorded.

    Raises InputError otherwise.
    """
    record = frozen(workspace.root)["inputs"]
    problems = []
    for path in input_files(workspace.root):
        name = _name(workspace.root, path)
        if name not in record:
            problems.append(f"{name} is not fixed")
        elif _current(record[name]) != digest(path):
            problems.append(f"{name} changed without a record")
    if problems:
        raise InputError("; ".join(problems))
    return {name: record[name] for name in (_name(workspace.root, p) for p in input_files(workspace.root))}


def _current(entry: dict) -> str:
    return entry["changes"][-1]["sha256"] if entry["changes"] else entry["sha256"]


def _name(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _time(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def _write(root: Path, record: dict) -> None:
    (root / FROZEN).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise InputError(f"{path}: {e}") from e
    if not isinstance(data, dict):
        raise InputError(f"{path}: not a mapping")
    return data


def _require(data: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise InputError(f"{where}: missing {', '.join(missing)}")


def _case(path: Path) -> Case:
    data = _yaml(path)
    _require(data, ("id", "feature", "purposes", "components", "search_space"), str(path))
    f = data["feature"]
    _require(f, ("id", "entry", "path", "outcome"), f"{path}: feature")
    route = f["path"] or {}
    feature = Feature(
        id=f["id"],
        name=f.get("name", f["id"]),
        entry=f["entry"],
        path_run=route.get("run"),
        actions=int(route.get("actions", 0)),
        outcome=f["outcome"],
        contains=tuple(f.get("contains") or ()),
        start=int(route.get("from", 0)),
    )
    if not 0 <= feature.start <= feature.actions:
        raise InputError(f"{path}: the path starts after its last action")
    purposes = []
    for p in data["purposes"]:
        _require(p, ("id", "node", "provenance", "specificity", "role"), f"{path}: purpose")
        purposes.append(
            Purpose(
                id=p["id"],
                parts={k: p.get(k, "?") for k in ("action", "object", "beneficiary", "context", "outcome")},
                node=p["node"],
                fit=p.get("fit", "?"),
                provenance=p["provenance"],
                specificity=p["specificity"],
                role=p["role"],
                requirements=tuple(p.get("requirements") or ()),
                oracle=p.get("oracle"),
            )
        )
    components = []
    for c in data["components"]:
        _require(c, ("id", "dimension"), f"{path}: component")
        if c["dimension"] not in DIMENSIONS:
            raise InputError(f"{path}: component {c['id']}: the dimension {c['dimension']} is not one Skuld imposes")
        components.append(
            Component(c["id"], c["dimension"], c.get("node"), c.get("entity"), c.get("value"), c.get("name", ""))
        )
    space = data["search_space"] or {}
    known = {c.id for c in components}
    alternatives = []
    for a in space.get("alternatives") or ():
        where = f"{path}: alternative {a.get('id')}"
        _require(a, ("id", "component", "changes", "intervention"), where)
        if a["component"] not in known or any(ch["component"] not in known for ch in a["changes"]):
            raise InputError(f"{where}: names a component the case does not list")
        alternatives.append(
            Alternative(
                id=a["id"],
                component=a["component"],
                removal=bool(a.get("removal", False)),
                changes=tuple(a["changes"]),
                intervention=a["intervention"] or {},
                condition=a.get("condition", a["id"]),
            )
        )
    return Case(
        id=data["id"],
        feature=feature,
        purposes=tuple(purposes),
        components=tuple(components),
        alternatives=tuple(alternatives),
        path=path,
    )


def _oracle(path: Path) -> Oracle:
    data = _yaml(path)
    _require(data, ("id", "version", "purpose", "reach", "success"), str(path))
    measurements = []
    for m in data.get("measurements") or ():
        _require(m, ("name", "metric", "better", "tolerance"), f"{path}: measurement")
        if m["better"] not in ("higher", "lower"):
            raise InputError(f"{path}: measurement {m['name']}: better is 'higher' or 'lower'")
        measurements.append(Measurement(m["name"], m["metric"], m["better"], float(m["tolerance"])))
    return Oracle(
        id=data["id"],
        version=str(data["version"]),
        purpose=data["purpose"],
        reach=tuple(data["reach"]),
        success=tuple(data["success"]),
        invalid=tuple(data.get("invalid") or ()),
        measurements=tuple(measurements),
        path=path,
    )


def _runs(root: Path, settings: dict) -> list[RunEntry]:
    path = root / "runs.jsonl"
    if not path.is_file():
        return []
    base = Path(settings.get("runs") or root)
    base = base if base.is_absolute() else root / base
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            directory = Path(e["dir"])
            entries.append(
                RunEntry(
                    e["run"],
                    directory if directory.is_absolute() else base / directory,
                    e["condition"],
                    e["order"],
                    e.get("excluded"),
                )
            )
    return entries


# -- the assessment workspace -------------------------------------------------------------------------------------

ASSESSMENT = "assessment.yaml"
#: The records of the exploration the expectation stage's context procedure reads: Loki's record, its events (the
#: screens' texts) and its screen graph
EXPLORATION = ("run.json", "events.jsonl", "graph.json")


def exploration_digest(folder: Path) -> str:
    """The digest of an exploration: of the records the context procedure reads, each by name and digest."""
    h = hashlib.sha256()
    for name in EXPLORATION:
        if (folder / name).is_file():
            h.update(f"{name} {digest(folder / name)}\n".encode())
    return h.hexdigest()


@dataclass(frozen=True)
class ReportRef:
    """A report an assessment reads, by path and digest."""

    path: Path
    sha256: str
    run: str | None = None  # for an O report: the run it is of

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))


@dataclass
class Assessment:
    """
    An assessment workspace: one application version, the O reports of its observations, D's report (or none), the
    exploration whose screens the expectation stage reads (or none), the frame and the corpus by digest, the models;
    and, where the folder is also a case workspace, its cases as the experimental channel's.
    """

    root: Path
    package: str
    version: str
    observations: list[ReportRef]
    declaration: ReportRef | None
    exploration: Path | None
    frame: object  # ratatoskr.frames.Frame
    corpus: Path
    corpus_sha256: str
    models: dict[str, str]
    cases: Workspace | None = None


def _ref(root: Path, entry: dict, where: str, check: bool) -> ReportRef:
    _require(entry, ("path", "sha256"), where)
    path = (root / entry["path"]).resolve()
    if not path.is_file():
        raise InputError(f"{where}: {path} does not exist")
    if check and digest(path) != entry["sha256"]:
        raise InputError(f"{where}: {path} has changed since the assessment named it (sha256)")
    return ReportRef(path, entry["sha256"], entry.get("run"))


def load_assessment(root: str | Path, check: bool = True) -> Assessment:
    """
    Loads an assessment workspace (`assessment.yaml`), checking that every report, the exploration's records
    (`EXPLORATION`), the frame and the corpus are those it names by digest (unless `check` is False).
    """
    from ratatoskr.frames import Frame

    from skuld import config
    from skuld.corpus import load as load_corpus

    root = Path(root)
    data = _yaml(root / ASSESSMENT)
    _require(data, ("application", "observation", "declaration", "frame", "corpus"), ASSESSMENT)
    _require(data["application"], ("package", "version"), f"{ASSESSMENT}: application")
    observations = [_ref(root, e, f"{ASSESSMENT}: observation", check) for e in data["observation"]]
    if not observations:
        raise InputError(f"{ASSESSMENT}: an assessment reads at least one O report")
    declaration = _ref(root, data["declaration"], f"{ASSESSMENT}: declaration", check) if data["declaration"] else None

    exploration = None
    if data.get("exploration"):
        e = data["exploration"]
        _require(e, ("run", "sha256"), f"{ASSESSMENT}: exploration")
        exploration = (root / e["run"]).resolve()
        record = exploration / "run.json"
        if not record.is_file():
            raise InputError(f"{ASSESSMENT}: exploration {exploration} has no run.json")
        if check and exploration_digest(exploration) != e["sha256"]:
            raise InputError(f"{ASSESSMENT}: the exploration's records have changed since the assessment named them")

    f = data["frame"]
    _require(f, ("id", "version", "sha256"), f"{ASSESSMENT}: frame")
    frame = Frame.load(f["id"])
    if check and (frame.version, frame.digest()) != (f["version"], f["sha256"]):
        raise InputError(f"{ASSESSMENT}: frame {f['id']} is {frame.version} ({frame.digest()[:12]}), not as named")

    c = data["corpus"]
    _require(c, ("path", "sha256"), f"{ASSESSMENT}: corpus")
    corpus = (root / c["path"]).resolve()
    corpus_sha256 = load_corpus(corpus).sha256
    if check and corpus_sha256 != c["sha256"]:
        raise InputError(f"{ASSESSMENT}: the corpus has changed since the assessment named it (sha256)")

    models = {"expectation": config.model(), "assessment": config.model(), **(data.get("models") or {})}
    cases = load(root) if (root / "workspace.yaml").is_file() else None
    application = data["application"]
    return Assessment(
        root,
        application["package"],
        str(application["version"]),
        observations,
        declaration,
        exploration,
        frame,
        corpus,
        corpus_sha256,
        models,
        cases,
    )


def describe_assessment(
    root: str | Path,
    package: str,
    version: str,
    observations: list[tuple[Path, str | None]],
    declaration: Path | None,
    exploration: Path | None,
    corpus: Path,
    frame: str = "gdpr-art5",
    comment: str | None = None,
) -> Path:
    """
    Writes `assessment.yaml` (`skuld describe`): every report, the exploration's records, the frame and the corpus
    named by their current digests, with paths relative to the workspace. `observations` are (report path, run id)
    pairs.
    """
    import os

    from ratatoskr.frames import Frame

    from skuld.corpus import load as load_corpus

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    def rel(path: Path) -> str:
        return os.path.relpath(Path(path).resolve(), root.resolve())

    loaded = Frame.load(frame)
    data = {
        "application": {"package": package, "version": version},
        "observation": [
            {"path": rel(p), "sha256": digest(Path(p)), **({"run": run} if run else {})} for p, run in observations
        ],
        "declaration": {"path": rel(declaration), "sha256": digest(Path(declaration))} if declaration else None,
        "exploration": (
            {"run": rel(exploration), "sha256": exploration_digest(Path(exploration))} if exploration else None
        ),
        "frame": loaded.reference(),
        "corpus": {"path": rel(corpus), "sha256": load_corpus(corpus).sha256},
    }
    text = (f"# {comment}\n" if comment else "") + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path = root / ASSESSMENT
    path.write_text(text, encoding="utf-8")
    return path
