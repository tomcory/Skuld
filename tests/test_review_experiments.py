"""The experiments a review of concerns shows (skuld.review_experiments, 0.12.33)."""

import json
from pathlib import Path

from skuld import review_experiments

PKG = "com.example.app"

CASE = """\
id: e1
feature:
  id: F-e1
  name: Onboarding
  entry: the app's entry screen
  path:
    run: rec
    from: 0
    actions: 3
  outcome: The user reaches the main screen.
purposes:
- id: P-e1-1
  action: set up
  object: the app for its first use
  beneficiary: user
  context: first launch
  outcome: ready-to-use app
  node: ServiceProvision
  fit: broader
  provenance: feature
  specificity: sufficient
  role: functional
  requirements:
  - id: R-e1-1.1
    statement: complete the onboarding
  oracle: O-e1-1@1
components:
- id: x-ads
  dimension: R
  name: ads.example
- id: x-android-id
  dimension: D
  name: android id
- id: x-loc
  dimension: G
  name: location
search_space:
  alternatives:
  - id: R-ads
    component: x-ads
    removal: true
    changes:
    - component: x-ads
      value: null
    intervention:
      block_hosts:
      - ads.example
  - id: D-android_id
    component: x-android-id
    removal: true
    changes:
    - component: x-android-id
      value: null
    intervention:
      sources:
        android_id: replace:0000000000000000
  - id: G-round1
    component: x-loc
    removal: false
    changes:
    - component: x-loc
      value: location.approximate-location
    intervention:
      sources:
        location: round:1
"""

ORACLE = """\
id: O-e1-1
version: 1
purpose: P-e1-1
reach:
- R-e1-1.1
success:
- screen_reached:
    exact_key: kmain
    after_action: 0
    until_action: 3
invalid: []
measurements: []
"""


def screen(seq, key, texts, shot=None, package=PKG, content=None):
    e = {"seq": seq, "type": "screen", "package": package, "exact_key": key, "texts": texts, "label": "post_action"}
    if content:
        e["content_key"] = content
    if shot:
        e["screenshot"] = shot
    return e


def run_folder(base: Path, name: str, events: list[dict]) -> None:
    d = base / "runs" / name
    (d / "screenshots").mkdir(parents=True)
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    for e in events:
        if e.get("screenshot"):
            (d / e["screenshot"]).write_bytes(f"png {name} {e['seq']}".encode())


def run_record(run, decision, messages, verified=None):
    out = {
        "id": run,
        "decisions": [{"purpose": "P-e1-1", "case": "e1", "oracle": "O-e1-1@1", "decision": decision}],
        "costs": {"messages": messages, "connections": 10, "connections_dropped": 2},
        "verification": {"status": verified or "not_applicable"},
    }
    return out


def comparison(alt, base_runs, alt_runs, outcome="preserves", divergence=()):
    return {
        "id": f"e1:P-e1-1:{alt}",
        "case": "e1",
        "purpose": "P-e1-1",
        "oracle": "O-e1-1@1",
        "alternative": alt,
        "baseline_runs": base_runs,
        "alternative_runs": alt_runs,
        "outcome": outcome,
        "divergence": list(divergence),
    }


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "cases").mkdir(parents=True)
    (root / "oracles").mkdir()
    (root / "cases" / "e1.yaml").write_text(CASE)
    (root / "oracles" / "O-e1-1@1.yaml").write_text(ORACLE)
    (root / "workspace.yaml").write_text(f"application:\n  package: {PKG}\nruns: ../runs\nrecording: rec\n")
    run_folder(
        tmp_path,
        "rec",
        [
            screen(1, "kstart", ["Welcome"], "screenshots/1.png"),
            screen(5, "kmain", ["Home", "Search"], "screenshots/5.png", content="cmain"),
        ],
    )
    # a baseline run that met the check at a screen Loki took no screenshot of: its visit's first is shown
    run_folder(
        tmp_path,
        "b1",
        [
            screen(1, "android", [], package="android"),
            screen(2, "kmain", ["Home"], "screenshots/2.png"),
            screen(3, "kmain", ["Home", "Search"]),
        ],
    )
    run_folder(tmp_path, "b2", [screen(1, "kmain", ["Home"], "screenshots/1.png")])
    # an alternative run that met it at a screen of the same content key, not the same structure key
    run_folder(tmp_path, "a1", [screen(1, "kother", ["Home!"], "screenshots/1.png", content="cmain")])
    (root / "runs.jsonl").write_text(
        "".join(
            json.dumps({"run": r, "dir": r, "condition": c, "order": i}) + "\n"
            for i, (r, c) in enumerate([("b1", "baseline"), ("b2", "baseline"), ("a1", "R-ads")], 1)
        )
    )
    report = {
        "features": [{"id": "F-e1", "name": "General Onboarding", "outcome": "The user lands on the main screen."}],
        "runs": [
            run_record("b1", "unmet", 300),
            run_record("b2", "met", 320),
            run_record("a1", "met", 250, verified="verified"),
        ],
        "comparisons": [
            comparison("R-ads", ["b1", "b2"], ["a1"], divergence=[{"run": "a1", "divergences": 1}]),
            comparison("D-android_id", ["b1", "b2"], [], outcome="undecided"),
        ],
    }
    (root / "report.json").write_text(json.dumps(report))
    return root


def test_a_comparison_is_shown_in_words_with_its_runs_and_screens(tmp_path):
    cards = review_experiments.index(workspace(tmp_path))
    card = cards["e1:P-e1-1:R-ads"]
    assert card["feature"] == {
        "launch": False,
        "name": "General Onboarding",
        "outcome": "The user lands on the main screen.",
    }
    assert card["purpose"] == {
        "text": "set up the app for its first use",
        "outcome": "ready-to-use app",
        "requirements": ["complete the onboarding"],
    }
    assert card["change"]["text"] == "every request to ads.example blocked"
    assert card["outcome"] == "preserves" and card["departed"] == 1
    (check,) = card["checks"]
    assert check["kind"] == "screen_reached" and "action 3" in check["text"]
    assert check["screen"]["texts"] == ["Home", "Search"] and check["screen"]["screenshot"].startswith("screenshots/")
    assert [r["decision"] for r in card["baseline"]["runs"]] == ["unmet", "met"]
    assert card["baseline"]["runs"][1] == {"decision": "met", "messages": 320, "connections": 10, "blocked": 2}
    assert card["alternative"]["runs"] == [
        {"decision": "met", "messages": 250, "connections": 10, "blocked": 2, "verified": "verified"}
    ]
    # the first run that met the check, at the screen it met it at (by the recording's content key for a1)
    assert card["baseline"]["met_at"]["texts"] == ["Home"]
    assert card["alternative"]["met_at"]["texts"] == ["Home!"]
    assert len(review_experiments.shots(card)) == 3
    shown = review_experiments.view(card)
    assert "_entry" not in json.dumps(shown)
    # a side without runs shows none
    assert cards["e1:P-e1-1:D-android_id"]["alternative"] == {"runs": [], "met_at": None}


def test_a_screen_without_its_own_screenshot_is_shown_with_its_visits_first(tmp_path):
    workspace(tmp_path)
    folder = tmp_path / "runs" / "b1"
    screens = review_experiments._screens(folder)
    # seq 3 changed within the visit that began at seq 2: Loki took no screenshot of it
    assert review_experiments._shot(folder, screens, screens[2])[0] == "screenshots/2.png"
    assert review_experiments._shot(folder, screens, screens[0]) is None


def test_changes_are_put_in_words():
    class Alt:
        def __init__(self, intervention, removal=True):
            self.intervention, self.removal, self.component, self.id = intervention, removal, "x", "X-1"

    assert review_experiments.change_text(Alt({"block_hosts": ["a.com", "b.com"]}), None) == (
        "every request to a.com, b.com blocked"
    )
    assert review_experiments.change_text(Alt({"sources": {"android_id": "replace:0000"}}), None) == (
        "the android id the app reads replaced by 0000"
    )
    assert review_experiments.change_text(Alt({"sources": {"location": "round:0"}}), None) == (
        "the location the app reads rounded to 0 decimals"
    )
    assert review_experiments.change_text(Alt({}), "ads sdk") == "ads sdk removed"


def test_the_other_checks_are_put_in_words():
    first = review_experiments._check({"first_screen_ready": {}}, [])
    assert first["kind"] == "first_screen_ready" and "cold start" in first["text"]
    text = review_experiments._check({"text_shown": {"any": ["Berlin"], "after_action": 4}}, [])
    assert text["texts"] == ["Berlin"] and "“Berlin”" in text["text"]


def test_where_a_check_was_met():
    screens = [screen(1, "s", [], package="android"), screen(2, "k1", ["Hello Berlin"]), screen(3, "k2", ["x"])]
    assert review_experiments.met_at(screens, PKG, {"first_screen_ready": {}}, {})["seq"] == 2
    assert review_experiments.met_at(screens, PKG, {"text_shown": {"any": ["Berlin"]}}, {})["seq"] == 2
    assert review_experiments.met_at(screens, PKG, {"screen_reached": {"exact_key": "k2"}}, {})["seq"] == 3
    assert review_experiments.met_at(screens, PKG, {"screen_reached": {"exact_key": "k9"}}, {}) is None
    # the launcher first: no screen of the app was the first
    assert (
        review_experiments.met_at([screen(1, "l", [], package="launcher")], PKG, {"first_screen_ready": {}}, {}) is None
    )


def test_an_evidence_item_names_its_comparison():
    item = {"kind": "run", "channel": "ex:e1", "premises": ["e1:P-e1-1:R-ads"]}
    assert review_experiments.comparison_of(item) == "e1:P-e1-1:R-ads"
    assert review_experiments.comparison_of({"kind": "doc", "channel": "ex:e1"}) is None


def test_a_workspace_without_a_case_report_has_no_experiments(tmp_path):
    assert review_experiments.index(tmp_path) == {}
