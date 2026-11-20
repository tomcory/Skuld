"""The review of the expectation stage's predictions (skuld.review_expectation): units, the draw, scores, κ."""

import json
from pathlib import Path

import pytest

from skuld import review_expectation as rx


def purpose(subject, n, role, status, node="Advertising"):
    return {
        "id": f"claim:{subject}:{n}",
        "type": "purpose",
        "subject": subject,
        "stage": "expectation",
        "of": [f"e1/s1:p{n - 1}"],
        "purpose": {
            "action": "send",
            "object": "id",
            "outcome": "to show ads [S1]",
            "node": node,
            "beneficiary": "provider",
            "role": role,
            "specificity": "sufficient",
        },
        "status": status,
        "supporting": ["item:1"] if status == "supported" else [],
    }


def dependency(subject, n, basis, status):
    return {
        "id": f"claim:{subject}:{n}",
        "type": "dependency",
        "subject": subject,
        "stage": "expectation",
        "of": ["e1/s1:d0"],
        "basis": [basis],
        "relationship": "essential",
        "status": status,
        "supporting": [],
    }


def workspace(base: Path, run: str, roles=("ancillary", "functional")) -> Path:
    root = base / run / "a.b@1"
    (root / "expectation" / "e1" / "s1").mkdir(parents=True)
    practices, claims = [], []
    for i, role in enumerate(roles):
        s = f"P-{i}"
        practices.append({"id": s, "claim_type": "transmits", "data": "d", "recipient": "r", "episodes": ["1"]})
        claims += [
            purpose(s, 1, role, "supported"),
            dependency(s, 2, f"claim:{s}:1", "supported"),
            purpose(s, 3, "ancillary", "not_established"),
            dependency(s, 4, f"claim:{s}:3", "not_assessable"),
        ]
    report = {
        "application": {"package": "a.b", "version": "1"},
        "report": {"components": [{"role": "model", "id": f"model-{run}", "stage": "expectation"}]},
        "subjects": {"practices": practices},
        "claims": claims,
        "evidence": [{"id": "item:1", "kind": "doc", "text": "Ads are shown."}],
    }
    (root / "assessment.json").write_text(json.dumps(report), encoding="utf-8")
    sample = root / "expectation" / "e1" / "s1"
    (sample / "answer.json").write_text(
        json.dumps(
            {
                "purposes": [],
                "dependencies": [
                    {
                        "steps": [
                            {"text": "Ads need the id [S1].", "cites": ["S1"]},
                            {"text": "Ads need the id [S1].", "cites": ["S1"]},
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (sample / "context.json").write_text(
        json.dumps(
            {
                "parts": [
                    {"id": "P-0", "kind": "practice", "text": "The app sends d to r."},
                    {"id": "P-1", "kind": "practice", "text": "The app sends d to r."},
                    {"id": "S1", "kind": "screen", "text": "An ad | Close"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def runs(tmp_path):
    return [workspace(tmp_path, "model-x"), workspace(tmp_path, "model-y")]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_unit_is_a_practice_with_its_purposes_dependencies_steps_and_context(runs):
    found = rx.units(runs[0])
    assert [u["practice"]["id"] for u in found] == ["P-0", "P-1"]
    u = found[1]
    assert (u["_role"], u["_status"]) == ("functional", "supported")
    p1, p2 = u["purposes"]
    assert p1["outcome"] == "to show ads" and p1["evidence"][0]["text"] == "Ads are shown."
    d = p1["dependencies"][0]
    assert d["asked"] and d["steps"] == [
        {"text": "Ads need the id.", "cites": [{"id": "S1", "kind": "screen", "text": "An ad | Close"}]}
    ]
    assert not p2["dependencies"][0]["asked"]  # not assessable: shown, not asked
    assert u["context"]["screens"] == ["An ad | Close"]
    assert rx.asked(p1) == list(rx.PURPOSE_QUESTIONS) and "cites" not in rx.asked(p2)


def test_the_draw_is_stratified_by_run_role_and_status_and_never_names_the_run(tmp_path, runs):
    folder = tmp_path / "x"
    manifest = rx.draw(folder, runs, per_stratum=5, seed=2)
    sample = read(folder / rx.SAMPLE)
    assert sample["kind"] == rx.KIND and len(sample["items"]) == 4
    vocab = {n["id"]: n for n in sample["vocabularies"]["purpose"]}
    assert {n["id"] for n in sample["vocabularies"]["data"]} >= {"data", "location.coordinates"}
    assert (
        vocab["TargetedAdvertising"]["parents"] == ["PersonalisedAdvertising"] and vocab["TargetedAdvertising"]["title"]
    )
    assert {(s["run"], s["role"]) for s in manifest["strata"]} == {
        ("model-x", "ancillary"),
        ("model-x", "functional"),
        ("model-y", "ancillary"),
        ("model-y", "functional"),
    }
    shown = json.dumps(sample)
    assert "model-x" not in shown and "claim:" not in shown
    key = read(folder / rx.KEY)
    assert all(k["claims"]["p1"].startswith("claim:") for k in key.values())
    with pytest.raises(rx.ReviewError):
        rx.draw(folder, runs)


def full_review(item, node="exact"):
    purposes = {p["key"]: {q: rx.PURPOSE_QUESTIONS[q][0] for q in rx.asked(p)} for p in item["purposes"]}
    purposes["p1"]["node"] = node
    deps = {
        d["key"]: {"relationship": "yes", "steps": "partly"}
        for p in item["purposes"]
        for d in p["dependencies"]
        if d["asked"]
    }
    return {
        "purposes": purposes,
        "dependencies": deps,
        "missed": [{"note": "weather", "functional": True}],
        "done": True,
    }


def test_scores_and_two_reviewers(tmp_path, runs):
    folder = tmp_path / "x"
    rx.draw(folder, runs, per_stratum=5, seed=2)
    items = read(folder / rx.SAMPLE)["items"]
    assert rx.problems(items[0], {}) and not rx.problems(items[0], full_review(items[0]))
    first = {i["id"]: full_review(i) for i in items}
    second = {i["id"]: full_review(i, node="wrong" if n == 0 else "exact") for n, i in enumerate(items)}
    (folder / rx.REVIEWS).write_text(json.dumps(first), encoding="utf-8")
    s = rx.score(folder)
    est = {(e["run"], e["level"], e["question"], e["role"]): e for e in s["estimates"]}
    assert est[("model-x", "purpose", "node", "all")]["rate"] == 1.0
    assert est[("model-x", "dependency", "steps", "all")]["rate"] == 0.0  # partly does not agree
    assert s["done"] == 4 and s["missed_functional"] == 4
    (folder / rx.REVIEWS).unlink()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(first), encoding="utf-8")
    b.write_text(json.dumps({"reviewer": "b", "items": second}), encoding="utf-8")
    out = rx.agree(folder, a, b)
    assert [(d["part"], d["question"]) for d in out["differences"]] == [("p1", "node")]
    seeded = read(folder / rx.REVIEWS)[items[0]["id"]]
    assert "node" not in seeded["purposes"]["p1"] and seeded["purposes"]["p1"]["plausible"] == "yes"
    assert out["seeded"] == 4


def test_a_unit_shows_what_the_stage_was_told_and_unknown_data_is_not_drawn(tmp_path):
    root = workspace(tmp_path, "model-x")
    context = root / "expectation" / "e1" / "s1" / "context.json"
    parts = json.loads(context.read_text())["parts"]
    parts.append({"id": "T1", "kind": "traffic", "text": "P-1: POST https://r.example/track · body: …id=«abc»… (d)"})
    context.write_text(json.dumps({"parts": parts}))
    report = json.loads((root / "assessment.json").read_text())
    report["subjects"]["practices"][0]["data"] = "data"  # O did not identify the datum
    (root / "assessment.json").write_text(json.dumps(report))
    found = rx.units(root)
    assert [u["practice"]["id"] for u in found] == ["P-1"]
    assert found[0]["told"] == "The app sends d to r."
    assert found[0]["context"]["traffic"] == ["POST https://r.example/track · body: …id=«abc»… (d)"]
    assert [u["practice"]["id"] for u in rx.units(root, known_data_only=False)] == ["P-0", "P-1"]


def test_weighted_rates_weigh_each_stratum_by_its_population_whatever_was_left_unsure():
    # two strata of 100 each: all 10 judged agree in one; in the other 5 disagree and 5 were unsure (not judged)
    by = {("a",): [10, 10], ("b",): [0, 5]}
    assert rx._weighted(by, {("a",): 100, ("b",): 100}) == 0.5
    assert rx._weighted({("a",): [0, 0]}, {("a",): 100}) is None


def application(base: Path, run: str, package: str, practices: int) -> Path:
    """A workspace of one application in a run, with `practices` ancillary supported practices (one stratum)."""
    root = workspace(base / package, run, roles=("ancillary",) * practices)
    report = read(root / "assessment.json")
    report["application"] = {"package": package, "version": "1"}
    (root / "assessment.json").write_text(json.dumps(report), encoding="utf-8")
    return root


def drawn_per_app(manifest):
    return {a["application"]: a["drawn"] for a in manifest["applications"]}


def test_a_cap_per_application_keeps_each_stratums_size(tmp_path):
    """20 Nov 2026: in the study, two applications had 18 and 15 of a run's 66 units."""
    roots = [application(tmp_path, "run", "big.app", 10), application(tmp_path, "run", "small.app", 3)]
    plain = rx.draw(tmp_path / "plain", roots, per_stratum=6, seed=1)
    assert "per_app" not in plain and sum(drawn_per_app(plain).values()) == 6
    assert {a["application"]: a["population"] for a in plain["applications"]} == {"big.app@1": 10, "small.app@1": 3}
    capped = rx.draw(tmp_path / "capped", roots, per_stratum=6, seed=1, per_app=3)
    assert capped["per_app"] == 3 and drawn_per_app(capped) == {"big.app@1": 3, "small.app@1": 3}
    assert [s["drawn"] for s in capped["strata"]] == [6]
    # where the other applications cannot fill the stratum, the cap gives way: the stratum keeps its size
    tight = rx.draw(tmp_path / "tight", roots, per_stratum=6, seed=1, per_app=2)
    assert drawn_per_app(tight) == {"big.app@1": 4, "small.app@1": 2} and [s["drawn"] for s in tight["strata"]] == [6]
    with pytest.raises(rx.ReviewError, match="at least 1"):
        rx.draw(tmp_path / "zero", roots, per_app=0)


def test_the_cap_is_shared_out_over_a_runs_strata_in_proportion():
    strata = {
        ("r", "a", "s"): [{"application": app, "n": i} for app in ("x", "y", "z") for i in range(10)],
        ("r", "f", "s"): [{"application": app, "n": i} for app in ("x", "y") for i in range(10)],
    }
    out = rx.capped(strata, {("r", "a", "s"): 9, ("r", "f", "s"): 3}, 4, __import__("random").Random(1))
    # shares: 4·9/12 = 3 in the first, max(1, round(4·3/12)) = 1 in the second, which y and x then fill
    first = [u["application"] for u in out[("r", "a", "s")]]
    assert len(first) == 9 and all(first.count(app) == 3 for app in "xyz")
    assert len(out[("r", "f", "s")]) == 3


def test_expect_score_reports_the_strata_a_partial_return_reached(tmp_path, runs):
    folder = tmp_path / "x"
    rx.draw(folder, runs, per_stratum=5, seed=2)
    items = read(folder / rx.SAMPLE)["items"]
    key = read(folder / rx.KEY)
    reviews = {i["id"]: full_review(i) for i in items if key[i["id"]]["stratum"]["run"] == "model-x"}
    (folder / rx.REVIEWS).write_text(json.dumps(reviews), encoding="utf-8")
    s = rx.score(folder)
    c = s["coverage"]
    assert c["partial"] and c["reviewed"] == 2 and c["units"] == 4
    assert {st["run"] for st in c["not_reviewed"]} == {"model-y"} and len(c["not_reviewed"]) == 2
    assert {(st["run"], st["reviewed"], st["judged"]) for st in s["strata"]} == {("model-x", 1, 1), ("model-y", 0, 0)}
    assert all(e["population_covered"] == 1.0 for e in s["estimates"])
