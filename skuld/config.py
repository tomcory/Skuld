"""Skuld's configuration: its config.json (at the repository's root) over Ratatoskr's defaults."""

import functools
from pathlib import Path

from ratatoskr import config as ratatoskr_config
from ratatoskr.llm import Options, options_for

CONFIG = Path(__file__).resolve().parents[1] / "config.json"


@functools.cache
def load() -> dict:
    """Skuld's config.json over Ratatoskr's defaults: the default model, the sampling of each task, the client."""
    return ratatoskr_config.load(CONFIG)


def options(task: str, **overrides) -> Options:
    """The sampling of a task (`propose`, `expect`, `judge`), with overrides (a command's --temperature)."""
    return options_for(load(), task).model_copy(update={k: v for k, v in overrides.items() if v is not None})


def model() -> str:
    return load()["model"]
