from ratatoskr.vocabularies import Vocabulary

from skuld import corpus

PASSAGE = """id: {id}
title: Identifiers
source: https://example.org/ids
retrieved: 2026-10-21
kind: platform
about:
  nodes: [device-or-other-ids.advertising-id]
  entities: [{entity}]
text: >-
  The advertising ID is resettable.
"""


def test_a_passage_is_relied_on_once_a_person_has_checked_it_against_its_source(tmp_path):
    (tmp_path / "ids.yaml").write_text(PASSAGE.format(id="ids", entity="appsflyer"))
    (tmp_path / "other.yaml").write_text(
        PASSAGE.format(id="wrong", entity="") + "verified: {by: assessor, date: 2026-10-23}\n"
    )
    problems = corpus.problems(corpus.load(tmp_path))
    assert problems == ["ids: not verified against its source (verified: {by, date})", "other.yaml: its id is wrong"]


def test_a_verification_written_as_text_is_named_not_taken(tmp_path):
    (tmp_path / "ids.yaml").write_text(PASSAGE.format(id="ids", entity="") + "verified: A. Person, 2026-10-24\n")
    assert corpus.problems(corpus.load(tmp_path)) == ["ids: verified is not a mapping (verified: {by, date})"]


def test_coverage_lists_what_os_claims_name_that_no_passage_is_about(tmp_path):
    (tmp_path / "ids.yaml").write_text(PASSAGE.format(id="ids", entity="appsflyer"))
    found = corpus.load(tmp_path)

    def claim(app, node, entity=None):
        return {"application": app, "datum": {"node": node}, "recipient": {"entity": entity} if entity else None}

    reports = [
        {"claims": [claim("a", "device-or-other-ids.advertising-id", "appsflyer"), claim("a", "location.coordinates")]},
        {"claims": [claim("b", "location.coordinates", "adjust"), claim("b", "data", "?")]},
    ]
    missing = corpus.coverage(found, reports, Vocabulary.load("asgard-data"))
    assert missing == {
        "node:location.coordinates": {"applications": ["a", "b"], "claims": 2},
        "entity:adjust": {"applications": ["b"], "claims": 1},
    }
