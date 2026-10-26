"""The experimental channel's status rule row by row: the readings of a comparison, and that no comparison is read
as both supporting and refuting a claim."""

import ast
import itertools
from pathlib import Path

import pytest

from skuld import rules
from skuld.comparison import Comparison, outcome
from skuld.inputs import Alternative, Case, Component, Feature, Purpose
from skuld.oracles import Decision, worse

PURPOSE = Purpose("p", {}, "ServiceProvision", "exact", "feature", "sufficient", "functional", (), "O@1")
COMPONENT = Component("e", "D", node="device-or-other-ids.advertising-id")


def alt(aid: str, removal: bool = False) -> Alternative:
    return Alternative(aid, "e", removal, ({"component": "e", "value": None},), {}, aid)


def comparison(aid: str, result: str, worse_: dict | None = None) -> Comparison:
    return Comparison(aid, "c", "p", aid, ["b1"], ["a1"], result, worse=worse_ or {})


def dep(result: str, worse_: dict | None = None) -> tuple[str | None, str]:
    made = rules.dependency(PURPOSE, COMPONENT, comparison("R", result, worse_), "search_space_not_run")
    return made.relationship, made.status


def test_a_preserving_removal_with_no_worse_measurement_is_not_dependent():
    assert dep("preserves", {"m": "none"}) == ("not_dependent", "supported")


def test_a_preserving_removal_with_a_measurement_worse_in_every_run_is_quality_dependent():
    assert dep("preserves", {"m": "all", "n": "none"}) == ("quality_dependent", "supported")


def test_a_preserving_removal_with_mixed_measurements_refutes_essential_only():
    assert dep("preserves", {"m": "some"}) == ("essential", "refuted")


def test_a_breaking_removal_is_essential():
    assert dep("breaks") == ("essential", "supported")


def test_an_undecided_comparison_reads_no_value():
    assert dep("undecided") == (None, "not_established")


def test_one_comparison_never_supports_and_refutes_a_claim():
    for result, w in itertools.product(("preserves", "breaks", "undecided"), ("none", "some", "all")):
        made = rules.dependency(PURPOSE, COMPONENT, comparison("R", result, {"m": w}), "x")
        assert not (made.supporting and made.challenging)
        a = rules.alternative(PURPOSE, alt("A"), comparison("A", result, {"m": w}), "x")
        assert not (a.supporting and a.challenging)


def test_an_alternative_is_demonstrated_by_a_preserving_comparison_and_refuted_by_a_breaking_one():
    assert rules.alternative(PURPOSE, alt("A"), comparison("A", "preserves"), "x").status == "supported"
    assert rules.alternative(PURPOSE, alt("A"), comparison("A", "breaks"), "x").status == "refuted"
    missing = rules.alternative(PURPOSE, alt("A"), None, "intervention_not_verified")
    assert (missing.status, missing.why) == ("not_established", "intervention_not_verified")


@pytest.mark.parametrize(
    ("purpose", "present", "expected"),
    [
        (PURPOSE, False, "not_applicable"),
        (Purpose("p", {}, "n", "?", "feature", "vague", "functional", (), "O@1"), True, "not_assessable"),
        (Purpose("p", {}, "n", "?", "technical", "sufficient", "ancillary", (), None), True, "not_assessable"),
    ],
)
def test_preconditions(purpose, present, expected):
    case = Case("c", Feature("F", "F", "e", None, 0, "o"), (purpose,), (COMPONENT,), (alt("R", True),), Path("."))
    made = rules.claims(case, {"e": present}, {}, {})
    assert {c.status for c in made} == {expected}
    assert [c.type for c in made] == ["dependency", "alternative"]


def test_a_component_without_a_removal_has_no_dependency_claim():
    case = Case("c", Feature("F", "F", "e", None, 0, "o"), (PURPOSE,), (COMPONENT,), (alt("A"),), Path("."))
    made = rules.claims(case, {"e": True}, {("p", "A"): comparison("A", "preserves")}, {})
    assert [(c.type, c.status) for c in made] == [("alternative", "supported")]


def test_outcomes():
    met, unmet = Decision("met"), Decision("unmet")
    assert outcome([met], [met]) == "preserves"
    assert outcome([met], [unmet]) == "breaks"
    assert outcome([met], [met, unmet]) == "undecided"
    assert outcome([unmet], [unmet]) == "undecided"


def test_worse_needs_more_than_the_tolerance_against_every_baseline_run():
    assert worse(5, [8, 9], "higher", 2)
    assert not worse(7, [8, 9], "higher", 2)
    assert not worse(5, [8, 5], "higher", 0)
    assert worse(12, [8, 9], "lower", 2)


def test_the_modules_that_write_statuses_call_no_model():
    for module in (
        "rules",
        "combine",
        "common",
        "experiments",
        "concerns",
        "comparison",
        "verify",
        "oracles",
        "context",
        "corpus",
        "transparency",
        "frame",
        "correspondence",
        "relations",
        "uncertainty",
        "select",
        "space",
    ):
        tree = ast.parse((Path(__file__).parents[1] / "skuld" / f"{module}.py").read_text())
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(name.startswith("ratatoskr.llm") for name in imported), module


def test_an_oracle_can_ask_for_a_text_on_a_screen_after_an_action():
    from types import SimpleNamespace

    from skuld.oracles import _text_shown

    run = SimpleNamespace(
        package="p",
        events=[
            {"type": "screen", "package": "p", "label": "initial", "texts": ["Welcome"]},
            {"type": "screen", "package": "p", "label": "post_action", "texts": ["Zürich", "18°"]},
            {"type": "action"},
            {"type": "screen", "package": "q", "label": "post_action", "texts": ["Bern"]},
        ],
    )
    assert _text_shown(run, ["Zürich"]) and _text_shown(run, ["Zürich"], after_action=1)
    assert not _text_shown(run, ["Zürich"], after_action=2)
    assert not _text_shown(run, ["Bern"])  # another app's screen
    assert _text_shown(run, ["18"])  # within a text


def test_granularity_is_ordered_by_precision_not_only_by_the_tree():
    from ratatoskr.vocabularies import Vocabulary

    from skuld.configuration import coarser

    v = Vocabulary.load("asgard-data")
    assert coarser("location.precise-location", "location.coordinates", v)  # above it
    assert coarser("location.approximate-location", "location.coordinates", v)  # stated coarser than precise
    assert coarser("location.city", "location.coordinates", v)  # below approximate, so coarser as well
    assert not coarser("location.coordinates", "location.approximate-location", v)
    assert not coarser("location.precise-location", "location.approximate-location", v)
