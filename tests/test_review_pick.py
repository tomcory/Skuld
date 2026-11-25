"""skuld review pick: a calibration sample of chosen units (0.12.38)."""

import json

import pytest

from skuld import review, review_pick
from tests.test_review import FRAME, assessment, workspace


@pytest.fixture(autouse=True)
def no_workspace_files(monkeypatch):
    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])


@pytest.fixture
def runs(tmp_path):
    return [workspace(tmp_path, "model-x", assessment()), workspace(tmp_path, "model-y", assessment(("criteo",)))]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_picked_units_are_renumbered_with_why_and_never_of_a_sample_to_avoid(tmp_path, runs):
    source, other = tmp_path / "candidates", tmp_path / "review"
    review.draw(source, runs, per_stratum=5, seed=3)
    review.draw(other, runs, per_stratum=1, seed=4, steps=["not_specific"])
    taken = set(review_pick.identities(other))
    free = [iid for ident, iid in review_pick.identities(source).items() if ident not in taken]
    clash = [iid for ident, iid in review_pick.identities(source).items() if ident in taken]
    assert free and clash
    with pytest.raises(review_pick.PickError, match="avoid"):
        review_pick.pick(source, tmp_path / "x", [clash[0]], {clash[0]: "a case"}, [other])
    with pytest.raises(review_pick.PickError, match="why"):
        review_pick.pick(source, tmp_path / "y", free[:1], {}, [other])
    m = review_pick.pick(source, tmp_path / "cal", free[:2], {i: f"case {i}" for i in free[:2]}, [other], prefix="k")
    sample, key = read(tmp_path / "cal" / review.SAMPLE), read(tmp_path / "cal" / review.KEY)
    assert [i["id"] for i in sample["items"]] == ["k01", "k02"] and set(key) == {"k01", "k02"}
    assert [u["from"] for u in m["derived"]["units"]] == free[:2]
    assert set(sample["applications"]) == {i["application"] for i in sample["items"]}
    assert m["files"]["sample.json"] and m["derived"]["avoided"]
    assert all(not i.get("blind_first") for i in sample["items"])
    # the derived sample is a sample: picked again, from itself
    review_pick.identities(tmp_path / "cal")
