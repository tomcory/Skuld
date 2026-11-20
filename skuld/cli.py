"""
skuld [--profile <name>] <command> …: every command with a named configuration over config.json (profiles/).
skuld config [--profiles]: the configuration in force (file, profile, digest, content), or the profiles.
skuld propose <exploration> --pilot …: generate and fix a workspace's inputs from Loki's exploration and the catalogue.
skuld corpus check | coverage <reports…>: the corpus's passages checked; the components no passage covers.
skuld catalogue: the catalogue's families.
skuld freeze <workspace>: fix the named inputs before the runs they judge.
skuld change <workspace> <input> --reason …: record a change of a fixed input.
skuld run <workspace> --recorded … --config … --device …: the runs, made by Loki in rotated order.
skuld analyse <workspace>: the expectation report.
skuld check <workspace>: the provenance of the reports (every digest verifies, every pointer resolves); an assessment
    is rebuilt with the reading and notice definition it names and compared.
skuld expect <workspace>: the expectation stage's samples (contexts without D, and the model's answers).
skuld judge <workspace>: the assessment stage's reasoning tier: specificity, compatibility and minimisation samples.
skuld describe <workspace> --package … --version … --observation …: write the assessment workspace's assessment.yaml.
skuld compat add <workspace> --o … --d … --reason … --author …: state that D of one version speaks for O's.
skuld assess <workspace>: the assessment of the version from what is kept (subjects, both stages), no model asked.
skuld aggregate <workspace>: the assessment's concerns compressed into aggregate.json and aggregate.md.
skuld review draw | score | agree | expect-draw | expect-score | expect-agree | export | import | exclude …: the review
    of aggregated concerns and of stage-1 predictions by two reviewers.
skuld select <workspace>: the choice of experiments from the assessment, each choice and refusal with its reason.
skuld calibrate draw <folder> <workspaces…> | score <folder> | check <folder> <workspaces…> | agree <folder> <reviews> <reviews>:
    E's calibration (EV-E9); workspaces of one application by several model families are drawn across families.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from ratatoskr.errors import ConfigError

from skuld import catalogue, config, corpus, execute, inputs, manifest, propose, select
from skuld.ask import AskError
from skuld.context import ContextError
from skuld.expectation import IndependenceError
from skuld.experiments import AnalysisError, analyse
from skuld.observe import ObservationError
from skuld.report import write

#: Skuld's corpus of documentation
CORPUS = Path(__file__).resolve().parents[1] / "corpus"
#: Skuld's catalogue of feature families
CATALOGUE = Path(__file__).resolve().parents[1] / "catalogue"
#: Asgard's folder, which holds the components and the pilots' data
ASGARD = Path(__file__).resolve().parents[2]
#: Loki's folder, next to Skuld's
LOKI = ASGARD / "Loki"


def component(name: str, folder: Path, relative_to: Path | None = None) -> list[str]:
    """
    The command that runs another component: config.json's `components.<name>` (an argument list) if given, else the
    executable in the component's own venv (`<folder>/.venv/bin/<name>`). Not `uv run --project`, which needs uv on
    the PATH and may re-sync that venv on every call (plan/archive/POST_PAPER_FIXES 3). `relative_to`: the path written relative to
    that folder, as a command run from a workspace is recorded.
    """
    given = (config.load().get("components") or {}).get(name)
    if given:
        return [str(a) for a in given]
    executable = Path(folder) / ".venv" / "bin" / name
    if not executable.is_file():
        raise execute.ExecutionError(
            f"{name} is not installed at {executable}: run `uv sync --all-extras` in {folder}, or give its command as "
            f"config.json's components.{name}"
        )
    return [inputs.portable(executable, relative_to) if relative_to else str(executable)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skuld", description="The Expectation dimension's analysis.")
    parser.add_argument(
        "--profile", help="a named configuration over config.json (profiles/<name>.json; or SKULD_PROFILE)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    config_ = commands.add_parser("config", help="the configuration in force: its file, profile, digest and content")
    config_.add_argument("--profiles", action="store_true", help="list the profiles instead")

    propose_ = commands.add_parser("propose", help="generate and fix a workspace's inputs from Loki's exploration")
    propose_.add_argument("exploration", help="Loki's exploration run (pseudo-saturation regime)")
    where = propose_.add_mutually_exclusive_group(required=True)
    where.add_argument("--pilot", help="the pilot: the workspace is pilots/<pilot>/skuld/<package>@<version>")
    where.add_argument("--workspace", help="the workspace's folder")
    propose_.add_argument("--catalogue", default=str(CATALOGUE), help="the catalogue folder (default: Skuld's)")
    propose_.add_argument("--model", default=None, help="(default: the configuration's)")
    propose_.add_argument(
        "--api", default=None, help="API that serves the model (default: the configuration's client.api)"
    )
    propose_.add_argument("--offline", action="store_true", help="only the answers kept")
    propose_.add_argument("--selection", type=Path, help="cases only for the practices this selection chose")
    propose_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")

    corpus_ = commands.add_parser(
        "corpus", help="check the corpus, or list what O's reports name that it does not cover"
    )
    corpus_.add_argument(
        "action",
        choices=["check", "coverage"],
        help="check: the passages; coverage <O reports…>: what no passage is about",
    )
    corpus_.add_argument("reports", nargs="*", help="for coverage: observation reports, or folders searched for them")
    corpus_.add_argument("--corpus", default=str(CORPUS), help="the corpus folder (default: Skuld's)")

    families = commands.add_parser("catalogue", help="list the catalogue's families and check them")
    families.add_argument("--catalogue", default=str(CATALOGUE), help="the catalogue folder (default: Skuld's)")

    freeze = commands.add_parser("freeze", help="fix every input not fixed yet, with its digest and author")
    freeze.add_argument("workspace")
    freeze.add_argument("--author", required=True, help="who wrote the inputs")
    freeze.add_argument("--model", action="store_true", help="the author is a model (its prompt in --prompt)")
    freeze.add_argument("--prompt", help="the model's prompt, for an author that is a model")

    change = commands.add_parser("change", help="record a change of a fixed input with its reason")
    change.add_argument("workspace")
    change.add_argument("input", help="the input's path in the workspace, e.g. cases/launch.yaml")
    change.add_argument("--reason", required=True, help="why the fixed input changed")

    run = commands.add_parser("run", help="make the runs of the conditions through Loki, in rotated order")
    run.add_argument("workspace")
    run.add_argument("--recorded", required=True, help="the recorded run the replays follow")
    run.add_argument("--config", required=True, help="Loki's base configuration")
    run.add_argument("--device", required=True, help="adb serial")
    run.add_argument(
        "--conditions",
        nargs="+",
        default=["all"],
        help="'baseline' and the alternatives' conditions; 'all' (the default): baseline and every alternative of the "
        "workspace's fixed cases",
    )
    run.add_argument("--json", action="store_true", help="one JSON line per run (order, condition, exit, folder)")
    run.add_argument("--repeat", type=_positive, default=3, help="runs per condition (default: 3)")
    run.add_argument("--loki", default=str(LOKI), help="Loki's folder (default: the sibling Loki)")
    run.add_argument(
        "--qualify", action="store_true", help="first one baseline replay; record the cases it does not qualify"
    )
    run.add_argument(
        "--case",
        help="replay only up to the end of this case's path (the cold start for the launch); 'all' conditions are "
        "then this case's",
    )
    run.add_argument(
        "--keep-going",
        action="store_true",
        help="Loki goes on with an episode's next actions after one it could not replay, instead of skipping them",
    )

    expect_ = commands.add_parser(
        "expect", help="ask the model the expectation stage's questions, per episode and seed"
    )
    expect_.add_argument("workspace", type=Path)
    expect_.add_argument("--model", default=None, help="(default: the assessment's, else config.json's)")
    expect_.add_argument(
        "--api", default=None, help="API that serves the model (default: the configuration's client.api)"
    )
    expect_.add_argument("--seeds", type=int, nargs="+", default=None, help="(default: config.json's, 1 2 3)")
    expect_.add_argument("--offline", action="store_true", help="only the samples kept")
    expect_.add_argument("--corpus", type=Path, default=None, help="(default: the corpus assessment.yaml names)")
    expect_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    judge_ = commands.add_parser(
        "judge", help="ask the model the reasoning tier's questions (specificity, compatibility, minimisation)"
    )
    judge_.add_argument("workspace", type=Path)
    judge_.add_argument("--model", default=None, help="(default: the assessment's, else config.json's)")
    judge_.add_argument(
        "--api", default=None, help="API that serves the model (default: the configuration's client.api)"
    )
    judge_.add_argument("--seeds", type=int, nargs="+", default=None, help="(default: config.json's, 1 2 3)")
    judge_.add_argument(
        "--question",
        choices=["specificity", "compatibility", "minimisation"],
        nargs="+",
        help="only these questions (default: all; compatibility reads the kept specificity samples)",
    )
    judge_.add_argument("--offline", action="store_true", help="only the samples kept")
    judge_.add_argument("--corpus", type=Path, default=None, help="(default: the corpus assessment.yaml names)")
    judge_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    describe = commands.add_parser("describe", help="write an assessment workspace's assessment.yaml, by digest")
    describe.add_argument("workspace", type=Path)
    describe.add_argument("--package", required=True, help="the application's package name")
    describe.add_argument("--version", required=True, help="the application version assessed")
    describe.add_argument(
        "--observation", nargs="+", required=True, help="O's reports, each PATH or PATH=RUN (default run: its folder)"
    )
    describe.add_argument("--declaration", type=Path, help="D's report (none: an assessment without D)")
    describe.add_argument("--exploration", type=Path, help="Loki's exploration run, whose screens stage 1 reads")
    describe.add_argument("--corpus", type=Path, default=CORPUS, help="the corpus, fixed by digest (default: Skuld's)")
    describe.add_argument("--comment", help="a first line saying what the assessment is")
    describe.add_argument("--frame", default="gdpr-art5", help="a bundled frame's id, or a frame file")
    describe.add_argument("--frame-version", help="an earlier version of the bundled frame (default: its current one)")
    describe.add_argument("--model", help="the model of both stages, written as models: (default: kept, else config's)")
    compat_ = commands.add_parser("compat", help="state that D of one version speaks for O of another")
    compat_sub = compat_.add_subparsers(dest="compat_command", required=True)
    compat_add = compat_sub.add_parser("add", help="add a compatibility statement to assessment.yaml")
    compat_add.add_argument("workspace", type=Path)
    compat_add.add_argument("--o", dest="o_version", required=True, help="the version O observed")
    compat_add.add_argument("--d", dest="d_version", required=True, help="the version D's collection is of")
    compat_add.add_argument("--reason", required=True, help="why D of that version speaks for O's")
    compat_add.add_argument("--author", required=True, help="who states it (a person's id)")
    assess_ = commands.add_parser("assess", help="assess an application version from its assessment workspace")
    assess_.add_argument("workspace", type=Path)
    assess_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    aggregate_ = commands.add_parser(
        "aggregate",
        help="group an assessment's concerns into aggregated concerns a reader can work through (after assess)",
    )
    aggregate_.add_argument("workspace", type=Path)
    review_ = commands.add_parser(
        "review",
        help="the reviewers' non-blind verification of aggregated concerns (draw, score, agree) and of the "
        "expectation stage's predictions (expect-draw, expect-score, expect-agree)",
    )
    review_.add_argument(
        "action",
        choices=[
            "draw",
            "score",
            "agree",
            "expect-draw",
            "expect-score",
            "expect-agree",
            "export",
            "import",
            "exclude",
        ],
        help="export: <package.zip> <drawn sample folders…> --reviewer <id>; import: <returned.zip> <reviews folder>; "
        "exclude: <drawn sample> <new folder> <the withdrawn workspaces…> --application <package> --reason <text>",
    )
    review_.add_argument("folder", type=Path, help="the review's folder (draw: a new one)")
    review_.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="draw: the workspaces (several runs of one application, the run named by the parent folder); "
        "agree: the two reviewers' reviews files",
    )
    review_.add_argument(
        "--per-stratum", type=int, help="units drawn per stratum (equal allocation; default: proportional, --per-run)"
    )
    review_.add_argument(
        "--per-run",
        type=int,
        help="draw: units per run, allocated to its strata in proportion (default: config.json's, 70)",
    )
    review_.add_argument("--anchor", type=int, help="supported units shown blind first (default: config.json's)")
    review_.add_argument("--seed", type=int, help="the draw's seed (default: config.json's)")
    review_.add_argument("--reviewer", help="export: the reviewer's id (letters, digits, - or _)")
    review_.add_argument(
        "--prefix", help="expect-draw: the units' id prefix (default x), e.g. one per part of a sample"
    )
    review_.add_argument(
        "--application",
        action="append",
        default=[],
        help="exclude: a withdrawn application (package or package@version)",
    )
    review_.add_argument("--reason", help="exclude: why the applications were withdrawn (recorded in the manifest)")
    review_.add_argument("--step", action="append", default=[], help="draw: only units of this step (repeatable)")
    select_ = commands.add_parser("select", help="choose the experiments the assessment asks for, within the budget")
    select_.add_argument("workspace", type=Path)
    fixed = select_.add_mutually_exclusive_group()
    fixed.add_argument("--replace", action="store_true", help="replace a fixed selection, keeping it")
    fixed.add_argument(
        "--extend", action="store_true", help="add to a fixed selection, keeping its choices (within an investigation)"
    )
    select_.add_argument("--budget-seconds", type=int, help="the device budget (default: config.json's)")
    select_.add_argument(
        "--list", action="store_true", help="print the candidates as JSON lines (device time, eligible, could change)"
    )
    select_.add_argument(
        "--groups",
        action="store_true",
        help="print the candidates' groups (data type × purpose) as JSON lines: members, interventions, shared device time",
    )
    check = commands.add_parser(
        "check", help="check the provenance of the assessment's and the case report, and that the assessment rebuilds"
    )
    check.add_argument("workspace")
    check.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")

    calibrate_ = commands.add_parser(
        "calibrate",
        help="draw a calibration sample from assessments, score the review, compare two reviewers, or check it holds",
    )
    calibrate_.add_argument(
        "action",
        choices=["draw", "score", "check", "agree"],
        help="draw <folder> <workspaces…>; score <folder>; check <folder> <workspaces…>; agree <folder> <a> <b>",
    )
    calibrate_.add_argument("folder", type=Path, help="the calibration's folder (draw: a new one)")
    calibrate_.add_argument(
        "workspaces",
        nargs="*",
        type=Path,
        help="draw, check: assessment workspaces (several of one application: one per model family); "
        "agree: the two reviewers' reviews files",
    )
    calibrate_.add_argument("--per-stratum", type=int, help="units drawn per stratum (default: config.json's)")
    calibrate_.add_argument("--seed", type=int, help="the draw's seed (default: config.json's)")
    calibrate_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")

    analyse_ = commands.add_parser("analyse", help="write report.json and report.md into the workspace")
    analyse_.add_argument("workspace")
    analyse_.add_argument("--offline", action="store_true", help="use existing observation reports only")
    return parser


def _environment() -> None:
    """Settings of the model APIs from Skuld's .env, where the environment does not set them. Values are never shown."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


#: Options of a command that only some of its actions read; given to another action, they are refused, not ignored
READ_BY = {
    "review": {
        "per_stratum": ("draw", "expect-draw"),
        "seed": ("draw", "expect-draw"),
        "per_run": ("draw",),
        "anchor": ("draw",),
        "step": ("draw",),
        "prefix": ("expect-draw",),
        "reviewer": ("export",),
        "application": ("exclude",),
        "reason": ("exclude",),
    },
    "calibrate": {"per_stratum": ("draw",), "seed": ("draw",), "registry": ("draw",)},
}


def _not_read(args) -> str | None:
    """Why the command line gives an option the command will not read, or None."""
    for option, actions in READ_BY.get(args.command, {}).items():
        if getattr(args, option, None) not in (None, []) and args.action not in actions:
            return (
                f"{args.command} {args.action} does not read --{option.replace('_', '-')} (only {', '.join(actions)})"
            )
    if args.command == "select" and (args.list or args.groups) and args.budget_seconds is not None:
        return "select --list and --groups list every candidate's device time; the budget is select's alone"
    if args.command == "freeze" and args.prompt and not args.model:
        return "freeze --prompt is the prompt of an author that is a model: give --model too"
    return None


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a positive number")
    return n


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.profile:
        os.environ["SKULD_PROFILE"] = args.profile
        config.load.cache_clear()
    if getattr(args, "api", "") is None:
        args.api = config.load()["client"]["api"]
    if refused := _not_read(args):
        print(f"error: {refused}", file=sys.stderr)
        return 2
    try:
        if args.command == "config":
            if args.profiles:
                for name, description in config.profiles().items():
                    print(f"{name}\n    {description}")
                return 0
            print(json.dumps({**config.provenance(), "config": config.load()}, indent=2, ensure_ascii=False))
            return 0
        if args.command == "propose":
            _environment()
            args.model = args.model or config.model()
            exploration = propose.read(args.exploration)
            root = (
                Path(args.workspace)
                if args.workspace
                else ASGARD / "pilots" / args.pilot / "skuld" / f"{exploration.package}@{exploration.version}"
            )
            settings = {
                "exploration": str(args.exploration),
                "model": args.model,
                "api": args.api,
                "offline": args.offline,
                "selection": str(args.selection) if args.selection else None,
            }
            with manifest.metered("propose", settings, root) as run:
                summary = propose.propose(
                    args.exploration,
                    root,
                    args.catalogue,
                    args.model,
                    # relative to the workspace, which Verðandi is run from
                    component("verdandi", ASGARD / "Verdandi", relative_to=root),
                    args.api,
                    args.offline,
                    selection=json.loads(args.selection.read_text(encoding="utf-8")) if args.selection else None,
                    registry=args.registry,
                )
            for key, entry in summary["episodes"].items():
                for case in entry["cases"]:
                    print(f"{case['case']:>8}  {case['family']:<40} {entry['title']}")
                if entry.get("refused"):
                    print(f"{key:>8}  {'(refused)':<40} {'; '.join(entry['refused'])}")
            print(f"{len(summary['fixed'])} inputs fixed in {root}")
            print(f"manifest {run.path}")
        elif args.command == "corpus":
            from ratatoskr.vocabularies import Vocabulary

            if not Path(args.corpus).is_dir():
                raise FileNotFoundError(f"no corpus folder {args.corpus}")
            found = corpus.load(args.corpus)
            if args.action == "check":
                norms = corpus.load(Path(args.corpus) / corpus.NORMS)
                problems = corpus.problems(found) + [f"{corpus.NORMS}/{p}" for p in corpus.problems(norms)]
                for problem in problems:
                    print(problem)
                print(f"{len(problems)} problem(s) in {len(found.passages) + len(norms.passages)} passages")
                return 1 if problems else 0
            paths = [
                q
                for p in map(Path, args.reports)
                for q in (sorted(p.rglob("observation_report.json")) if p.is_dir() else [p])
            ]
            reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
            missing = corpus.coverage(found, reports, Vocabulary.load("asgard-data"))
            for key, entry in missing.items():
                print(f"{key:<55} {len(entry['applications']):>3} app(s) {entry['claims']:>5} claim(s)")
            print(f"{len(missing)} component(s) without a passage, from {len(reports)} report(s)")
        elif args.command == "catalogue":
            if not (Path(args.catalogue) / "families").is_dir():
                raise FileNotFoundError(f"no catalogue folder {args.catalogue} (with families/)")
            found = catalogue.load(args.catalogue)
            for f in found.latest():
                state = "reviewed" if f.reviewed else "not reviewed"
                print(f"{f.key:<40} {state:<13} {f.data['name']}")
            print(f"{len(found.families)} families, digest {found.sha256}")
        elif args.command == "freeze":
            author = {"kind": "model" if args.model else "person", "name": args.author}
            if args.prompt:
                author["prompt"] = args.prompt
            for name in inputs.freeze(args.workspace, author):
                print(f"fixed {name}")
        elif args.command == "run":
            loki = Path(args.loki).resolve()  # Loki is started from its own folder
            workspace = inputs.load(args.workspace)
            conditions = args.conditions
            if conditions == ["all"] and args.case is None:
                conditions = [execute.BASELINE, *sorted(execute.interventions(workspace))]
            elif conditions == ["all"]:
                cases = [c for c in workspace.cases if c.id == args.case]
                conditions = [execute.BASELINE, *sorted({a.condition for c in cases for a in c.alternatives})]
            entries = execute.run(
                workspace,
                Path(args.recorded),
                Path(args.config),
                args.device,
                conditions,
                args.repeat,
                component("loki", loki),  # with Loki's extra frida installed
                cwd=loki,
                qualify=args.qualify,
                case=args.case,
                keep_going=args.keep_going,
            )
            for e in entries:
                if args.json:
                    record = {
                        "order": e["order"],
                        "condition": e["condition"],
                        "exit": e["exit"],
                        "folder": str(e["dir"]),
                    }
                    print(json.dumps(record), flush=True)
                else:
                    print(f"{e['order']:3d} {e['condition']:<10} exit {e['exit']}  {e['dir']}")
            # a replay Loki ended with an error fails the series, unless a retry replaced it
            failed = [e for e in entries if e["exit"] != 0 and not e.get("retried")]
            if failed:
                print(f"{len(failed)} of {len(entries)} replay(s) ended with an error", file=sys.stderr)
                return 1
        elif args.command == "expect":
            from skuld import assessment, expectation
            from skuld.parties import load_registry

            _environment()
            a = inputs.load_assessment(args.workspace)
            args.corpus = args.corpus or a.corpus
            registry = load_registry(args.registry)
            built = assessment.build(a, registry)
            names = expectation.names(registry)
            settings = {"model": args.model, "api": args.api, "seeds": args.seeds, "offline": args.offline}
            with manifest.metered("expect", settings, args.workspace) as run:
                samples = expectation.expect(
                    a, built, corpus.load(args.corpus), args.seeds, args.model, args.api, args.offline, names=names
                )
            asked = sum(not s.reused and s.text is not None for s in samples)
            missing = sum(s.text is None for s in samples)
            print(f"{len(samples)} samples ({asked} asked, {missing} missing) in {args.workspace / 'expectation'}")
            print(f"manifest {run.path}")
        elif args.command == "judge":
            from collections import Counter

            from skuld import assessment, expectation, judge
            from skuld.parties import load_registry

            _environment()
            a = inputs.load_assessment(args.workspace)
            args.corpus = args.corpus or a.corpus
            registry = load_registry(args.registry)
            built = assessment.build(a, registry)
            found = corpus.load(args.corpus)
            hypotheses = judge.stage1(a, built, found, registry)
            only = tuple(args.question or judge.QUESTIONS)
            settings = {
                "model": args.model,
                "api": args.api,
                "seeds": args.seeds,
                "offline": args.offline,
                "questions": list(only),
            }
            with manifest.metered("judge", settings, args.workspace) as run:
                samples = judge.judge(
                    a,
                    built,
                    found,
                    corpus.load(args.corpus / corpus.NORMS),
                    hypotheses,
                    [f.id for f in a.frame.requirement("purpose_compatible").factors],
                    args.seeds,
                    args.model,
                    args.api,
                    args.offline,
                    names=expectation.names(registry),
                    only=only,
                )
            asked = sum(not s.reused and s.text is not None for _, s in samples)
            missing = sum(s.text is None for _, s in samples)
            per = dict(Counter(q.question for q, _ in samples))
            print(f"{len(samples)} samples {per} ({asked} asked, {missing} missing) in {args.workspace / 'assessment'}")
            print(f"manifest {run.path}")
        elif args.command == "describe":
            observations = []
            for o in args.observation:
                path, _, run = o.partition("=")
                path = Path(path)
                folder = path.parent.parent if path.parent.name == "analysis" else path.parent
                observations.append((path, run or folder.name))
            written = inputs.describe_assessment(
                args.workspace,
                args.package,
                args.version,
                observations,
                args.declaration,
                args.exploration,
                args.corpus,
                frame=str(args.frame),
                comment=args.comment,
                frame_version=args.frame_version,
                model=args.model,
            )
            print(f"wrote {written}")
        elif args.command == "compat":
            statement = inputs.add_compatible_versions(
                args.workspace, args.o_version, args.d_version, args.reason, args.author
            )
            print(f"{args.workspace / inputs.ASSESSMENT}: {' ~ '.join(statement['versions'])} ({statement['fixed']})")
        elif args.command == "assess":
            from collections import Counter

            from skuld.assess import REPORT, assess

            report = assess(args.workspace, args.registry)
            outcomes: dict[str, Counter] = {}
            for r in report["relations"]:
                outcomes.setdefault(r["type"], Counter())[r["outcome"]] += 1
            relations = "; ".join(f"{t} {dict(c)}" for t, c in outcomes.items()) or "no relations"
            print(
                f"{len(report['subjects']['practices'])} practices, {len(report['subjects']['declarations'])} declarations; "
                f"{relations}; {len(report['concerns'])} concerns, {len(report['open'])} open conditions "
                f"-> {args.workspace / REPORT}"
            )
        elif args.command == "aggregate":
            from skuld.aggregate import REPORT as AGGREGATE
            from skuld.aggregate import run as aggregate

            a = aggregate(args.workspace)
            c = a["counts"]
            print(
                f"{c['concerns']} concerns -> {c['aggregated_concerns']} aggregated concerns in {c['themes']} themes; "
                f"{c['open']} open conditions -> {c['open_groups']} groups -> {args.workspace / AGGREGATE}"
            )
        elif args.command == "review" and args.action in ("export", "import"):
            from skuld import review_export

            if args.action == "export":
                if not args.paths or not args.reviewer:
                    raise review_export.ReviewError("export needs the drawn sample folders and --reviewer")
                out = review_export.export(args.folder, args.paths, args.reviewer)
                print(
                    f"{out} ({out.stat().st_size // 1024} KB) for reviewer {args.reviewer}: {len(args.paths)} sample(s)"
                )
            else:
                if len(args.paths) != 1:
                    raise review_export.ReviewError("import needs the reviews folder the samples were drawn into")
                flags: list[str] = []
                for path in review_export.import_(args.folder, args.paths[0], flags):
                    print(path)
                for flag in flags:
                    print(f"check: {flag}", file=sys.stderr)
        elif args.command == "review" and args.action == "exclude":
            from skuld import review_exclude

            if len(args.paths) < 2 or not args.reason:
                raise review_exclude.ExcludeError(
                    "exclude needs the new folder, the withdrawn workspaces, --application and --reason"
                )
            m = review_exclude.exclude(args.folder, args.paths[0], args.paths[1:], args.application, args.reason)
            d = m["derived"]
            print(f"{len(d['units'])} units of {', '.join(d['excluded'])} left out -> {args.paths[0]}")
            for s in m["strata"]:
                print(
                    f"  {' '.join(str(v) for k, v in s.items() if k not in ('population', 'drawn')):<90} {s['drawn']:>3} of {s['population']:>5}"
                )
        elif args.command == "review" and args.action.startswith("expect-"):
            from skuld import review_expectation as rx

            if args.action == "expect-draw":
                if not args.paths:
                    raise rx.ReviewError("expect-draw needs the workspaces")
                m = rx.draw(args.folder, args.paths, args.per_stratum, args.seed, args.prefix or "x")
                for st in m["strata"]:
                    name = " ".join(str(st[k]) for k in ("run", "role", "status"))
                    print(f"{name:<50} {st['drawn']:>3} of {st['population']:>4}")
                items = json.loads((args.folder / rx.SAMPLE).read_text(encoding="utf-8"))["items"]
                print(
                    f"{len(items)} practices, {sum(len(i['purposes']) for i in items)} purposes "
                    f"-> {args.folder / rx.SAMPLE}"
                )
            elif args.action == "expect-score":
                sc = rx.score(args.folder)
                for e in sc["estimates"]:
                    if e["role"] == "all":
                        print(f"{e['run']:<20} {e['level']:<11} {e['question']:<13} {e['rate']} ({e['judged']} judged)")
                print(
                    f"{sc['done']} of {sc['units']} practices done; {len(sc['missed'])} purposes noted as missed "
                    f"({sc['missed_functional']} functional) -> {args.folder / rx.SCORES}"
                )
            else:
                if len(args.paths) != 2:
                    raise rx.ReviewError("expect-agree needs the two reviewers' reviews files")
                result = rx.agree(args.folder, *args.paths)
                for name, q in result["questions"].items():
                    if name.startswith("all "):
                        print(f"{name[4:]:<28} kappa {q['kappa']} on {q['items']}")
                print(f"{len(result['differences'])} differing answers -> {args.folder / rx.AGREEMENT}")
        elif args.command == "review":
            from skuld import review

            if args.action == "draw":
                if not args.paths:
                    raise review.ReviewError("draw needs the workspaces")
                m = review.draw(
                    args.folder, args.paths, args.per_stratum, args.seed, args.anchor, args.per_run, args.step or None
                )
                for st in m["strata"]:
                    name = " ".join(str(st[k]) for k in ("run", "principle", "tier", "step", "status"))
                    print(f"{name:<90} {st['drawn']:>3} of {st['population']:>4}")
                print(
                    f"{sum(st['drawn'] for st in m['strata'])} units ({m['anchor']} shown blind first) "
                    f"-> {args.folder / review.SAMPLE}"
                )
            elif args.action == "score":
                sc = review.score(args.folder)
                for e in sc["estimates"]:
                    name = " ".join(str(e[k]) for k in ("run", "principle", "step", "status"))
                    print(f"{name:<80} {e['rate']} per unit, {e['members_rate']} per member ({e['units']} units)")
                a = sc["anchoring"]
                if "difference" in a:
                    print(f"anchoring: blind {a['blind_rate']}, non-blind {a['non_blind_rate']} on {a['units']} units")
                print(
                    f"{sc['judged']} of {sc['items']} judged, {sc['unsure']} unsure; "
                    f"{len(sc['recall']['missed'])} misses noted -> {args.folder / review.SCORES}"
                )
            else:
                if len(args.paths) != 2:
                    raise review.ReviewError("agree needs the two reviewers' reviews files")
                result = review.agree(args.folder, *args.paths)
                o = result["overall"]
                print(
                    f"overall kappa {o['overall']['kappa']} on {o['overall']['items']} units; evidence "
                    f"{o['evidence']['kappa']}, follows {o['follows']['kappa']}, phrases {o['phrases']['kappa']}; "
                    f"{len(result['disagreements'])} disagreements -> {args.folder / review.AGREEMENT}"
                )
        elif args.command == "select" and args.groups:
            for g in select.group_listing(args.workspace):
                print(json.dumps(g, ensure_ascii=False))
        elif args.command == "select" and args.list:
            for c in select.listing(args.workspace):
                print(json.dumps(c, ensure_ascii=False))
        elif args.command == "select":
            budget = args.budget_seconds if args.budget_seconds is not None else select.settings()["budget_seconds"]
            if not budget:
                print(
                    "experiments are off: the budget is 0 s (config's experiments.budget_seconds); "
                    "give --budget-seconds to choose within one",
                    file=sys.stderr,
                )
            selection = select.select(
                args.workspace, args.replace, budget_seconds=args.budget_seconds, extend=args.extend
            )
            for e in selection["entries"]:
                kind = "chosen" if e["kind"] == select.CHOICE else "refused"
                print(
                    f"{kind:<8} {e['practice']} {(str(e['node']) + ' (' + str(e['beneficiary']) + ')'):<46} {e['cost_seconds']:>6} s  {e['reason']}"
                )
            print(
                f"{len(select.chosen(selection))} of {len(selection['entries'])} chosen, "
                f"{selection['device_seconds']} s of device time -> {args.workspace / select.FILE}"
            )
        elif args.command == "check":
            from skuld.provenance import check as provenance
            from skuld.provenance import check_assessment

            root, found = Path(args.workspace), 0
            assessment_ws = (root / inputs.ASSESSMENT).is_file()
            case_ws = (root / "workspace.yaml").is_file() and (root / "report.json").is_file()
            if not assessment_ws and not case_ws:
                raise inputs.InputError(
                    f"{root}: nothing to check: neither an assessment workspace (assessment.yaml) nor a case workspace"
                    " with a report.json"
                )
            if assessment_ws and not (root / "assessment.json").is_file():
                print(f"assessment.json: absent; make it with skuld assess {root}")
                found += 1
            elif assessment_ws:
                from skuld import judge
                from skuld.assess import REPORT, build
                from skuld.expectation import notices_of

                report = json.loads((root / REPORT).read_text(encoding="utf-8"))
                # rebuild with the reading the report was made with, so that a later reading changes no old report, and
                # with the notice definition its stage-1 contexts were made with (1.1.0 if it names none)
                named = [
                    c.get("version")
                    for c in report.get("report", {}).get("components", [])
                    if c.get("id") == "skuld.judge.reading"
                ]
                reading = named[0] if named else judge.READING
                notes: list[str] = []
                rebuilt = members = None
                if reading in judge.READINGS:
                    try:
                        rebuilt, members = build(
                            root, args.registry, write=False, reading=reading, notices=notices_of(report)
                        )
                    except inputs.InputError:
                        pass  # a changed input refuses the rebuild; check_assessment names it by its digest
                problems = check_assessment(inputs.load_assessment(root, check=False), report, rebuilt, members, notes)
                if reading not in judge.READINGS:
                    problems.append(f"names the reading {reading}, which this Skuld does not know {judge.READINGS}")
                elif rebuilt is None:
                    problems.append("not rebuilt: an input it names has changed")
                for problem in problems:
                    print(f"{REPORT}: {problem}")
                for note in notes:
                    print(f"{REPORT}: note: {note}")
                print(
                    f"{REPORT}: {len(problems)} problem(s); {len(report['evidence'])} items, rebuilt identically"
                    if rebuilt is not None and not any("rebuilt" in p for p in problems) and not notes
                    else f"{REPORT}: {len(problems)} problem(s)"
                )
                found += len(problems)
            if case_ws:
                workspace = inputs.load(root)
                report = json.loads((workspace.root / "report.json").read_text(encoding="utf-8"))
                problems = provenance(workspace, report)
                for problem in problems:
                    print(f"report.json: {problem}")
                pointers = sum(len(i.get("provenance") or ()) for i in report["evidence"])
                print(f"report.json: {len(problems)} problem(s); {len(report['evidence'])} items, {pointers} pointers")
                found += len(problems)
            return 1 if found else 0
        elif args.command == "calibrate":
            from skuld import calibrate

            if args.action == "draw":
                if not args.workspaces:
                    raise calibrate.CalibrationError("draw needs the assessment workspaces")
                drawn = calibrate.draw(args.folder, args.workspaces, args.registry, args.per_stratum, args.seed)
                if drawn.get("families"):
                    print(f"across families: {', '.join(drawn['families'])}")
                for st in drawn["strata"]:
                    print(f"{calibrate.stratum_name(st):<75} {st['drawn']:>3} of {st['population']:>4}")
                print(f"{sum(st['drawn'] for st in drawn['strata'])} items -> {args.folder}")
            elif args.action == "score":
                scores = calibrate.score(args.folder)
                for st in scores["strata"]:
                    name = calibrate.stratum_name(st)
                    rate = (
                        "–"
                        if st["rate"] is None
                        else f"{st['rate']:.2f} [{st['interval'][0]:.2f}, {st['interval'][1]:.2f}]"
                    )
                    print(f"{name:<75} {st['measure']:<13} {rate:<20} {st['fails'] + st['holds']:>3} reviewed")
                for e in scores["estimates"] if scores.get("mode") == "families" else ():
                    rate = (
                        "–"
                        if e["rate"] is None
                        else f"{e['rate']:.2f} [{e['interval'][0]:.2f}, {e['interval'][1]:.2f}]"
                    )
                    name = f"{e['family']} {e['principle']} {e['step']}"
                    print(f"{name:<75} {e['measure']:<17} {rate:<20} {e['reviewed']:>3} reviewed")
                print(
                    f"{scores['reviewed']} of {scores['items']} reviewed, {scores['unsure']} unsure -> {args.folder / calibrate.SCORES}"
                )
            elif args.action == "agree":
                if len(args.workspaces) != 2:
                    raise calibrate.CalibrationError("agree needs the two reviewers' reviews files")
                result = calibrate.agree(args.folder, *args.workspaces)
                for name, k in [("overall", result["overall"]), *result["principles"].items()]:
                    print(
                        f"{name:<22} {k['agreed']:>3} of {k['items']:>3} agreed, kappa {k['kappa']}, "
                        f"on fails/holds {k['kappa_fails_holds']} ({k['items_fails_holds']} items)"
                    )
                print(
                    f"{len(result['disagreements'])} disagreement(s) to adjudicate; undecided: {result['undecided']}"
                    + (f"; reviews.json seeded with {result['seeded']} agreed decisions" if "seeded" in result else "")
                    + f" -> {args.folder / calibrate.AGREEMENT}"
                )
            else:
                problems = calibrate.check(args.folder, args.workspaces)
                for problem in problems:
                    print(problem)
                print(f"{len(problems)} component(s) the calibration does not hold for")
                return 1 if problems else 0
        elif args.command == "change":
            inputs.change(args.workspace, args.input, args.reason)
            print(f"recorded the change of {args.input}")
        else:
            workspace = inputs.load(args.workspace)
            report = analyse(workspace, make_observations=not args.offline)
            json_path, _ = write(report, workspace.root)
            outcomes = {}
            for k in report["comparisons"]:
                outcomes[k["outcome"]] = outcomes.get(k["outcome"], 0) + 1
            print(f"{json_path}: {len(report['runs'])} runs, {len(report['comparisons'])} comparisons {outcomes}")
    except (
        inputs.InputError,
        AnalysisError,
        ContextError,
        execute.ExecutionError,
        propose.ProposalError,
        select.SelectionError,
        catalogue.CatalogueError,
        corpus.CorpusError,
        IndependenceError,
        AskError,
        ConfigError,
        ObservationError,
        FileNotFoundError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
