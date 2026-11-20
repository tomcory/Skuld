"""The review of aggregated concerns (skuld.review): the draw (blind to the run), the scores, two reviewers' κ."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skuld import aggregate as ag
from skuld import review
from tests.test_aggregate import alternative, minimisation, not_specific, practice, purpose_claim, report

FRAME = SimpleNamespace(
    requirement=lambda rid: SimpleNamespace(id=rid, title=f"title of {rid}", provisions=("GDPR Art. 5",))
)


@pytest.fixture(autouse=True)
def no_workspace_files(monkeypatch):
    """The synthetic workspaces have no assessment.yaml: the frame is stubbed and no documents are copied."""
    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])


def assessment(recipients=("appnexus", "yahoo"), phrases=("improve our products", "help us improve them")):
    ps = [practice(f"P-{r}", "location.city", r) for r in recipients]
    claims, concerns = [], []
    for i, p in enumerate(ps):
        claims += [
            purpose_claim(p["id"], "TargetedAdvertising"),
            alternative(p["id"], 2, text="coarser location", supporting=["item:1"]),
        ]
        concerns.append({**minimisation(f"concern:m{i}", p["id"], 1, [f"claim:{p['id']}:2"]), "supporting": ["item:2"]})
    ds = [{"id": f"D-{i}", "value": "ImproveExistingProductsAndServices"} for i in range(len(phrases))]
    concerns += [
        {**not_specific(f"concern:s{i}", f"D-{i}", t), "supporting": ["item:3"]} for i, t in enumerate(phrases)
    ]
    r = report(concerns, claims, ps, ds)
    r["claims"][0]["purpose"].update(action="send", object="city", outcome="to target ads [S1, S2]")
    r["evidence"] = [
        {"id": "item:1", "kind": "doc", "text": "Location may be coarse.", "citation": {"id": "doc-a"}},
        {"id": "item:2", "kind": "doc", "text": "The SDK sends the city."},
        {"id": "item:3", "kind": "doc", "text": "WP203: purposes must be specific."},
    ]
    return r


def workspace(base: Path, run: str, r: dict) -> Path:
    root = base / run / "a.b@1"
    root.mkdir(parents=True)
    (root / "assessment.json").write_text(json.dumps(r), encoding="utf-8")
    (root / "aggregate.json").write_text(json.dumps(ag.aggregate(r)), encoding="utf-8")
    return root


@pytest.fixture
def runs(tmp_path):
    return [workspace(tmp_path, "model-x", assessment()), workspace(tmp_path, "model-y", assessment(("criteo",)))]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_units_show_es_output_in_full(runs):
    found, recall = review.units(runs[0])
    kinds = {u["kind"]: u for u in found}
    m = kinds["practice"]
    assert m["label"].startswith("location.city for TargetedAdvertising") and m["status"] == "not_established"
    assert {x["recipient"] for x in m["members"]} == {"appnexus", "yahoo"}
    assert m["members"][0]["alternatives"][0]["alternative"] == "coarser location"
    assert {e["id"] for e in m["evidence"]} == {"item:1", "item:2"}
    # the stage's citations point into a context the review does not show
    assert m["members"][0]["purpose_stated"]["outcome"] == "to target ads"
    d = kinds["declared"]
    assert [x["statement"] for x in d["members"]] == ["improve our products", "help us improve them"]
    assert {p["recipient"] for p in recall["practices"]} == {"appnexus", "yahoo"}


def test_the_draw_is_stratified_by_run_and_never_names_it(tmp_path, runs):
    folder = tmp_path / "review"
    manifest = review.draw(folder, runs, per_stratum=5, seed=3, anchor=1)
    sample, key = read(folder / review.SAMPLE), read(folder / review.KEY)
    assert sample["kind"] == review.KIND and {i["id"] for i in sample["items"]} == set(key)
    assert set(sample["vocabularies"]) == {"purpose", "data"}
    assert {k["run"] for k in key.values()} == {"model-x", "model-y"} == set(manifest["runs"])
    assert {s["run"] for s in manifest["strata"]} == {"model-x", "model-y"}
    shown = json.dumps(sample)
    assert "model-x" not in shown and "model-y" not in shown
    assert not any(k.startswith("_") for i in sample["items"] for k in i)
    assert sum(i.get("blind_first", False) for i in sample["items"]) == manifest["anchor"] == 1
    blind = next(i for i in sample["items"] if i.get("blind_first"))
    assert key[blind["id"]]["stratum"]["status"] == "supported"
    # the same seed draws the same sample; a drawn sample is never overwritten
    review.draw(tmp_path / "again", runs, per_stratum=5, seed=3, anchor=1)
    assert read(tmp_path / "again" / review.KEY) == key
    with pytest.raises(review.ReviewError):
        review.draw(folder, runs)


def test_a_workspace_without_its_aggregate_or_a_run_twice_is_refused(tmp_path, runs):
    (runs[0] / "aggregate.json").unlink()
    with pytest.raises(review.ReviewError, match="skuld aggregate"):
        review.draw(tmp_path / "r1", runs)
    twice = workspace(tmp_path / "elsewhere", "model-y", assessment())
    with pytest.raises(review.ReviewError, match="same run"):
        review.draw(tmp_path / "r2", [runs[1], twice])


def drawn(tmp_path, runs, anchor=0):
    folder = tmp_path / "review"
    review.draw(folder, runs, per_stratum=5, seed=3, anchor=anchor)
    return folder, read(folder / review.SAMPLE)["items"], read(folder / review.KEY)


def test_scores_are_agreement_per_unit_and_per_member(tmp_path, runs):
    folder, items, key = drawn(tmp_path, runs)
    reviews = {}
    for i in items:
        if i["kind"] == "declared":
            # one phrase of two judged not specific: half its members agree with E
            first, second = (m["concern"] for m in i["members"])
            reviews[i["id"]] = {
                "overall": "agree",
                "evidence": "yes",
                "follows": "yes",
                "phrases": {first: "not_specific", second: "specific"},
            }
        else:
            reviews[i["id"]] = {"overall": "disagree", "evidence": "partly", "follows": "no"}
    (folder / review.REVIEWS).write_text(json.dumps(reviews), encoding="utf-8")
    (folder / review.RECALL).write_text(
        json.dumps({"a.b@1": {"done": True, "missed": [{"requirement": "other", "subject": "P-x", "note": "n"}]}}),
        encoding="utf-8",
    )
    s = review.score(folder)
    assert s["measure"].startswith("agreement") and s["judged"] == len(items)
    est = {(e["run"], e["step"]): e for e in s["estimates"]}
    declared = est[("model-x", "not_specific")]
    assert declared["rate"] == 1.0 and declared["members_rate"] == 0.5
    assert est[("model-x", "less_invasive_alternative")]["rate"] == 0.0
    assert s["recall"]["applications_done"] == 1 and len(s["recall"]["missed"]) == 1
    crit = {(c["run"], c["step"]): c for c in s["criteria"]}
    assert crit[("model-y", "less_invasive_alternative")]["follows"] == {"no": 1}


def test_the_anchoring_units_compare_blind_and_non_blind(tmp_path, runs):
    folder, items, _ = drawn(tmp_path, runs, anchor=2)
    blind = [i for i in items if i.get("blind_first")]
    assert len(blind) == 2
    reviews = {
        blind[0]["id"]: {"blind": {"decision": "holds"}, "overall": "agree", "evidence": "yes", "follows": "yes"},
        blind[1]["id"]: {"blind": {"decision": "fails"}, "overall": "agree", "evidence": "yes", "follows": "yes"},
    }
    (folder / review.REVIEWS).write_text(json.dumps(reviews), encoding="utf-8")
    a = review.score(folder)["anchoring"]
    assert a["blind_rate"] == 0.5 and a["non_blind_rate"] == 1.0 and a["difference"] == 0.5


def test_a_changed_sample_is_not_scored(tmp_path, runs):
    folder, _, _ = drawn(tmp_path, runs)
    (folder / review.KEY).write_text("{}", encoding="utf-8")
    with pytest.raises(review.ReviewError, match="digest"):
        review.score(folder)


def test_two_reviewers_kappa_disagreements_and_seeding(tmp_path, runs):
    folder, items, _ = drawn(tmp_path, runs)
    ids = [i["id"] for i in items]
    first = {i: {"overall": "agree", "evidence": "yes", "follows": "yes"} for i in ids}
    second = {i: dict(first[i]) for i in ids}
    second[ids[0]] = {"overall": "disagree", "evidence": "no", "follows": "no", "note": "wrong"}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(first), encoding="utf-8")
    b.write_text(json.dumps({"reviewer": "b", "items": second}), encoding="utf-8")
    out = review.agree(folder, a, b)
    assert [d["id"] for d in out["disagreements"]] == [ids[0]]
    assert out["overall"]["overall"]["items"] == len(ids)
    assert out["overall"]["overall"]["agreed"] == len(ids) - 1
    assert set(out["runs"]) == {"model-x", "model-y"}
    seeded = read(folder / review.REVIEWS)
    assert ids[0] not in seeded and len(seeded) == len(ids) - 1


def test_agreement_refuses_a_reviews_file_that_is_not_there(tmp_path, runs):
    """A mistyped path agreed on nothing and seeded an empty reviews.json, which kept later runs from seeding."""
    folder, _, _ = drawn(tmp_path, runs)
    a = tmp_path / "a.json"
    a.write_text("{}", encoding="utf-8")
    with pytest.raises(review.ReviewError, match="no such reviews file"):
        review.agree(folder, a, tmp_path / "b-mistyped.json")
    assert not (folder / review.REVIEWS).exists()


def test_citations_are_removed_single_or_listed():
    assert review._uncited("to deliver ads [S1, S2, D3]") == "to deliver ads"
    assert review._uncited("read the ID [S1]") == "read the ID"
    assert review._uncited("[S1]") is None


def test_a_run_whose_workspaces_name_different_models_is_refused(tmp_path):
    def with_models(r, think):
        r["report"]["components"] = [{"role": "model", "id": "qwen", "stage": "assessment", **think}]
        return r

    one = workspace(tmp_path / "a", "run-q", with_models(assessment(), {"think": False}))
    other = assessment()
    other["application"] = {"package": "c.d", "version": "1"}
    root = tmp_path / "b" / "run-q" / "c.d@1"
    root.mkdir(parents=True)
    r = with_models(other, {"think": "low"})
    (root / "assessment.json").write_text(json.dumps(r), encoding="utf-8")
    (root / "aggregate.json").write_text(json.dumps(ag.aggregate(r)), encoding="utf-8")
    with pytest.raises(review.ReviewError, match="different models"):
        review.draw(tmp_path / "r", [one, root])
    manifest = review.draw(tmp_path / "ok", [one])
    assert manifest["run_models"] == {"run-q": ["qwen (think false)"]}


def test_a_workspace_that_asked_no_model_contradicts_no_run(tmp_path):
    asked = assessment()
    asked["report"]["components"] = [{"role": "model", "id": "qwen", "stage": "assessment", "think": "low"}]
    one = workspace(tmp_path / "a", "run-q", asked)
    nothing = report([])
    nothing["application"] = {"package": "c.d", "version": "1"}
    root = tmp_path / "b" / "run-q" / "c.d@1"
    root.mkdir(parents=True)
    (root / "assessment.json").write_text(json.dumps(nothing), encoding="utf-8")
    (root / "aggregate.json").write_text(json.dumps(ag.aggregate(nothing)), encoding="utf-8")
    manifest = review.draw(tmp_path / "r", [root, one])
    assert manifest["run_models"] == {"run-q": ["qwen (think low)"]}


def test_units_are_allocated_to_the_strata_in_proportion_by_default():
    strata = {
        ("x", "a"): list(range(300)),
        ("x", "b"): list(range(10)),
        ("x", "c"): list(range(2)),
        ("y", "a"): list(range(50)),
    }
    sizes = {k: review.allocation(strata, k, None, 70, 3) for k in strata}
    assert sizes == {("x", "a"): 67, ("x", "b"): 3, ("x", "c"): 2, ("y", "a"): 50}
    assert review.allocation(strata, ("x", "a"), 5, 70, 3) == 5  # equal allocation when asked


def test_a_verdict_derived_from_mixed_phrases_is_partly_and_counts_as_not_agreeing(tmp_path, runs):
    """12 Nov 2026: a declared-purpose unit E holds not specific takes its verdict from the phrases; some as E says is
    partly, which the rates count as judged and not agreeing, and an unsure phrase is left out."""
    folder, items, _ = drawn(tmp_path, runs)
    reviews = {}
    for i in items:
        if i["kind"] == "declared":
            first, second = (m["concern"] for m in i["members"])
            reviews[i["id"]] = {
                "overall": "partly",
                "derived": True,
                "evidence": "yes",
                "follows": "yes",
                "phrases": {first: "not_specific", second: "specific"},
            }
    (folder / review.REVIEWS).write_text(json.dumps(reviews), encoding="utf-8")
    s = review.score(folder)
    est = {(e["run"], e["step"]): e for e in s["estimates"]}
    assert est[("model-x", "not_specific")]["rate"] == 0.0 and est[("model-x", "not_specific")]["members_rate"] == 0.5
    assert s["judged"] == len(reviews)
    item = next(i for i in items if i["kind"] == "declared")
    first, second = (m["concern"] for m in item["members"])
    assert review._member_agreement(item, {"phrases": {first: "not_specific", second: "unsure"}}) == (1, 1)


def test_an_evidence_items_source_is_named_in_words():
    from skuld.review import source

    assert source({"kind": "claim", "claim": {"dimension": "O"}}) == "the practice as observed"
    assert source({"kind": "claim", "claim": {"dimension": "D"}}) == "the provider's documents"
    assert source({"kind": "doc", "method": 'traffic of {"claim": "c1"}'}) == "traffic as captured"
    assert source({"kind": "doc", "method": "screen of run-1"}) == "a screen of the app"
    assert (
        source({"kind": "doc", "citation": {"id": "norms/wp203-specific.yaml"}}) == "a legal norm or guidance (corpus)"
    )
    assert source({"kind": "doc", "citation": {"id": "appsflyer.yaml"}}) == "documentation (corpus)"


def test_a_draw_can_be_limited_to_steps(tmp_path, runs):
    m = review.draw(tmp_path / "x", runs, per_stratum=50, seed=1, steps=["not_specific"])
    assert m["steps"] == ["not_specific"] and {s["step"] for s in m["strata"]} == {"not_specific"}
    sample = read(tmp_path / "x" / review.SAMPLE)
    assert {i["step"] for i in sample["items"]} == {"not_specific"}
    assert set(sample["applications"]) == {i["application"] for i in sample["items"]}
