"""Each model family proposes and the union runs once; the launch's content conditions by the application's store
category (launch@3); select's union of several assessments' choices (21 Nov 2026)."""

import json
from pathlib import Path

import pytest
import yaml
from ratatoskr.schemas import validate

from skuld import catalogue as cat
from skuld import inputs, propose, select
from tests import workspace as ws
from tests.test_propose import ANSWER, FORECAST, RUN, FakeProvider, catalogue_with, exploration, report

#: launch@3 as the catalogue holds it, cut to its first purpose
LAUNCH3 = {
    "id": "launch",
    "version": 3,
    "name": "launch",
    "entry": "cold start from the launcher, fresh data",
    "path": "no action",
    "outcome": "an entry screen of the app, ready for input",
    "purposes": [
        {
            "id": "P1",
            "action": "start and present",
            "object": "the app's entry screen",
            "beneficiary": "user",
            "context": "first launch",
            "outcome": "the app is ready for the user's first input",
            "node": "ServiceProvision",
            "fit": "broader",
            "specificity": "sufficient",
            "role": "functional",
            "requirements": [{"id": "R1", "statement": "show an entry screen"}],
            "oracle": {
                "reach": ["R1"],
                "success": [{"first_screen_ready": {}}],
                "invalid": [{"hold_above_ms": 1000}, {"launcher_first": {}}],
                "measurements": [],
                "slots": {},
                "categories": [
                    {
                        "names": ["Weather", "Wetter"],
                        "success": [{"text_shown": {"any": ["°"]}}],
                        "control": {"intervention": "network", "expected": "breaks"},
                    },
                    {
                        "names": ["Maps & Navigation", "Karten & Navigation"],
                        "success": [{"text_shown": {"any": ["Suche", "Search", "Route"]}}],
                    },
                ],
            },
        }
    ],
    "author": {"kind": "person", "name": "test"},
}


# -- launch@3 ---------------------------------------------------------------------------------------------------------


def test_the_launch_adds_the_content_of_the_store_category_and_keeps_its_own_oracle_otherwise():
    cat.check(LAUNCH3)
    oracle = LAUNCH3["purposes"][0]["oracle"]
    assert cat.success(oracle, "Wetter") == [{"first_screen_ready": {}}, {"text_shown": {"any": ["°"]}}]
    assert cat.success(oracle, " maps &  navigation ")[1] == {"text_shown": {"any": ["Suche", "Search", "Route"]}}
    assert cat.success(oracle, "Health & Fitness") == cat.success(oracle, None) == [{"first_screen_ready": {}}]
    assert cat.control(LAUNCH3, "Weather") == {"intervention": "network", "expected": "breaks"}
    assert cat.control(LAUNCH3, "Maps & Navigation") is None and cat.control(LAUNCH3, None) is None
    with pytest.raises(cat.CatalogueError, match="unknown predicate"):
        broken = json.loads(json.dumps(LAUNCH3))
        broken["purposes"][0]["oracle"]["categories"][0]["success"] = [{"forecast_shown": {}}]
        cat.check(broken)
    with pytest.raises(cat.CatalogueError, match="names and conditions"):
        broken["purposes"][0]["oracle"]["categories"] = [{"names": [], "success": []}]
        cat.check(broken)


def test_the_store_category_is_read_from_a_listing_a_collection_or_d_s_report(tmp_path):
    collection = tmp_path / "Saga" / "collections" / ws.PACKAGE / "20261031T221430Z_7cd201"
    (collection / "documents" / "listing").mkdir(parents=True)
    (collection / "documents" / "listing" / "listing.json").write_text(json.dumps({"category": "Wetter"}))
    assert propose.store_category(collection / "documents" / "listing" / "listing.json") == "Wetter"
    assert propose.store_category(collection) == "Wetter"
    d = tmp_path / "Urda" / "reports" / ws.PACKAGE / "20261031T221430Z_7cd201" / "report.json"
    d.parent.mkdir(parents=True)
    # Urda writes the collection's path relative to its own folder, with Windows' separators
    path = "..\\Saga\\collections\\" + ws.PACKAGE + "\\20261031T221430Z_7cd201"
    d.write_text(json.dumps({"collection": {"path": path}}))
    assert propose.store_category(d) == "Wetter"
    assert propose.store_category(tmp_path / "nothing.json") is None and propose.store_category(None) is None


def launched(tmp_path: Path, category: str | None) -> tuple[Path, dict]:
    exp = exploration(tmp_path / "runs" / RUN)
    root = tmp_path / "ws"
    (root / "observation" / RUN).mkdir(parents=True)
    (root / "observation" / RUN / "observation_report.json").write_text(json.dumps(report()))
    catalogue = catalogue_with(tmp_path / "catalogue", FORECAST, LAUNCH3)
    propose.propose(exp, root, catalogue, "fake", ["verdandi"], provider=FakeProvider(ANSWER), category=category)
    return root, yaml.safe_load((root / "cases" / "launch.yaml").read_text(encoding="utf-8"))


def test_a_weather_apps_launch_checks_for_a_forecast_and_has_the_network_control(tmp_path):
    root, case = launched(tmp_path, "Wetter")
    workspace = inputs.load(root)
    oracle = workspace.oracles["O-launch-1@1"]
    assert oracle.success == ({"first_screen_ready": {}}, {"text_shown": {"any": ["°"]}})
    assert {"launcher_first": {}} in oracle.invalid
    assert (
        case["family"]["category"] == "Wetter"
        and case["control"] == LAUNCH3["purposes"][0]["oracle"]["categories"][0]["control"]
    )
    assert next(c for c in workspace.cases if c.id == "launch").control["intervention"] == "network"


def test_an_app_of_another_category_keeps_the_launch_without_content_or_control(tmp_path):
    root, case = launched(tmp_path, "Health & Fitness")
    assert inputs.load(root).oracles["O-launch-1@1"].success == ({"first_screen_ready": {}},)
    assert "control" not in case and case["family"]["category"] == "Health & Fitness"  # read, and no entry of it


# -- proposals per model, and their union -------------------------------------------------------------------------------


class Named(FakeProvider):
    """A model family's answers: the same flow, another answer."""


def proposed(tmp_path: Path) -> tuple[Path, Path, Path]:
    exp = exploration(tmp_path / "runs" / RUN)
    root = tmp_path / "ws"
    (root / "observation" / RUN).mkdir(parents=True)
    (root / "observation" / RUN / "observation_report.json").write_text(json.dumps(report()))
    catalogue = catalogue_with(tmp_path / "catalogue", FORECAST, LAUNCH3)
    return exp, root, catalogue


def test_each_model_proposes_into_its_own_folder_without_fixing(tmp_path):
    exp, root, catalogue = proposed(tmp_path)
    summary = propose.propose_model(exp, root, catalogue, "gemma4:31b", ["verdandi"], provider=FakeProvider(ANSWER))
    assert [c["case"] for c in summary["cases"]] == ["launch", "e1", "e1b"]
    assert (root / "proposals" / "gemma4-31b" / "summary.json").is_file()
    assert (root / "proposals" / "gemma4-31b" / "e1" / "a1" / "answer.json").is_file()
    assert not (root / inputs.FROZEN).exists() and not list((root / "cases").glob("*.yaml"))


def test_the_union_merges_identical_cases_naming_every_proposer_and_fixes_once(tmp_path):
    exp, root, catalogue = proposed(tmp_path)
    propose.propose_model(exp, root, catalogue, "gemma4:31b", ["verdandi"], provider=FakeProvider(ANSWER))
    forecast_only = {"features": [ANSWER["features"][0]]}
    propose.propose_model(exp, root, catalogue, "qwen3.8:27b", ["verdandi"], provider=FakeProvider(forecast_only))
    with pytest.raises(propose.ProposalError, match="no model's proposals"):
        propose.merge(exp, tmp_path / "empty", catalogue, ["verdandi"])
    summary = propose.merge(exp, root, catalogue, ["verdandi"])
    assert summary["models"] == ["gemma4:31b", "qwen3.8:27b"]
    cases = {c["case"]: c for e in summary["episodes"].values() for c in e["cases"]}
    assert list(cases) == ["launch", "e1", "e1b"]
    assert cases["e1"]["proposers"] == ["gemma4:31b", "qwen3.8:27b"] and cases["e1b"]["proposers"] == ["gemma4:31b"]
    assert cases["launch"]["proposers"] == ["skuld.propose"]  # filled by rule, once
    workspace = inputs.load(root)
    inputs.check_frozen(workspace)
    e1 = next(c for c in workspace.cases if c.id == "e1")
    assert [(p["kind"], p["name"], p["case"]) for p in e1.proposers] == [
        ("model", "gemma4:31b", "e1"),
        ("model", "qwen3.8:27b", "e1"),
    ]
    frozen = inputs.frozen(root)["inputs"]
    assert frozen["cases/e1.yaml"]["author"]["generated"]["answer"] == "proposals/gemma4-31b/e1/a1"
    with pytest.raises(propose.ProposalError, match="fixed inputs already"):
        propose.merge(exp, root, catalogue, ["verdandi"])


def test_the_case_report_names_the_proposers(tmp_path):
    from skuld.experiments import analyse

    exp, root, catalogue = proposed(tmp_path)
    propose.propose_model(exp, root, catalogue, "gemma4:31b", ["verdandi"], provider=FakeProvider(ANSWER))
    propose.propose_model(exp, root, catalogue, "qwen3.8:27b", ["verdandi"], provider=FakeProvider(ANSWER))
    propose.merge(exp, root, catalogue, ["verdandi"])
    report = analyse(inputs.load(root), make_observations=False)  # before any run
    validate("expectation_report", report)
    by_case = {c["id"]: c for c in report["cases"]}
    assert [p["name"] for p in by_case["e1"]["proposers"]] == ["gemma4:31b", "qwen3.8:27b"]
    assert by_case["launch"]["proposers"] == [{"kind": "rule", "name": "skuld.propose", "family": "launch@3"}]


# -- select's union -----------------------------------------------------------------------------------------------------


def selection(folder: Path, *chosen: str) -> Path:
    (folder / "inputs").mkdir(parents=True)
    entries = [
        {"id": f"selection:{p}:1", "practice": p, "kind": select.CHOICE, "reason": "within the budget"} for p in chosen
    ]
    (folder / select.FILE).write_text(json.dumps({"created": "2026-11-21T10:00:00+00:00", "entries": entries}))
    return folder


def test_select_writes_the_union_of_several_assessments_choices_into_chosen_yaml(tmp_path):
    root = tmp_path / "gemma"
    (root / "inputs").mkdir(parents=True)
    (root / select.CHOSEN).write_text(yaml.safe_dump({"chosen": [{"id": "P-1", "reason": "pursue"}]}))
    qwen = selection(tmp_path / "qwen", "P-1", "P-2")
    other = selection(tmp_path / "other", "P-2", "P-3")
    select.union(root, [qwen, other, root])
    chosen = yaml.safe_load((root / select.CHOSEN).read_text(encoding="utf-8"))["chosen"]
    assert [(e["id"], e["reason"]) for e in chosen] == [("P-1", "pursue"), ("P-2", "union"), ("P-3", "union")]
    assert [f["assessment"] for f in chosen[1]["from"]] == ["../qwen", "../other"]
    assert chosen[1]["from"][0]["reason"] == "within the budget"
    assert select._chosen(root)["P-2"] == ("union", 0) and "union" in select.UNBUDGETED
    select.union(root, [qwen])  # again: nothing twice
    again = yaml.safe_load((root / select.CHOSEN).read_text(encoding="utf-8"))["chosen"]
    assert again == chosen
    with pytest.raises(select.SelectionError, match="no selection"):
        select.union(root, [tmp_path / "none"])



def test_a_proposer_thinks_at_the_level_its_profile_gives_and_its_samples_record_it(tmp_path, monkeypatch):
    """23 Nov 2026: propose passed no thinking level, so qwen3.8:27b proposed at the gateway's default (xhigh), which
    the re-run had left for medium (D-49); `propose.think` in the configuration or its profile now sets it."""
    from skuld import config

    exp, root, catalogue = proposed(tmp_path)
    propose.propose_model(exp, root, catalogue, "gemma4:31b", ["verdandi"], provider=FakeProvider(ANSWER))
    record = json.loads((root / "proposals" / "gemma4-31b" / "e1" / "a1" / "record.json").read_text())
    assert "think" not in record["options"] and record["model"]["think"] == "model default"
    loaded = config.load()
    monkeypatch.setattr(config, "load", lambda: {**loaded, "propose": {"think": "medium"}})
    provider = FakeProvider(ANSWER)
    propose.propose_model(exp, root, catalogue, "qwen3.8:27b", ["verdandi"], provider=provider)
    record = json.loads((root / "proposals" / "qwen3.8-27b" / "e1" / "a1" / "record.json").read_text())
    assert provider.calls and record["options"]["think"] == "medium" and record["model"]["think"] == "medium"
