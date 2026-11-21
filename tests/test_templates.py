"""The prompts by version: the current one, or an earlier one a profile names, so that its samples are found again."""

import pytest
from ratatoskr.errors import ConfigError

from skuld import config, judge, templates


@pytest.fixture
def prompts(monkeypatch):
    def given(named: dict | None):
        loaded = dict(config.load())
        monkeypatch.setattr(config, "load", lambda: {**loaded, "prompts": named} if named is not None else loaded)

    return given


def test_the_current_prompts_put_the_context_last_after_the_fixed_instructions(prompts):
    prompts(None)
    for name in templates.CURRENT:
        text = templates.text(name)
        placeholder = "{flow}" if name == "propose" else "{context}"
        assert text.rstrip().endswith(placeholder), name
    assert "list no entry for it" in templates.text("minimisation")


def test_a_profile_that_names_an_earlier_version_gets_its_text_and_version(prompts):
    prompts({"minimisation": "2", "expectation": "4"})
    assert templates.version("minimisation") == "2" and "give none for it" in templates.text("minimisation")
    assert templates.text("expectation").index("{context}") < templates.text("expectation").index("For each practice")
    assert judge.procedure(judge.MINIMISATION)["version"] == "2"
    assert templates.version("specificity") == templates.CURRENT["specificity"]


def test_an_unknown_version_is_refused(prompts):
    prompts({"minimisation": "9"})
    with pytest.raises(ConfigError):
        templates.text("minimisation")


def test_the_prompt_versions_of_p10_and_the_ones_before_are_kept(prompts):
    """P10 (21 Nov 2026): minimisation 5 asks for typed arguments, 4 tells of the screens, specificity 3 leaves
    lawfulness out, expectation 9 forbids citing only the traffic for a need; the profiles of the study and the fixtures
    keep their pinned versions, and a profile pinning minimisation 4 or before gets the earlier answer form."""
    import json
    from pathlib import Path

    prompts(None)
    assert {k: templates.CURRENT[k] for k in ("minimisation", "specificity", "expectation", "expectation_traffic")} == {
        "minimisation": "5",
        "specificity": "3",
        "expectation": "9",
        "expectation_traffic": "9",
    }
    assert "(ids starting with S)" in templates.text("minimisation")
    assert "(ids starting with S)" in templates.text("minimisation", "4")
    # minimisation 5: the typed form, the facts (F), the kinds with their values in order; 4 has the free steps
    typed = templates.text("minimisation")
    for words in (
        '"change"',
        '"needs"',
        '"gives"',
        '"covers"',
        "(ids starting with F)",
        "app, developer, device, cross-app",
        "session, reinstall, reset, factory-reset",
        "precision_m",
        "never a reason that it needs to",
    ):
        assert words in typed, words
    assert "TECHNICALLY_SUPPORTED" not in typed and "TECHNICALLY_SUPPORTED" in templates.text("minimisation", "4")
    assert judge.schema("minimisation") is judge.SCHEMAS["minimisation"]
    assert "level" not in judge.SCHEMAS["minimisation"]["properties"]["alternatives"]["items"]["properties"]
    assert "(ids starting with S)" not in templates.text("minimisation", "3")
    assert "list no entry for it" in templates.text("minimisation", "3")
    assert "the legal basis\nare not assessed here" in templates.text("specificity")
    assert "legal basis" not in templates.text("specificity", "2")
    for name in ("expectation", "expectation_traffic"):
        assert "cite only the observed traffic" not in templates.text(name, "8")
    profiles = Path(__file__).parent.parent / "profiles"
    for path in [profiles / "fixtures-2026-10.json", *profiles.glob("study-2026-11-*.json")]:
        pinned = json.loads(path.read_text(encoding="utf-8"))["prompts"]
        assert pinned["minimisation"] == "2" and pinned["specificity"] == "1" and pinned["expectation"] == "4", path
    prompts({"minimisation": "4"})
    assert judge.schema("minimisation") is judge.SCHEMA_MINIMISATION_4
