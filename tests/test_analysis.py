"""The experimental channel from inputs to the case report, and the claims the status rule reads from its measurements,
on a synthetic workspace and on the dry run's records."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from ratatoskr.schemas import validate

from skuld import inputs
from skuld.experiments import AnalysisError, analyse, case_claims
from skuld.report import write
from tests import workspace as ws


def analysed(root: Path) -> tuple[dict, list]:
    """The case report of a workspace, and the experimental channel's claims read from it."""
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    return report, [c for made in case_claims(workspace, report).values() for c in made]


def claim(made: list, type_: str, purpose: str, **arguments):
    """The one claim of a type, purpose and arguments."""
    found = [
        c
        for c in made
        if c.type == type_ and c.purpose == purpose and all(getattr(c, k) == v for k, v in arguments.items())
    ]
    assert len(found) == 1, (type_, purpose, arguments, found)
    return found[0]


def technical(report: dict, alternative: str) -> str:
    from skuld.experiments import _comparison

    return _comparison(next(k for k in report["comparisons"] if k["alternative"] == alternative)).technical()


def test_preserving_removals_show_no_dependency_and_demonstrate_the_alternatives(tmp_path):
    report, made = analysed(ws.build(tmp_path))
    validate("expectation_report", report)
    for component, alternative in (("aaid", "A1"), ("tracker", "A2")):
        dependency = claim(made, "dependency", "P1", component=component)
        assert (dependency.relationship, dependency.status) == ("not_dependent", "supported")
        assert claim(made, "alternative", "P1", alternative=alternative).status == "supported"
    assert {c.status for c in made if c.purpose == "P2"} == {"not_assessable"}
    assert {c.why for c in made if c.purpose == "P2"} == {"oracle_not_observable"}


def test_a_supported_status_rests_on_its_comparison_and_a_refuted_one_challenges(tmp_path):
    plan = [(c, {"done": c != "A1"}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    _, made = analysed(ws.build(tmp_path, plan))
    supported = claim(made, "dependency", "P1", component="aaid")
    refuted = claim(made, "alternative", "P1", alternative="A1")
    assert supported.supporting == ["k:start:P1:A1"] and supported.challenging == []
    assert refuted.challenging == ["k:start:P1:A1"] and refuted.supporting == []


def test_unhooked_identifier_sources_are_unverifiable_and_raise_technical_uncertainty(tmp_path):
    report, _ = analysed(ws.build(tmp_path))
    a1 = next(r for r in report["runs"] if r["alternative"] == "A1")
    assert a1["verification"]["status"] == "verified"
    assert any("android-id" in part for part in a1["verification"]["unverifiable"])
    assert technical(report, "A1") == "moderate" and technical(report, "A2") == "low"


def test_connections_without_a_host_leave_a_removed_recipient_partly_unverifiable(tmp_path):
    plan = [(c, {"hostless": c == "A2"}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    report, _ = analysed(ws.build(tmp_path, plan))
    a2 = next(r for r in report["runs"] if r["alternative"] == "A2")
    assert a2["verification"]["status"] == "verified"
    assert any("without a host" in part for part in a2["verification"]["unverifiable"])
    comparison = next(k for k in report["comparisons"] if k["alternative"] == "A2")
    assert any("without a host" in part for part in comparison["unverifiable"])
    assert technical(report, "A2") == "moderate"


def test_counted_quic_flows_with_a_host_are_judged_by_their_host(tmp_path):
    # Heimdall's manifest counts QUIC as an exclusion, but the connections carry their host
    plan = [(c, {"exclusions": {"quic": 2} if c == "A2" else {}}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    report, _ = analysed(ws.build(tmp_path, plan))
    a2 = next(r for r in report["runs"] if r["alternative"] == "A2")
    assert not a2["verification"]["unverifiable"]
    assert technical(report, "A2") == "low"


def test_the_verification_is_derived_from_the_items_it_rests_on(tmp_path):
    report = analyse(inputs.load(ws.build(tmp_path)), make_observations=False)
    items = {e["id"]: e for e in report["evidence"]}
    run = next(r["id"] for r in report["runs"] if r["alternative"] == "A1")
    verification = items[f"v:start:{run}"]
    assert verification["provenance"] == [] and verification["premises"]
    assert all(items[p]["provenance"] for p in verification["premises"])
    comparison = items["k:start:P1:A1"]
    assert f"v:start:{run}" in comparison["premises"]


def test_a_run_of_another_version_is_outside_the_scope(tmp_path):
    root = ws.build(tmp_path, freeze=False)
    record = root / "runs" / "run-01" / "run.json"
    meta = json.loads(record.read_text(encoding="utf-8"))
    meta["app"] = {"version_name": "2.0"}
    record.write_text(json.dumps(meta))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    assert report["cases"][0]["excluded"]["run-01"].startswith("outside the case's scope")


def test_a_run_of_a_version_the_author_states_compatible_is_in_the_scope(tmp_path):
    """CamScanner, 12 Nov 2026: Play installed 7.28.5 for cases of 7.27.5; the author stated them compatible."""
    import yaml

    root = ws.build(tmp_path, freeze=False)
    record = root / "runs" / "run-01" / "run.json"
    meta = json.loads(record.read_text(encoding="utf-8"))
    meta["app"] = {"version_name": "2.0"}
    record.write_text(json.dumps(meta))
    version = str(inputs.load(root).application["version"])
    statement = {
        "versions": [version, "2.0"],
        "reason": "r",
        "author": {"kind": "human", "id": "a"},
        "fixed": "2026-11-12",
    }
    (root / "assessment.yaml").write_text(yaml.safe_dump({"compatible_versions": [statement]}))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    case = analyse(inputs.load(root), make_observations=False)["cases"][0]
    assert "run-01" not in case["excluded"]
    assert case["scope"]["observation"]["compatible_versions"][0]["versions"] == [version, "2.0"]


def test_an_alternative_whose_intervention_imposes_nothing_is_not_tested(tmp_path):
    root = ws.build(tmp_path, freeze=False)
    case = root / "cases" / "start.yaml"
    case.write_text(
        case.read_text(encoding="utf-8").replace("block_hosts:\n      - tracker.example", "block_hosts: []"),
        encoding="utf-8",
    )
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report, made = analysed(root)
    a2 = next(a for a in report["cases"][0]["scope"]["search_space"] if a["id"] == "A2")
    assert any("does not impose" in p for p in a2["problems"])
    # no member of the search space: no claim, and the reason it was not compared
    assert not [c for c in made if c.alternative == "A2" or c.component == "tracker"]
    assert {"purpose": "P1", "alternative": "A2", "reason": "precondition_failed"} in report["cases"][0]["untested"]


def test_runs_that_do_not_alternate_are_compared_at_a_raised_technical_uncertainty(tmp_path):
    plan = [("baseline", {})] * 3 + [("A1", {})] * 3 + [("A2", {})] * 3
    report, made = analysed(ws.build(tmp_path, plan))
    comparison = next(k for k in report["comparisons"] if k["alternative"] == "A2")
    assert comparison["alternating"] is False
    assert claim(made, "alternative", "P1", alternative="A2").status == "supported"
    assert technical(report, "A2") == "moderate"


def test_a_hooked_source_the_application_did_not_read_holds_its_effect(tmp_path):
    root = ws.build(tmp_path, freeze=False)
    for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["condition"] == "A1":
            path = root / "observation" / entry["run"] / "observation_report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["evidence"] = []
            report["claims"] = [c for c in report["claims"] if c["type"] != "accesses"]
            for c in report["claims"]:
                c["evidence"] = ["none"]
            path.write_text(json.dumps(report))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    a1 = next(r for r in report["runs"] if r["alternative"] == "A1")
    assert a1["verification"]["status"] == "verified"
    assert a1["verification"]["effect"][0]["note"] == "the application did not read the source"


def test_a_breaking_removal_supports_essential_and_refutes_its_alternative(tmp_path):
    plan = [(c, {"done": c != "A1"}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    _, made = analysed(ws.build(tmp_path, plan))
    dependency = claim(made, "dependency", "P1", component="aaid")
    assert (dependency.relationship, dependency.status) == ("essential", "supported")
    assert claim(made, "alternative", "P1", alternative="A1").status == "refuted"


def test_a_measurement_worse_in_every_run_reads_quality_dependent(tmp_path):
    plan = [(c, {"app_messages": 0 if c == "A1" else 2}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    _, made = analysed(ws.build(tmp_path, plan))
    dependency = claim(made, "dependency", "P1", component="aaid")
    assert (dependency.relationship, dependency.status) == ("quality_dependent", "supported")


def test_a_difference_within_the_tolerance_is_no_difference(tmp_path):
    plan = [(c, {"app_messages": 1 if c == "A1" else 2}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    _, made = analysed(ws.build(tmp_path, plan))
    assert claim(made, "dependency", "P1", component="aaid").relationship == "not_dependent"


def test_an_unverified_intervention_is_no_evidence(tmp_path):
    root = ws.build(tmp_path, freeze=False)
    for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["condition"] == "A1":  # the app was handed the device's identifier after all
            path = root / "observation" / entry["run"] / "observation_report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["evidence"][0]["proposition"]["value"] = ws.DEVICE_ID
            path.write_text(json.dumps(report))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report, made = analysed(root)
    assert all(r["verification"]["status"] == "failed" for r in report["runs"] if r["alternative"] == "A1")
    dependency = claim(made, "dependency", "P1", component="aaid")
    assert (dependency.status, dependency.why) == ("not_established", "intervention_not_verified")


def test_a_run_whose_instrumentation_failed_is_no_evidence(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    record = root / "runs" / "run-02" / "run.json"  # the first run under A1
    meta = json.loads(record.read_text(encoding="utf-8"))
    meta["instrumentation"].update(error="app_start_held", detail="held 1745 ms, over the limit of 1000 ms")
    record.write_text(json.dumps(meta))
    ws.rescope(root)  # O's scope gives the instrumentation's record
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    run = next(r for r in report["runs"] if r["id"] == "run-02")
    assert run["verification"]["status"] == "failed"
    assert "app_start_held" in run["verification"]["effect"][0]["note"]


def test_a_run_the_assessor_excluded_is_listed_with_the_reason_and_judges_nothing(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    lines = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    lines[0]["excluded"] = "the app was closed by hand during the run"
    (root / "runs.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    assert (
        report["cases"][0]["excluded"]["run-01"]
        == "excluded by the assessor: the app was closed by hand during the run"
    )
    assert all("run-01" not in k["baseline_runs"] for k in report["comparisons"])


def test_runs_made_before_the_inputs_were_fixed_judge_nothing(tmp_path):
    root = ws.build(tmp_path, freeze=False)
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat("2026-10-21T12:00:00+00:00"))
    report = analyse(inputs.load(root), make_observations=False)
    assert report["comparisons"] == []
    assert all(v == "made before the case's inputs were fixed" for v in report["cases"][0]["excluded"].values())


def test_a_fixed_input_removed_without_a_record_is_refused(tmp_path):
    root = ws.build(tmp_path)
    (root / "cases" / "start.yaml").unlink()  # its oracle stays, unused
    with pytest.raises(inputs.InputError, match="cases/start.yaml was removed without a record"):
        inputs.check_frozen(inputs.load(root))


def test_an_input_changed_without_a_record_is_refused_and_a_recorded_change_is_reported(tmp_path):
    root = ws.build(tmp_path)
    oracle = root / "oracles" / "O@1.yaml"
    oracle.write_text(oracle.read_text(encoding="utf-8") + "# a later note\n", encoding="utf-8")
    with pytest.raises(AnalysisError, match="changed without a record"):
        analyse(inputs.load(root), make_observations=False)
    with pytest.raises(inputs.InputError):
        inputs.freeze(root, ws.AUTHOR)
    inputs.change(root, "oracles/O@1.yaml", "a comment")
    report = analyse(inputs.load(root), make_observations=False)
    recorded = next(i for i in report["cases"][0]["inputs"] if i["kind"] == "oracle")
    assert recorded["fixed"] == ws.FIXED and recorded["changes"][0]["reason"] == "a comment"


def test_the_report_is_written_valid_with_a_rendering(tmp_path):
    root = ws.build(tmp_path)
    json_path, md_path = write(analyse(inputs.load(root), make_observations=False), root)
    validate("expectation_report", json.loads(json_path.read_text(encoding="utf-8")))
    assert "| start | P1 | A1 | 3 + 3 | preserves |" in md_path.read_text(encoding="utf-8")


def _dry_run() -> Path | None:
    root = os.environ.get("SKULD_DRY_RUN") or (
        Path(__file__).parents[1] / "workspaces" / "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4"
    )
    root = Path(root)
    return root if (root / "observation").is_dir() else None


@pytest.mark.skipif(_dry_run() is None, reason="no dry-run workspace with observation reports")
def test_the_dry_run_gives_the_worked_examples_experimental_claims():
    workspace = inputs.load(_dry_run())
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)
    by_case = case_claims(workspace, report)
    for case, purpose in (("launch", "P-L1"), ("onboarding", "P-O1")):
        for component in ("x-aaid", "x-appsflyer"):
            mine = [c for c in by_case[case] if c.purpose == purpose and c.component == component]
            dependency = next(c for c in mine if c.type == "dependency")
            assert (dependency.relationship, dependency.status) == ("not_dependent", "supported")
            assert next(c for c in mine if c.type == "alternative").status == "supported"
    assert {c.status for c in by_case["launch"] if c.purpose == "P-L2"} == {"not_assessable"}
    assert technical(report, "A1") == "moderate"
    assert all(r["verification"]["status"] in ("verified", "not_applicable") for r in report["runs"])


def test_a_replay_that_departs_within_the_features_path_is_no_run_of_it(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    case = root / "cases" / "start.yaml"
    case.write_text(
        case.read_text(encoding="utf-8").replace("  path: null", "  path: {run: rec-1, actions: 1}"), encoding="utf-8"
    )
    (root / "runs" / "rec-1").mkdir()
    (root / "runs" / "rec-1" / "events.jsonl").write_text(
        json.dumps({"seq": 3, "type": "screen"}) + "\n" + json.dumps({"seq": 5, "type": "action"}) + "\n"
    )

    def depart(run_id, source_seq):
        events = root / "runs" / run_id / "events.jsonl"
        events.write_text(
            events.read_text(encoding="utf-8")
            + json.dumps({"seq": 99, "type": "divergence", "source_seq": source_seq})
            + "\n"
        )

    depart("run-02", 5)  # within the path
    depart("run-03", 9)  # after it
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    report = analyse(inputs.load(root), make_observations=False)
    excluded = report["cases"][0]["excluded"]
    assert excluded["run-02"].startswith("did not follow the feature's path: 1 departure(s)")
    assert "run-03" not in excluded


def test_a_case_its_qualifying_replay_did_not_qualify_is_not_judged(tmp_path):
    root = ws.build(tmp_path / "ws")
    (root / "qualification.json").write_text(json.dumps({"run": "run-01", "cases": {"start": ["O@1 decides unmet"]}}))
    report = analyse(inputs.load(root), make_observations=False)
    assert not report["comparisons"]
    problems = {a["id"]: a["problems"] for a in report["cases"][0]["scope"]["search_space"]}
    assert set(problems) == {"A1", "A2"}
    assert all("did not qualify: O@1 decides unmet" in p[0] for p in problems.values())


def test_a_recipient_no_baseline_run_reaches_is_not_compared_and_its_claims_are_not_applicable(tmp_path):
    """C2 (author, 14 Nov 2026): an intervention that varies nothing on the case's path decides nothing."""
    root = ws.build(tmp_path, freeze=False)
    for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["condition"] == "baseline":
            path = root / "observation" / entry["run"] / "observation_report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["claims"] = [c for c in report["claims"] if c["id"] != "t2"]  # no transmission to the tracker
            path.write_text(json.dumps(report))
    inputs.freeze(root, ws.AUTHOR, now=datetime.fromisoformat(ws.FIXED))
    workspace = inputs.load(root)
    report = analyse(workspace, make_observations=False)
    validate("expectation_report", report)
    assert {k["alternative"] for k in report["comparisons"]} == {"A1"}
    made = [c for m in case_claims(workspace, report).values() for c in m]
    assert {c.status for c in made if c.component == "tracker" and c.purpose == "P1"} == {"not_applicable"}
    assert claim(made, "alternative", "P1", alternative="A1").status == "supported"
