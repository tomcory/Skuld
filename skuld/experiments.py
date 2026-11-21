"""
The experimental channel's case analysis (`skuld analyse`): from a case workspace's named inputs and the sources of its
runs to the case report (Ratatoskr's `expectation_report`), which the assessment reads by digest (`assess.py`).

For each case: the runs of its feature made after its inputs were fixed; the baseline configuration
from O's reports of the baseline runs; the verification of every run under an alternative; the
oracles' decisions; the comparisons; and the experimental channel's claims, with their evidence,
uncertainty and sufficiency, the channel's silence, open conditions and gaps.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ratatoskr.vocabularies import Vocabulary

import skuld
from skuld import configuration, oracles, rules, space, yamlio
from skuld.common import vocabulary
from skuld.comparison import Comparison, compare
from skuld.inputs import Case, InputError, Workspace, check_frozen, digest
from skuld.observe import ObservationError, annotators, observe, report_path, source_reads
from skuld.runs import Run, RunRefused, load
from skuld.uncertainty import needs, of
from skuld.verify import VERSION as verify_version
from skuld.verify import Verification, baseline_problem, imposes, settings, verify

BASELINE = "baseline"
DATA_VOCABULARY = "asgard-data"
PURPOSE_VOCABULARY = "dpv-purposes"


class AnalysisError(Exception):
    """A workspace that cannot be analysed: an input not fixed or changed without a record."""


@dataclass
class RunState:
    id: str
    entry: object
    run: Run | None = None
    report: dict | None = None
    refused: str | None = None
    cases: list[str] = field(default_factory=list)
    verification: Verification | None = None
    decisions: dict = field(default_factory=dict)


#: What of Loki's replay record says the replay departed from the recording; its other keys (until_action, keep_going,
#: blocked_actions) state how it was asked to replay
DIVERGED = ("divergences", "repairs", "skipped_actions")


def _diverged(run) -> bool:
    """Whether a replay departed from its recording."""
    return any((run.meta.get("replay") or {}).get(x) for x in DIVERGED)


def analyse(workspace: Workspace, make_observations: bool = True, now: datetime | None = None) -> dict:
    """The expectation report of a workspace."""
    try:
        frozen = check_frozen(workspace)
    except Exception as e:
        raise AnalysisError(str(e)) from e
    data_vocabulary = vocabulary(DATA_VOCABULARY)
    purpose_vocabulary = vocabulary(PURPOSE_VOCABULARY)

    states = {}
    for entry in workspace.runs:
        state = states[entry.id] = RunState(entry.id, entry)
        if entry.excluded:
            state.refused = f"excluded by the assessor: {entry.excluded}"
            continue
        try:
            state.run = load(entry.directory)
            state.report = observe(
                workspace.root,
                entry.id,
                entry.directory,
                workspace.verdandi,
                make_observations,
                workspace.verdandi_options,
            )
        except (RunRefused, ObservationError) as e:
            state.refused = str(e)
    _refuse_other_annotators(states)

    builder = _Report(workspace, frozen, states, data_vocabulary)
    for case in workspace.cases:
        builder.case(case)
    return builder.write(now, data_vocabulary, purpose_vocabulary)


def _refuse_other_annotators(states: dict) -> None:
    """Refuses the runs whose observation report was made with other annotators than the workspace's first run: a
    datum one report inferred and the other could not would look like a practice the replay removed."""
    reports = [s for s in states.values() if s.report is not None and not s.refused]
    if not reports:
        return
    expected = annotators(reports[0].report)
    for state in reports[1:]:
        found = annotators(state.report)
        if found != expected:
            state.refused = (
                f"its observation report was made with other annotators ({found or 'none'}) than the workspace's "
                f"first run ({expected or 'none'}); analyse every run alike (workspace.yaml: verdandi_options)"
            )


def unqualified(root: Path) -> dict[str, list[str]]:
    """The experimental cases a qualifying replay did not qualify, with why (`skuld run --qualify`)."""
    path = root / "qualification.json"
    if not path.is_file():
        return {}
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    except (ValueError, KeyError) as e:
        raise InputError(f"{path} cannot be read ({e}); run the qualifying replay again") from None
    return {c: p for c, p in cases.items() if p}


def runs_of(case: Case, state: RunState) -> bool:
    """Whether a run is meant as a run of the experimental case's feature: a replay of the recording its path is taken
    from, and, for a replay of a prefix of it (`skuld run --case`), one that went as far as the path's last action."""
    feature = case.feature
    run = state.run
    until = ((run.meta.get("replay") or {}) if run is not None else {}).get("until_action")
    if until is not None and until < feature.actions:
        return False
    if feature.path_run is None:
        return True
    return (run.meta.get("replay_of") or run.run_id) == feature.path_run


#: Events of a replay that depart from the recording at the recorded event they name (`source_seq`)
DEPARTURES = ("divergence", "repair", "replay_action_failed")


def departed(case: Case, run: Run) -> str | None:
    """
    Why a run did not follow the feature's path, or None if it did: a replay is a run of the feature only if it
    departed from the recording nowhere within the path, from just after the action before its first (so that
    reaching the start screen of its episode counts) to its last action. Departures before the path are judged by
    whether the replay then reaches the path's screens: every replayed action checks that it is on its recorded
    screen, and records a departure if not (author, 12 Nov 2026; before, any departure before the path counted).
    Departures after it are outside the feature.
    """
    feature = case.feature
    if feature.path_run is None or not run.meta.get("replay_of"):
        return None
    recorded = _recorded_actions(run.directory.parent / feature.path_run)
    if len(recorded) < feature.actions:
        return f"the recording has {len(recorded)} actions, the feature's path {feature.actions}"
    last = recorded[feature.actions - 1] if feature.actions else 0
    before = recorded[feature.start - 1] if feature.start else 0
    within = [e for e in run.events if e.get("type") in DEPARTURES and before < (e.get("source_seq") or 0) <= last]
    if within:
        kinds = ", ".join(sorted({e["type"] for e in within}))
        return f"did not follow the feature's path: {len(within)} departure(s) within it ({kinds})"
    return None


def _recorded_actions(folder: Path) -> list[int]:
    """The event numbers of a recording's actions."""
    path = folder / "events.jsonl"
    if not path.is_file():
        return []
    events = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [e["seq"] for e in events if e.get("type") == "action"]


class _Report:
    def __init__(self, workspace: Workspace, frozen: dict, states: dict[str, RunState], vocabulary: Vocabulary):
        self.ws = workspace
        self.frozen = frozen
        self.states = states
        self.vocabulary = vocabulary
        self.cases, self.comparisons, self.evidence = [], [], []
        self.features = {}
        self.verifications = {}
        self.unqualified = unqualified(workspace.root)
        self._evidence_ids = set()
        self.accepted_versions: dict[str, list[dict]] = {}

    # -- per case -------------------------------------------------------------------------------------------------

    def case(self, case: Case) -> None:
        ws = self.ws
        self.features.setdefault(case.feature.id, case.feature)
        inputs = [ws.file(case.path)] + [
            ws.file(ws.oracles[p.oracle].path) for p in case.purposes if p.oracle is not None
        ]
        fixed = max(datetime.fromisoformat(self.frozen[i]["fixed"]) for i in inputs)
        version = str(ws.application.get("version", "?"))
        stated = _compatible(ws.root, version)
        accepted = self.accepted_versions[case.id] = []

        usable, excluded = [], {}
        for state in self.states.values():
            if state.refused:
                excluded[state.id] = state.refused
            elif not runs_of(case, state):
                continue
            elif departure := departed(case, state.run):
                excluded[state.id] = departure
            elif (ran := str((state.run.meta.get("app") or {}).get("version_name", version))) != version and (
                ran not in stated
            ):
                excluded[state.id] = f"outside the case's scope: version {state.run.meta['app'].get('version_name')}"
            elif not _after(state.run.meta.get("started_at"), fixed):
                excluded[state.id] = "made before the case's inputs were fixed"
            else:
                usable.append(state)
                state.cases.append(case.id)
                if ran != version and stated[ran] not in accepted:
                    accepted.append(stated[ran])

        baseline = []
        for s in usable:
            if s.entry.condition == BASELINE:
                problem = baseline_problem(s.report)
                if problem:
                    excluded[s.id] = f"no baseline: {problem}"
                else:
                    baseline.append(s)
        # u_0 from the baseline runs of this experimental case's path: a component none of them shows (no read of its
        # source, no transmission to its recipient) is no component of it, and no comparison varies it (C2)
        u0 = configuration.baseline([s.report for s in baseline])
        present = {c.id: configuration.present(c, u0, self.vocabulary) for c in case.components}
        alternatives_ok, missing_why = [], {}
        problems = {}
        for alt in case.alternatives:
            issues = configuration.check(alt, case, u0, self.vocabulary)
            issues += [f"its intervention does not impose {c}" for c in imposes(alt, case)]
            if issues and present[alt.component]:
                problems[alt.id] = issues
                for p in case.purposes:
                    missing_why[(p.id, alt.id)] = "precondition_failed"
            else:
                alternatives_ok.append(alt)
        if case.id in self.unqualified:
            for alt in case.alternatives:
                problems[alt.id] = [f"the case did not qualify: {'; '.join(self.unqualified[case.id])}"]
                for p in case.purposes:
                    missing_why[(p.id, alt.id)] = "precondition_failed"
            alternatives_ok = []

        baseline_reads: dict[str, list[int]] = {}
        for s in baseline:
            for source in settings(s.report):
                baseline_reads.setdefault(source, []).append(len(source_reads(s.report, source)))

        under = {}
        for alt in alternatives_ok:
            if not present[alt.component]:
                # no comparison varies a component no baseline run shows (C2, below), and its runs cannot be verified
                # against a baseline that never read the source
                under[alt.id] = []
                continue
            runs = [s for s in usable if s.entry.condition == alt.condition]
            verified = []
            for s in runs:
                v = verify(s.run, s.report, alt, case, baseline_reads)
                s.verification = s.verification or v
                self.verifications[(case.id, s.id)] = v
                self._verification_evidence(case, s, v)
                if v.status == "verified":
                    verified.append(s)
                else:
                    excluded.setdefault(s.id, f"intervention for {alt.id} not verified")
            under[alt.id] = verified
            for p in case.purposes:
                if not runs:
                    missing_why[(p.id, alt.id)] = "search_space_not_run"
                elif not verified:
                    missing_why[(p.id, alt.id)] = "intervention_not_verified"

        comparisons = {}
        for purpose in case.purposes:
            if purpose.oracle is None:
                continue
            oracle = ws.oracles[purpose.oracle]
            decided = {}
            judged = {s.id: s for s in [*baseline, *(r for runs in under.values() for r in runs)]}
            for s in judged.values():
                d = s.decisions[(case.id, purpose.id)] = oracles.decide(oracle, s.run)
                decided[s.id] = d
                self._decision_evidence(case, purpose.id, oracle, s, d)
            valid_baseline = {s.id: decided[s.id] for s in baseline if decided[s.id].decision != "invalid"}
            for alt in alternatives_ok:
                if not present[alt.component]:
                    # C2 (author, 14 Nov 2026): no baseline run of the case's path read the source or reached the
                    # recipient, so the intervention varies nothing there; its claims are not applicable (rules)
                    missing_why.setdefault((purpose.id, alt.id), "precondition_failed")
                    continue
                valid = {s.id: decided[s.id] for s in under[alt.id] if decided[s.id].decision != "invalid"}
                if not valid_baseline or not valid:
                    # every run of a side was invalid for the oracle, or no baseline run was usable
                    missing_why.setdefault(
                        (purpose.id, alt.id), "precondition_failed" if judged else "search_space_not_run"
                    )
                    continue
                k = compare(
                    f"{case.id}:{purpose.id}:{alt.id}",
                    case.id,
                    purpose.id,
                    alt.id,
                    oracle,
                    valid_baseline,
                    valid,
                    {s.id: s.entry.order for s in usable},
                    {s: oracles.costs(self.states[s].run) for s in [*valid_baseline, *valid]},
                    [u for s in valid for u in self.verifications[(case.id, s)].unverifiable],
                    [
                        {"run": s, **self.states[s].run.meta["replay"]}
                        for s in [*valid_baseline, *valid]
                        if _diverged(self.states[s].run)
                    ],
                    [n for s in valid for n in self.verifications[(case.id, s)].substitutes],
                )
                comparisons[(purpose.id, alt.id)] = k
                self._comparison(k, case)

        self._case_record(case, inputs, u0, present, usable, excluded, problems, missing_why)

    # -- evidence -------------------------------------------------------------------------------------------------

    def _add(self, item: dict) -> None:
        if item["id"] not in self._evidence_ids:
            self._evidence_ids.add(item["id"])
            self.evidence.append(item)

    def _verification_evidence(self, case: Case, s: RunState, v: Verification) -> None:
        """The verification, derived from the items of O and of the instruments' records it rests on."""
        premises = []
        for item in v.items:
            pointer = {"unit": case.id, **item["pointer"], "method": "rule"}
            pointer["source"] = f"{pointer['source']}:{s.id}"
            iid = f"{item['key']}:{case.id}:{s.id}"
            premises.append(iid)
            self._add(
                {
                    "id": iid,
                    "channel": f"ex:{case.id}",
                    "proposition": {"kind": "observation", "run": s.id, "record": item["pointer"]["record"]},
                    "kinds": item["kinds"],
                    "provenance": [pointer],
                    "uncertainty": LOW,
                }
            )
        kinds = sorted({k for item in v.items for k in item["kinds"]}) or ["rt"]
        self._add(
            {
                "id": f"v:{case.id}:{s.id}",
                "channel": f"ex:{case.id}",
                "proposition": {
                    "kind": "observation",
                    "about": "verification",
                    "run": s.id,
                    "status": v.status,
                    **({"substitutes": v.substitutes} if v.substitutes else {}),
                },
                "kinds": kinds,
                "premises": premises,
                "provenance": [],
                "uncertainty": of("unverifiable") if v.unverifiable else LOW,
            }
        )

    def _decision_evidence(self, case: Case, purpose: str, oracle, s: RunState, d) -> None:
        name = self.ws.file(oracle.path)
        self._add(
            {
                "id": f"d:{s.id}:{case.id}:{purpose}",
                "channel": f"ex:{case.id}",
                "proposition": {
                    "kind": "decision",
                    "run": s.id,
                    "purpose": purpose,
                    "oracle": oracle.key,
                    "decision": d.decision,
                },
                "kinds": ["run"],
                "provenance": [
                    {
                        "unit": case.id,
                        "source": f"run:{s.id}",
                        "record": "events.jsonl",
                        "locator": "screen",
                        "method": "rule",
                    },
                    {
                        "unit": case.id,
                        "source": f"run:{s.id}",
                        "record": "run.json",
                        "locator": "replay",
                        "method": "rule",
                    },
                    {"input": name, "sha256": digest(oracle.path), "method": "rule"},
                ],
                "uncertainty": LOW,
            }
        )

    def _comparison(self, k: Comparison, case: Case) -> None:
        runs = [*k.baseline_runs, *k.alternative_runs]
        premises = [f"d:{r}:{case.id}:{k.purpose}" for r in runs] + [f"v:{case.id}:{r}" for r in k.alternative_runs]
        self._add(
            {
                "id": k.evidence,
                "channel": f"ex:{case.id}",
                "proposition": {"kind": "comparison", "comparison": k.id, "outcome": k.outcome},
                "kinds": ["run"],
                "premises": premises,
                "provenance": [],
                "uncertainty": k.technical(),
            }
        )
        self.comparisons.append(
            {
                "id": k.id,
                "case": k.case,
                "purpose": k.purpose,
                "oracle": case.purpose(k.purpose).oracle,
                "alternative": k.alternative,
                "baseline_runs": k.baseline_runs,
                "alternative_runs": k.alternative_runs,
                "outcome": k.outcome,
                "tradeoff": {
                    "measurements": {n: {**v, "worse": k.worse[n]} for n, v in k.measurements.items()},
                    "costs": k.costs,
                },
                "divergence": k.divergence,
                "alternating": k.alternating,
                "unverifiable": k.unverifiable,
                **({"substitutes": k.substitutes} if k.substitutes else {}),
                "evidence": k.evidence,
            }
        )

    # -- the case and the runs ------------------------------------------------------------------------------------

    def _case_record(
        self,
        case: Case,
        inputs: list[str],
        u0: dict,
        present: dict[str, bool],
        usable: list[RunState],
        excluded: dict,
        problems: dict,
        missing_why: dict,
    ) -> None:
        recorded = []
        for name in inputs:
            entry = self.frozen[name]
            kinds = ["feature", "purpose", "search_space"] if name.startswith("cases/") else ["oracle"]
            for kind in kinds:
                recorded.append(
                    {
                        "kind": kind,
                        "id": f"{case.id}:{kind}" if kind != "oracle" else Path(name).stem,
                        "path": name,
                        "sha256": entry["changes"][-1]["sha256"] if entry["changes"] else entry["sha256"],
                        "fixed": entry["fixed"],
                        "author": entry["author"],
                        "changes": entry["changes"],
                    }
                )
        sources = []
        for state in self.states.values():
            if state.id in excluded or state in usable:
                ok = state.refused is None
                for kind, type_ in (
                    ("run", "run_record"),
                    ("capture", "capture"),
                    ("observation", "observation_report"),
                ):
                    source = {"id": f"{kind}:{state.id}", "type": type_, "run": state.id, "analysable": ok}
                    if not ok:
                        source["reason"] = state.refused
                    sources.append(source)
        scope = _shared_scope([s.report for s in usable])
        if accepted := self.accepted_versions.get(case.id):
            # runs of another version taken into the experimental case's scope by the author's statement
            # (assessment.yaml)
            scope["compatible_versions"] = accepted
        self.cases.append(
            {
                "id": case.id,
                "feature": case.feature.id,
                "inputs": recorded,
                "purposes": [_purpose(p) for p in case.purposes],
                "oracles": [_oracle(self.ws.oracles[p.oracle], p.id) for p in case.purposes if p.oracle],
                "scope": {
                    "observation": scope,
                    "baseline": u0,
                    "components": [{**_component(c), "present": present[c.id]} for c in case.components],
                    "search_space": [
                        {
                            "id": a.id,
                            "component": a.component,
                            "removal": a.removal,
                            "changes": list(a.changes),
                            "intervention": a.intervention,
                            **({"problems": problems[a.id]} if a.id in problems else {}),
                        }
                        for a in case.alternatives
                    ],
                },
                "untested": [
                    {"purpose": p, "alternative": alt, "reason": why} for (p, alt), why in sorted(missing_why.items())
                ],
                "sources": sources,
                "acquisition": {"run_record": "acquired" if usable else "absent"},
                "excluded": excluded,
            }
        )

    def _runs(self) -> list[dict]:
        out = []
        for state in sorted(self.states.values(), key=lambda s: s.entry.order):
            if not state.cases:
                continue
            run = state.run
            v = state.verification
            out.append(
                {
                    "id": state.id,
                    "cases": state.cases,
                    "alternative": None if state.entry.condition == BASELINE else state.entry.condition,
                    "order": state.entry.order,
                    "time": {"start": run.meta.get("started_at", "?"), "end": run.meta.get("finished_at", "?")},
                    "settings": {
                        "instrumentation": (run.instrumentation or {}).get("settings") or [],
                        "block_hosts": ((run.meta.get("config") or {}).get("capture") or {}).get("block_hosts") or [],
                    },
                    "files": _files(run),
                    "observation_report": {
                        "path": self.ws.file(report_path(self.ws.root, state.id)),
                        "sha256": digest(report_path(self.ws.root, state.id)),
                    },
                    "verification": (
                        {"status": "not_applicable"}
                        if v is None
                        else {
                            "status": v.status,
                            "effect": v.effect,
                            "substitution": v.substitution,
                            **({"substitutes": v.substitutes} if v.substitutes else {}),
                            "unverifiable": v.unverifiable,
                        }
                    ),
                    "divergence": [run.meta["replay"]] if _diverged(run) else [],
                    "decisions": [
                        {
                            "purpose": purpose,
                            "case": case,
                            "oracle": next(
                                p.oracle for c in self.ws.cases if c.id == case for p in c.purposes if p.id == purpose
                            ),
                            "decision": d.decision,
                            "measurements": d.measurements,
                            **({"reason": "; ".join(d.reasons)} if d.reasons else {}),
                            "evidence": f"d:{state.id}:{case}:{purpose}",
                        }
                        for (case, purpose), d in state.decisions.items()
                    ],
                    "costs": oracles.costs(run),
                }
            )
        return out

    def write(self, now: datetime | None, data: Vocabulary, purposes: Vocabulary) -> dict:
        verdandi = sorted({s.report["report"]["verdandi"] for s in self.states.values() if s.report})
        return {
            "report": {
                "created": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                "skuld": skuld.__version__,
                "tools": {"verdandi": ", ".join(verdandi)} if verdandi else {},
                "components": [
                    {"role": "oracle_predicates", "id": "skuld.oracles", "version": oracles.VERSION},
                    {"role": "method", "id": "skuld.verify", "version": verify_version},
                    {"role": "method", "id": "verdandi", "version": ", ".join(verdandi) or "?"},
                    {"role": "vocabulary", **data.reference()},
                    {"role": "vocabulary", **purposes.reference()},
                ],
            },
            "application": {
                "package": self.ws.application.get("package", "?"),
                "version": str(self.ws.application.get("version", "?")),
                "platform": self.ws.application.get("platform", "?"),
            },
            "vocabularies": {"data": data.reference(), "purposes": purposes.reference()},
            "features": [_feature(f) for f in self.features.values()],
            "cases": self.cases,
            "runs": self._runs(),
            "comparisons": self.comparisons,
            "evidence": self.evidence,
        }


#: The uncertainty of a record of a run: low, a run's records state what they state
LOW = of()


def _shared_scope(reports: list[dict]) -> dict:
    """
    The parts of the runs' scopes they share; a part on which they differ is '?'. The instruments'
    configurations are the runs' own (they impose the configuration), as are time and exclusions.
    """
    scopes = [r["scopes"][0] for r in reports if r.get("scopes")]
    if not scopes:
        return {}
    shared = {}
    for key in ("application", "version", "persona", "permissions", "consent"):
        values = [s.get(key) for s in scopes]
        shared[key] = values[0] if all(v == values[0] for v in values) else "?"
    contexts = [{k: v for k, v in (s.get("context") or {}).items() if k != "instruments"} for s in scopes]
    shared["context"] = {
        k: (contexts[0][k] if all(c.get(k) == contexts[0][k] for c in contexts) else "?") for k in contexts[0]
    }
    return shared


def _after(started: str | None, fixed: datetime) -> bool:
    try:
        return datetime.fromisoformat(started) > fixed
    except (TypeError, ValueError):
        return False


def _files(run: Run) -> list[dict]:
    """The digests of the records the analysis read: Loki's record and events, and the capture's export."""
    export = run.directory / (run.meta.get("capture") or {}).get("export", "")
    paths = [run.directory / "run.json", run.directory / "events.jsonl", *sorted(export.glob("*.jsonl"))]
    return [{"path": p.relative_to(run.directory).as_posix(), "sha256": digest(p)} for p in paths if p.is_file()]


def _feature(f) -> dict:
    out = {
        "id": f.id,
        "name": f.name,
        "entry": f.entry,
        "path": {"run": f.path_run, "actions": [f.start, f.actions]}
        if f.path_run
        else {"run": "any", "actions": [0, 0]},
        "outcome": f.outcome,
    }
    if f.contains:
        out["contains"] = list(f.contains)
    return out


def _purpose(p) -> dict:
    return {
        "id": p.id,
        **p.parts,
        "node": p.node,
        "fit": p.fit,
        "provenance": p.provenance,
        "specificity": p.specificity,
        "role": p.role,
        "requirements": list(p.requirements),
        "oracle": p.oracle,
    }


def _oracle(o, purpose: str) -> dict:
    return {
        "id": o.key,
        "version": o.version,
        "purpose": purpose,
        "reach": list(o.reach),
        "observable": True,
        "measurements": [{"name": m.name, "better": m.better, "tolerance": m.tolerance} for m in o.measurements],
        "invalid": [str(i) for i in o.invalid],
    }


def _component(c) -> dict:
    out = {"id": c.id, "dimension": c.dimension}
    for key in ("node", "entity", "value", "name"):
        if getattr(c, key) not in (None, ""):
            out[key] = getattr(c, key)
    return out


# -- the experimental channel in the assessment -------------------------------------------------------------------------

#: The case report the assessment reads, in a folder that is both an assessment and a case workspace
CASE_REPORT = "report.json"


def case_report(cases: Workspace | None, root: Path) -> dict | None:
    path = root / CASE_REPORT
    if cases is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _comparison(k: dict) -> Comparison:
    measured = (k.get("tradeoff") or {}).get("measurements") or {}
    return Comparison(
        id=k["id"],
        case=k["case"],
        purpose=k["purpose"],
        alternative=k["alternative"],
        baseline_runs=k["baseline_runs"],
        alternative_runs=k["alternative_runs"],
        outcome=k["outcome"],
        worse={n: m.get("worse", "none") for n, m in measured.items()},
        unverifiable=k.get("unverifiable") or [],
        alternating=k.get("alternating", True),
        substitutes=k.get("substitutes") or [],
    )


def case_claims(cases: Workspace, report: dict) -> dict[str, list[rules.Claim]]:
    """The experimental channel's claims per case, read by the status rule from the case report's measurements: the
    comparisons, the components present in the baseline, the alternatives that are no members of the search space
    and why the others were not compared."""
    by_case = {c["id"]: c for c in report["cases"]}
    data = vocabulary(DATA_VOCABULARY)
    out = {}
    for case in cases.cases:
        measured = by_case.get(case.id)
        if measured is None:
            continue
        present = {c["id"]: c.get("present", False) for c in measured["scope"]["components"]}
        unknown = [c.id for c in case.components if c.id not in present]
        if unknown:
            raise AnalysisError(
                f"the case report has no component {', '.join(unknown)} of case {case.id}: run skuld analyse again"
            )
        invalid = {a["id"] for a in measured["scope"]["search_space"] if a.get("problems")}
        missing_why = {(u["purpose"], u["alternative"]): u["reason"] for u in measured.get("untested") or ()}
        compared = {
            (k["purpose"], k["alternative"]): _comparison(k) for k in report["comparisons"] if k["case"] == case.id
        }
        out[case.id] = rules.claims(case, present, compared, missing_why, invalid, data)
    return out


def premises(cases: Workspace | None, root: Path, practices: list, item) -> list[dict]:
    """
    The experimental channel's claims as premises of the assessment stage: each claim of an experimental case's
    experimental channel (`ex:<case>`), once per practice whose component the case's component varies (`space.varies`),
    with the case's purpose (provenance `case`) and the requirements its oracle reaches. `item(key, fields)` gives the
    evidence item of a comparison, of kind run, which points into the case report.
    """
    report = case_report(cases, root)
    if report is None:
        return []
    data = vocabulary(DATA_VOCABULARY)
    out: list[dict] = []
    for case_id, made in case_claims(cases, report).items():
        case = next(c for c in cases.cases if c.id == case_id)
        for n, c in enumerate(made, 1):
            component = case.component(c.component)
            purpose = case.purpose(c.purpose)
            oracle = cases.oracles.get(purpose.oracle) if purpose.oracle else None
            items = {
                k.evidence: item(
                    k.id,
                    {
                        "kind": "run",
                        "stage": "assessment",
                        "channel": f"ex:{case.id}",
                        "case": CASE_REPORT,
                        "premises": [k.id],
                        "method": f"the case report's comparison {k.id} ({k.outcome}"
                        + (f"; substitute: {', '.join(k.substitutes)}" if k.substitutes else "")
                        + ")",
                        "uncertainty": k.technical(),
                    },
                )
                for k in c.comparisons
            }
            decisive = c.status in ("supported", "refuted")
            for practice in practices:
                varied = space.varies(component.__dict__, practice, data)
                if varied is None:
                    continue
                x = {
                    "id": f"ex:{case.id}:{n}",
                    "type": c.type,
                    "stage": "assessment",
                    "channels": [f"ex:{case.id}"],
                    "subject": practice.id,
                    "case": case.id,
                    "scope": {"case": case.id, "requirements": list(oracle.reach) if oracle and c.comparisons else []},
                    "purpose": {
                        "id": purpose.id,
                        **purpose.parts,
                        "node": purpose.node,
                        "role": purpose.role,
                        "specificity": purpose.specificity,
                        "provenance": "case",
                        # where the case states it, it wins over stage 1's inference (gaps.oracle_step)
                        **({"achieved_on": purpose.achieved_on} if purpose.achieved_on else {}),
                    },
                    "component": varied,
                    "status": c.status,
                    # C1: whether a comparison broke the purpose (combine.experimental aligns it also below its node)
                    "broke": any(k.outcome == "breaks" for k in c.comparisons),
                    "supporting": [items[i] for i in c.supporting],
                    "challenging": [items[i] for i in c.challenging],
                    "uncertainty": needs(
                        *(k.technical() for k in c.comparisons),
                        of(*([] if purpose.provenance == "feature" else ["purpose_not_from_feature"])),
                    ),
                    "sufficiency": {
                        "sufficient": decisive,
                        **({} if decisive else {"reason": c.why, "missing": c.missing}),
                    },
                    **({"strength": "run"} if decisive else {}),
                    **({"relationship": c.relationship} if c.relationship else {}),
                    **({"alternative": f"{case.id}:{c.alternative}", "level": "demonstrated"} if c.alternative else {}),
                    # a substitutable dependency names its substitutes though it is supported
                    **(
                        {"reason": c.reason} if c.reason and (not decisive or c.relationship == "substitutable") else {}
                    ),
                }
                out.append(x)
    return out


def device_seconds(cases: Workspace | None, root: Path) -> float:
    """The device time of the case report's runs, from their start to their end."""
    report = case_report(cases, root)
    total = 0.0
    for run in (report or {}).get("runs", []):
        t = run.get("time") or {}
        if t.get("start") and t.get("end"):
            total += (datetime.fromisoformat(t["end"]) - datetime.fromisoformat(t["start"])).total_seconds()
    return round(total, 3)


def _compatible(root: Path, version: str) -> dict[str, dict]:
    """
    The versions the author states compatible with the experimental case's (`compatible_versions` of the workspace's
    assessment.yaml, where the workspace is also an assessment workspace), each with its statement: a run of such a
    version is in the case's scope.
    """
    from skuld.inputs import ASSESSMENT, _compatible_versions

    path = root / ASSESSMENT
    if not path.is_file():
        return {}

    out = {}
    for statement in _compatible_versions(yamlio.load(path.read_text(encoding="utf-8")) or {}):
        versions = [str(v) for v in statement["versions"]]
        if version in versions:
            other = versions[1 - versions.index(version)]
            out[other] = {**statement, "versions": versions, "fixed": str(statement["fixed"])}
    return out
