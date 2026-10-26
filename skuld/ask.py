"""
One way to ask a model, shared by the generator and the reasoning channel's stages.

A *sample* is a folder that keeps what was asked and what came back:

    record.json   what identifies the request (the caller's keys: prompt, procedure, options, ...), the model by API,
                  name and digest, the answer's digest, when it was asked and what it cost (seconds, tokens)
    prompt.txt    the prompt
    answer.json   the answer, as the model gave it

A sample is reused while the keys its caller names as its identity, and the model's name, are unchanged; a request
whose sample is missing or changed is asked, unless offline. Asking goes through Ratatoskr's client with the model's
default reasoning and a streamed response, and with the client's own response cache off: the samples are Skuld's
record of every answer, which a report is rebuilt from (EV-E-REPLAY).

`ask_with_feedback` asks again where the caller refuses an answer, with the refusal appended to the prompt, a sample of
its own per attempt and the next seed.
"""

import hashlib
import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ratatoskr.llm import Call, Client, Options, Provider
from ratatoskr.llm.client import default_limit

from skuld import config

#: The token limit of every request; a thinking model's reasoning counts towards it
MAX_TOKENS = 8192


class AskError(Exception):
    """A model could not be asked (offline without a kept sample is not an error: the answer is then None)."""


@dataclass
class Sample:
    folder: Path
    record: dict
    text: str | None  # None: offline, and no kept answer for this request
    reused: bool


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def client(api: str, provider: Provider | None = None) -> Client:
    """A client for Skuld's requests: config.json's client section, without the response cache, raising on failure."""
    return Client.from_config(config.load(), api=api, provider=provider, cache=False, raise_errors=True)


def _kept(folder: Path, record: dict, identity: tuple[str, ...]) -> str | None:
    path, answer = folder / "record.json", folder / "answer.json"
    if not path.is_file() or not answer.is_file():
        return None
    kept = json.loads(path.read_text(encoding="utf-8"))
    if all(kept.get(k) == record[k] for k in identity) and kept["model"]["name"] == record["model"]["name"]:
        return answer.read_text(encoding="utf-8")
    return None


def ask(
    folder: Path,
    prompt: str,
    schema: dict,
    record: dict,
    identity: tuple[str, ...],
    *,
    model: str,
    api: str,
    options: Options,
    offline: bool = False,
    provider: Provider | None = None,
    files: dict[str, str] | None = None,
    think: bool | None = None,
) -> Sample:
    """
    The sample of a request in `folder`: kept, or asked now. `record` holds the request's identity under the keys
    `identity` names, and gets the model, the options, the answer's digest and the time; `files` are written into the
    folder beside the answer (a context, for example). `think` switches a thinking model's reasoning on or off; None
    leaves the model's default and is not recorded, so that samples asked before the setting existed stay kept.
    """
    record = {**record, "model": {"api": api, "name": model}, "options": _options(options, think)}
    text = _kept(folder, record, (*identity, "options"))
    if text is not None:
        return Sample(folder, json.loads((folder / "record.json").read_text(encoding="utf-8")), text, True)
    if offline:
        return Sample(folder, record, None, False)
    asking = client(api, provider)
    call = Call(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        json_schema=schema,
        options=options,
        think=think,
        model_options={"stream": True},
    )
    try:
        result = asking.sync.chat(call)
        digest = asking.sync.digests().get(model)
    except Exception as e:
        raise AskError(f"{model}: {type(e).__name__}: {e}") from e
    record["model"]["digest"] = digest
    record["answer"] = {"sha256": sha256(result.content)}
    record["cost"] = {
        "seconds": round(result.seconds, 3),
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
        "thinking_chars": len(result.thinking or ""),
    }
    record["created"] = datetime.now(UTC).isoformat(timespec="seconds")
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (folder / name).write_text(content, encoding="utf-8")
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    (folder / "answer.json").write_text(result.content, encoding="utf-8")
    (folder / "record.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return Sample(folder, record, result.content, False)


def limit(model: str) -> int:
    """The simultaneous requests the server takes for a model: config.json's client.limits over Ratatoskr's."""
    return default_limit(model, config.load()["client"]["limits"])


def concurrently[T](jobs: list[Callable[[], T]], model: str) -> list[T]:
    """The results of `jobs`, in their order, at most `limit(model)` of them asking at a time."""
    with ThreadPoolExecutor(max_workers=limit(model)) as pool:
        return list(pool.map(lambda job: job(), jobs))


def ask_with_feedback(
    folders: Callable[[int], Path],
    prompt: str,
    schema: dict,
    record: Callable[[str], dict],
    identity: tuple[str, ...],
    refuse: Callable[[str | None], list[str]],
    *,
    attempts: int,
    seed: int,
    model: str,
    api: str,
    options: Options,
    offline: bool = False,
    provider: Provider | None = None,
    files: dict[str, str] | None = None,
    think: bool | None = None,
) -> tuple[Sample | None, list[str], int]:
    """
    Ask until `refuse` finds nothing wrong with an answer, at most `attempts` times: attempt n has its own folder
    (`folders(n)`), samples with seed + n - 1, and its prompt carries the previous attempt's refusals. Returns the
    last sample, its refusals (empty if accepted) and the attempts made; the samples of later attempts, kept from an
    earlier request, are removed. Offline, an attempt that is not kept ends the asking: the last kept attempt stands,
    with its refusals, or, if none is kept, a sample whose text is None, and nothing is removed.
    """
    sample, previous, refused = None, None, []
    for attempt in range(1, attempts + 1):
        asked = prompt
        if refused:
            asked += "\n\nYour previous answer was refused:\n" + "\n".join(f"- {p}" for p in refused)
            asked += "\nAnswer again, mending these."
        sample = ask(
            folders(attempt),
            asked,
            schema,
            record(asked),
            identity,
            model=model,
            api=api,
            options=options.model_copy(update={"seed": seed + attempt - 1}),
            offline=offline,
            provider=provider,
            files=files,
            think=think,
        )
        if sample.text is None:
            if previous is not None:  # offline: the last kept attempt stands, with its refusals
                return previous, refused, attempt - 1
            return sample, refused, attempt
        previous = sample
        refused = refuse(sample.text)
        if not refused:
            if not offline:
                _drop_later(folders, attempt, attempts)
            return sample, [], attempt
    return sample, refused, attempts


def _drop_later(folders: Callable[[int], Path], accepted: int, attempts: int) -> None:
    """Removes the samples of attempts after an accepted one: they answered an earlier request, not this one."""
    for later in range(accepted + 1, attempts + 1):
        folder = folders(later)
        if (folder / "record.json").is_file():
            shutil.rmtree(folder)


def _options(options: Options, think: bool | None = None) -> dict:
    """The options a sample records: those that identify the request (as samples recorded them before)."""
    return {"temperature": options.temperature, "seed": options.seed, **({"think": think} if think is not None else {})}


def supersede(root: Path, current: set[Path], when: str | None = None) -> list[Path]:
    """Moves the folders under `root` that no current question names (a batch or subject no longer asked about), with
    every sample in them, to superseded/<date>/ beside the workspace's other superseded samples, so that only the
    samples of current questions stay. The samples of a current question are kept, whatever their seeds."""
    if not root.is_dir():
        return []
    when = when or datetime.now(UTC).date().isoformat()
    workspace = root.parent if root.name == "expectation" else root.parent.parent
    moved = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder in current:
            continue
        target = workspace / "superseded" / when / folder.relative_to(workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(folder), str(target))
        moved.append(folder)
    return moved
