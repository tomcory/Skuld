"""A reviewer's package (skuld.review_export): what it holds, what it never holds, and the import of the returns."""

import json
import zipfile

import pytest

from skuld import review_expectation as rx
from skuld import review_export as rex
from tests.test_review_expectation import workspace


@pytest.fixture
def drawn(tmp_path):
    runs = [workspace(tmp_path, "model-x"), workspace(tmp_path, "model-y")]
    folder = tmp_path / "reviews" / "expect-1"
    rx.draw(folder, runs, per_stratum=5, seed=2)
    return folder


@pytest.mark.skipif(not (rex.TOOL / "node_modules").is_dir(), reason="the review tool's modules are not installed")
def test_the_package_holds_the_tool_and_the_sample_never_the_key(tmp_path, drawn):
    out = rex.export(tmp_path / "pkg.zip", [drawn], "a")
    names = zipfile.ZipFile(out).namelist()
    root = "asgard-review-a/"
    assert all(n.startswith(root) for n in names)
    assert f"{root}samples/expect-1/sample.json" in names and f"{root}tool/server.js" in names
    assert f"{root}tool/public/expectation.html" in names and f"{root}start-expect-1.command" in names
    assert f"{root}tool/node_modules/express/package.json" in names
    assert f"{root}tool/node_modules/vue/dist/vue.esm-browser.prod.js" in names
    assert not any(n.endswith(("key.json", "manifest.json")) for n in names)
    assert not any("/@babel/" in n for n in names)
    mode = zipfile.ZipFile(out).getinfo(f"{root}start-expect-1.command").external_attr >> 16
    assert mode & 0o111
    with pytest.raises(rex.ReviewError, match="exists"):
        rex.export(out, [drawn], "a")


def test_a_sample_that_names_its_run_is_not_exported(tmp_path, drawn):
    sample = json.loads((drawn / "sample.json").read_text())
    sample["items"][0]["note"] = "model-x"
    (drawn / "sample.json").write_text(json.dumps(sample))
    with pytest.raises(rex.ReviewError, match="not blind"):
        rex._check_blind(drawn)


def test_returned_reviews_are_filed_per_reviewer_keeping_an_earlier_return(tmp_path, drawn):
    returned = tmp_path / "reviews-a.zip"

    def pack(note):
        with zipfile.ZipFile(returned, "w") as z:
            z.writestr("reviewer.json", json.dumps({"reviewer": "a"}))
            z.writestr("samples/expect-1/reviews.json", json.dumps({"x001": {"note": note}}))

    pack("first")
    [target] = rex.import_(returned, drawn.parent)
    assert target == drawn.parent / "expect-1-a" / "reviews.json"
    assert (target.parent / "sample.json").is_file()
    pack("second")
    rex.import_(returned, drawn.parent)
    assert json.loads(target.read_text())["x001"]["note"] == "second"
    assert len(list(target.parent.glob("reviews.json.*.bak"))) == 1
    pack("third")  # within the same second: both earlier returns are kept
    rex.import_(returned, drawn.parent)
    assert len(list(target.parent.glob("reviews.json.*.bak"))) == 2


def test_a_finder_zips_appledouble_copy_is_not_read_as_reviewer_json(tmp_path, drawn):
    returned = _zip(
        tmp_path / "reviews-a.zip",
        {
            "__MACOSX/pkg/._reviewer.json": "\x00\x05binary",
            "pkg/reviewer.json": {"reviewer": "a"},
            "pkg/samples/expect-1/reviews.json": {"x001": {"note": "n"}},
        },
    )
    [target] = rex.import_(returned, drawn.parent)
    assert target == drawn.parent / "expect-1-a" / "reviews.json"


def _zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, str) else json.dumps(data))
    return path


def test_a_flat_zip_is_read_as_the_packages_one_sample(tmp_path, drawn):
    """Reviewer A's zip held reviews.json next to reviewer.json, and the import filed nothing and said nothing."""
    unit = json.loads((drawn / "sample.json").read_text())["items"][0]["id"]
    entry = {"note": "", "reviewed": "2026-11-14T10:06:17.667Z"}
    meta = {"reviewer": "a", "samples": [{"name": "expect-1", "kind": "x"}], "made": "2026-11-13T12:00:00+00:00"}
    flat = _zip(tmp_path / "flat.zip", {"reviewer.json": meta, "reviews.json": {unit: entry}})
    flags = []
    [target] = rex.import_(flat, drawn.parent, flags)
    assert target == drawn.parent / "expect-1-a" / "reviews.json" and flags == []
    two = {**meta, "samples": [{"name": "expect-1", "kind": "x"}, {"name": "other", "kind": "x"}]}
    with pytest.raises(rex.ReviewError, match="without its sample's folder, and the package names 2 samples"):
        rex.import_(_zip(tmp_path / "two.zip", {"reviewer.json": two, "reviews.json": {}}), drawn.parent)


def test_a_returned_package_cannot_name_a_path_outside_the_reviews_folder(tmp_path, drawn):
    unit = json.loads((drawn / "sample.json").read_text())["items"][0]["id"]
    for meta in (
        {"reviewer": "../x", "samples": [{"name": "expect-1", "kind": "x"}]},
        {"reviewer": "a", "samples": [{"name": "../expect-1", "kind": "x"}]},
    ):
        hostile = _zip(tmp_path / "h.zip", {"reviewer.json": meta, "reviews.json": {unit: {}}})
        with pytest.raises(rex.ReviewError, match="no plain name"):
            rex.import_(hostile, drawn.parent)


def test_a_zip_from_which_nothing_is_filed_is_refused(tmp_path, drawn):
    empty = _zip(tmp_path / "e.zip", {"reviewer.json": {"reviewer": "a"}, "notes.txt": "hi"})
    with pytest.raises(rex.ReviewError, match="no reviews.json or recall.json .*notes.txt"):
        rex.import_(empty, drawn.parent)


def test_a_return_whose_times_are_not_the_tools_is_flagged(tmp_path, drawn):
    """Reviewer B's file had every `reviewed` at 1970-01-01T00:00:00.0000 and no notes."""
    unit = json.loads((drawn / "sample.json").read_text())["items"][0]["id"]
    meta = {"reviewer": "b", "made": "2026-11-13T12:00:00+00:00"}
    reviews = {unit: {"reviewed": "1970-01-01T00:00:00.0000"}, "zz999": {"reviewed": "1970-01-01T00:00:00.000Z"}}
    returned = _zip(tmp_path / "b.zip", {"reviewer.json": meta, "samples/expect-1/reviews.json": reviews})
    flags = []
    [target] = rex.import_(returned, drawn.parent, flags)
    assert target.is_file()  # filed nonetheless: the reviews are the reviewer's
    text = "\n".join(flags)
    assert "zz999 is no unit of the sample" in text
    assert "1 of 2 entries have a reviewed time not in the tool's format" in text
    assert "1 of 2 entries were reviewed outside the review period (zz999: 1970-01-01T00:00:00.000Z)" in text
