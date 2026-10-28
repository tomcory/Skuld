import json

import pytest

from skuld import calibrate
from skuld.assess import REPORT
from tests.test_assess import ROOT

FIXTURES = [
    ROOT / "cases" / name
    for name in (
        "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4",
        "air.nn.mobile.app.main@3.8.96",
        "de.wetteronline.wetterapp@2026.20",
    )
]


def test_the_wilson_interval_is_inside_zero_and_one_and_around_the_rate():
    low, high = calibrate.wilson(3, 10)
    assert 0 < low < 0.3 < high < 1
    assert calibrate.wilson(0, 5)[0] == 0 and calibrate.wilson(5, 5)[1] == 1


@pytest.fixture
def drawn(tmp_path):
    if not all((root / REPORT).is_file() for root in FIXTURES):
        pytest.skip("the case study's workspaces are not in this checkout")
    folder = tmp_path / "calibration"
    manifest = calibrate.draw(folder, FIXTURES, per_stratum=4, seed=7)
    return folder, manifest


def test_a_sample_is_stratified_fixed_and_blind(drawn):
    folder, manifest = drawn
    items = json.loads((folder / calibrate.SAMPLE).read_text())["items"]
    key = json.loads((folder / calibrate.KEY).read_text())
    assert {i["id"] for i in items} == set(key)
    for s in manifest["strata"]:
        assert s["drawn"] == min(4, s["population"])
    assert sum(s["drawn"] for s in manifest["strata"]) == len(items)
    # the expert never sees E's outcome, concerns or reasoning
    shown = json.dumps(items)
    assert all(c not in shown for entry in key.values() for c in entry["concerns"])
    assert not any("stratum" in i or "concerns" in i for i in items)
    # every unit of the three kinds, with the collection's documents where D has a report
    assert {i["subject"]["kind"] for i in items} == {"collection", "statement", "practice"}
    assert all((folder / d["file"]).is_file() for i in items for d in i["documents"])
    # a practice item carries what the expectation stage read with it (screens, passages), never its answer
    practices = [i for i in items if i["subject"]["kind"] == "practice"]
    assert practices and all(set(i["context"]) == {"screens", "passages"} for i in practices)
    assert any(i["context"]["screens"] for i in practices) and any(i["context"]["passages"] for i in practices)
    # a drawn sample is never overwritten
    with pytest.raises(calibrate.CalibrationError):
        calibrate.draw(folder, FIXTURES)


def test_scores_compare_the_decisions_with_es_outcomes(drawn):
    folder, _ = drawn
    key = json.loads((folder / calibrate.KEY).read_text())
    # an expert who agrees with every concern and finds every silence a miss
    reviews = {
        iid: {"decision": "fails" if e["stratum"]["outcome"] in ("supported",) + calibrate.SILENT else "holds"}
        for iid, e in key.items()
    }
    (folder / calibrate.REVIEWS).write_text(json.dumps(reviews))
    scores = calibrate.score(folder)
    assert scores["reviewed"] == len(key)
    for s in scores["strata"]:
        expected = {"precision": 1.0, "miss_rate": 1.0, "concern_rate": 0.0}[s["measure"]]
        assert s["rate"] == expected
    # the files reviewed must be those drawn
    (folder / calibrate.KEY).write_text("{}")
    with pytest.raises(calibrate.CalibrationError):
        calibrate.score(folder)


def test_a_calibration_holds_only_for_the_components_it_was_drawn_with(drawn, tmp_path):
    folder, _ = drawn
    assert calibrate.check(folder, FIXTURES) == []
    changed = tmp_path / "changed"
    changed.mkdir()
    report = json.loads((FIXTURES[0] / REPORT).read_text())
    for c in report["report"]["components"]:
        if c["role"] == "model":
            c["sha256"] = "0" * 64  # another build of the model
    (changed / REPORT).write_text(json.dumps(report))
    assert any("model" in p and "not calibrated" in p for p in calibrate.check(folder, [changed]))
