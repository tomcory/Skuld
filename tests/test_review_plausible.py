"""Plausible on five values with picked reasons (skuld.review_expectation 3, 24 Nov 2026): the study's reviewers found
"partly" too broad, standing both for "almost there" and for "a little bit"."""

import json
import shutil

import pytest

from skuld import review_expectation as rx
from skuld import review_export as rex
from tests.test_review_expectation import full_review, read, workspace


@pytest.fixture
def drawn(tmp_path):
    runs = [workspace(tmp_path, "model-x"), workspace(tmp_path, "model-y")]
    folder = tmp_path / "x"
    rx.draw(folder, runs, per_stratum=5, seed=2)
    return folder, read(folder / rx.SAMPLE)["items"]


def judged(item, plausible, reasons=None):
    r = full_review(item)
    r["purposes"]["p1"]["plausible"] = plausible
    if reasons is not None:
        r["purposes"]["p1"]["plausible_reasons"] = reasons
    return r


def test_the_sample_carries_the_scale_and_the_reasons_to_pick_from(drawn):
    folder, _ = drawn
    questions = read(folder / rx.SAMPLE)["questions"]
    assert questions["purpose"]["plausible"] == ["yes", "mostly", "partly", "no", "unsure"]
    reasons = questions["reasons"]["plausible"]
    assert reasons["when"] == ["mostly", "partly"]
    assert [o["id"] for o in reasons["options"]] == [
        "overstates",
        "vague",
        "bundles",
        "part_of_flow",
        "loose_fit",
        "other",
    ]
    assert all(o["label"] and o["hint"] for o in reasons["options"])
    assert reasons["free"] == "other"
    assert read(folder / rx.MANIFEST)["method"]["version"] == "3"


def test_mostly_and_partly_need_a_known_reason_yes_and_no_none(drawn):
    _, items = drawn
    item = items[0]
    assert "p1: plausible reasons" in rx.problems(item, judged(item, "mostly"))
    assert "p1: plausible reasons" in rx.problems(item, judged(item, "partly", ["made_up"]))
    assert not rx.problems(item, judged(item, "partly", ["loose_fit", "bundles"]))
    assert not rx.problems(item, judged(item, "no"))


def test_the_rate_is_strict_and_lenient_and_the_reasons_are_counted(drawn):
    folder, items = drawn
    answers = ["yes", "mostly", "partly", "no"]
    reviews = {}
    for n, item in enumerate(items):
        a = answers[n % 4]
        reviews[item["id"]] = judged(item, a, ["overstates"] if a in ("mostly", "partly") else None)
    (folder / rx.REVIEWS).write_text(json.dumps(reviews))
    s = rx.score(folder)
    plausible = [e for e in s["estimates"] if e["question"] == "plausible" and e["role"] == "all"]
    total = {k: sum(e["answers"].get(k, 0) for e in plausible) for k in answers}
    n = sum(e["judged"] for e in plausible)
    strict = sum(e["rate"] * e["judged"] for e in plausible) / n
    lenient = sum(e["lenient_rate"] * e["judged"] for e in plausible) / n
    # mostly counts only leniently: the two rates differ by the share of mostly
    assert strict == pytest.approx(total["yes"] / n)
    assert lenient - strict == pytest.approx(total["mostly"] / n) and total["mostly"] > 0
    reasons = {}
    for e in plausible:
        for k, v in e.get("reasons", {}).items():
            reasons[k] = reasons.get(k, 0) + v
    assert reasons == {
        f"{a}:overstates": sum(1 for i in range(len(items)) if answers[i % 4] == a) for a in ("mostly", "partly")
    }
    # a question without an order has no lenient rate
    assert all("lenient_rate" not in e for e in s["estimates"] if e["question"] == "node")


def test_weighted_kappa_counts_a_near_miss_less_than_a_far_one():
    order = rx.ORDERED["plausible"]
    near = [("yes", "yes"), ("mostly", "mostly"), ("partly", "partly"), ("no", "no"), ("yes", "mostly")] * 4
    far = [("yes", "yes"), ("mostly", "mostly"), ("partly", "partly"), ("no", "no"), ("yes", "no")] * 4
    assert rx.weighted_kappa(near, order) > rx.weighted_kappa(far, order)
    assert rx.weighted_kappa([(a, a) for a in order], order) == 1.0
    assert rx.weighted_kappa([("unsure", "yes")], order) is None  # unsure is left out


def test_two_reviewers_get_weighted_and_lenient_kappa_on_plausible(drawn, tmp_path):
    folder, items = drawn
    first = {
        i["id"]: judged(i, "yes" if n % 2 else "mostly", None if n % 2 else ["vague"]) for n, i in enumerate(items)
    }
    second = {i["id"]: judged(i, "mostly" if n % 2 else "mostly", ["vague"]) for n, i in enumerate(items)}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(first))
    b.write_text(json.dumps(second))
    out = rx.agree(folder, a, b)
    q = out["questions"]["all purpose plausible"]
    assert "weighted_kappa" in q and "lenient_kappa" in q
    assert "weighted_kappa" not in out["questions"]["all purpose node"]


@pytest.mark.skipif(
    not shutil.which("node") or not (rex.TOOL / "node_modules").is_dir(), reason="Node.js or the tool's modules missing"
)
def test_the_tool_asks_for_reasons_and_refuses_unknown_ones(drawn):
    from tests.test_review_tool import call, serve

    folder, items = drawn
    proc, base = serve(folder)
    try:
        item = items[0]
        body = judged(item, "mostly")
        status, text = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 400 and "p1 plausible reasons" in text
        body["purposes"]["p1"]["plausible_reasons"] = ["nonsense"]
        status, text = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 400 and "plausible_reasons" in text
        body["purposes"]["p1"]["plausible_reasons"] = ["overstates"]
        status, _ = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 200
        status, shown = call(base, "/items/0")
        assert shown["questions"]["reasons"]["plausible"]["when"] == ["mostly", "partly"]
    finally:
        proc.kill()
        proc.wait()
    page = (rex.TOOL / "public" / "expectation.html").read_text()
    assert "toggleReason" in page and "Why not a plain yes?" in page and "<i>Mostly</i>" in page


def test_other_needs_its_written_reason_which_the_scores_list(drawn):
    folder, items = drawn
    item = items[0]
    assert "p1: plausible other reason" in rx.problems(item, judged(item, "partly", ["other"]))
    blank = judged(item, "partly", ["other"])
    blank["purposes"]["p1"]["plausible_other"] = "   "
    assert "p1: plausible other reason" in rx.problems(item, blank)
    given = judged(item, "partly", ["other", "vague"])
    given["purposes"]["p1"]["plausible_other"] = " names the wrong company "
    assert not rx.problems(item, given)
    (folder / rx.REVIEWS).write_text(json.dumps({item["id"]: given}))
    s = rx.score(folder)
    listed = [o for e in s["estimates"] if e["question"] == "plausible" for o in e.get("other_reasons", [])]
    assert {"id": item["id"], "purpose": "p1", "answer": "partly", "text": "names the wrong company"} in listed


@pytest.mark.skipif(
    not shutil.which("node") or not (rex.TOOL / "node_modules").is_dir(), reason="Node.js or the tool's modules missing"
)
def test_the_tool_asks_for_the_text_of_other(drawn):
    from tests.test_review_tool import call, serve

    folder, items = drawn
    proc, base = serve(folder)
    try:
        item = items[0]
        body = judged(item, "mostly", ["other"])
        status, text = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 400 and "p1 plausible other reason" in text
        body["purposes"]["p1"]["plausible_other"] = 42
        status, text = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 400 and "must be text" in text
        body["purposes"]["p1"]["plausible_other"] = "names the wrong company"
        status, _ = call(base, f"/reviews/{item['id']}", "PUT", body)
        assert status == 200
    finally:
        proc.kill()
        proc.wait()
    page = (rex.TOOL / "public" / "expectation.html").read_text()
    assert "otherAsked" in page and "Your reason (required)" in page


# -- mostly and reasons for every question with partly (24 Nov 2026) --------------------------------------------------


def test_every_question_with_partly_offers_mostly_and_its_own_reasons():
    from skuld import review
    from skuld import review_reasons as rr

    for q in ("plausible", "cites"):
        assert "mostly" in rx.PURPOSE_QUESTIONS[q] and q in rx.REASONS
    for q in ("relationship", "steps"):
        assert "mostly" in rx.DEPENDENCY_QUESTIONS[q] and q in rx.REASONS
    assert "mostly" in review.EVIDENCE and "mostly" in review.FOLLOWS
    lists = {q: [o[0] for o in r["options"]] for q, r in {**rr.STAGE_ONE, **rr.CONCERNS}.items()}
    assert all(ids[-1] == "other" and len(ids) >= 5 for ids in lists.values())
    # tailored: no two questions share their list
    assert len({tuple(ids) for ids in lists.values()}) == len(lists)


def test_a_needs_mostly_names_its_reasons_and_they_are_counted(drawn):
    folder, items = drawn
    item = items[0]
    r = full_review(item)
    dep = next(iter(r["dependencies"]))
    r["dependencies"][dep] = {"relationship": "mostly", "steps": "yes"}
    assert f"{dep}: relationship reasons" in rx.problems(item, r)
    r["dependencies"][dep]["relationship_reasons"] = ["overstated", "other"]
    assert f"{dep}: relationship other reason" in rx.problems(item, r)
    r["dependencies"][dep]["relationship_other"] = "the SDK works without it"
    assert not rx.problems(item, r)
    (folder / rx.REVIEWS).write_text(json.dumps({item["id"]: r}))
    s = rx.score(folder)
    rel = [e for e in s["estimates"] if e["question"] == "relationship" and e["role"] == "all"]
    assert sum(e.get("reasons", {}).get("mostly:overstated", 0) for e in rel) == 1
    assert any(o["text"] == "the SDK works without it" for e in rel for o in e.get("other_reasons", []))


def test_a_concern_criterions_reasons_are_carried_scored_and_weighted(tmp_path, monkeypatch):
    from skuld import review
    from tests.test_review import FRAME, assessment
    from tests.test_review import workspace as concern_workspace

    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])
    runs = [concern_workspace(tmp_path, "model-x", assessment()), concern_workspace(tmp_path, "model-y", assessment())]
    folder = tmp_path / "c"
    review.draw(folder, runs, per_stratum=5, seed=1)
    sample = read(folder / review.SAMPLE)
    assert sample["questions"]["criteria"]["follows"] == ["yes", "mostly", "partly", "no"]
    assert [o["id"] for o in sample["questions"]["reasons"]["evidence"]["options"]][-1] == "other"
    ids = [i["id"] for i in sample["items"]]
    first = {
        i: {"overall": "agree", "evidence": "mostly", "evidence_reasons": ["fragmented"], "follows": "yes"} for i in ids
    }
    second = {i: {"overall": "agree", "evidence": "yes", "follows": "yes"} for i in ids}
    (folder / review.REVIEWS).write_text(json.dumps(first))
    s = review.score(folder)
    counted = [c for c in s["criteria"] if c.get("reasons")]
    assert counted and all(c["reasons"] == {"evidence:mostly:fragmented": c["evidence"]["mostly"]} for c in counted)
    (folder / review.REVIEWS).unlink()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(first))
    b.write_text(json.dumps(second))
    out = review.agree(folder, a, b)
    assert "weighted_kappa" in out["overall"]["evidence"] and "weighted_kappa" in out["overall"]["follows"]
    assert "weighted_kappa" not in out["overall"]["overall"]


@pytest.mark.skipif(
    not shutil.which("node") or not (rex.TOOL / "node_modules").is_dir(), reason="Node.js or the tool's modules missing"
)
def test_the_tool_checks_a_concern_criterions_reasons(tmp_path, monkeypatch):
    from skuld import review
    from tests.test_review import FRAME, assessment
    from tests.test_review import workspace as concern_workspace
    from tests.test_review_tool import call, serve

    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])
    runs = [concern_workspace(tmp_path, "model-x", assessment()), concern_workspace(tmp_path, "model-y", assessment())]
    folder = tmp_path / "c"
    review.draw(folder, runs, per_stratum=5, seed=1)
    item = next(i for i in read(folder / review.SAMPLE)["items"] if not i.get("blind_phrases"))
    proc, base = serve(folder)
    try:
        status, text = call(base, f"/reviews/{item['id']}", "PUT", {"evidence": "mostly", "evidence_reasons": ["nope"]})
        assert status == 400 and "evidence_reasons" in text
        status, _ = call(
            base, f"/reviews/{item['id']}", "PUT", {"evidence": "mostly", "evidence_reasons": ["fragmented"]}
        )
        assert status == 200
        status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"evidence": "yes"})
        assert "evidence_reasons" not in json.loads((folder / review.REVIEWS).read_text())[item["id"]]
        status, shown = call(base, "/items/0")
        assert shown["questions"]["criteria"]["evidence"][1] == "mostly"
    finally:
        proc.kill()
        proc.wait()
    page = (rex.TOOL / "public" / "aggregate.html").read_text()
    assert "setCriterion" in page and "Why not a plain yes?" in page
