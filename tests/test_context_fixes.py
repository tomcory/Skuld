"""The stage-1 context fixes of 0.12.6 (22 Nov 2026): a run Loki stopped on an error is read with its snapshot's
traffic; a screen gets only a screenshot of its own visit, or of a visit that showed the same, and never one file
twice; gate 1 is decided on the screenshot's and the description's own visit, by Loki's notice record and by Skuld's
classifier."""

import json
import logging

import pytest

from skuld import assessment, expectation, images, inputs
from skuld.context import ContextError
from skuld.runs import RunRefused, load
from tests.test_described import GEMMA, contexts, described_run, png, workspace_of
from tests.test_expectation import PACKAGE, corpus, o_report

STOPPED = "error: AdbError(\"device 'emulator-5566' not found\")"
SNAPSHOT = "capture-snapshot/3-20261122-091324"
MESSAGE = {
    "id": "m1",
    "http_request": {
        "method": "GET",
        "host": "adco.example",
        "path": "/track?aid=38400000-8cf0-11bd-b23e-10b96e40000d",
    },
}


def events_of(run) -> list[dict]:
    return [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines() if line.strip()]


def write_events(run, events: list[dict]) -> None:
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def screenshots(context) -> dict[str, str]:
    """The screenshot each screen part names, by its id."""
    return {
        p["id"]: x["record"] for p in context.parts if p["kind"] == "screen" for x in p["provenance"] if x.get("sha256")
    }


def descriptions_of(context) -> list[str]:
    return [p["text"] for p in context.parts if p["kind"] == "description"]


@pytest.fixture
def own(monkeypatch):
    monkeypatch.setattr(expectation, "describer", lambda model: model)


# Fix 1: a run that ended on an error


def errored_run(tmp_path, snapshot: bool = True):
    """test_described's run, stopped by Loki on an error at its end: no final export, and (with `snapshot`) the
    capture's latest snapshot, which O annotated."""
    run = described_run(tmp_path)
    meta = json.loads((run / "run.json").read_text())
    meta["capture"] = {"backend": "heimdall", "session": "3", "error": "adb_failed", "detail": "device not found"}
    events = events_of(run)
    if snapshot:
        meta["capture"]["snapshot"] = SNAPSHOT
        (run / SNAPSHOT).mkdir(parents=True)
        (run / SNAPSHOT / "messages.jsonl").write_text(json.dumps(MESSAGE) + "\n")
        (run / SNAPSHOT / "connections.jsonl").write_text("")
        events.append({"seq": 90, "type": "capture", "state": "snapshot", "snapshot": SNAPSHOT})
    events.append({"seq": 91, "type": "run_end", "stop_reason": STOPPED})
    write_events(run, events)
    (run / "run.json").write_text(json.dumps(meta))
    return run


def evidenced_workspace(tmp_path, run):
    """test_described's workspace, its O report's claims with evidence in the snapshot's message."""
    report = o_report(run.name)
    for claim in report["claims"]:
        claim["evidence"] = ["ev1"]
    node = "device-or-other-ids.advertising-id"
    report["evidence"] = [
        {
            "id": "ev1",
            "proposition": {"kind": "datum", "message": "m1", "field": "path", "node": node},
            "provenance": [{"span": [11, 47]}],
        }
    ]
    path = tmp_path / "o.json"
    path.write_text(json.dumps(report))
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", [(path, run.name)], None, run, corpus(tmp_path))
    with (root / "assessment.yaml").open("a") as f:
        f.write("models: {expectation: fake}\n")
    a = inputs.load_assessment(root)
    return a, assessment.build(a, None)


def test_a_run_stopped_on_an_error_is_read_with_its_snapshot(tmp_path):
    run = errored_run(tmp_path)
    with pytest.raises(RunRefused) as refusal:
        load(run, capture=False)  # a replay that failed is still refused
    assert refusal.value.reason == "failed"
    loaded = load(run, capture=False, errored=True)
    assert loaded.traffic["source"] == "snapshot" and loaded.traffic["folder"] == SNAPSHOT
    assert loaded.traffic["why"].startswith(f"Loki stopped the run: {STOPPED}; no final export (adb_failed)")
    assert loaded.messages is None
    captured = load(run, errored=True)
    assert [m["id"] for m in captured.messages] == ["m1"] and captured.connections == ()


def test_a_run_stopped_on_an_error_without_any_capture_is_refused(tmp_path):
    run = errored_run(tmp_path, snapshot=False)
    with pytest.raises(RunRefused) as refusal:
        load(run, capture=False, errored=True)
    assert refusal.value.reason == "failed" and "no usable capture" in str(refusal.value)


def test_the_latest_snapshot_folder_stands_in_where_none_is_named(tmp_path):
    run = errored_run(tmp_path)
    meta = json.loads((run / "run.json").read_text())
    del meta["capture"]["snapshot"]
    (run / "run.json").write_text(json.dumps(meta))
    write_events(run, [e for e in events_of(run) if e.get("type") != "capture"])
    older = run / "capture-snapshot/3-20261122-081318"
    older.mkdir()
    (older / "messages.jsonl").write_text("")
    assert load(run, capture=False, errored=True).traffic["folder"] == SNAPSHOT


def test_stage_one_gets_the_screens_and_traffic_of_a_run_stopped_on_an_error(tmp_path, own):
    from skuld.common import DATA, vocabulary
    from skuld.corpus import load as load_corpus

    run = errored_run(tmp_path)
    a, built = evidenced_workspace(tmp_path, run)
    launch = next(b for b in expectation.batches(a, built) if b.key == "launch")
    assert launch.run == run.name and launch.screens  # skipped before 0.12.6: no screens
    context = expectation.assemble(
        launch, a, load_corpus(a.corpus), vocabulary(DATA), traffic=True, prompt_version="10", model=GEMMA
    )
    traffic = [p for p in context.parts if p["kind"] == "traffic"]
    assert traffic and "adco.example/track" in traffic[0]["text"]
    pointer = traffic[0]["provenance"][1]
    assert pointer["origin"] == "run" and pointer["record"] == f"{SNAPSHOT}/messages.jsonl#m1"
    assert pointer["capture"] == "snapshot" and "no final export (adb_failed)" in pointer["why"]
    assert screenshots(context) and descriptions_of(context)


def test_a_refused_run_is_not_skipped_silently(tmp_path, own, caplog):
    run = errored_run(tmp_path, snapshot=False)
    a, built = workspace_of(tmp_path, run)
    with caplog.at_level(logging.WARNING), pytest.raises(ContextError, match="no run of the assessment can be read"):
        expectation.batches(a, built)
    assert any("does not use run" in r.message and "failed" in r.message for r in caplog.records)


# Fix 2: a screenshot of another visit


def revisited_run(tmp_path, same: bool):
    """A run whose home screen (s-home) is visited again in episode 1 without a screenshot of its own, the second
    visit showing the same as the first (`same`) or other content under the same screen id and keys."""
    run = described_run(tmp_path)
    events = events_of(run)
    for e in events:
        e.update(exact_key=f"k-{e['screen_id']}", content_key=f"c-{e['screen_id']}")
    home = next(e for e in events if e["screen_id"] == "s-home")
    texts = home["texts"] if same else ["Settings", "Units: metric"]
    events.append({"type": "screen", "seq": 4, "screen_id": "s-home", "episode": "1", "texts": texts, **_keys(home)})
    write_events(run, events)
    return run


def _keys(event):
    return {"exact_key": event["exact_key"], "content_key": event["content_key"]}


def test_no_screenshot_of_another_visit_whose_content_differs(tmp_path, own):
    run = revisited_run(tmp_path, same=False)
    (run / "graph.json").write_text(
        json.dumps({"screens": {"s-home": {"screenshot": "screenshots/00001_screen_1.png"}}})
    )
    a, built = workspace_of(tmp_path, run)
    e1 = contexts(a, built, "10")["e1"]
    texts = {p["id"]: p["text"] for p in e1.parts if p["kind"] == "screen"}
    assert texts == {"S1": "Your plan | Week 1: three sessions", "S2": "Settings | Units: metric"}
    assert set(screenshots(e1)) == {"S1"}  # before 0.12.6, S2 had the home screen's first screenshot


def test_a_visit_that_shows_the_same_may_have_another_visits_screenshot(tmp_path, own):
    run = revisited_run(tmp_path, same=True)
    a, built = workspace_of(tmp_path, run)
    e1 = contexts(a, built, "10")["e1"]
    home = next(e for e in events_of(run) if e["screen_id"] == "s-home")
    assert screenshots(e1) == {"S1": "screenshots/00003_screen_3.png", "S2": home["screenshot"]}


def test_one_file_is_never_attached_twice_in_a_request(tmp_path, own):
    """Six of the extra screens of episode 1 visited again, each showing the same as before without a screenshot of its
    own: their first visits' screenshots may stand in, once each."""
    run = described_run(tmp_path, extra_screens=12)
    events = events_of(run)
    for e in events:
        e.update(exact_key=f"k-{e['screen_id']}", content_key=f"c-{e['screen_id']}")
    extras = [e for e in events if e["screen_id"].startswith("s-x")]
    events += [{k: v for k, v in e.items() if k != "screenshot"} | {"seq": 30 + k} for k, e in enumerate(extras[:6])]
    write_events(run, events)
    graph = {e["screen_id"]: {"screenshot": e["screenshot"]} for e in reversed(events) if e.get("screenshot")}
    (run / "graph.json").write_text(json.dumps({"screens": graph}))
    a, built = workspace_of(tmp_path, run)
    e1 = contexts(a, built, "10")["e1"]
    assert sum(p["kind"] == "screen" for p in e1.parts) == 19
    named = list(screenshots(e1).values())
    assert len(named) == images.MAX_IMAGES and len(set(named)) == len(named)  # 13 files, 8 of them spread
    assert list(screenshots(e1))[0] == "S1" and list(screenshots(e1))[-1] == "S13"
    assert len({s["path"] for s in expectation.images_of(e1, run)}) == images.MAX_IMAGES


# Fix 3: gate 1 on the screenshot's own visit


def notice_run(tmp_path, how: str):
    """A run whose plan screen (s-plan) is visited twice in episode 1: first a notice (`how`: Loki recorded it as one,
    its own texts not; or its own texts are one), described and with a screenshot that graph.json names for the screen;
    then, after another screen, a clean visit without a screenshot or description of its own, which in the case of
    Loki's record shows the same texts under the same keys."""
    run = described_run(tmp_path)
    events = events_of(run)
    plan = next(e for e in events if e["screen_id"] == "s-plan")
    plan.update(exact_key="k-plan", content_key="c-plan")
    clean = {k: v for k, v in plan.items() if k != "screenshot"}
    clean.update(seq=5, texts=list(plan["texts"]))
    if how == "own texts":
        plan["texts"] = [*plan["texts"], "We share your data with partners as set out in our Privacy Policy."]
    between = {"type": "screen", "seq": 4, "screen_id": "s-break", "episode": "1", "texts": ["Take a break"]}
    events += [between, clean]
    if how == "loki":
        events.append({"seq": 6, "type": "notice_capture", "screen_id": "s-plan", "screen_seq": 3, **_keys(plan)})
    write_events(run, events)
    graph = {"screens": {"s-plan": {"screenshot": plan["screenshot"]}}}  # the screen's first visit, as Loki keeps it
    (run / "graph.json").write_text(json.dumps(graph))
    described = {"visit": 3, "screen_seq": 3, "screen_id": "s-plan", "episode": "1", "model": GEMMA}
    with (run / "descriptions.jsonl").open("a") as f:
        f.write(json.dumps({**described, "screen": "The visit Loki read to its end.", "in_episode": ""}) + "\n")
    return run, plan


@pytest.mark.parametrize("how", ["loki", "own texts"])
def test_a_screenshot_of_a_notice_visit_is_never_attached(tmp_path, own, how):
    run, plan = notice_run(tmp_path, how)
    a, built = workspace_of(tmp_path, run)
    e1 = contexts(a, built, "10")["e1"]
    texts = [p["text"] for p in e1.parts if p["kind"] == "screen"]
    assert texts[1:] == ["Take a break", "Your plan | Week 1: three sessions"]  # the clean visit is S3
    assert plan["screenshot"] not in screenshots(e1).values()
    assert "S3" not in screenshots(e1)  # no screenshot of its own, and the one of the same content is a notice's
    # nor the notice visit's description, for the notice visit or as the latest earlier one of the clean visit
    assert all("read to its end" not in t for t in descriptions_of(e1))
    assert all(plan["screenshot"] not in screenshots(c).values() for c in contexts(a, built, "10").values())


# A run none of the fixes concern keeps its contexts byte for byte, so that its kept samples are found again


def _shown_0_12_5(run, episode, first=None):
    """`expectation._shown` as Skuld 0.12.5 made it."""
    from skuld import context as ctx

    graph = json.loads((run.directory / "graph.json").read_text(encoding="utf-8")).get("screens", {})
    shown = []
    for event in run.events:
        if event.get("type") != "screen":
            continue
        if episode is not None and str(event.get("episode")) != episode:
            continue
        sid = event.get("screen_id")
        text = " | ".join(event["texts"]) if event.get("texts") else ctx.screen_text(graph.get(sid) or {})
        text = text[: expectation.SCREEN_TEXT] if text else text
        if text and (not shown or (shown[-1]["sid"], shown[-1]["text"]) != (sid, text)):
            shot = event.get("screenshot") or (graph.get(sid) or {}).get("screenshot")
            shown.append(
                {"sid": sid, "text": text, "seq": event.get("seq"), "episode": event.get("episode"), "screenshot": shot}
            )
        if first is not None and len(shown) >= first:
            break
    return shown


def _described_0_12_5(batch, screen_parts, model, notices):
    """`expectation._described` as Skuld 0.12.5 made it (its description_of did not look at notice visits)."""
    shown = batch.shown[: len(screen_parts)]
    usable = [
        i
        for i, s in enumerate(shown)
        if not s.get("notice") and s.get("screenshot") and (batch.directory / s["screenshot"]).is_file()
    ]
    chosen = [usable[j] for j in images.spread(len(usable))]
    for i in chosen:
        path = shown[i]["screenshot"]
        screen_parts[i]["provenance"].append(
            {"origin": "run", "record": path, "run": batch.run, "sha256": images.digest(batch.directory / path)}
        )
    out = list(screen_parts)
    if model:
        found = expectation.descriptions(batch.directory, model)
        for i, s in enumerate(shown):
            if s.get("notice"):
                continue
            d = expectation.description_of({k: v for k, v in s.items() if k != "noticed"}, found)
            if d is None:
                continue
            text = f"(about S{i + 1}) {d['screen'].strip()} {(d.get('in_episode') or '').strip()}".strip()
            if expectation.classify([d["screen"], d.get("in_episode") or ""], notices or expectation.NOTICES):
                continue
            record = f"{expectation.DESCRIPTIONS}#visit/{d.get('visit')}/{model}"
            out.append(expectation._part(f"S{i + 1}.d", "description", text, ("run", record), batch.run))
    if chosen:
        ids = ", ".join(f"S{i + 1}" for i in chosen)
        text = (
            f"{len(chosen)} screenshot{'s are' if len(chosen) > 1 else ' is'} attached after this text, in this order: "
            f"{ids}. A screenshot shows its screen as the user saw it; cite the screen's id."
        )
        out.append(expectation._part("images", "images", text, ("run", "screenshots"), batch.run))
    return out


def test_a_run_the_fixes_do_not_concern_keeps_its_contexts(tmp_path, own, monkeypatch):
    """Own screenshots, a visit in episode 1 without one that shows the same as the screen's first visit in episode 2
    (graph.json's screenshot then is the right one), screens that are notices by Skuld's classifier, no notice of Loki's, a final export."""
    run = described_run(tmp_path, extra_screens=12)
    events = events_of(run)
    for e in events:
        e.update(exact_key=f"k-{e['screen_id']}", content_key=f"c-{e['screen_id']}")
    tips = {"type": "screen", "seq": 30, "screen_id": "s-tips", "episode": "2", "texts": ["Tips", "Drink water"]}
    tips.update(exact_key="k-tips", content_key="c-tips", screenshot="screenshots/00030_screen_30.png")
    (run / tips["screenshot"]).write_bytes(png((7, 7, 7)))
    revisit = {k: v for k, v in tips.items() if k != "screenshot"}
    revisit.update(seq=40, episode="1")
    events += [tips, revisit]
    events.append({"seq": 41, "type": "run_end", "stop_reason": "max_flows"})
    write_events(run, events)
    first = {}
    for e in events:
        if e.get("screenshot"):
            first.setdefault(e["screen_id"], {"screenshot": e["screenshot"]})
    (run / "graph.json").write_text(json.dumps({"screens": first}))
    a, built = workspace_of(tmp_path, run)
    after = {k: c.sha256 for k, c in contexts(a, built, "10").items()}
    assert "screenshots/00030_screen_30.png" in screenshots(contexts(a, built, "10")["e1"]).values()
    monkeypatch.setattr(
        expectation,
        "_shown",
        lambda run, episode, first=None, noticed=None, notices=None: _shown_0_12_5(run, episode, first),
    )
    monkeypatch.setattr(expectation, "_described", _described_0_12_5)
    before = {k: c.sha256 for k, c in contexts(a, built, "10").items()}
    assert after == before
