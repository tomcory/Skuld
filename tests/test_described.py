"""Screen descriptions and screenshots in stage 1 and the minimisation context (0.12.4, the rerun plan's D-37)."""

import io
import json

import pytest
from ratatoskr.llm import LLMResponse, Provider
from ratatoskr.llm.content import text_of

from skuld import ask, assessment, expectation, images, inputs, judge
from skuld.context import Context
from tests.test_expectation import PACKAGE, corpus, o_report, run_folder

GEMMA, QWEN = "gemma4:31b", "qwen3.8:27b"


def png(color: tuple[int, int, int], size=(1080, 2400)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def described_run(tmp_path, extra_screens: int = 0):
    """test_expectation's run, with a screenshot of every screen and both models' descriptions of each visit; the
    plan screen (seq 3) is described by an earlier visit (seq 2 in its episode would not do: an exact seq first)."""
    run = run_folder(tmp_path)
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    for k in range(extra_screens):  # further screens of episode 1, each its own text
        events.append(
            {"type": "screen", "seq": 10 + k, "screen_id": f"s-x{k}", "episode": "1", "texts": [f"Screen {k}", "Next"]}
        )
    (run / "screenshots").mkdir()
    for n, e in enumerate(events):
        e["screenshot"] = f"screenshots/{e['seq']:05d}_screen_{n}.png"
        (run / e["screenshot"]).write_bytes(png((n * 20 % 255, 80, 160)))
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    lines = []
    for e in events:
        seq = e["seq"] if e["screen_id"] != "s-plan" else 1  # the plan screen: described at an earlier visit
        for model in (GEMMA, QWEN):
            lines.append(
                {
                    "visit": seq,
                    "screen_seq": seq,
                    "screen_id": e["screen_id"],
                    "episode": e["episode"],
                    "screenshot": e["screenshot"],
                    "model": model,
                    "prompt_version": "1",
                    "screen": f"{model} reads {e['screen_id']}.",
                    "in_episode": "It follows the start.",
                }
            )
    lines.append({"visit": 99, "screen_seq": 0, "screen_id": "s-consent", "model": GEMMA, "error": "timeout"})
    (run / "descriptions.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return run


def workspace_of(tmp_path, run):
    report = tmp_path / "o.json"
    report.write_text(json.dumps(o_report(run.name)))
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", [(report, run.name)], None, run, corpus(tmp_path))
    with (root / "assessment.yaml").open("a") as f:
        f.write("models: {expectation: fake}\n")
    a = inputs.load_assessment(root)
    return a, assessment.build(a, None)


@pytest.fixture
def described(tmp_path, monkeypatch):
    monkeypatch.setattr(expectation, "describer", lambda model: model)  # expectation.descriptions: "own"
    run = described_run(tmp_path)
    return (*workspace_of(tmp_path, run), run)


def contexts(a, built, version, model=GEMMA):
    from skuld.common import DATA, vocabulary
    from skuld.corpus import load

    corpus_ = load(a.corpus)
    return {
        b.key: expectation.assemble(b, a, corpus_, vocabulary(DATA), prompt_version=version, model=model)
        for b in expectation.batches(a, built)
    }


def test_each_family_reads_its_own_models_descriptions_never_cited(described):
    a, built, run = described
    launch = contexts(a, built, "10")["launch"]
    descriptions = [p for p in launch.parts if p["kind"] == "description"]
    # the launch batch shows the run's first screens: the consent screen is a notice (left out); the sign-up form held
    # one (its texts kept, no description, no image); the plan screen's description is of an earlier visit
    assert [p["text"] for p in descriptions] == [
        "(about S1) gemma4:31b reads s-home. It follows the start.",
        "(about S3) gemma4:31b reads s-plan. It follows the start.",
    ]
    assert descriptions[0]["provenance"][0]["record"] == "descriptions.jsonl#visit/1/gemma4:31b"
    assert "S1.d" not in launch.ids and "S1" in launch.ids  # a description is never citable
    rendered = expectation.render(launch)
    assert "(about S1) gemma4:31b reads s-home." in rendered and "[S1.d]" not in rendered
    qwen = contexts(a, built, "10", QWEN)["launch"]
    assert [p["text"] for p in qwen.parts if p["kind"] == "description"][0].startswith("(about S1) qwen3.8:27b")
    # the plan screen of episode 1 has its description from an earlier visit of the same screen
    e1 = contexts(a, built, "10")["e1"]
    assert [p["text"] for p in e1.parts if p["kind"] == "description"] == [
        "(about S1) gemma4:31b reads s-plan. It follows the start."
    ]


def test_screenshots_are_named_by_digest_never_of_a_notice_screen(described):
    a, built, run = described
    launch = contexts(a, built, "10")["launch"]
    screens = {p["id"]: p for p in launch.parts if p["kind"] == "screen"}
    assert set(screens) == {"S1", "S2", "S3"}  # home; the sign-up form without its notice line; the plan
    home, signup = screens["S1"], screens["S2"]
    assert [x.get("sha256") for x in home["provenance"]][1] == images.digest(run / home["provenance"][1]["record"])
    assert all("sha256" not in x for x in signup["provenance"])  # it held a notice: no screenshot
    listed = [p for p in launch.parts if p["kind"] == "images"]
    assert listed and "in this order: S1, S3." in listed[0]["text"] and "images" not in launch.ids
    shots = expectation.images_of(launch, run)
    assert [s["path"] for s in shots] == [home["provenance"][1]["record"], screens["S3"]["provenance"][1]["record"]]
    assert shots[0]["data"][:3] == b"\xff\xd8\xff"  # JPEG
    # a changed screenshot is not the one the context names
    (run / home["provenance"][1]["record"]).write_bytes(png((1, 2, 3)))
    with pytest.raises(Exception, match="differs"):
        expectation.images_of(launch, run)


def test_at_most_eight_screenshots_spread_over_the_screens(tmp_path, monkeypatch):
    monkeypatch.setattr(expectation, "describer", lambda model: model)
    run = described_run(tmp_path, extra_screens=12)
    a, built = workspace_of(tmp_path, run)
    e1 = contexts(a, built, "10")["e1"]
    with_shots = [p["id"] for p in e1.parts if p["kind"] == "screen" and len(p["provenance"]) > 1]
    screens = [p["id"] for p in e1.parts if p["kind"] == "screen"]
    assert len(screens) == 13 and len(with_shots) == images.MAX_IMAGES
    assert with_shots[0] == "S1" and with_shots[-1] == "S13"
    assert images.spread(3) == [0, 1, 2] and images.spread(13) == [0, 2, 3, 5, 7, 9, 10, 12]


def test_version_9_makes_the_context_it_made_before(described):
    a, built, run = described
    for context in contexts(a, built, "9").values():
        assert {p["kind"] for p in context.parts} <= {"application", "practice", "screen", "passage"}
        assert all(len(p["provenance"]) == 1 for p in context.parts)


def test_a_cited_description_is_refused(described):
    a, built, run = described
    launch_batch = next(b for b in expectation.batches(a, built) if b.key == "launch")
    launch = contexts(a, built, "10")["launch"]
    practice = launch_batch.practices[0].id
    answer = {
        "purposes": {
            practice: [
                {
                    "id": "p1",
                    "action": "a",
                    "object": "o",
                    "beneficiary": "USER",
                    "context": "c",
                    "outcome": "x",
                    "node": "Marketing",
                    "role": "ANCILLARY",
                    "specific": True,
                    "achieved_on": "SERVER",
                    "cites": {"outcome": ["S1.d"]},
                }
            ]
        },
        "dependencies": {practice: []},
    }
    refused = expectation.refusals(json.dumps(answer), launch_batch, launch.ids)
    assert any("S1.d" in r for r in refused)


class Seeing(Provider):
    """Records each request's content; answers every practice with one purpose citing the first screen."""

    api = "fake"

    def __init__(self):
        super().__init__()
        self.contents = []

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        import re

        content = prompt.messages[0]["content"]
        self.contents.append(content)
        text = text_of(content) if isinstance(content, list) else content
        practices = re.findall(r"\[(P-[0-9a-f]{10})\]", text)
        purpose = {
            "id": "p1",
            "action": "a",
            "object": "o",
            "beneficiary": "USER",
            "context": "c",
            "outcome": "x",
            "node": "Marketing",
            "role": "ANCILLARY",
            "specific": True,
            "achieved_on": "SERVER",
            "cites": {"outcome": ["S1"]},
        }
        return LLMResponse(
            text=json.dumps({"purposes": {p: [purpose] for p in practices}, "dependencies": {p: [] for p in practices}})
        )


def test_the_request_carries_the_screenshots_and_the_record_names_them(described, monkeypatch):
    from skuld.corpus import load

    a, built, run = described
    fake = Seeing()
    monkeypatch.setattr(ask, "served", lambda api, provider=None: {})
    samples = expectation.expect(a, built, load(a.corpus), seeds=[1], model=GEMMA, api="fake", provider=fake)
    with_images = [c for c in fake.contents if isinstance(c, list)]
    assert with_images, "no request carried an image"
    assert all(sum(1 for part in c if part["type"] == "image") <= images.MAX_IMAGES for c in with_images)
    record = next(s.record for s in samples if s.record.get("images"))
    assert {"path", "sha256", "bytes"} == set(record["images"][0])
    context = Context(tuple(json.loads((samples[0].folder / "context.json").read_text())["parts"]))
    assert record["context"]["sha256"] == context.sha256  # the screenshots' digests are in the context


def test_the_minimisation_context_gives_descriptions_never_cited(described):
    a, built, run = described
    shown = judge.screens_of(a, built)
    practice = next(iter(shown))
    parts = judge._screens(shown[practice], GEMMA)
    described_parts = [p for p in parts if p["kind"] == "description"]
    assert described_parts and all(p["text"].startswith("(about S") for p in described_parts)
    assert all(p["id"] not in Context(tuple(parts)).ids for p in described_parts)
    assert judge._screens(shown[practice]) == [p for p in parts if p["kind"] == "screen"]
