"""Experiments in the assessment: the components a case varies, ≈ between case and hypothesis purposes, the
combination deciding by strength, concern (v) from a comparison, and the choice of experiments."""

import json
from types import SimpleNamespace

import pytest
from ratatoskr.frames import Frame
from ratatoskr.vocabularies import Vocabulary

from skuld import combine, concerns, select, space
from skuld.uncertainty import of

DATA = Vocabulary.load("asgard-data")
PURPOSES = Vocabulary.load("dpv-purposes")
#: A hypothesis from documents, and a premise whose comparison had too few runs
DOC = of("from_documents")
RUN = of("few_runs")


@pytest.fixture(autouse=True)
def every_purpose_observable(request, monkeypatch):
    """The selection's other rules are tested on purposes any experiment could observe; the tests of observability
    (marked `catalogue`) read Skuld's catalogue."""
    if "catalogue" not in request.keywords:
        monkeypatch.setattr(
            select, "observed_purposes", lambda: [("Purpose", b) for b in ("user", "provider", "other")]
        )


def practice(pid, data, recipient=None, claim_type="accesses", relation=None):
    return SimpleNamespace(
        id=pid,
        data=data,
        recipient=recipient,
        claim_type=claim_type,
        party={"relation": relation} if relation else None,
        episodes=["1"],
    )


def hypothesis(pid, subject, node, who="user", status="supported"):
    return {
        "id": pid,
        "type": "purpose",
        "stage": "expectation",
        "of": [f"e1/s1:p{pid[-1]}"],
        "subject": subject,
        "purpose": {"node": node, "beneficiary": who},
        "status": status,
        "channels": ["reasoning:e1/s1"],
        "supporting": [],
        "challenging": [],
        "uncertainty": DOC,
        "sufficiency": {"sufficient": True},
    }


def premise(n, kind, status, subject="P-loc", node="ServiceProvision", **fields):
    return {
        "id": f"ex:forecast:{n}",
        "type": kind,
        "stage": "assessment",
        "channels": ["ex:forecast"],
        "subject": subject,
        "case": "forecast",
        "scope": {"case": "forecast", "requirements": ["R-W1.1"]},
        "purpose": {"id": "P-W1", "node": node, "beneficiary": "user", "provenance": "case"},
        "component": f"{subject}.data",
        "status": status,
        "supporting": [f"x{n}"] if status == "supported" else [],
        "challenging": [f"x{n}"] if status == "refuted" else [],
        "uncertainty": RUN,
        "sufficiency": {"sufficient": status in ("supported", "refuted")},
        **({"strength": "run"} if status in ("supported", "refuted") else {}),
        **fields,
    }


def test_a_case_component_varies_the_practices_of_its_datum_and_recipient():
    loc = {"id": "x-loc", "dimension": "G", "node": "location.coordinates"}
    tracker = {"id": "x-adco", "dimension": "R", "entity": "adco"}
    assert space.varies(loc, practice("P1", "location.coordinates"), DATA) == "P1.data"
    assert space.varies({**loc, "node": "location"}, practice("P1", "location.coordinates"), DATA) == "P1.data"
    assert space.varies(loc, practice("P2", "location.city"), DATA) is None
    assert space.varies(tracker, practice("P3", "data", "adco", "transmits"), DATA) == "P3.recipient"
    assert space.varies(tracker, practice("P4", "data", "other", "transmits"), DATA) is None


def test_skuld_imposes_what_its_rules_derive_and_never_blocks_the_provider():
    assert space.imposable(practice("P1", "location.coordinates")) == [
        {"component": "P1.data", "dimension": "G", "alternatives": ["G-round1", "G-round0"]}
    ]
    assert space.imposable(practice("P2", "device-or-other-ids.advertising-id"))[0]["alternatives"] == [
        "D-advertising_id"
    ]
    assert space.imposable(practice("P3", "data", "adco", "transmits", "other"))[0]["alternatives"] == ["R-adco"]
    assert space.imposable(practice("P4", "data", "example", "transmits", "own")) == []
    assert space.imposable(practice("P5", "data", "domain:cdn.example", "transmits")) == []


def test_a_hypothesis_aligns_with_the_nearest_case_purpose_above_it_of_its_beneficiary():
    cases = [
        {"id": "P-A", "node": "ServiceManagement", "beneficiary": "user"},
        {"id": "P-B", "node": "ServiceProvision", "beneficiary": "user"},
        {"id": "P-C", "node": "ServiceProvision", "beneficiary": "provider"},
    ]
    to = combine.aligned(
        [
            hypothesis("claim:P:1", "P", "RequestedServiceProvision"),
            hypothesis("claim:P:2", "P", "Advertising", "provider"),
        ],
        cases,
        PURPOSES,
    )
    assert to == {"claim:P:1": cases[1]}


def test_a_comparison_decides_over_reasoning_and_stands_alone_where_reasoning_is_silent():
    h = hypothesis("claim:P-loc:1", "P-loc", "ServiceProvision")
    guessed = {
        **h,
        "id": "claim:P-loc:2",
        "type": "dependency",
        "basis": ["claim:P-loc:1"],
        "component": "P-loc.data",
        "relationship": "essential",
        "status": "supported",
        "strength": "doc",
    }
    premises = [
        premise(1, "dependency", "refuted", relationship="essential"),
        premise(3, "dependency", "supported", subject="P-ads", node="ServiceProvision", relationship="not_dependent"),
    ]
    out = combine.experimental([h, guessed], premises, PURPOSES, combine.Numbers())
    essential = next(c for c in out if c["type"] == "dependency" and c["subject"] == "P-loc")
    assert (essential["status"], essential["relationship"], essential["strength"]) == ("refuted", "essential", "run")
    assert essential["of"] == ["ex:forecast:1", "claim:P-loc:2"] and essential["basis"] == ["claim:P-loc:1"]
    assert essential["challenging"] == ["x1"] and essential["supporting"] == []
    silent = next(c for c in out if c["subject"] == "P-ads")
    assert silent["status"] == "supported" and silent["basis"] == [] and silent["of"] == ["ex:forecast:3"]


def test_a_demonstrated_alternative_is_a_minimisation_concern():
    frame = Frame.load("gdpr-art5")
    h = hypothesis("claim:P-loc:1", "P-loc", "ServiceProvision")
    tested = combine.experimental(
        [h],
        [
            premise(1, "alternative", "supported", alternative="forecast:G1", level="demonstrated"),
            premise(2, "alternative", "refuted", alternative="forecast:G0", level="demonstrated"),
        ],
        PURPOSES,
        combine.Numbers(),
    )
    stated, covered = concerns.less_invasive_alternative(frame, [h], [], set(), {}, tested)
    assert [(c.requirement, c.subject) for c in covered] == [("data_minimised", "P-loc")] and len(stated) == 1
    c = stated[0]
    assert c.status == "supported"
    assert "forecast:G1 demonstrated" in c.reason
    assert c.channels == ["ex:forecast"] and c.supporting == ["x1"]
    # the run's, the purpose's and the judgement of minimal; demonstrated, so no not_demonstrated
    assert c.uncertainty == {
        "level": "moderate",
        "reasons": [
            {"reason": "few_runs", "level": "moderate"},
            {"reason": "from_documents", "level": "moderate"},
            {"reason": "open_judgement", "level": "moderate"},
        ],
    }


def test_an_experiment_that_cannot_observe_the_purpose_leaves_the_concern_not_assessable():
    frame = Frame.load("gdpr-art5")
    h = hypothesis("claim:P-ads:1", "P-ads", "Advertising", "provider")
    reason = "the purpose has no observable oracle"
    unobservable = premise(1, "alternative", "not_assessable", subject="P-ads", node="Marketing", reason=reason)
    unobservable["sufficiency"] = {"sufficient": False, "reason": "oracle_not_observable"}
    unobservable["alternative"] = "launch:A1"
    tested = combine.experimental([h], [unobservable], PURPOSES, combine.Numbers())
    for t in tested:
        t["basis"] = ["claim:P-ads:1"]
    stated, _ = concerns.less_invasive_alternative(frame, [h], [], set(), {}, tested)
    assert (stated[0].status, stated[0].reason) == ("not_assessable", reason)


def test_an_experiment_that_decided_nothing_neither_merges_hypotheses_nor_gives_a_concern_a_premise():
    """12 Nov 2026: pedometer's launch Marketing purpose (no oracle) merged E's Advertising (supported) and
    TargetedAdvertising (not established) hypotheses into one claim; Weather's undecided comparison created a
    minimisation concern E's reasoning had not raised. Neither happens now: such a premise stands alone."""
    frame = Frame.load("gdpr-art5")
    ads = hypothesis("claim:P-ads:1", "P-ads", "Advertising", "provider")
    targeted = hypothesis("claim:P-ads:2", "P-ads", "TargetedAdvertising", "provider")
    deps = [
        {
            **ads,
            "id": "claim:P-ads:3",
            "type": "dependency",
            "basis": ["claim:P-ads:1"],
            "component": "P-ads.data",
            "status": "supported",
        },
        {
            **targeted,
            "id": "claim:P-ads:4",
            "type": "dependency",
            "basis": ["claim:P-ads:2"],
            "component": "P-ads.data",
            "status": "not_established",
        },
    ]
    unobservable = premise(1, "dependency", "not_assessable", subject="P-ads", node="Marketing")
    out = combine.experimental([ads, targeted, *deps], [unobservable], PURPOSES, combine.Numbers())
    assert [(c["of"], c["basis"], c["status"]) for c in out] == [(["ex:forecast:1"], [], "not_assessable")]
    loc = hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision")
    undecided = premise(2, "alternative", "not_established", alternative="forecast:G1")
    tested = combine.experimental([loc], [undecided], PURPOSES, combine.Numbers())
    assert [c["basis"] for c in tested] == [[]]
    stated, covered = concerns.less_invasive_alternative(frame, [loc], [], set(), {}, tested)
    assert stated == [] and covered == []


def report(claims, concerns_=()):
    return {"claims": claims, "concerns": list(concerns_)}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 0, "repeats": 3, "run_seconds": 100})
    practices = [
        {"id": "P-loc", "claim_type": "accesses", "data": "location.coordinates", "recipient": None, "episodes": ["1"]},
        {
            "id": "P-ads",
            "claim_type": "transmits",
            "data": "data",
            "recipient": "adco",
            "episodes": ["0"],
            "party": {"relation": "other"},
        },
        {
            "id": "P-own",
            "claim_type": "transmits",
            "data": "data",
            "recipient": "example",
            "episodes": ["2"],
            "party": {"relation": "own"},
        },
    ]
    (tmp_path / "subjects.json").write_text(json.dumps({"practices": practices}))
    claims = [
        hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision"),
        hypothesis("claim:P-ads:1", "P-ads", "Advertising", "provider"),
        hypothesis("claim:P-own:1", "P-own", "ServiceOptimisation", "provider"),
        hypothesis("claim:P-own:2", "P-own", "ServiceMonitoring", "provider", status="not_established"),
    ]
    (tmp_path / "assessment.json").write_text(json.dumps(report(claims)))
    return tmp_path


def test_with_experiments_off_every_candidate_is_refused_with_its_reason(workspace):
    selection = select.select(workspace)
    by = {e["purpose"]: e for e in selection["entries"]}
    assert set(by) == {"claim:P-loc:1", "claim:P-ads:1", "claim:P-own:1"}  # supported purposes only
    assert by["claim:P-own:1"]["reason"] == "Skuld can impose nothing on its components"
    assert all(e["kind"] == select.REFUSAL for e in by.values())
    assert "experiments are off" in by["claim:P-loc:1"]["reason"]
    assert by["claim:P-loc:1"]["cost_seconds"] == ((1 + 2) * 3 + 1) * 100
    assert selection["device_seconds"] == 0
    with pytest.raises(select.SelectionError):
        select.select(workspace)


def test_a_pursued_practice_is_chosen_and_the_budget_takes_the_rest_in_order(workspace, monkeypatch):
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-ads, reason: pursue}\n")
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 1000, "repeats": 3, "run_seconds": 100})
    selection = select.select(workspace)
    by = {e["purpose"]: e for e in selection["entries"]}
    assert by["claim:P-ads:1"]["kind"] == select.CHOICE and by["claim:P-ads:1"]["reason"].startswith("pursued")
    assert by["claim:P-loc:1"]["kind"] == select.REFUSAL and "over the budget" in by["claim:P-loc:1"]["reason"]
    named = select.named(workspace)
    assert {(n["kind"], n["id"]) for n in named} >= {(select.CHOICE, "selection:P-ads:1")}
    assert all(len(n["sha256"]) == 64 for n in named)
    episodes, keep = select.keeps(selection, DATA)
    assert episodes == {"0"}
    assert keep({"id": "x-adco", "dimension": "R", "entity": "adco"})
    assert not keep({"id": "x-loc", "dimension": "G", "node": "location.coordinates"})


def test_what_an_experiment_decided_or_could_not_assess_is_not_asked_again(workspace):
    claims = json.loads((workspace / "assessment.json").read_text(encoding="utf-8"))["claims"]
    decided = {**premise(1, "alternative", "supported"), "id": "claim:P-loc:2", "basis": ["claim:P-loc:1"]}
    tried = {
        **premise(2, "alternative", "not_assessable", subject="P-ads"),
        "id": "claim:P-ads:2",
        "basis": ["claim:P-ads:1"],
        "reason": "no oracle observes the purpose",
    }
    (workspace / "assessment.json").write_text(json.dumps(report(claims + [decided, tried])))
    by = {e["purpose"]: e for e in select.select(workspace)["entries"]}
    assert "claim:P-loc:1" not in by
    assert by["claim:P-ads:1"]["kind"] == select.REFUSAL and "could not assess it" in by["claim:P-ads:1"]["reason"]


def test_a_combined_claims_uncertainty_is_either_over_agreeing_members_else_needs_over_all():
    run = of("few_runs", "runs_not_alternated")
    model = of("own_knowledge")
    members = [{"uncertainty": run}, {"uncertainty": model}]
    assert combine._uncertainty(members, minimum=False) == {
        "level": "high",
        "reasons": [
            {"reason": "own_knowledge", "level": "high"},
            {"reason": "few_runs", "level": "moderate"},
            {"reason": "runs_not_alternated", "level": "moderate"},
        ],
    }
    # the alternative of the lowest level, with its own reasons only
    assert combine._uncertainty(members, minimum=True) == run


def test_an_undecided_combination_gives_the_reason_of_the_claims_that_were_assessed():
    def sample(n, status, reason):
        return {
            **hypothesis(f"b/s{n}:p0", "P", "ServiceProvision", status=status),
            "channels": [f"reasoning:b/s{n}"],
            "sufficiency": {"sufficient": False, "missing": [reason]},
            "reason": reason,
        }

    out = combine.hypotheses(
        [
            sample(1, "not_established", "its action is not shown by the context"),
            sample(2, "not_assessable", "too vague"),
        ],
        combine.Numbers(),
    )
    # the sample that could not assess it abstains (combination 2, author 13 Nov 2026)
    assert (out[0]["status"], out[0]["reason"]) == ("not_established", "its action is not shown by the context")


def test_the_chosen_entries_name_their_reason(workspace, monkeypatch):
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-loc, reason: calibrate}\n")
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 0, "repeats": 3, "run_seconds": 100})
    by = {e["purpose"]: e for e in select.select(workspace)["entries"]}
    assert by["claim:P-loc:1"]["kind"] == select.CHOICE and by["claim:P-loc:1"]["reason"].startswith(
        "in the calibration"
    )
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-loc, reason: because}\n")
    with pytest.raises(select.SelectionError, match="the reason is one of"):
        select.select(workspace, replace=True)


# -- the Investigator's budget and order (S-26) ------------------------------------------------------------------------


def test_the_investigators_order_is_taken_by_rank_within_its_budget(workspace):
    costs = {c["practice"]: c["cost_seconds"] for c in select.listing(workspace)}
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text(
        "chosen:\n  - {id: P-ads, reason: investigate, rank: 1}\n  - {id: P-loc, reason: investigate, rank: 2}\n"
    )
    selection = select.select(workspace, budget_seconds=costs["P-ads"])
    by = {e["practice"]: e for e in selection["entries"]}
    assert by["P-ads"]["kind"] == select.CHOICE and "rank 1" in by["P-ads"]["reason"]
    assert by["P-loc"]["kind"] == select.REFUSAL and "over the budget" in by["P-loc"]["reason"]
    assert selection["settings"]["budget_seconds"] == costs["P-ads"]
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-ads, reason: investigate}\n")
    with pytest.raises(select.SelectionError, match="rank"):
        select.select(workspace, replace=True)


def test_a_selection_is_extended_within_an_investigation_and_keeps_what_it_held(workspace):
    first = select.select(workspace, budget_seconds=0)
    report_ = json.loads((workspace / "assessment.json").read_text(encoding="utf-8"))
    report_["claims"].append(hypothesis("claim:P-loc:7", "P-loc", "ServiceProvision"))
    (workspace / "assessment.json").write_text(json.dumps(report_))
    extended = select.select(workspace, budget_seconds=10**6, extend=True)
    kept = [e for e in first["entries"] if select.refusal(e)]  # refused whatever the budget
    assert kept and extended["entries"][: len(kept)] == kept
    new = extended["entries"][len(kept) :]
    budget = [e["purpose"] for e in first["entries"] if not select.refusal(e)]  # refused only for the budget (0)
    assert [e["purpose"] for e in new] == budget + ["claim:P-loc:7"]
    assert all(e["kind"] == select.CHOICE for e in new)
    assert len(list((workspace / "inputs").glob("selection-*.json"))) == 1  # the earlier one is kept


def test_an_extension_decides_again_what_an_earlier_budget_refused(workspace):
    # Odin's batches: the first gets just its choice's device time, so Skuld refuses the rest over the budget; a
    # second batch in the same workspace line must be able to choose one of those
    costs = {c["practice"]: c["cost_seconds"] for c in select.listing(workspace)}
    (workspace / "inputs").mkdir()
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-ads, reason: investigate, rank: 1}\n")
    first = select.select(workspace, budget_seconds=costs["P-ads"])
    assert {e["practice"]: e["kind"] for e in first["entries"]}["P-loc"] == select.REFUSAL
    (workspace / select.CHOSEN).write_text("chosen:\n  - {id: P-loc, reason: investigate, rank: 1}\n")
    second = select.select(workspace, budget_seconds=costs["P-ads"] + costs["P-loc"], extend=True)
    by = {e["practice"]: e for e in second["entries"]}
    assert by["P-ads"] == {e["practice"]: e for e in first["entries"]}["P-ads"]  # the earlier choice, as it was
    assert by["P-loc"]["kind"] == select.CHOICE and "rank 1" in by["P-loc"]["reason"]
    # the runs are shared: the baseline is counted once, so P-loc adds only its interventions (2 × repeats runs)
    assert second["device_seconds"] == costs["P-ads"] + 2 * 3 * 100
    assert len(second["entries"]) == len(first["entries"])  # decided again, not added twice


def test_the_listing_says_whether_an_experiment_could_change_a_result(workspace):
    # one signal: qualification's experiment step for the purpose, which tests the experiment's outcomes on the case
    listed = select.listing(workspace)
    assert not any(c["could_change"] for c in listed)  # no qualification: no step says it could
    report_ = json.loads((workspace / "assessment.json").read_text(encoding="utf-8"))
    report_["qualification"] = {
        "next_steps": [
            {
                "kind": "experiment",
                "target": {"practice": c["practice"], "purpose": c["purpose"]},
                "could_change": c["practice"] != "P-ads",
            }
            for c in listed
        ]
    }
    (workspace / "assessment.json").write_text(json.dumps(report_))
    by = {c["practice"]: c for c in select.listing(workspace)}
    assert not by["P-ads"]["could_change"] and by["P-loc"]["could_change"]
    assert not by["P-own"]["could_change"]  # not eligible: no experiment step
    assert by["P-own"]["eligible"] is False and by["P-own"]["refusal"]
    assert not (workspace / select.FILE).exists()  # listing writes nothing


def test_skuld_run_takes_every_condition_by_default_and_prints_json_lines(tmp_path, monkeypatch, capsys):
    from skuld import cli, execute, inputs

    seen = {}
    monkeypatch.setattr(inputs, "load", lambda root: "ws")
    monkeypatch.setattr(execute, "interventions", lambda ws: {"G-round1": {}, "R-block": {}})

    def run(workspace, recorded, base, device, conditions, *rest, **kw):
        seen["conditions"] = conditions
        return [{"order": 1, "condition": "baseline", "exit": 0, "dir": "runs/x"}]

    monkeypatch.setattr(execute, "run", run)
    cli.main(["run", str(tmp_path), "--recorded", "r", "--config", "c", "--device", "d", "--json"])
    assert seen["conditions"] == ["baseline", "G-round1", "R-block"]
    assert json.loads(capsys.readouterr().out.strip()) == {
        "order": 1,
        "condition": "baseline",
        "exit": 0,
        "folder": "runs/x",
    }


# -- groups: data type × purpose node (author, 12 Nov 2026) -----------------------------------------------------------


@pytest.fixture
def grouped(workspace):
    """A second and third recipient of the same data for the same purpose: one group of three candidates."""
    subjects = json.loads((workspace / "subjects.json").read_text(encoding="utf-8"))
    for n, entity in ((2, "adtwo"), (3, "adthree")):
        subjects["practices"].append(
            {
                "id": f"P-ads{n}",
                "claim_type": "transmits",
                "data": "data",
                "recipient": entity,
                "episodes": [str(n + 2)],
                "party": {"relation": "other"},
            }
        )
    (workspace / "subjects.json").write_text(json.dumps(subjects))
    report_ = json.loads((workspace / "assessment.json").read_text(encoding="utf-8"))
    report_["claims"] += [hypothesis(f"claim:P-ads{n}:1", f"P-ads{n}", "Advertising", "provider") for n in (2, 3)]
    (workspace / "assessment.json").write_text(json.dumps(report_))
    return workspace


def test_a_group_is_chosen_or_refused_as_one(grouped, monkeypatch):
    (grouped / "inputs").mkdir()
    (grouped / select.CHOSEN).write_text("chosen:\n  - {id: P-ads2, reason: pursue}\n")
    selection = select.select(grouped)
    by = {e["practice"]: e for e in selection["entries"]}
    ads = [by[p] for p in ("P-ads", "P-ads2", "P-ads3")]
    assert {e["group"] for e in ads} == {"group:data:Advertising"}
    # one member pursued: the group is chosen together, whatever the budget (0)
    assert all(
        e["kind"] == select.CHOICE and "with its group group:data:Advertising (3 candidates)" in e["reason"]
        for e in ads
    )
    assert by["P-loc"]["kind"] == select.REFUSAL and "experiments are off" in by["P-loc"]["reason"]
    # the baseline once, then one recipient removal per member: (3 + 1) + 3 × 3 runs of 100 s
    assert sum(e["cost_seconds"] for e in ads) == selection["device_seconds"] == (4 + 3 * 3) * 100
    assert by["P-own"]["group"] == "group:data:ServiceOptimisation" and by["P-own"]["cost_seconds"] == 0


def test_shared_interventions_are_counted_once(grouped, monkeypatch):
    # P-loc's two roundings and the ads' removals are distinct; a second purpose of the same location practice shares
    # P-loc's roundings, so it adds nothing but is its own group
    report_ = json.loads((grouped / "assessment.json").read_text(encoding="utf-8"))
    report_["claims"].append(hypothesis("claim:P-loc:2", "P-loc", "ServiceProvision"))
    (grouped / "assessment.json").write_text(json.dumps(report_))
    monkeypatch.setattr(select, "settings", lambda: {"budget_seconds": 10**6, "repeats": 3, "run_seconds": 100})
    selection = select.select(grouped)
    by = {e["purpose"]: e for e in selection["entries"]}
    assert by["claim:P-loc:1"]["group"] != by["claim:P-loc:2"]["group"]
    assert by["claim:P-loc:2"]["cost_seconds"] == 0  # its roundings are counted already
    # baseline 4 runs, 2 roundings and 3 removals of 3 runs each
    assert selection["device_seconds"] == (4 + 5 * 3) * 100


def test_the_listings_name_the_group_and_odins_fields_stay(grouped):
    listed = select.listing(grouped)
    assert all(
        {"id", "group", "practice", "purpose", "concern", "cost_seconds", "eligible", "could_change"} <= set(c)
        for c in listed
    )
    ads = [c for c in listed if c["group"] == "group:data:Advertising"]
    assert len(ads) == 3 and all(c["cost_seconds"] == ((1 + 1) * 3 + 1) * 100 for c in ads)  # alone, as before
    groups = {g["id"]: g for g in select.group_listing(grouped)}
    g = groups["group:data:Advertising"]
    assert len(g["members"]) == 3 and g["interventions"] == ["R-adco", "R-adthree", "R-adtwo"]
    assert g["cost_seconds"] == (4 + 3 * 3) * 100 and g["eligible"]
    assert (
        not groups["group:data:ServiceOptimisation"]["eligible"]
        and groups["group:data:ServiceOptimisation"]["cost_seconds"] == 0
    )
    assert not (grouped / select.FILE).exists()


# -- observability (author, 12 Nov 2026: 15 of the gemma run's 18 groups had no oracle for their purpose) -------------


@pytest.mark.catalogue
def test_a_purpose_no_family_observes_is_refused_and_one_a_family_observes_is_not():
    from skuld.common import PURPOSES, vocabulary

    purposes, observed = vocabulary(PURPOSES), select.observed_purposes()
    assert ("ServiceProvision", "user") in observed  # the launch family's
    why = select.unobservable("ServiceUsageAnalytics", "provider", observed, purposes)
    assert why and "provider at ServiceUsageAnalytics" in why
    assert select.unobservable("ServiceUsageAnalytics", "third parties", observed, purposes)
    # the same node is observable for the user, through a family's purpose above it of that beneficiary
    assert select.unobservable("RequestedServiceProvision", "user", observed, purposes) is None
    # catalogue of 21 Nov 2026: notification preferences at CommunicationManagement, no longer ServiceManagement, and
    # perks as the provider's DirectMarketing (perks-details-view@3), which is above no advertising node
    assert select.unobservable("ServiceUsageAnalytics", "user", observed, purposes)
    assert select.unobservable("TargetedAdvertising", "provider", observed, purposes)
    assert select.unobservable("DirectMarketing", "provider", observed, purposes) is None
    assert select.unobservable("NoSuchNode", "provider", observed, purposes) is None  # left to the cases


@pytest.mark.catalogue
def test_the_selection_refuses_an_unobservable_group_with_its_reason():
    report = {
        "concerns": [],
        "claims": [
            hypothesis("h-ads", "P-ads", "ServiceUsageAnalytics", who="provider"),
            hypothesis("h-map", "P-map", "RequestedServiceProvision"),
        ],
    }
    practices = [
        vars(practice("P-ads", "device-or-other-ids.advertising-id")),
        vars(practice("P-map", "location.coordinates")),
    ]
    found = {c["practice"]: c for c in select.candidates(report, practices)}
    assert "no experiment could observe its purpose" in select.refusal(found["P-ads"])
    assert "unobservable" not in found["P-map"]


def test_a_preserved_purpose_reaches_its_own_node_only_and_a_broken_one_also_those_below():
    """C1 (author, 14 Nov 2026): that a function survives without the data shows nothing for a narrower purpose; that
    it breaks holds for every purpose it includes."""
    narrower = hypothesis("claim:P-loc:1", "P-loc", "RequestedServiceProvision")
    preserved = premise(1, "alternative", "supported", alternative="forecast:G1", level="demonstrated", broke=False)
    broken = premise(2, "alternative", "refuted", alternative="forecast:G0", level="demonstrated", broke=True)
    out = combine.experimental([narrower], [preserved, broken], PURPOSES, combine.Numbers())
    by = {c["alternative"]: c for c in out}
    assert by["forecast:G1"]["basis"] == []
    assert by["forecast:G0"]["basis"] == ["claim:P-loc:1"]
    assert by["forecast:G0"]["uncertainty"] == of("aligned_above", "few_runs")
    same = hypothesis("claim:P-loc:1", "P-loc", "ServiceProvision")
    out = combine.experimental([same], [preserved], PURPOSES, combine.Numbers())
    assert out[0]["basis"] == ["claim:P-loc:1"]
