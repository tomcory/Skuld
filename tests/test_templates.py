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
