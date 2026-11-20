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
