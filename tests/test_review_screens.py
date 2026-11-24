"""The screens a review shows, with their descriptions and screenshots as stage 1 was given them, and D-45 (0.12.19)."""

import json
import random
import shutil
import zipfile

import pytest

from skuld import expectation, review_screens
from skuld import review_expectation as rx
from skuld import review_export as rex
from tests.test_described import GEMMA, QWEN, contexts, described_run, workspace_of


@pytest.fixture
def described(tmp_path, monkeypatch):
    """test_described's workspace: a run with screenshots and both models' descriptions."""
    monkeypatch.setattr(expectation, "describer", lambda model: model)  # expectation.descriptions: "own"
    run = described_run(tmp_path)
    return (*workspace_of(tmp_path, run), run)


def write_contexts(a, built, root, model=GEMMA):
    """The workspace's stage-1 contexts of prompt version 10, as `skuld expect` keeps them (expectation/<batch>/s1/)."""
    for name, context in contexts(a, built, "10", model).items():
        folder = root / "expectation" / name / "s1"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "context.json").write_text(json.dumps({"parts": list(context.parts)}))


def empty_description(run, screen_id, model):
    lines = [json.loads(x) for x in (run / "descriptions.jsonl").read_text().splitlines()]
    for x in lines:
        if x.get("screen_id") == screen_id and x.get("model") == model:
            x["screen"] = ""
    (run / "descriptions.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_each_screen_has_its_own_familys_description_and_the_screenshot_the_context_attached(described):
    a, built, run = described
    root = a.root
    write_contexts(a, built, root)
    found = review_screens.index(root)
    launch = json.loads((root / "expectation" / "launch" / "s1" / "context.json").read_text())["parts"]
    home, signup = (p for p in launch if p["id"] in ("S1", "S2"))
    entry = found[review_screens.screen_key(home)]
    assert entry["description"] == "gemma4:31b reads s-home. It follows the start."  # without "(about S1)"
    assert entry["screenshot"] == (home["provenance"][1]["record"], home["provenance"][1]["sha256"])
    assert entry["empty"] == set()
    shown = review_screens.view(entry)
    assert shown == {
        "description": entry["description"],
        "screenshot": f"screenshots/{home['provenance'][1]['sha256']}.png",
        "visit": shown["visit"],
    }
    assert shown["visit"].startswith("v")
    # the sign-up form held a notice: the stage was given neither its description nor its screenshot, and none from
    # its visit either
    assert set(review_screens.view(found[review_screens.screen_key(signup)])) <= {"visit"}


def test_a_screen_whose_description_is_empty_by_either_model_is_marked_d45(described):
    a, built, run = described
    root = a.root
    write_contexts(a, built, root)
    empty_description(run, "s-home", QWEN)  # the other family's model: the gemma family's review still may not show it
    found = review_screens.index(root)
    home = next(k for k in found if k[1] == "s-home")
    assert found[home]["empty"] == {QWEN} and found[home]["description"]
    assert review_screens.empty([found[home]]) == [QWEN]
    # the plan screen joins on an earlier visit (seq 1): its emptiness is that visit's
    empty_description(run, "s-plan", GEMMA)
    found = review_screens.index(root)
    plan = [k for k in found if k[1] == "s-plan"]
    assert plan and all(GEMMA in found[k]["empty"] for k in plan)


def test_a_context_that_is_not_its_batchs_screens_is_refused(described):
    a, built, run = described
    root = a.root
    write_contexts(a, built, root)
    path = root / "expectation" / "launch" / "s1" / "context.json"
    parts = json.loads(path.read_text())["parts"]
    for p in parts:
        if p["id"] == "S1":
            p["provenance"][0]["record"] = "events.jsonl#screen/s-other"
    path.write_text(json.dumps({"parts": parts}))
    with pytest.raises(review_screens.ScreenError, match="not its batch's screen 1"):
        review_screens.index(root)


def test_screenshots_are_copied_once_by_digest_and_a_changed_file_is_refused(described, tmp_path):
    a, built, run = described
    root = a.root
    write_contexts(a, built, root)
    entries = list(review_screens.index(root).values())
    with_shot = [e for e in entries if e["screenshot"]]
    out = tmp_path / "sample"
    assert review_screens.copy_screenshots(out, entries + entries) == len({e["screenshot"][1] for e in with_shot})
    assert sorted(p.name for p in (out / "screenshots").iterdir()) == sorted(
        {f"{e['screenshot'][1]}.png" for e in with_shot}
    )
    (run / with_shot[0]["screenshot"][0]).write_bytes(b"changed")
    with pytest.raises(review_screens.ScreenError, match="differs"):
        review_screens.copy_screenshots(tmp_path / "other", entries)


def test_a_workspace_without_stage_one_contexts_shows_screens_as_before(tmp_path):
    assert review_screens.index(tmp_path) == {}


def test_d45_takes_the_strata_next_eligible_unit_in_the_seeds_order():
    units = [{"n": n, "ok": n % 3 != 0} for n in range(12)]
    order = random.Random(5).sample(units, len(units))
    passed: list = []
    taken = rx.eligible_first(units, 4, random.Random(5), lambda u: u["ok"], passed)
    assert taken == [u for u in order if u["ok"]][:4]
    last = order.index(taken[-1])
    assert passed == [u for u in order[:last] if not u["ok"]]
    # fewer eligible than the size: every eligible one
    assert len(rx.eligible_first(units, 20, random.Random(5), lambda u: u["ok"], [])) == 8


def test_the_cap_per_application_passes_over_ineligible_units_too():
    strata = {("r", "ancillary", "supported"): [{"application": f"a{n % 3}", "n": n, "ok": n != 0} for n in range(9)]}
    passed: list = []
    out = rx.capped(strata, {k: 4 for k in strata}, 2, random.Random(1), lambda u: u["ok"], passed)
    taken = out[("r", "ancillary", "supported")]
    assert len(taken) == 4 and all(u["ok"] for u in taken)
    assert all(not u["ok"] for u in passed)


@pytest.mark.skipif(not (rex.TOOL / "node_modules").is_dir(), reason="the review tool's modules are not installed")
def test_the_package_holds_the_samples_screenshots(tmp_path):
    from tests.test_review_expectation import workspace

    runs = [workspace(tmp_path, "model-x"), workspace(tmp_path, "model-y")]
    folder = tmp_path / "reviews" / "expect-1"
    rx.draw(folder, runs, per_stratum=5, seed=2)
    (folder / "screenshots").mkdir()
    (folder / "screenshots" / "abc.png").write_bytes(b"png")
    names = zipfile.ZipFile(rex.export(tmp_path / "pkg.zip", [folder], "a")).namelist()
    assert "asgard-review-a/samples/expect-1/screenshots/abc.png" in names


def test_the_tool_serves_the_screenshots_and_both_pages_show_them():
    server = (rex.TOOL / "server.js").read_text()
    assert "app.use('/screenshots'" in server
    for page in ("expectation.html", "aggregate.html"):
        text = (rex.TOOL / "public" / page).read_text()
        assert "e.screenshot" in text and "e.description" in text and 'class="zoom"' in text
    assert "screen_details" in (rex.TOOL / "public" / "expectation.html").read_text()


def test_described_reader_still_skips_empty_descriptions_for_stage_one(described):
    a, built, run = described
    empty_description(run, "s-home", GEMMA)
    assert all(d["screen_id"] != "s-home" for d in expectation.descriptions(run, GEMMA))


def test_an_empty_description_by_either_model_is_never_shown():
    entry = {"description": "A form.", "screenshot": ("screenshots/1.png", "ab"), "directory": None, "empty": set()}
    assert review_screens.view(entry)["description"] == "A form."
    entry["empty"] = {GEMMA}
    assert review_screens.view(entry) == {"screenshot": "screenshots/ab.png"}


def stage_one_workspace(tmp_path, run):
    """test_review_expectation's workspace, its context's screens named by run: S1 (cited by the steps) and S2."""
    from tests.test_review_expectation import workspace

    root = workspace(tmp_path, run)
    path = root / "expectation" / "e1" / "s1" / "context.json"
    parts = json.loads(path.read_text())["parts"]
    parts[2]["provenance"] = [{"origin": "run", "record": "events.jsonl#screen/s-ad", "run": "r1"}]
    parts.append(
        {
            "id": "S2",
            "kind": "screen",
            "text": "Settings",
            "provenance": [{"origin": "run", "record": "events.jsonl#screen/s-set", "run": "r1"}],
        }
    )
    path.write_text(json.dumps({"parts": parts}))
    return root


def entries(cited_empty=(), other_empty=()):
    return {
        ("r1", "s-ad", "An ad | Close"): {
            "description": "An ad.",
            "screenshot": None,
            "directory": None,
            "empty": set(cited_empty),
        },
        ("r1", "s-set", "Settings"): {
            "description": "Settings.",
            "screenshot": None,
            "directory": None,
            "empty": set(other_empty),
        },
    }


def test_stage_one_d45_passes_over_a_unit_only_for_a_cited_screen_and_hides_the_others(tmp_path, monkeypatch):
    runs = [stage_one_workspace(tmp_path, "model-x"), stage_one_workspace(tmp_path, "model-y")]
    # an empty description of an uncited screen: every unit stays eligible, the screen shows no description
    monkeypatch.setattr(rx, "index", lambda root: entries(other_empty={GEMMA}))
    m = rx.draw(tmp_path / "s1", runs, per_stratum=5, seed=2, exclude_empty_descriptions=True)
    assert m["empty_descriptions"]["ineligible"] == 0 and m["empty_descriptions"]["passed_over"] == []
    item = json.loads((tmp_path / "s1" / "sample.json").read_text())["items"][0]
    assert item["context"]["screens"] == ["An ad | Close", "Settings"]
    assert item["context"]["screen_details"] == [{"description": "An ad."}, {}]
    # an empty description of the screen the steps cite: no unit may be drawn
    monkeypatch.setattr(rx, "index", lambda root: entries(cited_empty={GEMMA}))
    m = rx.draw(tmp_path / "s2", runs, per_stratum=5, seed=2, exclude_empty_descriptions=True)
    assert m["empty_descriptions"]["ineligible"] == 4 and sum(s["drawn"] for s in m["strata"]) == 0
    assert {tuple(p["empty_by"]) for p in m["empty_descriptions"]["passed_over"]} == {(GEMMA,)}
    # without the option the draw is as before
    m = rx.draw(tmp_path / "s3", runs, per_stratum=5, seed=2)
    assert "empty_descriptions" not in m and sum(s["drawn"] for s in m["strata"]) == 4


# -- the re-run's review sizes (24 Nov 2026: 50 per sample, 25 per model) ----------------------------------------------


def test_shares_take_a_census_whole_and_the_rest_in_proportion_with_a_floor():
    from skuld.review import shares

    pops = {"exp": 7, "a": 334, "b": 51, "c": 118, "d": 15, "e": 67, "f": 376}
    out = shares(pops, 25, 1, frozenset({"exp"}))
    assert out["exp"] == 7 and sum(out.values()) == 25 and all(out[k] >= 1 for k in pops)
    assert out["f"] >= out["a"] > out["c"] >= out["e"] >= out["b"] >= out["d"]
    assert shares({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}  # never more than a stratum holds


def test_equal_shares_fill_the_strata_one_at_a_time():
    out = rx.equal_shares({"a": 340, "b": 10, "c": 215, "d": 9}, 25)
    assert sum(out.values()) == 25 and sorted(out.values()) == [6, 6, 6, 7] and out["a"] == 7
    assert rx.equal_shares({"a": 352, "b": 2, "c": 200, "d": 20}, 25) == {"a": 8, "b": 2, "c": 8, "d": 7}


def test_a_concern_draw_of_one_tier_with_its_experiments_drawn_whole(tmp_path, monkeypatch):
    from skuld import review
    from tests.test_review import FRAME, assessment, workspace

    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])
    runs = []
    for run in ("model-x", "model-y"):
        r = assessment(("appnexus", "yahoo", "criteo"), alternative_status="supported")
        r["evidence"].append({"id": "item:9", "kind": "run", "channel": "ex:e1", "method": "the case report"})
        r["concerns"][0]["supporting"] = ["item:9"]
        runs.append(workspace(tmp_path, run, r))
    every = [u for root in runs for u in review.units(root)[0]]
    backed = sum(u["_experiment"] for u in every)
    assert backed >= 2
    m = review.draw(tmp_path / "c", runs, seed=1, tiers=["reasoning"], total_per_run=3, census_experiments=True)
    assert m["allocation"] == {"total_per_run": 3, "floor": 3, "census_experiments": True} and m["tiers"] == [
        "reasoning"
    ]
    key = read_key(tmp_path / "c")
    assert sum(1 for k in key.values() if k["stratum"]["experiment"]) == backed
    assert all(s["drawn"] == s["population"] for s in m["strata"] if s["experiment"])
    assert all(s["tier"] == "reasoning" for s in m["strata"])


def read_key(folder):
    return json.loads((folder / "key.json").read_text())


def test_a_screen_changed_in_place_shows_its_visits_first_screenshot_before_the_change(tmp_path, monkeypatch):
    """Loki takes one screenshot per visit (a structure key); stage 1 shows a state changed in place as a screen of its
    own, without one: the review shows the visit's first screenshot, labelled, and names the visit for grouping."""
    from tests.test_described import described_run, workspace_of

    monkeypatch.setattr(expectation, "describer", lambda model: model)
    run = described_run(tmp_path)
    events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
    for e in events:
        e["exact_key"] = f"k-{e['screen_id']}"
    plan = next(e for e in events if e["screen_id"] == "s-plan")
    events.append({**plan, "seq": 4, "texts": ["Your plan", "Week 1: four sessions"], "screenshot": None})
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    a, built = workspace_of(tmp_path, run)
    write_contexts(a, built, a.root)
    found = review_screens.index(a.root)
    first = next(v for k, v in found.items() if k[2] == "Your plan | Week 1: three sessions")
    changed = next(v for k, v in found.items() if k[2] == "Your plan | Week 1: four sessions")
    assert changed["visit"] == first["visit"] == plan["seq"]
    assert changed["screenshot"] is None and changed["before"][0] == plan["screenshot"]
    shown = review_screens.view(changed)
    assert shown["before_change"] is True and shown["visit"] == f"v{plan['seq']}"
    assert shown["screenshot"] == f"screenshots/{changed['before'][1]}.png"
    assert "before_change" not in review_screens.view(first)
    out = tmp_path / "copied"
    assert review_screens.copy_screenshots(out, [changed]) == 1 and (out / shown["screenshot"]).is_file()


def test_a_screen_at_several_visits_is_shown_as_one_both_models_described(tmp_path, monkeypatch):
    """D-45 per visit: the same screen (text) at a later visit whose gemma description is empty neither hides the
    description of the earlier visit nor makes the screen ineligible; if every visit's is empty, it is."""
    from tests.test_described import described_run, workspace_of

    monkeypatch.setattr(expectation, "describer", lambda model: model)
    run = described_run(tmp_path)
    events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
    plan = next(e for e in events if e["screen_id"] == "s-plan")
    home = next(e for e in events if e["screen_id"] == "s-home")
    events += [{**home, "seq": 4, "episode": "1"}, {**plan, "seq": 5}]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    lines = [json.loads(x) for x in (run / "descriptions.jsonl").read_text().splitlines()]
    lines.append({"visit": 5, "screen_seq": 5, "screen_id": "s-plan", "episode": "1", "model": GEMMA, "screen": ""})
    (run / "descriptions.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    a, built = workspace_of(tmp_path, run)
    write_contexts(a, built, a.root)
    found = review_screens.index(a.root)
    key = next(k for k in found if k[1] == "s-plan")
    assert found[key]["occurrences"] >= 2
    assert found[key]["empty"] == set() and review_screens.view(found[key])["description"]
    # every visit's description empty: the screen is empty, its description hidden
    for x in lines:
        if x.get("screen_id") == "s-plan" and x.get("model") == GEMMA:
            x["screen"] = ""
    (run / "descriptions.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    found = review_screens.index(a.root)
    assert found[key]["empty"] == {GEMMA} and "description" not in review_screens.view(found[key])


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is not installed")
def test_a_traffic_line_is_split_into_request_field_excerpt_and_data_type():
    import subprocess

    script = """
import(process.argv[1]).then(m => {
  const g = m.groupTraffic([
    'P-1a2b: POST https://h.example/v1/x?a=1&b=two · header:9:User-Agent: …Android 14; «sdk_gphone64» Build… (app-info.device)',
    'POST https://h.example/v1/x?a=1&b=two · body: …"model":"«sdk_gphone64»","hw"… (app-info.device)',
    'POST https://other.example/p · content encrypted by the application',
    'not a traffic line',
  ]);
  console.log(JSON.stringify(g));
});"""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, (rex.TOOL / "public" / "traffic.js").as_uri()],
        capture_output=True,
        text=True,
        check=True,
    )
    groups = json.loads(out.stdout)
    assert [len(g["findings"]) for g in groups] == [2, 1, 0]
    request = groups[0]["request"]
    assert (request["method"], request["host"], request["path"]) == ("POST", "h.example", "/v1/x")
    assert request["params"] == [["a", "1"], ["b", "two"]]
    header, body = groups[0]["findings"]
    assert (header["field"]["label"], header["field"]["name"], header["datum"]) == (
        "Header",
        "User-Agent",
        "sdk_gphone64",
    )
    assert (body["field"]["label"], body["node"]) == ("Body", "app-info.device")
    assert groups[1]["findings"][0]["note"] == "content encrypted by the application"
    assert groups[2]["raw"] == "not a traffic line"
    for page in ("expectation.html", "aggregate.html"):
        text = (rex.TOOL / "public" / page).read_text()
        assert "traffic-list" in text and "useTraffic(app)" in text and "described-label" in text
