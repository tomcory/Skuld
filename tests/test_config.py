"""Skuld's configuration: config.json, a named profile over it, the files it names by digest, and its provenance."""

import json
import os

import pytest
from ratatoskr.errors import ConfigError

from skuld import config, expectation
from skuld.cli import main

#: The digest of the Expectation paper's purpose map, as its assessments name it (`node_mapping.map`)
STUDY_MAP = "2c8e24b1ddb8e20e0aaf216ff635ffa4d9b32f3c89fe1b26a565561ede8cc252"


@pytest.fixture
def fresh(monkeypatch):
    """No profile and Skuld's own config.json, before and after (load and the purpose map are cached)."""
    monkeypatch.delenv("SKULD_PROFILE", raising=False)
    monkeypatch.delenv("SKULD_CONFIG", raising=False)

    def clear():
        config.load.cache_clear()
        expectation._purpose_map_file.cache_clear()

    clear()
    yield monkeypatch
    os.environ.pop("SKULD_PROFILE", None)  # `skuld --profile` sets it itself, outside monkeypatch
    clear()


def test_without_a_profile_it_is_config_json(fresh):
    assert config.provenance()["profile"] is None
    assert config.load()["model"] == json.loads(config.CONFIG.read_text())["model"]
    assert config.file("purpose_map") is None and expectation.purpose_map() == {}


def test_the_studys_profiles_are_its_final_setups(fresh):
    assert set(config.profiles()) >= {"study-2026-11-gemma-vendor", "study-2026-11-qwen-low-traffic-topup"}
    fresh.setenv("SKULD_PROFILE", "study-2026-11-gemma-vendor")
    c = config.load()
    assert c["model"] == "gemma4:31b"
    assert c["sampling"]["default"]["max_tokens"] == 32768
    assert c["sampling"]["tasks"]["expect"] == {"temperature": 1.0, "top_p": 0.95, "top_k": 64}
    # the study profiles state what they had from config.json then, so that a later config.json changes no study run
    assert c["sampling"]["tasks"]["propose"] == {"temperature": 0.2, "seed": 1}
    assert c["sampling"]["default"]["temperature"] == 0.0 and c["sampling"]["default"]["top_k"] is None
    # think is part of a sample's options, which identify it: the profile keeps the run's "low" to keep its samples
    assert c["expectation"]["think"] == "low" and c["expectation"]["traffic"] and c["expectation"]["topup"]
    assert c["client"]["timeout"] == 1800.0 and c["client"]["limits"]["models"]["gemma4:31b"] == 8
    assert c["assessment"]["known_data_only"] and c["assessment"]["seeds"] == [1, 2, 3]
    assert "description" not in c
    # the purpose map is in the repository, named by a relative path and its digest
    assert config.file("purpose_map") == (config.ROOT / "purpose-maps" / "study-2026-11.json", STUDY_MAP)
    assert expectation.purpose_map()["Identification"]["node"] == "IdentityVerification"
    assert expectation.purpose_map_sha256() == STUDY_MAP
    fresh.setenv("SKULD_PROFILE", "study-2026-11-qwen-low-traffic-topup")
    config.load.cache_clear()
    c = config.load()
    assert c["model"] == "qwen3.8:27b" and c["sampling"]["tasks"]["expect"] == {"temperature": 0.4}
    assert c["expectation"]["think"] == "low" and c["client"]["timeout"] == 1800.0


def test_a_profile_merges_key_by_key_and_lists_replace():
    below = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    assert config.merge(below, {"a": {"y": [3]}, "c": 2}) == {"a": {"x": 1, "y": [3]}, "b": 1, "c": 2}
    assert below == {"a": {"x": 1, "y": [1, 2]}, "b": 1}  # unchanged


def test_an_unknown_profile_and_a_changed_file_are_refused(fresh, tmp_path):
    fresh.setenv("SKULD_PROFILE", "no-such-profile")
    with pytest.raises(ConfigError, match="Unknown profile no-such-profile; Skuld's are .*study-2026-11-gemma-vendor"):
        config.load()
    fresh.delenv("SKULD_PROFILE")
    changed = tmp_path / "map.json"
    changed.write_text('{"entries": {}}', encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"purpose_map": {"path": str(changed), "sha256": STUDY_MAP}}), encoding="utf-8")
    fresh.setenv("SKULD_CONFIG", str(cfg))
    config.load.cache_clear()
    with pytest.raises(ConfigError, match="not the 2c8e24b1ddb8 named"):
        config.file("purpose_map")
    # a path alone, as before profiles, is read without a digest to check
    cfg.write_text(json.dumps({"purpose_map": str(changed)}), encoding="utf-8")
    config.load.cache_clear()
    assert config.file("purpose_map")[0] == changed


def test_the_provenance_names_the_profile_and_what_was_in_force(fresh):
    plain = config.provenance()
    fresh.setenv("SKULD_PROFILE", "study-2026-11-gemma-vendor")
    config.load.cache_clear()
    p = config.provenance()
    assert p["profile"] == "study-2026-11-gemma-vendor" and p["file"] == str(config.CONFIG)
    assert len(p["sha256"]) == 64 and p["sha256"] != plain["sha256"]


def test_a_run_manifest_records_the_configuration(fresh, tmp_path):
    from skuld import manifest

    fresh.setenv("SKULD_PROFILE", "study-2026-11-gemma-vendor")
    with manifest.metered("expect", {"model": "m"}, tmp_path) as run:
        pass
    data = json.loads(run.path.read_text(encoding="utf-8"))
    assert data["configuration"]["profile"] == "study-2026-11-gemma-vendor"


def test_the_command_line_chooses_and_shows_a_profile(fresh, capsys):
    assert main(["config", "--profiles"]) == 0
    assert "study-2026-11-qwen-low-traffic-topup" in capsys.readouterr().out
    assert main(["--profile", "study-2026-11-qwen-low-traffic-topup", "config"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["profile"] == "study-2026-11-qwen-low-traffic-topup" and shown["config"]["model"] == "qwen3.8:27b"
    assert main(["--profile", "nope", "config"]) == 1


@pytest.mark.parametrize(
    "argv, why",
    [
        (["review", "score", "f", "--per-run", "5"], "review score does not read --per-run"),
        (["review", "export", "f", "--application", "x"], "review export does not read --application"),
        (["calibrate", "agree", "f", "--registry", "r"], "calibrate agree does not read --registry"),
        (["select", "ws", "--list", "--budget-seconds", "60"], "the budget is select's alone"),
        (["freeze", "ws", "--author", "x", "--prompt", "p"], "give --model too"),
    ],
)
def test_an_option_the_command_does_not_read_is_refused(argv, why, capsys):
    from skuld import cli

    assert cli.main(argv) == 2
    assert why in capsys.readouterr().err
