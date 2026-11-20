"""A family's review, stored beside the family file and outside its digest (20 Nov 2026)."""

from datetime import UTC, datetime

import pytest
import yaml

from skuld import catalogue
from skuld.cli import main
from tests.test_propose import FORECAST

WHEN = datetime(2026, 11, 20, 10, tzinfo=UTC)


def test_a_review_changes_neither_the_familys_digest_nor_the_catalogues(tmp_path):
    found = catalogue.load(tmp_path)
    family = found.add(FORECAST)
    assert "reviewed" not in family.data and not family.reviewed  # the empty field is no longer written
    digest, listing = family.sha256, found.sha256
    text = family.path.read_text(encoding="utf-8")

    reviewed = found.review(family.key, "author", "purposes and oracle checked", WHEN)
    assert reviewed.reviewed and reviewed.review_state() == "reviewed by author 2026-11-20"
    assert family.path.read_text(encoding="utf-8") == text
    stored = yaml.safe_load(catalogue.review_path(tmp_path, family.key).read_text(encoding="utf-8"))
    assert stored == {
        "family": family.key,
        "sha256": digest,
        "by": "author",
        "time": "2026-11-20T10:00:00+00:00",
        "note": "purposes and oracle checked",
    }

    again = catalogue.load(tmp_path)
    assert again.get(family.id).reviewed and again.get(family.id).sha256 == digest and again.sha256 == listing
    with pytest.raises(catalogue.CatalogueError, match="reviewed already"):
        again.review(family.key, "someone")
    with pytest.raises(catalogue.CatalogueError, match="no family"):
        again.review("current-location-forecast@9", "author")


def test_a_review_of_another_text_is_no_review(tmp_path):
    found = catalogue.load(tmp_path)
    family = found.add(FORECAST)
    found.review(family.key, "author", time=WHEN)
    family.path.write_text(family.path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    changed = catalogue.load(tmp_path).get(family.id)
    assert not changed.reviewed and "another text" in changed.review_state()


def test_a_review_in_the_family_file_is_still_read_and_marked_deprecated(tmp_path):
    folder = tmp_path / "families"
    folder.mkdir()
    old = {**FORECAST, "version": 1, "reviewed": {"by": "author", "time": "2026-11-12", "note": ""}}
    (folder / "current-location-forecast@1.yaml").write_text(yaml.safe_dump(old, sort_keys=False), encoding="utf-8")
    family = catalogue.load(tmp_path).get("current-location-forecast")
    assert family.reviewed and family.review["legacy"] is True
    assert family.review_state() == "reviewed by author 2026-11-12 (in the family file; deprecated)"
    with pytest.raises(catalogue.CatalogueError, match="reviewed already"):
        catalogue.load(tmp_path).review(family.key, "someone")


def test_skuld_catalogue_records_and_shows_reviews(tmp_path, capsys):
    family = catalogue.load(tmp_path).add(FORECAST)
    assert main(["catalogue", "--catalogue", str(tmp_path)]) == 0
    assert "not reviewed" in capsys.readouterr().out
    assert main(["catalogue", "--catalogue", str(tmp_path), "--review", family.key]) == 1  # no --by
    assert main(["catalogue", "--catalogue", str(tmp_path), "--review", family.key, "--by", "author"]) == 0
    capsys.readouterr()
    assert main(["catalogue", "--catalogue", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"{family.key}" in out and "reviewed by author" in out and "0 newest not reviewed" in out
