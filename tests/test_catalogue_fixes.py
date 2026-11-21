"""The catalogue's checks of 21 Nov 2026: slot keys, a superseded family, a category entry's reach; and every family of
Skuld's catalogue loads, its newest versions passing the strict check with nodes of the purpose vocabulary."""

import json

import pytest
import yaml

from skuld import catalogue as cat
from skuld import inputs, propose
from skuld.common import vocabulary
from skuld.oracles import PREDICATES
from skuld.select import CATALOGUE
from tests.test_propose import ANSWER, FORECAST, catalogue_with, exploration
from tests.test_proposers import LAUNCH3, launched

#: How current-location-forecast@1 wrote its slot: the comma ends the description in a YAML flow mapping
CUT = "{kind: text, description: the name of the place the forecast is shown for, as the screen at the end shows it}"


def with_slot(slot: dict) -> dict:
    oracle = {**FORECAST["purposes"][0]["oracle"], "slots": {"place": slot}}
    return {**FORECAST, "purposes": [{**FORECAST["purposes"][0], "oracle": oracle}]}


def test_a_slot_with_other_keys_than_kind_and_description_is_refused():
    cut = yaml.safe_load(CUT)
    assert cut["description"] == "the name of the place the forecast is shown for" and len(cut) == 3
    with pytest.raises(cat.CatalogueError, match="slot place has keys other than kind and description"):
        cat.check(with_slot(cut))
    cat.check(with_slot({"kind": "text", "description": "the place, as the screen shows it"}))
    cat.check(with_slot(cut), strict_slots=False)  # as a family written before is read


def test_a_family_written_before_with_a_cut_slot_is_read_but_refused_for_new_use(tmp_path):
    folder = catalogue_with(tmp_path / "c", with_slot(yaml.safe_load(CUT)))
    catalogue = cat.load(folder)
    (old,) = catalogue.families
    assert old.key == "current-location-forecast@1" and "as the screen at the end shows it" in old.problems[0]
    with pytest.raises(cat.CatalogueError, match="malformed"):
        catalogue.usable("current-location-forecast")
    with pytest.raises(cat.CatalogueError, match="other than kind and description"):
        catalogue.add(dict(old.data))  # a new version must be whole
    fixed = catalogue.add(with_slot({"kind": "text", "description": "the place, as the screen at the end shows it"}))
    assert fixed.key == "current-location-forecast@2" and not fixed.problems
    assert catalogue.usable("current-location-forecast") == fixed
    assert cat.load(folder).get("current-location-forecast", 1).problems  # still read, for the cases naming it


def test_a_superseded_family_is_offered_to_no_proposer(tmp_path):
    old = {**FORECAST, "id": "oauth-sign-up"}
    folder = catalogue_with(tmp_path / "c", FORECAST, old)
    catalogue = cat.load(folder)
    last = catalogue.add({**old, "superseded_by": "current-location-forecast"})
    assert last.superseded_by == "current-location-forecast"
    assert [f.key for f in catalogue.latest()] == ["current-location-forecast@1"]
    assert [f.key for f in catalogue.latest(superseded=True)] == ["current-location-forecast@1", "oauth-sign-up@2"]
    with pytest.raises(cat.CatalogueError, match="superseded by current-location-forecast"):
        catalogue.usable("oauth-sign-up")
    with pytest.raises(cat.CatalogueError, match="superseded_by"):
        cat.check({**old, "superseded_by": "Not An Id"})
    flow = propose.read(exploration(tmp_path / "runs" / "run")).flows[0]
    feature = {**ANSWER["features"][0], "family": "oauth-sign-up"}
    found = propose.feature_problems(feature, flow, cat.load(folder), vocabulary("dpv-purposes"))
    assert any("superseded" in p for p in found)


def test_a_category_entry_adds_the_requirements_its_conditions_reach(tmp_path, monkeypatch):
    launch = json.loads(json.dumps(LAUNCH3))
    p1 = launch["purposes"][0]
    p1["requirements"].append({"id": "R3", "statement": "show the app's primary content"})
    p1["oracle"]["categories"][0]["reach"] = ["R3"]
    cat.check(launch)
    assert cat.reach(p1["oracle"], "Wetter") == ["R1", "R3"] and cat.reach(p1["oracle"], "Health") == ["R1"]
    broken = json.loads(json.dumps(launch))
    broken["purposes"][0]["oracle"]["categories"][0]["reach"] = ["R9"]
    with pytest.raises(cat.CatalogueError, match="category entry 1 reaches"):
        cat.check(broken)
    monkeypatch.setattr("tests.test_proposers.LAUNCH3", launch)
    root, case = launched(tmp_path, "Weather")
    assert inputs.load(root).oracles["O-launch-1@1"].reach == ("R-launch-1.1", "R-launch-1.2")


# -- Skuld's catalogue ----------------------------------------------------------------------------------------------

needs_catalogue = pytest.mark.skipif(not (CATALOGUE / "families").is_dir(), reason="no catalogue/ (git-ignored)")


@needs_catalogue
def test_every_family_of_the_catalogue_loads_and_its_newest_pass_the_strict_check():
    catalogue = cat.load(CATALOGUE)
    assert {f.key for f in catalogue.families if f.problems} <= {
        "current-location-forecast@1",
        "current-location-forecast@2",
        "questionnaire-onboarding@1",
    }
    purposes = vocabulary("dpv-purposes")
    for f in catalogue.latest(superseded=True):
        cat.check(f.data)
        assert not f.problems, f.key
        for p in f.data["purposes"]:
            assert p["node"] in purposes, (f.key, p["node"])
            for spec in (p.get("oracle") or {}).get("success") or ():
                assert next(iter(spec)) in PREDICATES
    for f in catalogue.latest():
        assert catalogue.usable(f.id) == f
    superseded = {f.id: f.superseded_by for f in catalogue.latest(superseded=True) if f.superseded_by}
    assert superseded == {"oauth-sign-up": "third-party-authentication"}


@needs_catalogue
def test_the_launch_is_the_newest_and_checks_no_content():
    # launch@5 (live check of 21 Nov 2026): a cold start with fresh data shows a weather app's welcome screen, not its
    # forecast, so the launch checks only that the first screen is ready; content is left to goal-directed cases
    catalogue = cat.load(CATALOGUE)
    launch = catalogue.get(propose.RULE_FILLED)
    assert launch.version >= 5
    oracle = launch.data["purposes"][0]["oracle"]
    assert {"launcher_first": {}} in oracle["invalid"] and {"hold_above_ms": 1000} in oracle["invalid"]
    assert not oracle.get("categories")
    assert cat.success(oracle, "Weather") == [{"first_screen_ready": {}}]


def test_launch_4_checked_a_weather_apps_temperature_by_digit_and_degree():
    oracle = cat.load(CATALOGUE).get("launch", 4).data["purposes"][0]["oracle"]
    (weather,) = [e for e in oracle["categories"] if "Weather" in e["names"]]
    assert weather["success"] == [{"text_shown": {"any": [f"{d}°" for d in range(10)]}}]
    assert weather["control"] == {"intervention": "network", "expected": "breaks"} and weather["reach"] == ["R3"]
    assert cat.category_entry(oracle, "Productivity") is None and cat.category_entry(oracle, "Business") is None
    assert cat.success(oracle, "Productivity") == [{"first_screen_ready": {}}]
