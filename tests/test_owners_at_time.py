"""Owners at the scope's time: a recipient observed, or named by D, before an acquisition is read with its owner then,
not today's (Ratatoskr's `at=`; TODO "Owners at the scope's time")."""

from ratatoskr.registry import Registry

from skuld import assessment, parties

#: AppCo bought TrackCo on 2026-11-01; before, TrackCo was owned by no one
REGISTRY = Registry(
    {
        "entities": [
            {"id": "appco", "name": "AppCo", "domains": ["appco.example"]},
            {
                "id": "trackco",
                "name": "TrackCo",
                "domains": ["trackco.example"],
                "parent": "appco",
                "parents": [{"parent": "appco", "from": "2026-11-01", "to": None, "assertion": "a1"}],
            },
        ]
    }
)
PROVIDER = parties.Controller(frozenset({"appco"}), frozenset({"appco.example"}), "appco.example")


def test_a_recipient_before_its_acquisition_is_another_organisation():
    before = parties.relate("trackco", REGISTRY, PROVIDER, at=assessment.at("2026-10-22T21:54:12.192+00:00"))
    after = parties.relate("trackco", REGISTRY, PROVIDER, at=assessment.at("2026-11-12T08:00:00Z"))
    assert before.relation == parties.OTHER and after.relation == parties.OWN
    # without a time, today's owner, as before
    assert parties.relate("trackco", REGISTRY, PROVIDER).relation == parties.OWN


def test_a_time_that_cannot_be_read_is_none():
    assert assessment.at(None) is None and assessment.at("yesterday") is None


def test_a_study_that_pins_its_register_reads_that_build_or_none(tmp_path, monkeypatch):
    import json

    import pytest
    from ratatoskr.errors import ConfigError

    from skuld import config

    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"entities": [{"id": "appco", "name": "AppCo", "domains": ["appco.example"]}]}))
    digest = Registry.load(path).digest()
    loaded = dict(config.load())

    def pinned(sha):
        monkeypatch.setattr(config, "load", lambda: {**loaded, "registry": {"path": str(path), "sha256": sha}})

    pinned(digest)
    assert "appco" in parties.load_registry().entities
    pinned("0" * 64)
    with pytest.raises(ConfigError, match="pins"):
        parties.load_registry()
    # absent while pinned: refused, not read as no register
    with pytest.raises(ConfigError, match="No recipient registry"):
        parties.load_registry(tmp_path / "none.json")
    # absent and unpinned, the recipients are domains, as before
    pinned(None)
    assert parties.load_registry(tmp_path / "none.json") is None
