"""
Skuld's configuration: its config.json (at the repository's root, or the file SKULD_CONFIG names), with a named
profile over it if one is chosen, over Ratatoskr's defaults.

A profile (`profiles/<name>.json`, chosen by SKULD_PROFILE or `skuld --profile <name>`) holds only what differs from
config.json, merged key by key (a list or a value replaces the one below it), and says what it is for in its
`description`. Skuld's profiles are the setups a study ran with, so that they can be run again outside the machine
they ran on (`POST_PAPER_FIXES.md` 2):

    study-2026-11-gemma-vendor            the Expectation paper's final gemma4:31b run (vendor sampling)
    study-2026-11-qwen-low-traffic-topup  the Expectation paper's final qwen3.8:27b run

A file a configuration names (the purpose map) is given by its path, relative to the repository's root unless
absolute, and may be given with its digest, `{"path": ..., "sha256": ...}`; a file whose digest differs is refused.
A command's run manifest records the profile and the digest of the configuration it ran with (`provenance`).
"""

import functools
import hashlib
import json
import os
from pathlib import Path

from ratatoskr import config as ratatoskr_config
from ratatoskr.errors import ConfigError
from ratatoskr.llm import Options, options_for

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
PROFILES = ROOT / "profiles"


def profiles() -> dict[str, str]:
    """The profiles Skuld comes with: {name: description}."""
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8")).get("description", "")
        for p in sorted(PROFILES.glob("*.json"))
    }


def merge(below: dict, over: dict) -> dict:
    """`over` merged into `below` key by key: mappings merge, anything else replaces."""
    out = dict(below)
    for k, v in over.items():
        out[k] = merge(below[k], v) if isinstance(v, dict) and isinstance(below.get(k), dict) else v
    return out


def _profile(name: str) -> dict:
    path = PROFILES / f"{name}.json"
    if not path.is_file():
        raise ConfigError(f"Unknown profile {name}; Skuld's are {', '.join(profiles()) or 'none'}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("description", None)
    return data


def profile_name() -> str | None:
    return os.environ.get("SKULD_PROFILE") or None


def source() -> Path:
    return Path(os.environ.get("SKULD_CONFIG") or CONFIG)


@functools.cache
def load() -> dict:
    """Skuld's config.json, with the chosen profile over it, over Ratatoskr's defaults."""
    data = json.loads(source().read_text(encoding="utf-8"))
    if name := profile_name():
        data = merge(data, _profile(name))
    return ratatoskr_config.resolve(data)


def provenance() -> dict:
    """What a run manifest records of the configuration: its file, the profile, the digest of what was in force."""
    canonical = json.dumps(load(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "file": str(source()),
        "profile": profile_name(),
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def file(key: str) -> tuple[Path, str] | None:
    """A file the configuration names under `key` (a path, or {path, sha256}): its path and the digest of its text,
    refused if it differs from the digest named."""
    entry = load().get(key)
    if not entry:
        return None
    named = entry.get("sha256") if isinstance(entry, dict) else None
    path = Path(entry["path"] if isinstance(entry, dict) else entry)
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file():
        raise ConfigError(f"{key}: {path} does not exist")
    digest = hashlib.sha256(path.read_bytes().decode("utf-8").encode("utf-8")).hexdigest()
    if named and digest != named:
        raise ConfigError(f"{key}: {path} has the digest {digest[:12]}, not the {named[:12]} named")
    return path, digest


def options(task: str, **overrides) -> Options:
    """The sampling of a task (`propose`, `expect`, `judge`), with overrides (a command's --temperature)."""
    return options_for(load(), task).model_copy(update={k: v for k, v in overrides.items() if v is not None})


def model() -> str:
    return load()["model"]
