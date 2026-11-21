import pytest
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


def _passage(folder, id_, about, kind="platform", extra=""):
    (folder / f"{id_}.yaml").write_text(
        f"id: {id_}\ntitle: t\nsource: https://example.org\nkind: {kind}\n{extra}about: {about}\ntext: x\n"
    )


def test_passages_about_the_datum_never_push_out_those_about_its_recipient(tmp_path):
    for n in range(5):
        _passage(tmp_path, f"a{n}", "{nodes: [device-or-other-ids.advertising-id]}")
    for n in range(4):
        _passage(tmp_path, f"z{n}", "{entities: [adco]}", kind="component")
    data = Vocabulary.load("asgard-data")
    found = corpus.load(tmp_path).about("device-or-other-ids.advertising-id", "adco", data)
    # at most PER_NODE (4) about the node and PER_ENTITY (3) about the entity, each capped on its own
    assert (corpus.PER_NODE, corpus.PER_ENTITY) == (4, 3)
    assert [p.id for p in found] == ["a0", "a1", "a2", "a3", "z0", "z1", "z2"]
    # four about the node and none about an entity: all four (the Advertising ID's fourth passage, 21 Nov 2026)
    assert [p.id for p in corpus.load(tmp_path).about("device-or-other-ids.advertising-id", None, data)] == [
        "a0",
        "a1",
        "a2",
        "a3",
    ]
    # fewer: all of them, in the corpus's order
    for name in ("a2", "a3", "a4", "z2", "z3"):
        (tmp_path / f"{name}.yaml").unlink()
    found = corpus.load(tmp_path).about("device-or-other-ids.advertising-id", "adco", data)
    assert [p.id for p in found] == ["a0", "a1", "z0", "z1"]


def test_the_root_datum_finds_no_passage_by_node_only_by_entity(tmp_path):
    for n in range(2):
        (tmp_path / f"a{n}.yaml").write_text(
            f"id: a{n}\ntitle: t\nsource: https://example.org\nkind: platform\n"
            "about: {nodes: [device-or-other-ids.advertising-id]}\ntext: x\n"
        )
    (tmp_path / "r.yaml").write_text(
        "id: r\ntitle: t\nsource: https://example.org\nkind: platform\nabout: {nodes: [data]}\ntext: x\n"
    )
    (tmp_path / "z.yaml").write_text(
        "id: z\ntitle: t\nsource: https://example.org\nkind: component\nabout: {entities: [adco]}\ntext: x\n"
    )
    found, data = corpus.load(tmp_path), Vocabulary.load("asgard-data")
    assert [p.id for p in found.about("data", "adco", data)] == ["z"]
    assert found.about("data", None, data) == []
    # a node other than the root: as before, the node above it (the root) and the node itself
    assert [p.id for p in found.about("device-or-other-ids.advertising-id", None, data)] == ["a0", "a1", "r"]


def test_a_passage_without_its_title_or_text_is_named_not_a_traceback(tmp_path):
    (tmp_path / "ids.yaml").write_text(PASSAGE.format(id="ids", entity="appsflyer").replace("title: Identifiers\n", ""))
    with pytest.raises(corpus.CorpusError, match="ids.yaml: no title"):
        corpus.load(tmp_path)
