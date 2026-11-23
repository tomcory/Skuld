"""Asking a model: an answer cut off at the token limit is asked again with a raised limit, then refused."""

from ratatoskr.llm import LLMResponse, Options, Provider

from skuld import ask, config


class CutOff(Provider):
    """Cut off at the limit until `fits` tokens are allowed."""

    api = "fake"

    def __init__(self, fits: int | None):
        super().__init__()
        self.fits, self.limits = fits, []

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        limit = getattr(params, "max_tokens", None)
        self.limits.append(limit)
        whole = self.fits is not None and limit is not None and limit >= self.fits
        return LLMResponse(text='{"a": 1}' if whole else '{"a": ', finish_reason=None if whole else "length")


def _ask(tmp_path, provider):
    ask.reset_usage()
    return ask.ask(
        tmp_path / "s1",
        "prompt",
        {"type": "object"},
        {"question": "q"},
        ("question",),
        model="m",
        api="fake",
        options=Options(max_tokens=8192),
        provider=provider,
    )


def test_config_json_raises_the_limit_for_a_cut_off_answer():
    assert config.load()["client"]["max_tokens_cap"] == 32768


def test_an_answer_that_fits_under_a_raised_limit_is_kept(tmp_path):
    provider = CutOff(fits=16384)
    sample = _ask(tmp_path, provider)
    assert sample.text == '{"a": 1}' and (tmp_path / "s1" / "answer.json").is_file()
    assert ask.usage().truncated == 0


def test_an_answer_cut_off_at_the_cap_is_refused_and_kept_aside(tmp_path):
    sample = _ask(tmp_path, CutOff(fits=None))
    assert sample.text is None
    folder = tmp_path / "s1"
    assert not (folder / "answer.json").exists() and (folder / "answer.length.json").read_text() == '{"a": '
    assert "cut off" in sample.record["refused"] and ask.usage().truncated == 1
    # not kept: the next run asks again
    again = _ask(tmp_path, CutOff(fits=8192))
    assert again.text == '{"a": 1}' and ask.usage().calls == 1


class CutOffFirst(Provider):
    """Cut off at any limit while the prompt carries no refusal; answers once told it was cut off."""

    api = "fake"

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        told = "cut off" in str(prompt)
        return LLMResponse(text='{"a": 1}' if told else '{"a": ', finish_reason=None if told else "length")


def _feedback(tmp_path, offline=False):
    return ask.ask_with_feedback(
        lambda n: tmp_path / "s1" if n == 1 else tmp_path / "s1" / f"a{n}",
        "prompt",
        {"type": "object"},
        lambda asked: {"question": "q", "prompt": ask.sha256(asked)},
        ("question", "prompt"),
        lambda text: [],
        attempts=2,
        seed=1,
        model="m",
        api="fake",
        options=Options(max_tokens=8192),
        offline=offline,
        provider=CutOffFirst(),
    )


def test_an_answer_cut_off_is_refused_and_the_next_attempt_asked_also_when_read_offline(tmp_path):
    sample, refused, attempts = _feedback(tmp_path)
    assert sample.text == '{"a": 1}' and refused == [] and attempts == 2
    # offline, the attempt kept aside as cut off leads on to the kept second one
    sample, refused, attempts = _feedback(tmp_path, offline=True)
    assert sample.text == '{"a": 1}' and attempts == 2


class RefusedThenCutOff(Provider):
    """Answers the first prompt; cut off once told the answer was refused."""

    api = "fake"

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        told = "refused" in str(prompt)
        return LLMResponse(text='{"a": ' if told else '{"a": 1}', finish_reason="length" if told else None)


def test_a_last_attempt_cut_off_leaves_the_last_answer_standing_with_its_refusals(tmp_path):
    def run(offline=False):
        return ask.ask_with_feedback(
            lambda n: tmp_path / "s1" if n == 1 else tmp_path / "s1" / f"a{n}",
            "prompt",
            {"type": "object"},
            lambda asked: {"question": "q", "prompt": ask.sha256(asked)},
            ("question", "prompt"),
            lambda text: ["wrong"],
            attempts=2,
            seed=1,
            model="m",
            api="fake",
            options=Options(max_tokens=8192),
            offline=offline,
            provider=RefusedThenCutOff(),
        )

    for offline in (False, True):
        sample, refused, attempts = run(offline)
        assert sample.text == '{"a": 1}' and refused == ["wrong"] and attempts == 1


class Serves(Provider):
    """Answers, and states what serves the model as the gateway's /v1/models does."""

    api = "fake"

    def __init__(self, weights: str | None):
        super().__init__()
        self.weights, self.asked = weights, 0

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        self.asked += 1
        return LLMResponse(text='{"a": 1}')

    async def served(self):
        return {"m": {"owned_by": "vllm", "root": self.weights, "max_model_len": 131072}} if self.weights else {}


def test_a_sample_records_what_serves_its_model_and_the_reasoning_default(tmp_path):
    sample = _ask(tmp_path, Serves("google/gemma-4-31b-FP8"))
    model = sample.record["model"]
    assert model["served"] == {"owned_by": "vllm", "root": "google/gemma-4-31b-FP8", "max_model_len": 131072}
    assert model["think"] == "model default" and "think" not in sample.record["options"]
    assert ask.usage().served == {"m": model["served"]}


def test_a_kept_sample_of_other_weights_under_the_same_name_is_not_reused(tmp_path):
    _ask(tmp_path, Serves("google/gemma-4-31b-FP8"))
    same = Serves("google/gemma-4-31b-FP8")
    assert _ask(tmp_path, same).reused and same.asked == 0
    other = Serves("gemma4:31b-q4_K_M")
    assert not _ask(tmp_path, other).reused and other.asked == 1
    # a server that states nothing matches by name, as a sample that states nothing does
    silent = Serves(None)
    assert _ask(tmp_path, silent).reused and silent.asked == 0


class Rejects(Provider):
    """Answers with the finish reason it is given (runaway, refusal) until `heals`, then properly."""

    api = "fake"

    def __init__(self, reason: str, heals: bool = False):
        super().__init__()
        self.reason, self.heals = reason, heals

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        if self.heals:
            return LLMResponse(text='{"a": 1}', finish_reason="stop")
        return LLMResponse(
            text='{"a": ' + " " * 50, finish_reason=self.reason, refusal="no" if self.reason == "refusal" else None
        )


def test_a_runaway_or_refused_answer_leaves_its_sample_missing_and_the_run_goes_on(tmp_path):
    for reason, words in (("runaway", "ran away"), ("refusal", "refused")):
        folder = tmp_path / reason
        sample = _ask(folder, Rejects(reason))
        assert sample.text is None and words in sample.record["refused"]
        assert not (folder / "s1" / "answer.json").exists() and (folder / "s1" / "record.rejected.json").is_file()
        assert ask.usage().rejected == 1 and ask.usage().failed == 0
        # not kept: the next run asks again
        again = _ask(folder, Rejects(reason, heals=True))
        assert again.text == '{"a": 1}' and ask.usage().calls == 1


def test_a_sample_whose_answer_was_rejected_when_asked_again_is_missing_by_design_not_a_problem(tmp_path):
    """23 Nov 2026: asked again (its identity changed) and rejected, a sample's answer is removed but the record.json of
    the answer before stays, naming it; `skuld check` took that for an answer missing (the re-run's gemma Adobe Scan,
    assessment/minimisation/P-3fd565f146/s3/a2). The record kept aside beside it says it is missing by design (0.9.2);
    an answer missing without one is still a problem."""
    import hashlib
    import json

    from skuld.provenance import _samples

    parts = [{"id": "Q1", "kind": "purpose", "text": "t"}]
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    folder = tmp_path / "assessment" / "minimisation" / "P-x" / "s3" / "a2"

    def asked(question, provider):
        record = {"question": question, "context": {"sha256": digest}}
        files = {"context.json": json.dumps({"parts": parts})}
        options = Options(max_tokens=8192)
        return ask.ask(
            folder,
            "p",
            {},
            record,
            ("question",),
            model="m",
            api="fake",
            options=options,
            provider=provider,
            files=files,
        )

    asked("q", Rejects("runaway", heals=True))
    assert _samples(tmp_path)[1] == []
    assert asked("q2", Rejects("runaway")).text is None
    assert not (folder / "answer.json").exists() and json.loads((folder / "record.json").read_text())["answer"]
    assert _samples(tmp_path)[1] == []
    (folder / "record.rejected.json").unlink()
    assert _samples(tmp_path)[1] == ["sample assessment/minimisation/P-x/s3/a2: its answer is missing"]
