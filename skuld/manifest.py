"""
The run manifest of a command that may ask a model (`skuld expect`, `judge`, `propose`; I-5): what was run, with which
settings, whether it succeeded, and what it cost, written into the workspace the command worked in:

    <workspace>/manifests/<command>_<UTC time>.json

It is Ratatoskr's run manifest (the run, its settings, Skuld's commit and whether the repository was dirty, start and
end), the configuration (its file, the profile, the digest of what was in force), with the models asked and their
digests, the status (`ok`, or `failed` with the error), and `calls`: the keys
of Ratatoskr's client statistics (`calls` asked, `cached` for samples kept and reused, `failed`, `retries`, tokens,
seconds) and Skuld's `missing` (offline, without a kept sample) and `thinking_chars`. A run that fails writes its
manifest too, with what it had spent by then.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ratatoskr.llm.manifest import RunManifest

import skuld
from skuld import ask, config

ROOT = Path(__file__).resolve().parents[1]
FOLDER = "manifests"


class Run:
    """The manifest being written; `folder` is the workspace, which a command may only know after it started."""

    def __init__(self, command: str, settings: dict, folder: Path | None):
        self.command, self.folder = command, folder
        self.manifest = RunManifest(command, settings, root=ROOT)
        self.manifest.data["skuld"] = skuld.__version__
        self.manifest.data["configuration"] = config.provenance()
        self.path: Path | None = None

    def write(self, error: BaseException | None) -> Path | None:
        if self.folder is None:
            return None
        used = ask.usage()
        data = self.manifest.data
        data["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
        data["status"] = "failed" if error else "ok"
        if error:
            data["error"] = f"{type(error).__name__}: {error}"
        data["models"] = dict(used.models)
        data["calls"] = used.as_dict()
        stamp = data["started"].replace("-", "").replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
        path, n = Path(self.folder) / FOLDER / f"{self.command}_{stamp}.json", 1
        while path.exists():  # two runs in the same second
            n += 1
            path = path.with_name(f"{self.command}_{stamp}_{n}.json")
        self.path = self.manifest.write(path)
        return self.path


@contextmanager
def metered(command: str, settings: dict, folder: Path | None = None):
    """Counts the model use of the block and writes its manifest when it ends, also when it fails."""
    ask.reset_usage()
    run = Run(command, settings, folder)
    try:
        yield run
    except BaseException as e:
        run.write(e)
        raise
    run.write(None)
