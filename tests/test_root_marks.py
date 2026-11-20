"""D's marks on the root (Urda 2.1.0): a declaration that names no data holds of all data (`_no_data`); a root D holds
only because it could not place the value (`_unplaced`) is undecided, not all data; an earlier report, which marks
neither, is read as before (POST_PAPER_FIXES 5, URDA_RERUN_PLAN 5)."""

from ratatoskr import claims as claim_views
from ratatoskr.frames import Frame

from skuld import assessment, concerns, correspondence, judge, relations
from skuld.common import PURPOSES, vocabulary
from tests.test_assess import claim, o_report, workspace
from tests.test_rule_tier import DATA, REGISTRY, TYPES, d_claim, d_report

NAME = "personal-info.name"


def _report(claims, tilt, urda="2.1.0"):
    """A D report whose policy channel's derived document holds `tilt`, its claims at the paths their ids name."""
    report = d_report(claims)
    report["channels"][0]["tilt"] = tilt
    if urda:
        report["report"] = {"urda": urda}
    return report


def _denial(n, data="data", **fields):
    c = d_claim("declares_collection", data, "-", **fields)
    c["id"], c["declaration"] = f"policy:/notDisclosed/{n}", f"/notDisclosed/{n}"
    return c


def _relate(tmp_path, o_claims, report):
    a = workspace(tmp_path, [o_report(o_claims)], report)
    built = assessment.build(a, REGISTRY)
    return built, correspondence.relate(built, a.declaration.load(), [], REGISTRY, DATA, TYPES)


def _practice(rel, aspect="data"):
    return [r for r in rel if r.aspect == aspect and r.subject and r.subject.startswith("P-")]


def test_the_marks_are_read_from_the_derived_document_at_the_claims_path(tmp_path):
    tilt = {"notDisclosed": [{"category": "data", "_no_data": True}, {"category": "data", "_unplaced": ["category"]}]}
    built, _ = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([_denial(0), _denial(1)], tilt))
    first, second = built.declarations
    assert (first.no_data, first.unplaced, first.marked) == (True, [], True)
    assert (second.no_data, second.unplaced) == (False, ["category"]) and second.unplaced_data(DATA.root)


def test_a_denial_of_no_data_in_particular_contradicts_under_no_condition_of_its_own(tmp_path):
    """ "We do not share any data with third parties", RealCalc's "None": the root as stated, any data."""
    tilt = {"notDisclosed": [{"category": "data", "_no_data": True}]}
    _, rel = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([_denial(0)], tilt))
    (contradiction,) = [r for r in rel if r.outcome == "contradicts"]
    assert contradiction.condition is None and contradiction.condition_kind is None


def test_a_root_the_model_placed_in_a_marked_report_holds_of_all_data(tmp_path):
    """Urda 2.1.0 may place a phrase of data in general at the root, unmarked: all data, as stated."""
    _, rel = _relate(
        tmp_path, [claim("c1", NAME, "adco")], _report([_denial(0)], {"notDisclosed": [{"category": "data"}]})
    )
    (contradiction,) = [r for r in rel if r.outcome == "contradicts"]
    assert contradiction.condition is None


def test_a_denial_of_a_value_d_could_not_place_leaves_the_practice_undecided(tmp_path):
    """Peacock's "Camera" denied, unplaced: it says nothing of a name sent to adco either way."""
    tilt = {"notDisclosed": [{"category": "data", "_unplaced": ["category"]}]}
    _, rel = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([_denial(0)], tilt))
    assert not [r for r in rel if r.outcome == "contradicts"]
    undecided = [r for r in _practice(rel) if r.outcome == "insufficient_evidence"]
    assert len(undecided) == 1 and "could not place" in undecided[0].alignment
    # the denial declares no collection: the practice is still observed without declaration
    assert "observed_without_declaration" in {r.outcome for r in _practice(rel)}


def test_an_unmarked_root_denial_of_an_earlier_report_contradicts_under_a_condition(tmp_path):
    """Urda before 2.1.0: the root may be all data or an unplaced value, so the denial is read as before."""
    _, rel = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([_denial(0)], {}, urda=None))
    (contradiction,) = [r for r in rel if r.outcome == "contradicts"]
    assert contradiction.condition == "the denial, labelled only data, means the data observed"
    assert contradiction.condition_kind == "fact"


def test_a_collection_of_data_d_could_not_place_corresponds_to_no_practice(tmp_path):
    """A declared value D could not place is not a declaration of all data: the practice is undecided, not covered."""
    positive = d_claim("declares_collection", "data")
    positive["id"], positive["declaration"] = "policy:/dataDisclosed/0", "/dataDisclosed/0"
    tilt = {"dataDisclosed": [{"category": "data", "_unplaced": ["category"]}]}
    _, rel = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([positive], tilt))
    (data,) = _practice(rel)
    assert data.outcome == "insufficient_evidence" and "could not place" in data.alignment
    # unmarked, in an earlier report, the root is all data: the practice corresponds
    _, rel = _relate(_fresh(tmp_path / "earlier"), [claim("c1", NAME, "adco")], _report([positive], {}, urda=None))
    assert _practice(rel)[0].outcome == "corresponds_hierarchically"


def test_an_unplaced_collection_no_practice_meets_is_undecided_not_declared_without_observation(tmp_path):
    positive = d_claim("declares_collection", "data")
    positive["id"], positive["declaration"] = "policy:/dataDisclosed/0", "/dataDisclosed/0"
    tilt = {"dataDisclosed": [{"category": "data", "_unplaced": ["category"]}]}
    _, rel = _relate(tmp_path, [], _report([positive], tilt))  # no practice it could relate to
    of_d = [r for r in rel if r.subject == "D-0"]
    assert [r.outcome for r in of_d] == ["insufficient_evidence"]


def test_a_provision_item_declares_no_collection(tmp_path):
    """ "You are not obliged to provide …": an item for all data marked _no_data projects no collection claim, so it
    no longer makes every practice correspond (50 of the study's 83 root data items of the policy)."""
    tilt = {
        "dataDisclosed": [
            {
                "category": "data",
                "nonDisclosure": {"consequences": "you cannot register", "_provenance": []},
                "_provenance": [],
                "_no_data": True,
            }
        ]
    }
    report = d_report([])
    report["channels"][0]["tilt"] = tilt
    report.pop("claims")
    report["report"] = {"urda": "2.1.0", "claims": claim_views.declaration_constants()}
    assert not [c for c in claim_views.of_report(report) if c["type"] == "declares_collection"]
    _, rel = _relate(tmp_path, [claim("c1", NAME, "adco")], report)
    assert _practice(rel)[0].outcome == "observed_without_declaration"


def _fresh(path):
    path.mkdir()
    return path


def _purpose(data, value, n=0, field="dataDisclosed"):
    c = d_claim("declares_purpose", data, value=value, kind="justification")
    c["id"], c["declaration"] = f"policy:/{field}/{n}/purposes/0", f"/{field}/{n}"
    return c


def _hypothesis(built, node="Advertising"):
    p = built.practices[0]
    return {
        "id": "E:h:1",
        "type": "purpose",
        "status": "supported",
        "subject": p.id,
        "purpose": {"node": node, "beneficiary": "provider"},
        "uncertainty": {"t": "low", "s": "low", "n": "low"},
    }


def test_a_purpose_declared_for_data_d_could_not_place_leaves_purpose_limitation_undecided(tmp_path):
    """ "We use Camera for advertising", Camera unplaced: whether a purpose is specified for the practice's data, and
    whether it covers the practice's, is undecided (concern iv not established), not decided for all data."""
    tilt = {
        "dataDisclosed": [{"category": "data", "_unplaced": ["category"], "purposes": [{"purpose": "Advertising"}]}]
    }
    built, _ = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([_purpose("data", "Advertising")], tilt))
    (spec,) = judge.specified(built, [], vocabulary(PURPOSES))
    assert spec.data == [] and spec.unplaced == ["D-0"]
    (case,) = judge.limitation(built, [], [_hypothesis(built)])
    assert case.relevant == [] and case.covering == [] and [s.node for s in case.unplaced_covering] == ["Advertising"]
    frame = Frame.load("gdpr-art5")
    (concern,), _ = concerns.purpose_limitation(frame, [case], [], [], {})
    assert concern.status == "not_established" and "could not place" in concern.reason
    # in an earlier report the root is all data: the purpose is specified for the practice's data and covers it
    built, _ = _relate(
        _fresh(tmp_path / "earlier"),
        [claim("c1", NAME, "adco")],
        _report([_purpose("data", "Advertising")], {}, urda=None),
    )
    (case,) = judge.limitation(built, [], [_hypothesis(built)])
    assert [s.node for s in case.covering] == ["Advertising"]


def test_a_purpose_d_could_not_place_specifies_nothing_and_denies_no_purpose_in_particular(tmp_path):
    root = vocabulary(PURPOSES).root
    positive = _purpose(NAME, root)
    denial = d_claim("declares_purpose", NAME, "-", value=root, kind="justification")
    denial["id"], denial["declaration"] = "policy:/notDisclosed/0", "/notDisclosed/0"
    tilt = {
        "dataDisclosed": [{"category": NAME, "purposes": [{"purpose": root, "_unplaced": ["purpose"]}]}],
        "notDisclosed": [{"category": NAME, "aspect": "purpose", "purpose": root, "_unplaced": ["purpose"]}],
    }
    built, _ = _relate(tmp_path, [claim("c1", NAME, "adco")], _report([positive, denial], tilt))
    first, second = built.declarations
    assert first.unplaced_purpose(root) and second.unplaced_purpose(root)
    assert judge.specified(built, [], vocabulary(PURPOSES)) == []
    (d_e,) = relations.d_e(built, [_hypothesis(built)], {}, DATA, vocabulary(PURPOSES))
    assert (d_e.outcome, d_e.reason) == ("not_comparable", "D could not place the purpose")
