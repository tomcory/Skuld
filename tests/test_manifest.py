"""The run manifest of the commands that may ask a model (I-5): the tally of asked, kept, missing and failed requests,
the manifest written into the workspace, also when the run fails, and the command line printing its path."""

import json

import pytest
from ratatoskr.llm import LLMResponse, Options, Provider
from ratatoskr.schemas import load_schema  # noqa: F401  (Ratatoskr is importable: the manifest is its RunManifest)

from skuld import ask, cli, manifest

from .test_expectation import workspace  # noqa: F401  (fixture)

SCHEMA = {"type": "object"}


class Stub(Provider):
    api = "stub"

    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    async def complete(self, model, prompt, *args, **kwargs):
        if self.fail:
            raise ValueError("the model is gone")
        return LLMResponse(text='{"a": 1}', input_tokens=120, output_tokens=8)


def asked(folder, provider, offline=False, prompt="p"):
    return ask.ask(
        folder,
        prompt,
        SCHEMA,
        {"prompt_id": prompt},
        ("prompt_id",),
        model="m",
        api="stub",
        options=Options(),
        offline=offline,
        provider=provider,
    )


def test_the_tally_counts_asked_kept_missing_and_failed_requests(tmp_path):
    ask.reset_usage()
    asked(tmp_path / "s1", Stub())
    asked(tmp_path / "s1", Stub())  # kept: not asked again
    asked(tmp_path / "s2", Stub(), offline=True)
    with pytest.raises(ask.AskError):
        asked(tmp_path / "s3", Stub(fail=True))
    used = ask.usage()
    assert (used.calls, used.cached, used.missing, used.failed) == (1, 1, 1, 1)
    assert (used.prompt_tokens, used.output_tokens) == (120, 8) and "m" in used.models
    ask.reset_usage()
    assert ask.usage().calls == 0


def test_the_manifest_is_written_into_the_workspace_also_when_the_run_fails(tmp_path):
    with manifest.metered("expect", {"model": "m"}, tmp_path) as run:
        asked(tmp_path / "s1", Stub())
    data = json.loads(run.path.read_text(encoding="utf-8"))
    assert run.path.parent == tmp_path / "manifests" and run.path.name.startswith("expect_")
    assert data["run"] == "expect" and data["config"] == {"model": "m"} and data["status"] == "ok"
    assert data["calls"]["calls"] == 1 and data["calls"]["prompt_tokens"] == 120 and data["skuld"]
    assert {"started", "finished", "git_commit", "models"} <= set(data)

    with pytest.raises(ask.AskError), manifest.metered("judge", {}, tmp_path) as failed:
        asked(tmp_path / "s1", Stub())  # kept
        asked(tmp_path / "s4", Stub(fail=True))
    data = json.loads(failed.path.read_text(encoding="utf-8"))
    assert data["status"] == "failed" and "the model is gone" in data["error"]
    assert (data["calls"]["cached"], data["calls"]["failed"]) == (1, 1)

    with manifest.metered("judge", {}, tmp_path) as again:  # the same second: a file of its own
        pass
    assert again.path != failed.path or again.path.exists()
    assert len(list((tmp_path / "manifests").glob("judge_*.json"))) == 2


def test_skuld_expect_writes_its_manifest_and_prints_where(workspace, capsys):  # noqa: F811
    a, _ = workspace
    corpus = a.root.parent / "corpus"
    assert cli.main(["expect", str(a.root), "--offline", "--corpus", str(corpus)]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("manifest ")
    data = json.loads(open(line.removeprefix("manifest "), encoding="utf-8").read())
    assert data["run"] == "expect" and data["status"] == "ok" and data["config"]["offline"] is True
    assert data["calls"]["calls"] == 0 and data["calls"]["missing"] > 0  # offline, nothing kept
