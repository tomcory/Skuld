"""
One way to ask a model, shared by the generator and the reasoning channel's stages.

A *sample* is a folder that keeps what was asked and what came back:

    record.json   what identifies the request (the caller's keys: prompt, procedure, options, ...), the model by API,
                  name and digest, the answer's digest, when it was asked and what it cost (seconds, tokens)
    prompt.txt    the prompt
    answer.json   the answer, as the model gave it

A sample is reused while the keys its caller names as its identity, the model's name and the options it records
(temperature, seed, top_p/top_k/min_p where set, think) are unchanged; a request whose sample is missing or changed is
asked, unless offline. Asking goes through Ratatoskr's client with the configured thinking and a streamed response, and with the client's own response cache off: the samples are Skuld's
record of every answer, which a report is rebuilt from (EV-E-REPLAY).

`ask_with_feedback` asks again where the caller refuses an answer, with the refusal appended to the prompt, a sample of
its own per attempt and the next seed.

An answer cut off at the token limit, or one Ratatoskr's client rejects (refused, withheld, runaway, a prompt over the
context), is no sample: its record is kept aside (`record.length.json`, `record.rejected.json`) and the request asked
again next time; the run goes on without it.

Every request is counted in the process's tally (`usage()`): asked, kept (`cached`), missing offline, failed, with the
tokens and seconds of those asked and each model's digest. A command reads it into its run manifest (`manifest.py`).
"""

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ratatoskr.llm import Call, Client, Options, Provider
from ratatoskr.llm.client import AnswerRejected, default_limit

from skuld import config

#: The token limit of every request; a thinking model's reasoning counts towards it
MAX_TOKENS = 8192


class AskError(Exception):
    """A model could not be asked (offline without a kept sample is not an error: the answer is then None)."""


@dataclass
class Usage:
    """The model use of a run, with the keys of Ratatoskr's client statistics; `cached` counts kept samples."""

    calls: int = 0
    cached: int = 0
    missing: int = 0  # offline, and no sample kept
    truncated: int = 0  # cut off at the token limit (after Ratatoskr's re-asks up to max_tokens_cap): refused
    rejected: int = 0  # the model refused, the API withheld it, it ran away or the prompt did not fit: refused
    failed: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_chars: int = 0
    seconds: float = 0.0
    models: dict = field(default_factory=dict)  # name -> digest of the models asked
    served: dict = field(default_factory=dict)  # name -> what the server states it serves (Ratatoskr's served())

    def as_dict(self) -> dict:
        return {
            k: (round(v, 3) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
            if k not in ("models", "served")
        }


_usage = Usage()
_lock = threading.Lock()


def usage() -> Usage:
    """The tally since the last reset."""
    return _usage


def reset_usage() -> None:
    global _usage
    with _lock:
        _usage = Usage()


def _count(**added) -> None:
    with _lock:
        for k, v in added.items():
            if k in ("models", "served"):
                getattr(_usage, k).update(v)
            else:
                setattr(_usage, k, getattr(_usage, k) + v)


@dataclass
class Sample:
    folder: Path
    record: dict
    text: str | None  # None: offline and no kept answer, or an answer cut off at the token limit (refused)
    reused: bool


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def client(api: str, provider: Provider | None = None) -> Client:
    """A client for Skuld's requests: config.json's client section, without the response cache, raising on failure."""
    return Client.from_config(config.load(), api=api, provider=provider, cache=False, raise_errors=True)


#: What the server serves, per API, asked once per process (`served`)
_SERVED: dict[str, dict] = {}
#: The fields of what is served that make two answers of one model name not interchangeable: the backend and weights
SERVED_IDENTITY = ("owned_by", "root")


def served(api: str, provider: Provider | None = None) -> dict[str, dict]:
    """{model: what the server's model list states of it (backend `owned_by`, weights `root`, `max_model_len`)}, as
    Ratatoskr's served() gives it; {} where the server lists nothing or cannot be asked. On the SNET gateway, Ollama's
    digests (/api/tags) are those of its Q4 copies also of the models vLLM serves in FP8, so a sample records this
    beside the digest."""
    if provider is None and api in _SERVED:
        return _SERVED[api]
    try:
        listing = client(api, provider).sync.served()
    except Exception:  # noqa: BLE001 (a server without a list states nothing)
        listing = {}
    if provider is None:
        _SERVED[api] = listing
    return listing


def _kept(folder: Path, record: dict, identity: tuple[str, ...], now: dict | None = None) -> str | None:
    """The kept answer of the request, if its record matches the identity and the model's name. Where both the kept
    record and the server now state what serves the model (`now`), they must also agree in backend and weights, so
    that a Q4 and an FP8 answer under one name are not taken for each other; a sample that states nothing (asked before
    20 Nov 2026), or a server that states nothing, is matched by name as before."""
    path, answer = folder / "record.json", folder / "answer.json"
    if not path.is_file() or not answer.is_file():
        return None
    kept = json.loads(path.read_text(encoding="utf-8"))
    if not (all(kept.get(k) == record[k] for k in identity) and kept["model"]["name"] == record["model"]["name"]):
        return None
    then = kept["model"].get("served")
    if then and now and any(then.get(k) != now.get(k) for k in SERVED_IDENTITY):
        return None
    return answer.read_text(encoding="utf-8")


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
    think: bool | str | None = None,
) -> Sample:
    """
    The sample of a request in `folder`: kept, or asked now. `record` holds the request's identity under the keys
    `identity` names, and gets the model, the options, the answer's digest and the time; `files` are written into the
    folder beside the answer (a context, for example). `think` switches a thinking model's reasoning on or off, or sets
    its level ("low", "xhigh": on the gateway an effort for Qwen, a cap on thinking tokens for Gemma); None leaves the
    model's default, which is not part of the options (so that samples asked before the setting existed stay kept) but
    is recorded as the model's `think`, "model default". The record also states what the server says it serves
    (`served`); a kept sample that states it is reused only for the same backend and weights (`_kept`).
    """
    record = {**record, "model": {"api": api, "name": model}, "options": _options(options, think)}
    now = None if offline else served(api, provider).get(model)
    text = _kept(folder, record, (*identity, "options"), now)
    if text is not None:
        _count(cached=1)
        return Sample(folder, json.loads((folder / "record.json").read_text(encoding="utf-8")), text, True)
    if offline:
        _count(missing=1)
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
    except AnswerRejected as e:
        # an answer that came back unusable (refused, withheld, runaway, over the context) is no sample: its record is
        # kept aside and the request asked again next time, as a cut-off answer is; it does not end the run
        _count(rejected=1, retries=asking.stats.retries)
        record["refused"] = str(e)
        record["created"] = datetime.now(UTC).isoformat(timespec="seconds")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
        (folder / "record.rejected.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        (folder / "answer.json").unlink(missing_ok=True)
        return Sample(folder, record, None, False)
    except Exception as e:
        _count(failed=1, retries=asking.stats.retries)
        raise AskError(f"{model}: {type(e).__name__}: {e}") from e
    record["model"]["digest"] = digest
    if now:
        record["model"]["served"] = now
    # the reasoning setting asked with, outside the identity (options): unset, it is the model's default
    record["model"]["think"] = think if think is not None else "model default"
    record["answer"] = {"sha256": sha256(result.content)}
    record["cost"] = {
        "seconds": round(result.seconds, 3),
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
        "thinking_chars": len(result.thinking or ""),
    }
    if getattr(result, "finish_reason", None):
        record["finish_reason"] = result.finish_reason  # 'length': the token limit cut the answer off
    cut_off = record.get("finish_reason") == "length"
    _count(
        calls=1,
        truncated=1 if cut_off else 0,
        retries=asking.stats.retries,
        models={model: digest},
        served={model: now} if now else {},
        **{k: record["cost"][k] or 0 for k in ("seconds", "prompt_tokens", "output_tokens", "thinking_chars")},
    )
    record["created"] = datetime.now(UTC).isoformat(timespec="seconds")
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (folder / name).write_text(content, encoding="utf-8", newline="\n")
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
    if cut_off:
        # an answer cut off at the token limit is no sample: kept aside, with its record, and asked again next time
        record["refused"] = "cut off at the token limit (finish_reason length)"
        (folder / "answer.length.json").write_text(result.content, encoding="utf-8", newline="\n")
        (folder / "record.length.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        (folder / "answer.json").unlink(missing_ok=True)
        return Sample(folder, record, None, False)
    (folder / "answer.json").write_text(result.content, encoding="utf-8", newline="\n")
    (folder / "record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
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
    think: bool | str | None = None,
) -> tuple[Sample | None, list[str], int]:
    """
    Ask until `refuse` finds nothing wrong with an answer, at most `attempts` times: attempt n has its own folder
    (`folders(n)`), samples with seed + n - 1, and its prompt carries the previous attempt's refusals. Returns the
    last sample, its refusals (empty if accepted) and the attempts made; the samples of later attempts, kept from an
    earlier request, are removed. An answer cut off at the token limit is refused (the next attempt is asked, told
    so); it is kept aside, not kept, so it is asked again next time. If the last attempt is cut off, the last attempt
    that answered stands, with its refusals (no answer only where every attempt was cut off). Offline, an attempt that is not kept and was not
    cut off ends the asking: the last kept attempt stands, with its refusals, or, if none is kept, a sample whose text
    is None, and nothing is removed.
    """
    sample, refused = None, []
    answered = None  # the last attempt that gave an answer: (sample, its refusals, attempt)
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
            cut = _cut_off(sample, folders(attempt), offline)
            if cut:  # an answer cut off at the token limit is refused like any other: the next attempt is asked
                refused = [cut]
                continue
            if answered is not None:  # offline: the last kept answer stands, with its refusals
                return answered
            return sample, refused, attempt
        refused = refuse(sample.text)
        answered = (sample, refused, attempt)
        if not refused:
            if not offline:
                _drop_later(folders, attempt, attempts)
            return sample, [], attempt
    if sample is not None and sample.text is None and answered is not None:
        return answered  # the last attempt was cut off: the last answer stands, with its refusals
    return sample, refused, attempts


def _cut_off(sample: Sample, folder: Path, offline: bool) -> str | None:
    """Why an attempt has no answer if the token limit cut it off: asked now, from its record; offline, from the
    record kept aside beside it (record.length.json)."""
    if not offline:
        return sample.record.get("refused")
    kept_aside = folder / "record.length.json"
    if not kept_aside.is_file():
        return None
    return json.loads(kept_aside.read_text(encoding="utf-8")).get("refused")


def _drop_later(folders: Callable[[int], Path], accepted: int, attempts: int) -> None:
    """Removes the samples of attempts after an accepted one: they answered an earlier request, not this one."""
    for later in range(accepted + 1, attempts + 1):
        folder = folders(later)
        if (folder / "record.json").is_file():
            shutil.rmtree(folder)


def _options(options: Options, think: bool | str | None = None) -> dict:
    """The options a sample records: those that identify the request (as samples recorded them before). top_p, top_k
    and min_p are recorded where they are set (a model's recommended sampling, 12 Nov 2026); unset, as in every sample
    before, they are left out, so that those samples keep their identity."""
    out = {"temperature": options.temperature, "seed": options.seed}
    for key in ("top_p", "top_k", "min_p"):
        if getattr(options, key, None) is not None:
            out[key] = getattr(options, key)
    return {**out, **({"think": think} if think is not None else {})}


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
