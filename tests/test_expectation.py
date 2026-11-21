"""Tests of the expectation stage: batches, the stage-1 context (gate 1), readings (gate 2), gate 3, end to end."""

import json
import re
from pathlib import Path

import pytest
from ratatoskr.llm import LLMResponse, Provider

from skuld import assessment, expectation, inputs
from skuld.assess import assess
from skuld.context import Context, ContextError
from skuld.corpus import load as load_corpus

PACKAGE = "com.example.app"
#: A consent dialog that states the purpose verbatim: stage 1 must not see it
CONSENT = ["We use your advertising ID to attribute installs to our campaigns.", "Accept all", "Manage options"]
PURPOSE_TEXT = "attribute installs to our campaigns"
#: A sign-up form whose one line accepting the policy is a privacy notice: stage 1 sees the form without that line
SIGN_UP = ["Create account", "Email address", "The Terms of Use and the Privacy Policy have been read and accepted."]


def run_folder(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"schema_version": 2, "status": "finished", "run_id": "run-1"}))
    screens = [
        ("s-consent", None, CONSENT),
        ("s-home", None, ["Welcome", "Start your first workout"]),
        ("s-signup", None, SIGN_UP),
        ("s-plan", "1", ["Your plan", "Week 1: three sessions"]),
    ]
    events = [
        {"type": "screen", "seq": n, "screen_id": sid, "episode": ep, "texts": texts}
        for n, (sid, ep, texts) in enumerate(screens)
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (run / "graph.json").write_text(json.dumps({"screens": {}}))
    return run


def o_report(run_id: str) -> dict:
    def claim(cid, node, episode, actor):
        return {
            "id": cid,
            "type": "transmits",
            "datum": {"node": node},
            "recipient": {
                "entity": "adco",
                "domain": "adco.example",
                "endpoint": {"host": "h"},
                "categories": ["advertising"],
            },
            "qualifiers": {"actor": {"kind": "component", "component": actor}, "contexts": [{"episode": episode}]},
            "polarity": "+",
            "status": "supported",
            "observations": [run_id],
        }

    return {
        "observations": [{"id": run_id, "package": PACKAGE, "version": "1.0"}],
        "scopes": [{"observation": run_id, "application": PACKAGE, "version": "1.0"}],
        "claims": [
            claim("c1", "device-or-other-ids.advertising-id", "?", "AdSDK"),
            claim("c2", "app-activity.app-interactions", "1", "AdSDK"),
        ],
        "statuses": [],
    }


def corpus(tmp_path: Path) -> Path:
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "a.yaml").write_text(
        "id: a\ntitle: Install attribution\nsource: https://example.org/attribution\nkind: component\n"
        "about: {entities: [adco]}\ntext: AdCo attributes installs to campaigns; it can match installs without the advertising ID.\n"
    )
    return folder


@pytest.fixture
def workspace(tmp_path):
    run = run_folder(tmp_path)
    report = tmp_path / "o.json"
    report.write_text(json.dumps(o_report(run.name)))
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", [(report, run.name)], None, run, corpus(tmp_path))
    with (root / "assessment.yaml").open("a") as f:
        f.write("models: {expectation: fake}\n")
    a = inputs.load_assessment(root)
    return a, assessment.build(a, None)


class FakeModel(Provider):
    """Answers for the first practice of the prompt; records every prompt."""

    api = "fake"

    def __init__(self):
        super().__init__()
        self.prompts = []

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        text = prompt.messages[0]["content"]
        self.prompts.append(text)
        practice = re.findall(r"\[(P-[0-9a-f]{10})\]", text)[0]
        answer = {
            "purposes": [
                {
                    "practice": practice,
                    "id": "p1",
                    "action": "attribute",
                    "object": "the installation",
                    "beneficiary": "PROVIDER",
                    "context": "first launch",
                    "outcome": "the campaign that led to it is known",
                    "node": "Marketing",
                    "role": "ANCILLARY",
                    "specific": True,
                    "cites": {"outcome": ["D1"]},
                }
            ],
            "dependencies": [
                {
                    "practice": practice,
                    "purpose": "p1",
                    "component": f"{practice}.recipient",
                    "relationship": "ESSENTIAL",
                    "steps": [
                        {"text": "Attribution is what AdCo does.", "cites": ["D1"]},
                        {"text": "The app sends it, so it is needed.", "cites": [practice]},
                    ],
                },
                {
                    "practice": practice,
                    "purpose": "p1",
                    "component": f"{practice}.data",
                    "relationship": "ESSENTIAL",
                    "steps": [{"text": "It is sent.", "cites": [practice]}],
                },
            ],
        }
        return LLMResponse(text=json.dumps(answer))


def test_a_batch_per_episode_and_notice_screens_are_left_out(workspace):
    a, built = workspace
    batches = {b.key: b for b in expectation.batches(a, built)}
    assert set(batches) == {"e1", "launch"}
    launch = batches["launch"]
    assert [p.data for p in launch.practices] == ["device-or-other-ids.advertising-id"]
    assert [s for s, _ in launch.screens] == ["s-home", "s-signup", "s-plan"]
    assert launch.left_out[0]["screen"] == "s-consent" and launch.left_out[0]["kind"] == "consent_dialog"
    assert launch.left_out[0]["whole"]
    assert dict(launch.screens)["s-signup"] == "Create account | Email address"
    assert launch.left_out[1] == {"screen": "s-signup", "kind": "privacy_notice", "terms": ["privacy"], "whole": False}


def test_with_a_batch_size_an_episode_is_split_into_batches_of_at_most_that_many_practices(workspace, monkeypatch):
    """expectation.batch_size, off by default: qwen answered only the first practice of 27 of the study's 72 batches."""
    from skuld import config

    a, built = workspace
    whole = {b.key: b for b in expectation.batches(a, built)}
    loaded = config.load()
    monkeypatch.setattr(config, "load", lambda: {**loaded, "expectation": {**loaded["expectation"], "batch_size": 1}})
    split = expectation.batches(a, built)
    for key, batch in whole.items():
        mine = [b for b in split if b.key == key or b.key.startswith(key + ".")]
        assert [p for b in mine for p in b.practices] == batch.practices
        assert all(len(b.practices) == 1 and b.screens == batch.screens for b in mine)
        if len(batch.practices) > 1:
            assert [b.key for b in mine] == [f"{key}.{n}" for n in range(1, len(batch.practices) + 1)]


def test_the_stage_1_context_refuses_d_and_notices(workspace, tmp_path):
    a, built = workspace
    batch = expectation.batches(a, built)[-1]
    context = expectation.assemble(
        batch,
        a,
        load_corpus(a.corpus),
        __import__("ratatoskr.vocabularies").vocabularies.Vocabulary.load("asgard-data"),
    )
    assert PURPOSE_TEXT not in expectation.render(context)
    d_part = {
        "id": "X1",
        "kind": "practice",
        "text": "declared",
        "provenance": [{"origin": "d_report", "record": "/claims/0"}],
    }
    with pytest.raises(ContextError, match="d_report"):
        expectation.check(Context(context.parts + (d_part,)))
    notice = {
        "id": "S9",
        "kind": "screen",
        "text": " | ".join(CONSENT),
        "provenance": [{"origin": "run", "record": "x"}],
    }
    with pytest.raises(ContextError, match="notice"):
        expectation.check(Context(context.parts + (notice,)))


def test_samples_are_kept_and_the_consent_screen_never_reaches_the_model(workspace):
    a, built = workspace
    model = FakeModel()
    samples = expectation.expect(a, built, load_corpus(a.corpus), seeds=[1, 2], provider=model)
    assert len(samples) == 4 and len(model.prompts) == 4
    assert all(PURPOSE_TEXT not in p for p in model.prompts)
    record = json.loads((samples[0].folder / "record.json").read_text(encoding="utf-8"))
    from ratatoskr.llm import options_for

    from skuld import config

    expected = options_for(config.load(), "expect").temperature  # the configuration's, whatever it is
    assert record["model"]["name"] == "fake" and record["options"]["temperature"] == expected
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1, 2], provider=model)
    assert len(model.prompts) == 4  # kept, not asked again


def test_a_sample_records_the_thinking_switch_only_where_it_is_set(workspace, tmp_path, monkeypatch):
    from skuld import config

    a, built = workspace
    model = FakeModel()
    unset = json.loads(config.CONFIG.read_text(encoding="utf-8"))
    unset["expectation"]["think"] = None
    (tmp_path / "unset.json").write_text(json.dumps(unset))
    monkeypatch.setenv("SKULD_CONFIG", str(tmp_path / "unset.json"))
    config.load.cache_clear()
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
    record = json.loads((a.root / "expectation" / "launch" / "s1" / "record.json").read_text(encoding="utf-8"))
    assert "think" not in record["options"] and "thinking_chars" in record["cost"]
    switched = json.loads(config.CONFIG.read_text(encoding="utf-8"))
    switched["expectation"]["think"] = False
    (tmp_path / "config.json").write_text(json.dumps(switched))
    monkeypatch.setenv("SKULD_CONFIG", str(tmp_path / "config.json"))
    config.load.cache_clear()
    try:
        asked = len(model.prompts)
        expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
        # switched off, the reasoning makes another request: asked again, not kept
        assert len(model.prompts) == 2 * asked
        record = json.loads((a.root / "expectation" / "launch" / "s1" / "record.json").read_text(encoding="utf-8"))
        assert record["options"]["think"] is False
    finally:
        monkeypatch.delenv("SKULD_CONFIG")
        config.load.cache_clear()


def test_readings_apply_the_status_rules_and_the_citation_rule(workspace):
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    (name, context, answer), *_ = [
        k for k in expectation.kept(a, built, load_corpus(a.corpus)) if k[0].startswith("launch")
    ]
    practices = {p.id: p for p in built.practices}
    claims = expectation.read(answer, name, context, practices)
    by = {(c["type"], c.get("component", "").rsplit(".", 1)[-1]): c for c in claims}
    purpose = by[("purpose", "")]
    assert purpose["status"] == "supported" and purpose["purpose"]["role"] == "ancillary"
    assert purpose["purpose"]["beneficiary"] == "provider"
    recipient = by[("dependency", "recipient")]
    # the step citing the practice is dropped; the remaining one cites a passage
    assert (recipient["status"], recipient["relationship"]) == ("supported", "essential")
    assert recipient["dropped_steps"][0]["step"] == 1
    data = by[("dependency", "data")]
    assert data["status"] == "not_established" and len(data["dropped_steps"]) == 1
    assert data["sufficiency"]["reason"] == "own_knowledge"
    assert not [c for c in claims if c["type"] == "alternative"]
    # a screen or passage must show the outcome, what the processing is for; the practice shows only that it happens
    shown = answer["purposes"][0]
    practice = shown["practice"]
    for cites in ({"outcome": ["own knowledge"]}, {"outcome": [practice]}, {"outcome": ["D1", "own knowledge"]}):
        (c,) = expectation.read({"purposes": [{**shown, "cites": cites}]}, name, context, practices)
        assert (c["status"], c["strength"]) == ("not_established", "own")
        assert c["reason"] == "no screen or passage shows its outcome" and c["sufficiency"]["reason"] == "own_knowledge"
    # the practice cited beside the passage does not count, and does no harm
    (c,) = expectation.read({"purposes": [{**shown, "cites": {"outcome": [practice, "D1"]}}]}, name, context, practices)
    assert c["status"] == "supported"
    (c,) = expectation.read({"purposes": [{**shown, "cites": ["A1", "D1"]}]}, name, context, practices)
    assert c["status"] == "not_established"
    # no dependency identified is silence: no claim
    silent = {**answer["dependencies"][0], "relationship": "NO_DEPENDENCY_IDENTIFIED"}
    assert [c["type"] for c in expectation.read({**answer, "dependencies": [silent]}, name, context, practices)] == [
        "purpose"
    ]


def test_a_purpose_says_where_it_is_achieved_from_prompt_version_7(workspace):
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    (name, context, answer), *_ = [
        k for k in expectation.kept(a, built, load_corpus(a.corpus)) if k[0].startswith("launch")
    ]
    practices = {p.id: p for p in built.practices}
    shown = answer["purposes"][0]
    for said, read in (("SERVER", "server"), ("DEVICE", "device")):
        (c,) = expectation.read({"purposes": [{**shown, "achieved_on": said}]}, name, context, practices)
        assert c["purpose"]["achieved_on"] == read
    (c,) = expectation.read(
        {"purposes": [{k: v for k, v in shown.items() if k != "achieved_on"}]}, name, context, practices
    )
    assert "achieved_on" not in c["purpose"]  # an earlier prompt's answer does not say
    # the keyed schema of version 7 requires it; version 6's does not know it
    pid = shown["practice"]
    seven = expectation.answer_schema([pid], "7")["properties"]["purposes"]["properties"][pid]["items"]
    six = expectation.answer_schema([pid], "6")["properties"]["purposes"]["properties"][pid]["items"]
    assert "achieved_on" in seven["required"] and seven["properties"]["achieved_on"]["enum"] == ["DEVICE", "SERVER"]
    assert "achieved_on" not in six["properties"] and expectation.answer_schema([pid], "5") == expectation.ANSWER_SCHEMA


def test_the_assessment_reads_kept_samples_and_gate_3_holds(workspace):
    from skuld.assess import build

    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    report, members = build(a.root)
    stage1 = [c for c in report["claims"] if c["stage"] == "expectation"]
    assert stage1 and report["report"]["cost"]["model_calls"] == 0
    assert all(m in {x["id"] for x in members} for c in stage1 for m in c["of"])  # combined; the samples' stay out
    assert any(c["role"] == "model" and c["id"] == "fake" for c in report["report"]["components"])
    supported = [c for c in stage1 if c["status"] == "supported"]
    items = {e["id"]: e for e in report["evidence"]}
    assert all(
        items[x]["claim"]["dimension"] == "O" for c in supported for x in c["supporting"] if items[x]["kind"] == "claim"
    )

    # a tampered sample whose context reaches D fails the report
    path = next((a.root / "expectation").glob("launch/s1/context.json"))
    parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
    parts.append(
        {
            "id": "X1",
            "kind": "passage",
            "text": "the policy",
            "provenance": [{"origin": "d_report", "record": "/claims/0"}],
        }
    )
    path.write_text(json.dumps({"parts": parts}))
    with pytest.raises(expectation.IndependenceError, match="d_report"):
        assess(a.root)


def test_samples_made_with_the_registers_names_are_found_again(workspace):
    from ratatoskr.registry import Registry

    a, built = workspace
    register = Registry({"entities": [{"id": "adco", "name": "AdCo", "domains": ["adco.example"]}]})
    names = expectation.names(register)
    made = expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel(), names=names)
    assert "AdCo (register entity adco" in (made[0].folder / "prompt.txt").read_text(encoding="utf-8")
    # the assessment reads them with the same names; without them the contexts differ and nothing is found
    assert len(expectation.kept(a, built, load_corpus(a.corpus), register)) == len(made)
    assert expectation.kept(a, built, load_corpus(a.corpus)) == []


class Incomplete(FakeModel):
    """Leaves the first practice without a purpose on the first attempt, as models do over many practices."""

    async def complete(self, model, prompt, *args, **kwargs):
        response = await super().complete(model, prompt, *args, **kwargs)
        if "previous answer was refused" in prompt.messages[0]["content"]:
            return response
        answer = json.loads(response.text)
        answer["purposes"] = []
        return LLMResponse(text=json.dumps(answer))


def test_a_refused_answer_is_asked_again_with_the_refusal_and_the_retry_is_read(workspace):
    a, built = workspace
    model = Incomplete()
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
    assert len(model.prompts) == 4  # two batches, each asked twice, the second time with the refusal
    assert sum("has no purpose" in p for p in model.prompts) == 2
    names = [n for n, _, _ in expectation.kept(a, built, load_corpus(a.corpus))]
    assert sorted(names) == ["e1/s1/a2", "launch/s1/a2"]
    # asked again with an answer accepted at once, the retry of the earlier request goes
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel(), names={"adco": "AdCo"})
    assert not (a.root / "expectation" / "launch" / "s1" / "a2").exists()
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=Incomplete())
    # offline, without the second attempt kept, the first stands, refusals and all
    import shutil

    shutil.rmtree(a.root / "expectation" / "launch" / "s1" / "a2")
    assert "launch/s1" in [n for n, _, _ in expectation.kept(a, built, load_corpus(a.corpus))]


def test_a_batch_no_longer_asked_moves_to_superseded_on_an_online_run(workspace):
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    stale = a.root / "expectation" / "e9" / "s1"
    stale.mkdir(parents=True)
    (stale / "record.json").write_text("{}")
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], offline=True)
    assert stale.is_dir()  # offline, nothing moves
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[2], provider=FakeModel())
    assert not stale.exists() and list((a.root / "superseded").glob("*/expectation/e9/s1/record.json"))
    assert (a.root / "expectation" / "launch" / "s1").is_dir()  # another seed of a current batch stays


def test_a_practice_a_batch_left_without_a_purpose_is_topped_up_alone(workspace, monkeypatch):
    """13 Nov 2026: qwen answered only the first practice of a batch, also when asked again; with expectation.topup
    each practice left without a purpose is asked alone, below the batch's sample, and read like any sample."""
    from skuld import config

    a, built = workspace
    loaded = config.load()
    monkeypatch.setattr(config, "load", lambda: {**loaded, "expectation": {**loaded["expectation"], "topup": True}})

    class FirstSilent(FakeModel):
        """Gives no purpose on a batch's two attempts (4 requests: two batches), answers from then on."""

        async def complete(self, model, prompt, *args, **kwargs):
            if len(self.prompts) < 4:
                self.prompts.append(prompt.messages[0]["content"])
                return LLMResponse(text=json.dumps({"purposes": [], "dependencies": []}))
            return await super().complete(model, prompt, *args, **kwargs)

    model = FirstSilent()
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
    assert len(model.prompts) == 6  # two batches asked twice, then a top-up per practice
    names = [n for n, _, _ in expectation.kept(a, built, load_corpus(a.corpus))]
    topups = [n for n in names if "/topup/" in n]
    assert topups and all(n.split("/")[2] == "topup" for n in topups)
    batch_practices = {b.key: {p.id for p in b.practices} for b in expectation.batches(a, built)}
    for key, practices in batch_practices.items():
        covered = set()
        for name, _, answer in expectation.kept(a, built, load_corpus(a.corpus)):
            if name.split("/")[0] == key:
                covered |= {x["practice"] for x in answer.get("purposes", [])}
        assert covered == practices
    record = json.loads((a.root / "expectation" / topups[0] / "record.json").read_text())
    assert record["topup_of"] == "/".join(topups[0].split("/")[:2]) and len(record["practices"]) == 1
    asked = len(model.prompts)
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
    assert len(model.prompts) == asked  # everything kept: nothing asked again


def test_without_the_topup_setting_nothing_is_topped_up(workspace):
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    assert not any("/topup/" in n for n, _, _ in expectation.kept(a, built, load_corpus(a.corpus)))


def test_the_notice_definition_is_versioned(workspace):
    """A report names the notice definition its stage-1 contexts were made with; one that names none was made with
    1.1.0, under which "Start tracking your run" spoke of data (Ratatoskr's notices 1.2.0 no longer)."""
    from ratatoskr import notices

    assert expectation.NOTICES == notices.VERSION
    assert expectation.notices_of({"report": {"components": []}}) == "1.1.0"
    named = {"report": {"components": [notices.component("1.2.0")]}}
    assert expectation.notices_of(named) == "1.2.0"
    run = {
        "id": "S9",
        "kind": "screen",
        "text": "Start tracking your run | Privacy",
        "provenance": [{"origin": "run", "record": "x"}],
    }
    a, built = workspace
    context = expectation.assemble(
        expectation.batches(a, built)[-1],
        a,
        load_corpus(a.corpus),
        __import__("ratatoskr.vocabularies").vocabularies.Vocabulary.load("asgard-data"),
    )
    expectation.check(Context(context.parts + (run,)))  # 1.2.0: no notice
    with pytest.raises(ContextError, match="notice"):
        expectation.check(Context(context.parts + (run,)), "1.1.0")


def test_a_dependency_names_its_purpose_by_id_or_by_a_node_only_one_purpose_of_its_practice_has():
    purposes = [
        {"practice": "[P-1]", "id": "P-1.purpose.1", "node": "Advertising"},
        {"practice": "P-1", "id": "P-1.purpose.2", "node": "ServiceProvision"},
        {"practice": "P-1", "id": "P-1.purpose.3", "node": "ServiceProvision"},
    ]
    keys = expectation._purpose_keys(purposes)
    assert keys[("P-1", "P-1.purpose.2")] == ("P-1", "P-1.purpose.2")
    assert keys[("P-1", "Advertising")] == ("P-1", "P-1.purpose.1")
    assert ("P-1", "ServiceProvision") not in keys  # two purposes have it: which one is meant is not known


# -- the answer keyed by practice id (prompt version 6, 21 Nov 2026) -----------------------------------------------


def keyed_answer(answer: dict) -> dict:
    """A list-shaped answer as prompt version 6 asks for it: purposes and dependencies keyed by practice id."""
    out = {}
    for section in ("purposes", "dependencies"):
        out[section] = {}
        for item in answer[section]:
            out[section].setdefault(item["practice"], []).append({k: v for k, v in item.items() if k != "practice"})
    return out


def test_a_batchs_schema_requires_every_practice_of_the_batch():
    from jsonschema import Draft202012Validator

    schema = expectation.answer_schema(["P-a", "P-b"], "6")
    for section in ("purposes", "dependencies"):
        part = schema["properties"][section]
        assert part["type"] == "object" and part["required"] == ["P-a", "P-b"]
        assert set(part["properties"]) == {"P-a", "P-b"} and part["additionalProperties"] is False
        assert "practice" not in part["properties"]["P-a"]["items"]["properties"]
        assert "practice" not in part["properties"]["P-a"]["items"]["required"]
    assert schema["properties"]["purposes"]["properties"]["P-a"]["minItems"] == 1
    # no contains/minContains, which guided decoders often ignore
    assert "contains" not in json.dumps(schema)
    item = {
        "id": "p1",
        "action": "a",
        "object": "o",
        "beneficiary": "USER",
        "context": "c",
        "outcome": "x",
        "node": "ServiceProvision",
        "role": "FUNCTIONAL",
        "specific": True,
        "cites": {"outcome": []},
    }
    validator = Draft202012Validator(schema)
    assert not list(
        validator.iter_errors({"purposes": {"P-a": [item], "P-b": [item]}, "dependencies": {"P-a": [], "P-b": []}})
    )
    # the first practice alone, as qwen answered 27 of the study's 72 batches, is refused by the schema
    assert list(validator.iter_errors({"purposes": {"P-a": [item]}, "dependencies": {"P-a": []}}))
    assert list(validator.iter_errors({"purposes": {"P-a": [item], "P-b": []}, "dependencies": {"P-a": [], "P-b": []}}))
    # an earlier prompt version (a profile's) is asked with the list shape it was asked with
    assert expectation.answer_schema(["P-a"], "5") is expectation.ANSWER_SCHEMA
    assert expectation.answer_schema(["P-a"], "4") is expectation.ANSWER_SCHEMA


def test_a_keyed_answer_reads_to_the_claims_of_the_list_answer_and_a_list_answer_still_reads(workspace):
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    (name, context, answer), *_ = [
        k for k in expectation.kept(a, built, load_corpus(a.corpus)) if k[0].startswith("launch")
    ]
    practices = {p.id: p for p in built.practices}
    as_list = expectation.read(answer, name, context, practices)
    keyed = keyed_answer(answer)
    assert as_list and expectation.read(keyed, name, context, practices) == as_list
    assert expectation.listed(answer) == answer  # an answer of an earlier prompt, as the study's kept samples
    practice = answer["purposes"][0]["practice"]
    assert expectation.answered(json.dumps(keyed)) == {practice}
    batch = next(b for b in expectation.batches(a, built) if b.key == "launch")
    assert expectation.refusals(json.dumps(keyed), batch, context.ids) == expectation.refusals(
        json.dumps(answer), batch, context.ids
    )


def test_the_stage_1_prompt_tells_the_keyed_shape_and_earlier_versions_are_kept():
    from skuld import templates

    for prompt in ("expectation", "expectation_traffic"):
        assert templates.CURRENT[prompt] == "9"
        for keyed in ("6", "7", "8", "9"):
            assert "under the practice's id" in templates.text(prompt, keyed)
        for earlier in ("4", "5"):
            assert "under the practice's id" not in templates.text(prompt, earlier)
        # version 7 asks where each purpose is achieved; the earlier ones do not
        assert '"achieved_on"' in templates.text(prompt, "7")
        assert all('"achieved_on"' not in templates.text(prompt, v) for v in ("4", "5", "6"))
        # version 8 says that a passage documents only the practices it was retrieved for; the earlier ones do not
        assert "documents only the practices" in templates.text(prompt, "8")
        assert all("documents only the practices" not in templates.text(prompt, v) for v in ("4", "5", "6", "7"))
        # version 9 says that a step may not cite only the traffic for a need; the earlier ones do not
        assert "cite only the observed traffic" in templates.text(prompt, "9")
        assert all("cite only the observed traffic" not in templates.text(prompt, v) for v in ("4", "5", "6", "7", "8"))


def test_each_passage_names_the_practices_it_was_retrieved_for_from_prompt_version_8(workspace, tmp_path):
    """21 Nov 2026: 78% of the passages a practice saw in its batch had been retrieved for other practices of it."""
    from ratatoskr.vocabularies import Vocabulary

    a, built = workspace
    folder = a.corpus
    (folder / "b.yaml").write_text(
        "id: b\ntitle: Advertising ID\nsource: https://example.org/adid\nkind: platform\n"
        "about: {nodes: [device-or-other-ids.advertising-id]}\ntext: The advertising ID is resettable.\n"
    )
    found, data = load_corpus(folder), Vocabulary.load("asgard-data")
    two = [p for p in built.practices if p.data == "device-or-other-ids.advertising-id"][:1]
    two += [p for p in built.practices if p.data != "device-or-other-ids.advertising-id"][:1]
    assert len(two) == 2 and all(p.recipient == "adco" for p in two)
    batch = expectation.Batch("e1", two, None, [], [])
    passages = [
        p["text"]
        for p in expectation.assemble(batch, a, found, data, prompt_version="8").parts
        if p["kind"] == "passage"
    ]
    first, second = two[0].id, two[1].id
    assert passages[0].startswith(
        f"(retrieved for {first}, {second}) Install attribution (https://example.org/attribution): "
    )
    assert passages[1].startswith(f"(retrieved for {first}) Advertising ID (https://example.org/adid): ")
    rendered = expectation.render(expectation.assemble(batch, a, found, data, prompt_version="8"))
    assert f"[D2] (retrieved for {first}) Advertising ID" in rendered
    # an earlier version's context is made as it was, so that its kept samples are found again
    earlier = expectation.assemble(batch, a, found, data, prompt_version="7")
    assert [p["text"] for p in earlier.parts if p["kind"] == "passage"] == [t.split(") ", 1)[1] for t in passages]
    # the version in force labels
    from skuld import templates

    assert expectation.labeled(templates.version(expectation.prompt_id())) and expectation.LABELED_SINCE == 8


def test_a_model_given_the_keyed_schema_answers_every_practice_and_needs_no_topup(workspace, monkeypatch):
    from skuld import config

    a, built = workspace
    loaded = config.load()
    monkeypatch.setattr(config, "load", lambda: {**loaded, "expectation": {**loaded["expectation"], "topup": True}})

    class Keyed(FakeModel):
        """Answers as the schema it is given asks: every practice id the schema requires."""

        async def complete(self, model, prompt, *args, **kwargs):
            self.prompts.append(prompt.messages[0]["content"])
            ids = prompt.response_schema["properties"]["purposes"]["required"]
            one = json.loads((await FakeModel().complete(model, prompt)).text)
            answer = {"purposes": {}, "dependencies": {}}
            for pid in ids:
                answer["purposes"][pid] = [{k: v for k, v in one["purposes"][0].items() if k != "practice"}]
                answer["dependencies"][pid] = []
            return LLMResponse(text=json.dumps(answer))

    model = Keyed()
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=model)
    batches = expectation.batches(a, built)
    assert len(model.prompts) == len(batches)  # no refusal, no top-up
    for b in batches:
        (_, _, answer), *_ = [k for k in expectation.kept(a, built, load_corpus(a.corpus)) if k[0].startswith(b.key)]
        assert {x["practice"] for x in answer["purposes"]} == {p.id for p in b.practices}


def test_a_dependency_step_citing_only_traffic_is_dropped_from_reading_5(workspace):
    """P10 fix 3: traffic shows that the processing happens, not that it is needed, like the practice; a dependency left
    with no grounded step is own knowledge, at essential and quality_dependent alike. Reading 4 reads as before."""
    a, built = workspace
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1], provider=FakeModel())
    (name, context, answer), *_ = [
        k for k in expectation.kept(a, built, load_corpus(a.corpus)) if k[0].startswith("launch")
    ]
    practices = {p.id: p for p in built.practices}
    practice = answer["dependencies"][0]["practice"]
    traffic = {
        "id": "T1",
        "kind": "traffic",
        "text": f"{practice}: POST https://adco.example/attribution",
        "provenance": [{"origin": "o_report", "record": "c1"}],
    }
    context = Context(context.parts + (traffic,))

    def dependency(relationship, *steps, reading):
        given = {**answer["dependencies"][0], "relationship": relationship}
        given["steps"] = [{"text": "AdCo receives it.", "cites": cites} for cites in steps]
        claims = expectation.read({**answer, "dependencies": [given]}, name, context, practices, reading)
        (c,) = [c for c in claims if c["type"] == "dependency"]
        return c

    assert expectation.READING == "5"
    for relationship in ("ESSENTIAL", "QUALITY_DEPENDENT"):
        c = dependency(relationship, ["T1"], reading="5")
        assert (c["status"], c["strength"], c["sufficiency"]["reason"]) == ("not_established", "own", "own_knowledge")
        assert c["dropped_steps"] == [{"step": 0, "reason": expectation.TRAFFIC_ONLY}]
        assert c["reason"] == "no step is left that grounds the need"
        # beside a passage the traffic-only step is still dropped, and the passage grounds the need
        c = dependency(relationship, ["T1"], ["D1"], reading="5")
        assert c["status"] == "supported" and len(c["dropped_steps"]) == 1
        # a step citing traffic and a passage stays
        assert "dropped_steps" not in dependency(relationship, ["T1", "D1"], reading="5")
        # reading 4: the traffic grounds the need, as before
        c = dependency(relationship, ["T1"], reading="4")
        assert c["status"] == "supported" and "dropped_steps" not in c
    with pytest.raises(ValueError):
        dependency("ESSENTIAL", ["T1"], reading="6")
