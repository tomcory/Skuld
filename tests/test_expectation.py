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
    assert record["model"]["name"] == "fake" and record["options"]["temperature"] == 0.4
    expectation.expect(a, built, load_corpus(a.corpus), seeds=[1, 2], provider=model)
    assert len(model.prompts) == 4  # kept, not asked again


def test_a_sample_records_the_thinking_switch_only_where_it_is_set(workspace, tmp_path, monkeypatch):
    from skuld import config

    a, built = workspace
    model = FakeModel()
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
