import os

import pytest

from skuld import config


@pytest.fixture(autouse=True)
def _unpinned_registry(monkeypatch):
    """config.json pins the study's registry build (`registry.sha256`); the tests build registries of their own, so
    they read the repository's config.json without that pin. A test of the pin names a config of its own
    (SKULD_CONFIG) or replaces config.load, which this leaves as it is."""
    load = config.load

    def unpinned() -> dict:
        data = load()
        if not os.environ.get("SKULD_CONFIG"):
            data = {**data, "registry": {**(data.get("registry") or {}), "sha256": None}}
        return data

    unpinned.cache_clear = getattr(load, "cache_clear", lambda: None)
    monkeypatch.setattr(config, "load", unpinned)


@pytest.fixture(autouse=True)
def _no_machine_settings(tmp_path, monkeypatch):
    """Ratatoskr's machine file (~/.config/ratatoskr/env, 0.42.0), shared limits and priority of the machine the tests
    run on stay out of the tests; the OpenAI API without an endpoint means OpenAI's own, as before 0.42.0."""
    from ratatoskr import env

    monkeypatch.setenv("RATATOSKR_ENV", str(tmp_path / "no-machine-file"))
    monkeypatch.setenv("RATATOSKR_SHARED_DIR", str(tmp_path / "limits"))
    for name in ("RATATOSKR_SHARED_LIMITS", "RATATOSKR_PRIORITY", "RATATOSKR_COMPONENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_OFFICIAL", "1")
    env.reload()
    yield
    env.reload()
