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
    items = json.loads((folder / calibrate.SAMPLE).read_text(encoding="utf-8"))["items"]
    key = json.loads((folder / calibrate.KEY).read_text(encoding="utf-8"))
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
    key = json.loads((folder / calibrate.KEY).read_text(encoding="utf-8"))
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
    report = json.loads((FIXTURES[0] / REPORT).read_text(encoding="utf-8"))
    for c in report["report"]["components"]:
        if c["role"] == "model":
            c["sha256"] = "0" * 64  # another build of the model
    (changed / REPORT).write_text(json.dumps(report))
    assert any("model" in p and "not calibrated" in p for p in calibrate.check(folder, [changed]))


# -- across model families --------------------------------------------------------------------------------------------

FAMILIES = ("gemma4:31b", "gpt-oss:120b", "qwen3.8:27b")
INPUTS = {"observation": ["o1"], "declaration": "d1", "exploration": None, "frame": ["f", "1", "x"], "corpus": "c1"}


def _unit(principle, step, grain, outcome, tier="reasoning", concerns=(), **shown):
    return {
        "stratum": {"principle": principle, "tier": tier, "step": step, "outcome": outcome},
        "concerns": list(concerns),
        "requirement": {"id": "r", "title": "R", "principle": principle, "provisions": []},
        "question": calibrate.QUESTIONS[step],
        "subject": {"kind": "practice" if grain and grain[0] == "practice" else "collection"},
        "grain": grain,
        **shown,
    }


def _workspaces(tmp_path, monkeypatch, plan, inputs=None):
    """Assessment workspaces from a plan {(app, family): [units]}, with units, inputs and documents stubbed."""
    roots, made = [], {}
    for (app, family), us in plan.items():
        root = tmp_path / "ws" / f"{app}-{family.replace(':', '_')}"
        root.mkdir(parents=True)
        report = {
            "application": {"package": app, "version": "1"},
            "report": {"components": [{"role": "model", "id": family, "sha256": "s"}]},
        }
        (root / REPORT).write_text(json.dumps(report))
        made[str(root)] = us
        roots.append(root)
    copied = []
    monkeypatch.setattr(calibrate, "units", lambda root, report, registry: [dict(u) for u in made[str(root)]])
    monkeypatch.setattr(calibrate, "_inputs", lambda root: (inputs or {}).get(str(root), INPUTS))
    monkeypatch.setattr(calibrate, "copy_documents", lambda root, target: copied.append(root) or [])
    monkeypatch.setattr(calibrate, "load_registry", lambda path: None)
    return roots, copied


def _plan():
    T, M = "transparency", "data_minimisation"
    ads = ("practice", "P-1", "TargetedAdvertising")
    return {
        ("app.a", FAMILIES[0]): [
            _unit(T, "information_not_given", ("collection", "R1"), "supported", "rule", ["c1"]),
            _unit(
                M,
                "less_invasive_alternative",
                ads,
                "supported",
                concerns=["c2"],
                purpose={"action": "deliver", "node": "TargetedAdvertising"},
                context={"screens": ["s1"], "passages": []},
            ),
            _unit(M, "less_invasive_alternative", None, "silent"),
        ],
        ("app.a", FAMILIES[1]): [
            _unit(T, "information_not_given", ("collection", "R1"), "supported", "rule", ["c3"]),
            _unit(
                M,
                "less_invasive_alternative",
                ads,
                "silent",
                purpose={"action": "show ads", "node": "TargetedAdvertising"},
                context={"screens": ["s1", "s2"], "passages": ["p1"]},
            ),
        ],
        ("app.a", FAMILIES[2]): [
            _unit(T, "information_not_given", ("collection", "R1"), "silent", "rule"),
        ],
    }


def test_across_families_units_merge_by_grain_and_strata_count_the_families_raising(tmp_path, monkeypatch):
    roots, copied = _workspaces(tmp_path, monkeypatch, _plan())
    folder = tmp_path / "cal"
    manifest = calibrate.draw(folder, roots, per_stratum=10, seed=3)
    assert manifest["mode"] == "families" and manifest["families"] == sorted(FAMILIES)
    key = json.loads((folder / calibrate.KEY).read_text())
    items = json.loads((folder / calibrate.SAMPLE).read_text())["items"]
    by_step = {(e["stratum"]["step"], e["stratum"]["raised"]): e for e in key.values()}
    # the collection's requirement: one unit, raised by two of three
    r1 = by_step[("information_not_given", 2)]
    assert r1["outcomes"] == {FAMILIES[0]: "supported", FAMILIES[1]: "supported", FAMILIES[2]: "silent"}
    # the practice's purpose by node: one unit; the family that did not infer it is absent
    ads = by_step[("less_invasive_alternative", 1)]
    assert ads["outcomes"][FAMILIES[2]] == calibrate.ABSENT and ads["concerns"][FAMILIES[0]] == ["c2"]
    # a purpose without a node aligns with nothing: its own unit, absent for the others
    alone = by_step[("less_invasive_alternative", 0)]
    assert sorted(alone["outcomes"].values()) == ["absent", "absent", "silent"]
    assert len(items) == 3
    # blind: no family, outcome or concern in what the reviewers see; context is the union, without repeats
    shown = json.dumps(items)
    assert not any(f in shown for f in FAMILIES) and "c2" not in shown and "supported" not in shown
    practice = next(i for i in items if i.get("purpose", {}).get("node") == "TargetedAdvertising")
    assert practice["context"] == {"screens": ["s1", "s2"], "passages": ["p1"]}
    # the application's documents are copied once
    assert len(copied) == 1


def test_across_families_the_inputs_and_families_must_match(tmp_path, monkeypatch):
    plan = _plan()
    roots, _ = _workspaces(tmp_path, monkeypatch, plan, {})
    other = dict(INPUTS, declaration="d2")
    monkeypatch.setattr(calibrate, "_inputs", lambda root: other if "qwen" in str(root) else INPUTS)
    with pytest.raises(calibrate.CalibrationError, match="declaration"):
        calibrate.draw(tmp_path / "c1", roots)
    plan2 = {("app.a", FAMILIES[0]): [], ("app.a", FAMILIES[1]): [], ("app.b", FAMILIES[0]): []}
    roots2, _ = _workspaces(tmp_path / "two", monkeypatch, plan2)
    with pytest.raises(calibrate.CalibrationError, match="assessed by"):
        calibrate.draw(tmp_path / "c2", roots2)


def test_across_families_scores_per_family_and_two_reviewers_agree(tmp_path, monkeypatch):
    roots, _ = _workspaces(tmp_path, monkeypatch, _plan())
    folder = tmp_path / "cal"
    calibrate.draw(folder, roots, seed=3)
    key = json.loads((folder / calibrate.KEY).read_text())
    ids = sorted(key)
    first = {i: {"decision": "fails", "note": "a"} for i in ids}
    second = {i: {"decision": "fails" if n else "holds"} for n, i in enumerate(ids)}
    (tmp_path / "ra.json").write_text(json.dumps(first))
    (tmp_path / "rb.json").write_text(json.dumps({"reviewer": "b", "items": second}))
    result = calibrate.agree(folder, tmp_path / "ra.json", tmp_path / "rb.json")
    assert result["overall"]["items"] == 3 and result["overall"]["agreed"] == 2
    assert [d["id"] for d in result["disagreements"]] == [ids[0]]
    seeded = json.loads((folder / calibrate.REVIEWS).read_text())
    assert set(seeded) == set(ids[1:])  # the disagreement is left for adjudication
    seeded[ids[0]] = {"decision": "fails"}
    (folder / calibrate.REVIEWS).write_text(json.dumps(seeded))
    scores = calibrate.score(folder)
    assert scores["reviewed"] == 3
    est = {(e["family"], e["step"], e["measure"]): e for e in scores["estimates"]}
    # every unit judged a concern: the families' concerns are all confirmed, their silences and absences all misses
    assert est[(FAMILIES[0], "information_not_given", "precision")]["rate"] == 1.0
    assert est[(FAMILIES[2], "information_not_given", "miss_rate")]["rate"] == 1.0
    assert est[(FAMILIES[2], "less_invasive_alternative", "miss_rate_absent")]["rate"] == 1.0
    # a second agree does not overwrite the adjudicated reviews
    calibrate.agree(folder, tmp_path / "ra.json", tmp_path / "rb.json")
    assert json.loads((folder / calibrate.REVIEWS).read_text())[ids[0]] == {"decision": "fails"}


def test_kappa():
    f, h = "fails", "holds"
    assert calibrate.kappa([(f, f), (h, h), (f, h), (h, h)]) == pytest.approx(0.5)
    assert calibrate.kappa([(f, f), (f, f)]) is None and calibrate.kappa([]) is None
