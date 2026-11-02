"""
skuld propose <exploration> --pilot …: generate and fix a workspace's inputs from Loki's exploration and the catalogue.
skuld corpus check | coverage <reports…>: the corpus's passages checked; the components no passage covers.
skuld catalogue: the catalogue's families.
skuld freeze <workspace>: fix the named inputs before the runs they judge.
skuld change <workspace> <input> --reason …: record a change of a fixed input.
skuld run <workspace> --recorded … --config … --device …: the runs, made by Loki in rotated order.
skuld analyse <workspace>: the expectation report.
skuld check <workspace>: the provenance of the report (every digest verifies, every pointer resolves).
skuld expect <workspace>: the expectation stage's samples (contexts without D, and the model's answers).
skuld judge <workspace>: the assessment stage's reasoning tier: specificity, compatibility and minimisation samples.
skuld describe <workspace> --package … --version … --observation …: write the assessment workspace's assessment.yaml.
skuld assess <workspace>: the assessment of the version from what is kept (subjects, both stages), no model asked.
skuld select <workspace>: the choice of experiments from the assessment, each choice and refusal with its reason.
skuld calibrate draw <folder> <workspaces…> | score <folder> | check <folder> <workspaces…>: E's calibration (EV-E9).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from skuld import catalogue, config, corpus, execute, inputs, manifest, propose, select
from skuld.ask import AskError
from skuld.context import ContextError
from skuld.expectation import IndependenceError
from skuld.experiments import AnalysisError, analyse
from skuld.report import write

#: Skuld's corpus of documentation
CORPUS = Path(__file__).resolve().parents[1] / "corpus"
#: Skuld's catalogue of feature families
CATALOGUE = Path(__file__).resolve().parents[1] / "catalogue"
#: Asgard's folder, which holds the components and the pilots' data
ASGARD = Path(__file__).resolve().parents[2]
#: Loki's folder, next to Skuld's
LOKI = ASGARD / "Loki"
#: The model of the generator and both stages
MODEL = config.model()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skuld", description="The Expectation dimension's analysis.")
    commands = parser.add_subparsers(dest="command", required=True)

    propose_ = commands.add_parser("propose", help="generate and fix a workspace's inputs from Loki's exploration")
    propose_.add_argument("exploration", help="Loki's exploration run (pseudo-saturation regime)")
    where = propose_.add_mutually_exclusive_group(required=True)
    where.add_argument("--pilot", help="the pilot: the workspace is pilots/<pilot>/skuld/<package>@<version>")
    where.add_argument("--workspace", help="the workspace's folder")
    propose_.add_argument("--catalogue", default=str(CATALOGUE), help="the catalogue folder (default: Skuld's)")
    propose_.add_argument("--model", default=MODEL, help=f"(default: {MODEL})")
    propose_.add_argument("--api", default="ollama", help="API that serves the model (default: ollama)")
    propose_.add_argument("--offline", action="store_true", help="only the answers kept")
    propose_.add_argument("--selection", type=Path, help="cases only for the practices this selection chose")
    propose_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")

    corpus_ = commands.add_parser(
        "corpus", help="check the corpus, or list what O's reports name that it does not cover"
    )
    corpus_.add_argument("action", choices=["check", "coverage"])
    corpus_.add_argument("reports", nargs="*", help="for coverage: observation reports, or folders searched for them")
    corpus_.add_argument("--corpus", default=str(CORPUS), help="the corpus folder (default: Skuld's)")

    families = commands.add_parser("catalogue", help="list the catalogue's families and check them")
    families.add_argument("--catalogue", default=str(CATALOGUE))

    freeze = commands.add_parser("freeze", help="fix every input not fixed yet, with its digest and author")
    freeze.add_argument("workspace")
    freeze.add_argument("--author", required=True, help="who wrote the inputs")
    freeze.add_argument("--model", action="store_true", help="the author is a model (its prompt in --prompt)")
    freeze.add_argument("--prompt", help="the model's prompt, for an author that is a model")

    change = commands.add_parser("change", help="record a change of a fixed input with its reason")
    change.add_argument("workspace")
    change.add_argument("input", help="the input's path in the workspace, e.g. cases/launch.yaml")
    change.add_argument("--reason", required=True)

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
    run.add_argument("--repeat", type=int, default=3, help="runs per condition (default: 3)")
    run.add_argument("--loki", default=str(LOKI), help="Loki's folder (default: the sibling Loki)")
    run.add_argument(
        "--qualify", action="store_true", help="first one baseline replay; record the cases it does not qualify"
    )

    expect_ = commands.add_parser(
        "expect", help="ask the model the expectation stage's questions, per episode and seed"
    )
    expect_.add_argument("workspace", type=Path)
    expect_.add_argument("--model", default=None, help="(default: config.json's)")
    expect_.add_argument("--api", default="ollama")
    expect_.add_argument("--seeds", type=int, nargs="+", default=None, help="(default: config.json's, 1 2 3)")
    expect_.add_argument("--offline", action="store_true", help="only the samples kept")
    expect_.add_argument("--corpus", type=Path, default=CORPUS)
    expect_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    judge_ = commands.add_parser(
        "judge", help="ask the model the reasoning tier's questions (specificity, compatibility, minimisation)"
    )
    judge_.add_argument("workspace", type=Path)
    judge_.add_argument("--model", default=None, help="(default: the assessment's, else config.json's)")
    judge_.add_argument("--api", default="ollama")
    judge_.add_argument("--seeds", type=int, nargs="+", default=None, help="(default: config.json's, 1 2 3)")
    judge_.add_argument("--question", choices=["specificity", "compatibility", "minimisation"], nargs="+")
    judge_.add_argument("--offline", action="store_true", help="only the samples kept")
    judge_.add_argument("--corpus", type=Path, default=CORPUS)
    judge_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    describe = commands.add_parser("describe", help="write an assessment workspace's assessment.yaml, by digest")
    describe.add_argument("workspace", type=Path)
    describe.add_argument("--package", required=True)
    describe.add_argument("--version", required=True)
    describe.add_argument(
        "--observation", nargs="+", required=True, help="O's reports, each PATH or PATH=RUN (default run: its folder)"
    )
    describe.add_argument("--declaration", type=Path, help="D's report (none: an assessment without D)")
    describe.add_argument("--exploration", type=Path, help="Loki's exploration run, whose screens stage 1 reads")
    describe.add_argument("--corpus", type=Path, default=CORPUS)
    describe.add_argument("--comment", help="a first line saying what the assessment is")
    assess_ = commands.add_parser("assess", help="assess an application version from its assessment workspace")
    assess_.add_argument("workspace", type=Path)
    assess_.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")
    select_ = commands.add_parser("select", help="choose the experiments the assessment asks for, within the budget")
    select_.add_argument("workspace", type=Path)
    select_.add_argument("--replace", action="store_true", help="replace a fixed selection, keeping it")
    select_.add_argument(
        "--extend", action="store_true", help="add to a fixed selection, keeping its choices (within an investigation)"
    )
    select_.add_argument("--budget-seconds", type=int, help="the device budget (default: config.json's)")
    select_.add_argument(
        "--list", action="store_true", help="print the candidates as JSON lines (device time, eligible, could change)"
    )
    check = commands.add_parser(
        "check", help="check the provenance of the assessment's and the case report, and that the assessment rebuilds"
    )
    check.add_argument("workspace")
    check.add_argument("--registry", type=Path, help="the recipient registry (default: Ratatoskr's built one)")

    calibrate_ = commands.add_parser(
        "calibrate", help="draw a calibration sample from assessments, score the expert's review, or check it holds"
    )
    calibrate_.add_argument("action", choices=["draw", "score", "check"])
    calibrate_.add_argument("folder", type=Path, help="the calibration's folder (draw: a new one)")
    calibrate_.add_argument("workspaces", nargs="*", type=Path, help="draw, check: assessment workspaces")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "propose":
            _environment()
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
                    ["uv", "run", "--project", inputs.portable(ASGARD / "Verdandi", root), "verdandi"],
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
            loki = Path(args.loki)
            workspace = inputs.load(args.workspace)
            conditions = args.conditions
            if conditions == ["all"]:
                conditions = [execute.BASELINE, *sorted(execute.interventions(workspace))]
            entries = execute.run(
                workspace,
                Path(args.recorded),
                Path(args.config),
                args.device,
                conditions,
                args.repeat,
                ["uv", "run", "--project", str(loki), "--extra", "frida", "loki"],
                cwd=loki,
                qualify=args.qualify,
            )
            for e in entries:
                if args.json:
                    record = {"order": e["order"], "condition": e["condition"], "exit": e["exit"], "folder": str(e["dir"])}
                    print(json.dumps(record), flush=True)
                else:
                    print(f"{e['order']:3d} {e['condition']:<10} exit {e['exit']}  {e['dir']}")
        elif args.command == "expect":
            from skuld import assessment, expectation
            from skuld.parties import load_registry

            _environment()
            a = inputs.load_assessment(args.workspace)
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
                comment=args.comment,
            )
            print(f"wrote {written}")
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
        elif args.command == "select" and args.list:
            for c in select.listing(args.workspace, args.budget_seconds):
                print(json.dumps(c, ensure_ascii=False))
        elif args.command == "select":
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
            if (root / inputs.ASSESSMENT).is_file():
                from skuld.assess import REPORT, build

                report = json.loads((root / REPORT).read_text(encoding="utf-8"))
                rebuilt, members = build(root, args.registry, write=False)
                problems = check_assessment(inputs.load_assessment(root), report, rebuilt, members)
                for problem in problems:
                    print(f"{REPORT}: {problem}")
                print(
                    f"{REPORT}: {len(problems)} problem(s); {len(report['evidence'])} items, rebuilt identically"
                    if not any("rebuilt" in p for p in problems)
                    else f"{REPORT}: {len(problems)} problem(s)"
                )
                found += len(problems)
            if (root / "workspace.yaml").is_file() and (root / "report.json").is_file():
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
                for st in drawn["strata"]:
                    name = f"{st['principle']} {st['tier']} {st['step']} {st['outcome']}"
                    print(f"{name:<75} {st['drawn']:>3} of {st['population']:>4}")
                print(f"{sum(st['drawn'] for st in drawn['strata'])} items -> {args.folder}")
            elif args.action == "score":
                scores = calibrate.score(args.folder)
                for st in scores["strata"]:
                    name = f"{st['principle']} {st['tier']} {st['step']} {st['outcome']}"
                    rate = (
                        "–"
                        if st["rate"] is None
                        else f"{st['rate']:.2f} [{st['interval'][0]:.2f}, {st['interval'][1]:.2f}]"
                    )
                    print(f"{name:<75} {st['measure']:<13} {rate:<20} {st['fails'] + st['holds']:>3} reviewed")
                print(
                    f"{scores['reviewed']} of {scores['items']} reviewed, {scores['unsure']} unsure -> {args.folder / calibrate.SCORES}"
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
        IndependenceError,
        AskError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
