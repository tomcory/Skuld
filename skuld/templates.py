"""
The prompts' texts by version. `prompts/<id>.md` is the current version (CURRENT); earlier versions are kept as
`prompts/versions/<id>-<version>.md`, so that the samples asked with them are found again under a configuration that
names them (config.json's or a profile's `prompts`, e.g. `{"minimisation": "2"}` in the fixtures' profile). A prompt's
version is part of every sample's identity, and so is the digest of its text.

    expectation, expectation_traffic   8: each passage of the context names the practices it was retrieved for, and
                                          the prompt says a passage documents only those (expectation.LABELED_SINCE;
                                          21 Nov 2026); 7: each purpose says where it is achieved (achieved_on: DEVICE or SERVER),
                                          required by the answer schema (21 Nov 2026); 6: the answer keyed by practice id, every practice of the batch required by
                                          the schema (expectation.answer_schema; 21 Nov 2026); 5: the context last,
                                          after the fixed instructions (INFERENCE_GUIDE.md: a fixed part first and
                                          byte-identical, so the server reuses its prefix); 4 before
    specificity, compatibility          2: the context last; 1 before
    minimisation                        3: the context last, and "list no entry for it" where a component admits no
                                          alternative, which the models wrote as "none" (2: "give none for it")
    propose                             2: the context (the flow) last, the answer's form before it; the generator's
                                          version (propose.VERSION) names the prompt with the procedure
"""

from importlib import resources

from ratatoskr.errors import ConfigError

CURRENT = {
    "expectation": "8",
    "expectation_traffic": "8",
    "specificity": "2",
    "compatibility": "2",
    "minimisation": "3",
    "propose": "2",
}


def version(prompt: str) -> str:
    """The version of a prompt in force: the configuration's `prompts.<id>`, else the current one."""
    from skuld import config

    named = (config.load().get("prompts") or {}).get(prompt)
    return str(named) if named is not None else CURRENT[prompt]


def text(prompt: str, given: str | None = None) -> str:
    """A prompt's template in the version `given`, else the one in force."""
    v = given or version(prompt)
    folder = resources.files("skuld") / "prompts"
    path = folder / f"{prompt}.md" if v == CURRENT[prompt] else folder / "versions" / f"{prompt}-{v}.md"
    if not path.is_file():
        raise ConfigError(f"prompt {prompt} has no version {v} (prompts/versions/{prompt}-{v}.md)")
    return path.read_text(encoding="utf-8")
