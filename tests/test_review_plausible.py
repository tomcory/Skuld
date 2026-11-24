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
    assert [o["id"] for o in reasons["options"]] == ["overstates", "vague", "bundles", "part_of_flow", "loose_fit"]
    assert all(o["label"] and o["hint"] for o in reasons["options"])
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
