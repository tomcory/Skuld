"""skuld review exclude: a drawn sample without a withdrawn application's units, with the strata's populations reduced."""

import json
import shutil
from pathlib import Path

import pytest

from skuld import review
from skuld import review_exclude as rex
from skuld import review_expectation as rx
from tests import test_review as tr
from tests import test_review_expectation as tre


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def as_app(root: Path, package: str) -> Path:
    """A copy of a synthetic workspace as another application of the same run."""
    other = root.parent / f"{package}@1"
    shutil.copytree(root, other)
    for name in ("assessment.json", "aggregate.json"):
        p = other / name
        if p.is_file():
            data = read(p)
            if "application" in data:
                data["application"] = {"package": package, "version": "1"}
            p.write_text(json.dumps(data), encoding="utf-8")
    return other


def withdraw(roots: list[Path], to: Path) -> list[Path]:
    """Moves the workspaces out of their runs, as the study does with a withdrawn application."""
    moved = []
    for root in roots:
        target = to / f"_withdrawn-{root.parent.name}" / root.name
        target.parent.mkdir(parents=True)
        shutil.move(root, target)
        moved.append(target)
    return moved


def test_stage1_sample_loses_the_application_and_its_share_of_each_stratum(tmp_path):
    base = tmp_path / "skuld"
    kept = [tre.workspace(base, "model-x"), tre.workspace(base, "model-y")]
    gone = [as_app(r, "c.d") for r in kept]
    folder = tmp_path / "s"
    m = rx.draw(folder, kept + gone, per_stratum=1, seed=3)
    key = read(folder / rx.KEY)
    gone_keys = {w["key"] for w in m["workspaces"] if w["application"] == "c.d@1"}
    dropped = {i for i, e in key.items() if e["workspace"] in gone_keys}
    assert dropped  # the draw picked some of c.d's units
    reviews = {i: tre.full_review(it) for it in read(folder / rx.SAMPLE)["items"] for i in [it["id"]]}
    (folder / rx.REVIEWS).write_text(json.dumps(reviews), encoding="utf-8")

    moved = withdraw(gone, tmp_path)
    out = tmp_path / "derived"
    d = rex.exclude(folder, out, moved, ["c.d"], "withdrawn")

    assert d["derived"]["excluded"] == ["c.d@1"] and set(d["derived"]["units"]) == dropped
    assert {i["id"] for i in read(out / rx.SAMPLE)["items"]} == set(key) - dropped  # ids kept
    assert set(read(out / rx.REVIEWS)) == set(key) - dropped
    assert all(w["application"] == "a.b@1" for w in d["workspaces"])
    # each application contributes the same units per stratum here, so every population halves
    before = {rx._skey(s): s for s in m["strata"]}
    for s in d["strata"]:
        assert s["population"] * 2 == before[rx._skey(s)]["population"]
        assert s["drawn"] <= s["population"]
    assert rx.score(out)["units"] == len(key) - len(dropped)
    # a reviewer's file of the original sample is read against the derived key unchanged
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(reviews), encoding="utf-8")
    b.write_text(json.dumps(reviews), encoding="utf-8")
    (out / rx.REVIEWS).unlink()
    assert rx.agree(out, a, b)["differences"] == []


def test_the_withdrawn_workspace_must_be_the_one_drawn_from(tmp_path):
    base = tmp_path / "skuld"
    kept = [tre.workspace(base, "model-x")]
    gone = [as_app(kept[0], "c.d")]
    folder = tmp_path / "s"
    rx.draw(folder, kept + gone, per_stratum=1, seed=3)
    with pytest.raises(rex.ExcludeError, match="give the workspace"):
        rex.exclude(folder, tmp_path / "o1", [], ["c.d"], "withdrawn")
    with pytest.raises(rex.ExcludeError, match="no workspace of"):
        rex.exclude(folder, tmp_path / "o2", gone, ["x.y"], "withdrawn")
    a = read(gone[0] / "assessment.json")
    a["claims"] = a["claims"][:1]
    (gone[0] / "assessment.json").write_text(json.dumps(a), encoding="utf-8")
    with pytest.raises(rex.ExcludeError, match="give the workspace"):  # changed: its digest matches no record
        rex.exclude(folder, tmp_path / "o3", gone, ["c.d"], "withdrawn")
    (folder / rx.KEY).write_text("{}", encoding="utf-8")
    with pytest.raises(rex.ExcludeError, match="not the file drawn"):
        rex.exclude(folder, tmp_path / "o4", gone, ["c.d"], "withdrawn")


def test_concern_sample_loses_the_application_its_documents_and_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "_frame", lambda root: tr.FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])
    base = tmp_path / "skuld"
    kept = [tr.workspace(base, "model-x", tr.assessment()), tr.workspace(base, "model-y", tr.assessment(("criteo",)))]
    for r in kept:  # the synthetic reports name no application; the draw reads it from the report
        a = read(r / "assessment.json")
        a["application"] = {"package": "a.b", "version": "1"}
        (r / "assessment.json").write_text(json.dumps(a), encoding="utf-8")
    gone = [as_app(r, "c.d") for r in kept]
    folder = tmp_path / "s"
    m = review.draw(folder, kept + gone, per_stratum=50, seed=1)
    (folder / review.RECALL).write_text(
        json.dumps({"a.b@1": {"done": True}, "c.d@1": {"done": True}}), encoding="utf-8"
    )
    moved = withdraw(gone, tmp_path)
    out = tmp_path / "derived"
    d = rex.exclude(folder, out, moved, ["c.d@1"], "withdrawn")
    sample = read(out / review.SAMPLE)
    assert list(sample["applications"]) == ["a.b@1"]
    assert list(read(out / review.RECALL)) == ["a.b@1"]
    # every unit was drawn (50 per stratum), so after the exclusion drawn equals population in every stratum
    assert all(s["drawn"] == s["population"] for s in d["strata"])
    assert sum(s["population"] for s in d["strata"]) * 2 == sum(s["population"] for s in m["strata"])
    assert review.score(out)
