import json
from pathlib import Path

import pytest
import yaml
from ratatoskr.llm import LLMResponse, Provider
from ratatoskr.vocabularies import Vocabulary

from skuld import catalogue as cat
from skuld import inputs, oracles, propose, space
from skuld.runs import load as load_run
from tests import workspace as ws

RUN = "20261023T100000Z_com.example.app_abcdef"

FORECAST = {
    "id": "current-location-forecast",
    "version": 1,
    "name": "forecast for the current location",
    "entry": "the app open",
    "path": "open the forecast for the place the device is at",
    "outcome": "the forecast for the place",
    "purposes": [
        {
            "id": "P1",
            "action": "determine and display",
            "object": "the weather forecast",
            "beneficiary": "user",
            "context": "the device's current location",
            "outcome": "the forecast for the area the user is in",
            "node": "ServiceProvision",
            "fit": "broader",
            "specificity": "sufficient",
            "role": "functional",
            "requirements": [
                {"id": "R1", "statement": "determine an area relevant to the user"},
                {"id": "R2", "statement": "display the forecast with the area's name"},
            ],
            "oracle": {
                "reach": ["R1", "R2"],
                "success": [
                    {"text_shown": {"any": "{place}", "after_action": "{path_end}", "until_action": "{path_end}"}}
                ],
                "invalid": [{"hold_above_ms": 1000}],
                "measurements": [],
                "slots": {"place": {"kind": "text", "description": "the place the forecast is for"}},
            },
        }
    ],
    "author": {"kind": "person", "name": "test"},
    "reviewed": None,
}
LAUNCH = {
    **FORECAST,
    "id": "launch",
    "name": "launch",
    "purposes": [
        {
            **FORECAST["purposes"][0],
            "requirements": [{"id": "R1", "statement": "show an entry screen"}],
            "oracle": {
                "reach": ["R1"],
                "success": [{"first_screen": {"activity_suffix": "{first_activity}"}}],
                "slots": {"first_activity": {"kind": "activity", "description": "the first screen's activity"}},
            },
        }
    ],
}
NEW = {
    "id": "place-picking",
    "name": "picking a place",
    "entry": "the app open",
    "path": "choose a place from a list",
    "outcome": "the chosen place is shown",
    "purposes": [
        {
            "action": "offer",
            "object": "places to choose from",
            "beneficiary": "user",
            "context": "choosing a place",
            "outcome": "a place chosen",
            "node": "ServiceProvision",
            "fit": "broader",
            "role": "functional",
            "requirements": ["offer places to choose from"],
            "oracle": {
                "reach": [1],
                "conditions": [{"check": "screen_reached", "slot": "picker"}],
                "slots": [{"name": "picker", "kind": "screen", "description": "the list of places"}],
            },
        }
    ],
}
ANSWER = {
    "features": [
        {
            "family": "current-location-forecast",
            "new_family": None,
            "slots": [{"name": "place", "values": ["Zurich"]}],
            "name": "forecast",
            "outcome": "the forecast for Zurich",
        },
        {
            "family": "new",
            "new_family": NEW,
            "slots": [{"name": "picker", "values": ["k1"]}],
            "name": "place picker",
            "outcome": "a list of places",
        },
    ]
}


class FakeProvider(Provider):
    api = "fake"

    def __init__(self, answer: dict):
        super().__init__()
        self.answer, self.calls = json.dumps(answer), 0

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        self.calls += 1
        assert "current-location-forecast" in prompt.messages[0]["content"]
        assert '"id": "launch"' not in prompt.messages[0]["content"]  # filled by rule, not asked
        return LLMResponse(text=self.answer)

    async def digests(self):
        return {"fake": "sha256:" + "f" * 64}


def screen(seq, key, texts, after_action=False, activity="Main"):
    return {
        "seq": seq,
        "ts": "2026-10-23T10:00:00+00:00",
        "type": "screen",
        "episode": 1,
        "screen_id": f"s-{key}",
        "package": ws.PACKAGE,
        "activity": f"{ws.PACKAGE}.{activity}",
        "exact_key": key,
        "label": "post_action" if after_action else "initial",
        "texts": texts,
    }


def action(seq, episode):
    return {"seq": seq, "ts": "2026-10-23T10:00:01+00:00", "type": "action", "episode": episode, "kind": "tap"}


def exploration(folder: Path) -> Path:
    """Loki's exploration: a first run of two actions ending at a forecast, a survey, and a flow only partly done."""
    events = [
        {"seq": 1, "ts": "2026-10-23T10:00:00+00:00", "type": "run_start"},
        screen(2, "k0", ["Welcome", "Start", "Forecast app"], activity="Welcome"),
        screen(3, "k1", ["Pick a place", "Zurich", "Bern"], after_action=True),
        action(4, 1),
        screen(5, "k2", ["Forecast", "in Zurich", "12 degrees"], after_action=True),
        action(6, 1),
        {"seq": 7, "ts": "2026-10-23T10:00:02+00:00", "type": "episode_end", "episode": 1, "success": True},
        action(8, 2),
        action(9, 3),
        {"seq": 10, "ts": "2026-10-23T10:00:03+00:00", "type": "episode_end", "episode": 3, "success": False},
    ]
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    meta = {
        "schema_version": 2,
        "run_id": RUN,
        "package": ws.PACKAGE,
        "status": "finished",
        "app": {"version_name": "1.0"},
    }
    (folder / "run.json").write_text(json.dumps(meta))
    episodes = [
        {"episode": 1, "kind": "first_run", "label": "(first run)", "item_id": None},
        {"episode": 2, "kind": "survey", "label": "(survey)", "item_id": None},
        {"episode": 3, "kind": "flow", "label": "Share", "item_id": "f1"},
    ]
    (folder / "episodes.json").write_text(json.dumps(episodes))
    item = {"id": "f1", "title": "Share", "where": "", "category": "sharing", "verified": "partly"}
    (folder / "checklist.json").write_text(json.dumps({"items": [item]}))
    return folder


def report() -> dict:
    """O's report of the exploration: the advertising ID read at launch, location read and sent in the first run."""
    out = ws.observation_report(RUN, aaid=ws.DEVICE_ID, blocked=True)
    aaid = out["claims"][0]
    aaid["datum"]["value_identity"] = "source:advertising_id"
    aaid["qualifiers"]["contexts"] = [{"time": "t", "episode": "?"}]
    location = ws._claim("l1", "accesses", "location.coordinates", None, ["x1"])
    location["datum"]["value_identity"] = "source:location"
    location["qualifiers"]["contexts"] = [{"time": "t", "episode": "1"}]
    sent = ws._claim(
        "t9",
        "transmits",
        "location.coordinates",
        {"endpoint": {"host": "t.tracker.example"}, "entity": "tracker", "domain": "tracker.example"},
        ["x1"],
    )
    sent["qualifiers"]["contexts"] = [{"time": "t", "episode": "1"}]
    own = ws._claim(
        "t10",
        "transmits",
        "data",
        {"endpoint": {"host": "api.example.com"}, "entity": "example", "domain": "example.com"},
        ["x1"],
    )
    own["qualifiers"]["contexts"] = [{"time": "t", "episode": "1"}]
    out["claims"] += [location, sent, own]
    return out


def catalogue_with(folder: Path, *families: dict) -> Path:
    (folder / "families").mkdir(parents=True)
    for f in families:
        (folder / "families" / f"{f['id']}@{f['version']}.yaml").write_text(yaml.safe_dump(f, sort_keys=False))
    return folder


@pytest.fixture
def made(tmp_path):
    exp = exploration(tmp_path / "runs" / RUN)
    root = tmp_path / "ws"
    (root / "observation" / RUN).mkdir(parents=True)
    (root / "observation" / RUN / "observation_report.json").write_text(json.dumps(report()))
    catalogue = catalogue_with(tmp_path / "catalogue", FORECAST, LAUNCH)
    provider = FakeProvider(ANSWER)
    summary = propose.propose(exp, root, catalogue, "fake", ["verdandi"], provider=provider)
    return root, catalogue, summary, provider


# -- the catalogue ------------------------------------------------------------------------------------------------


def test_a_family_is_checked_for_its_predicates_slots_and_reach():
    cat.check(FORECAST)
    oracle = FORECAST["purposes"][0]["oracle"]

    def with_oracle(**changes):
        return {**FORECAST, "purposes": [{**FORECAST["purposes"][0], "oracle": {**oracle, **changes}}]}

    with pytest.raises(cat.CatalogueError, match="unknown predicate"):
        cat.check(with_oracle(success=[{"guess": {}}]))
    with pytest.raises(cat.CatalogueError, match="undeclared slots"):
        cat.check(with_oracle(success=[{"text_shown": {"any": "{city}"}}]))
    with pytest.raises(cat.CatalogueError, match="declared but not used"):
        cat.check(with_oracle(success=[{"text_shown": {"any": ["Zurich"]}}]))
    with pytest.raises(cat.CatalogueError, match="not requirements of the purpose"):
        cat.check(with_oracle(reach=["R9"]))
    with pytest.raises(cat.CatalogueError, match="lower-case words"):
        cat.check({**FORECAST, "id": "Forecast"})


def test_a_slot_that_is_a_whole_argument_takes_its_value_and_one_within_a_text_is_written_into_it():
    assert cat.fill({"any": "{place}", "after_action": "{path_end}"}, {"place": ["Zurich"], "path_end": 2}) == {
        "any": ["Zurich"],
        "after_action": 2,
    }
    assert cat.fill("in {place}", {"place": "Bern"}) == "in Bern"


def test_a_change_to_a_family_is_its_next_version(tmp_path):
    catalogue = cat.load(catalogue_with(tmp_path / "c", FORECAST))
    before = catalogue.sha256
    family = catalogue.add({**FORECAST, "name": "forecast here"})
    assert (
        family.key == "current-location-forecast@2"
        and (tmp_path / "c" / "families" / "current-location-forecast@1.yaml").is_file()
    )
    assert [f.key for f in cat.load(tmp_path / "c").latest()] == ["current-location-forecast@2"]
    assert cat.load(tmp_path / "c").sha256 != before


# -- the flows ----------------------------------------------------------------------------------------------------


def test_the_flows_are_the_episodes_judged_carried_out_with_their_actions_and_screens(tmp_path):
    exp = propose.read(exploration(tmp_path / RUN))
    assert exp.package == ws.PACKAGE and exp.version == "1.0"
    (flow,) = exp.flows  # the survey is no flow, and the share flow was only partly carried out
    assert (flow.episode, flow.start, flow.end) == (1, 0, 2)
    assert [s.key for s in flow.entry] == ["k0"] and [s.key for s in flow.outcome] == ["k2"]
    assert "after=2 LAST key=k2" in propose.render_flow(flow)


def test_a_slot_must_come_from_the_flows_screens_and_tell_its_outcome_from_its_entry(tmp_path):
    flow = propose.read(exploration(tmp_path / RUN)).flows[0]
    catalogue = cat.load(catalogue_with(tmp_path / "c", FORECAST, LAUNCH))
    purposes = Vocabulary.load("dpv-purposes")

    def refused(feature, titles=()):
        return propose.feature_problems(feature, flow, catalogue, purposes, titles)

    forecast = ANSWER["features"][0]
    assert refused(forecast) == []
    assert (
        "not shown by the screens after" in refused({**forecast, "slots": [{"name": "place", "values": ["Paris"]}]})[0]
    )
    assert "first screen too" in refused({**forecast, "slots": [{"name": "place", "values": ["Forecast"]}]})[0]
    picker = ANSWER["features"][1]
    assert refused(picker) == []
    assert "after its start" in refused({**picker, "slots": [{"name": "picker", "values": ["k0"]}]})[0]
    named = {**NEW, "purposes": [{**NEW["purposes"][0], "requirements": ["read the coordinates"]}]}
    assert "names 'coordinates'" in refused({**picker, "new_family": named})[0]
    named = {**NEW, "purposes": [{**NEW["purposes"][0], "requirements": ["know the precise location"]}]}
    assert "names 'Precise location'" in refused({**picker, "new_family": named}, ["Precise location"])[0]
    assert refused({**forecast, "family": "launch"}) == ["the launch is no feature of a flow"]
    assert "no family of the catalogue" in refused({**forecast, "family": "nearby-search"})[0]


def test_the_search_space_is_derived_from_what_o_establishes_in_the_episode():
    components, alternatives = space.derive(report(), {"1"}, ws.PACKAGE)
    assert [a["id"] for a in alternatives] == ["G-round1", "G-round0", "R-tracker"]  # not the provider's example.com
    assert alternatives[-1]["intervention"] == {"block_hosts": ["tracker.example"]}
    elsewhere = {"time": "t", "episode": "4"}
    other = report()
    other["claims"][-2]["qualifiers"]["contexts"].append(elsewhere)
    other["claims"][-2]["recipient"] = {**other["claims"][-2]["recipient"], "domain": "tracker.example"}
    seen = ws._claim(
        "t11",
        "transmits",
        "data",
        {"endpoint": {"host": "x.trk.example"}, "entity": "tracker", "domain": "trk.example"},
        ["x1"],
    )
    seen["qualifiers"]["contexts"] = [elsewhere]
    other["claims"].append(seen)
    # a recipient's domains are those of the whole recording, so that every case imposes the same condition
    assert space.derive(other, {"1"}, ws.PACKAGE)[1][-1]["intervention"] == {
        "block_hosts": ["tracker.example", "trk.example"]
    }
    assert "R-tracker" not in [a["id"] for a in space.derive(other, {"?"}, ws.PACKAGE)[1]]
    _, at_launch = space.derive(report(), {"?", "0"}, ws.PACKAGE)
    assert [a["id"] for a in at_launch] == ["D-advertising_id"]
    assert at_launch[0]["intervention"]["sources"]["advertising_id"] == f"replace:{ws.ZERO}"
    # the provider's recipients are those parties.relate decides, as for the assessment's practices
    alternatives = space.derive(report(), {"1"}, ws.PACKAGE, own=lambda r: False)[1]
    assert [a["id"] for a in alternatives] == ["G-round1", "G-round0", "R-example", "R-tracker"]
    alternatives = space.derive(report(), {"1"}, ws.PACKAGE, own=lambda r: r["entity"] == "tracker")[1]
    assert [a["id"] for a in alternatives] == ["G-round1", "G-round0", "R-example"]


# -- the workspace ------------------------------------------------------------------------------------------------


def test_the_generator_writes_and_fixes_a_case_per_feature(made):
    root, catalogue, summary, provider = made
    assert provider.calls == 1
    assert [c["case"] for e in summary["episodes"].values() for c in e["cases"]] == ["launch", "e1", "e1b"]
    workspace = inputs.load(root)
    frozen = inputs.check_frozen(workspace)
    forecast = next(c for c in workspace.cases if c.id == "e1")
    assert (forecast.feature.start, forecast.feature.actions, forecast.feature.path_run) == (0, 2, RUN)
    assert forecast.feature.contains == ("F-launch",)
    assert [a.id for a in forecast.alternatives] == ["G-round1", "G-round0", "R-tracker"]
    assert forecast.purposes[0].provenance == "feature"
    oracle = workspace.oracles[forecast.purposes[0].oracle]
    assert oracle.success == ({"text_shown": {"any": ["Zurich"], "after_action": 2, "until_action": 2}},)
    assert oracle.reach == ("R-e1-1.1", "R-e1-1.2")
    author = frozen["cases/e1.yaml"]["author"]
    assert author["kind"] == "model" and author["generated"]["family"]["id"] == "current-location-forecast"
    assert author["generated"]["answer"] == "proposals/e1/a1"
    launch = next(c for c in workspace.cases if c.id == "launch")
    assert workspace.oracles[launch.purposes[0].oracle].success == (
        {"first_screen": {"activity_suffix": f"{ws.PACKAGE}.Welcome"}},
    )
    assert frozen["cases/launch.yaml"]["author"]["name"] == "test"  # filled by rule: the family's author
    new = cat.load(catalogue).get("place-picking")
    assert new.key == "place-picking@1" and new.data["derived_from"]["run"] == RUN and not new.reviewed


def test_generated_inputs_are_fixed_once_and_answers_are_kept(made, tmp_path):
    root, catalogue, _, _ = made
    with pytest.raises(propose.ProposalError, match="fixed inputs already"):
        propose.propose(tmp_path / "runs" / RUN, root, catalogue, "fake", ["verdandi"], offline=True)
    (root / inputs.FROZEN).unlink()
    for folder in ("cases", "oracles"):
        for f in (root / folder).iterdir():
            f.unlink()
    for f in (catalogue / "families").glob("place-picking*"):
        f.unlink()
    summary = propose.propose(tmp_path / "runs" / RUN, root, catalogue, "fake", ["verdandi"], offline=True)
    assert [c["case"] for c in summary["episodes"]["e1"]["cases"]] == ["e1", "e1b"]


def test_a_feature_refused_twice_is_left_out_and_the_others_kept(tmp_path):
    exp = exploration(tmp_path / "runs" / RUN)
    root = tmp_path / "ws"
    (root / "observation" / RUN).mkdir(parents=True)
    (root / "observation" / RUN / "observation_report.json").write_text(json.dumps(report()))
    catalogue = catalogue_with(tmp_path / "catalogue", FORECAST, LAUNCH)
    wrong = {"features": [ANSWER["features"][0], {**ANSWER["features"][1], "slots": []}]}
    provider = FakeProvider(wrong)
    summary = propose.propose(exp, root, catalogue, "fake", ["verdandi"], provider=provider)
    assert provider.calls == 2
    assert [c["case"] for c in summary["episodes"]["e1"]["cases"]] == ["e1"]
    assert summary["episodes"]["e1"]["refused"] == ["feature 2: slot picker is not filled"]
    assert "Your previous answer was refused" in (root / "proposals" / "e1" / "a2" / "prompt.txt").read_text(
        encoding="utf-8"
    )


# -- the predicates and the path ----------------------------------------------------------------------------------


def test_texts_and_screens_are_judged_between_the_actions_an_oracle_names(tmp_path):
    folder = exploration(tmp_path / RUN)
    (folder / "graph.json").write_text(json.dumps({"screens": {}}))
    run = load_run(folder, capture=False)
    assert oracles._text_shown(run, ["in Zurich"], after_action=2, until_action=2)
    assert not oracles._text_shown(run, ["Pick a place"], after_action=2, until_action=2)
    assert oracles._text_shown(run, ["Pick a place"], after_action=0, until_action=1)
    assert oracles._screen_reached(run, "k1", after_action=0, until_action=2)
    assert not oracles._screen_reached(run, "k1", after_action=2)


def test_a_path_cannot_start_after_its_last_action(tmp_path):
    root = ws.build(tmp_path / "ws", freeze=False)
    case = yaml.safe_load((root / "cases" / "start.yaml").read_text(encoding="utf-8"))
    case["feature"]["path"] = {"run": "rec-1", "from": 3, "actions": 2}
    (root / "cases" / "start.yaml").write_text(yaml.safe_dump(case))
    with pytest.raises(inputs.InputError, match="starts after its last action"):
        inputs.load(root)
