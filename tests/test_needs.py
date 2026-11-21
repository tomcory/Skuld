"""Requirements shared with experiments (P10 fix 4): the generator shows the reasoning's needs and a case's requirement
names the need it corresponds to; an oracle that reaches the requirement confirms or refutes the need."""

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from ratatoskr.vocabularies import Vocabulary

from skuld import catalogue as cat
from skuld import combine, inputs, propose, select
from skuld.experiments import CASE_REPORT, analyse, premises
from tests import workspace as ws
from tests.test_propose import ANSWER, FORECAST, LAUNCH, RUN, FakeProvider, catalogue_with, exploration, report

CLAIM = "claim:P-1:4"
NEED = f"{CLAIM}:N1"
PRACTICE = SimpleNamespace(
    id="P-1", data="device-or-other-ids.advertising-id", recipient="tracker", claim_type="transmits"
)


# -- experiments: the needs a case's comparison tests --------------------------------------------------------------


def premises_of(tmp_path: Path, plan=None, need: str | None = NEED) -> list[dict]:
    """The experimental premises of the synthetic workspace, whose P1 requirement R1 (reached by its oracle) names
    `need`."""
    case = json.loads(json.dumps(ws.CASE))
    if need:
        case["purposes"][0]["requirements"][0]["need"] = need
    root = tmp_path / "ws"
    original = ws.CASE
    ws.CASE = case
    try:
        ws.build(root, plan)
    finally:
        ws.CASE = original
    workspace = inputs.load(root)
    (root / CASE_REPORT).write_text(json.dumps(analyse(workspace, make_observations=False)))
    return premises(workspace, root, [PRACTICE], lambda key, fields: f"item:{key}")


def alternative(*need_ids: str, status="supported", change_key="remove", component="P-1.data") -> dict:
    """A combined Alternative claim of the reasoning's typed form."""
    return {
        "id": CLAIM,
        "type": "alternative",
        "tier": "reasoning",
        "stage": "assessment",
        "channels": ["reasoning:s1"],
        "subject": "P-1",
        "component": component,
        "change": {"kind": "remove"},
        "change_key": change_key,
        "needs": [{"id": i, "requirement": "start the app", "cites": ["S1"], "grounded": True} for i in need_ids],
        "level": "technically_supported" if status == "supported" else "plausible",
        "basis": ["claim:P-1:1"],
        "purpose": {"node": "ServiceProvision", "beneficiary": "user"},
        "status": status,
        "supporting": ["item:9"] if status == "supported" else [],
        "challenging": [],
        "strength": "doc",
        "uncertainty": {"level": "moderate", "reasons": [{"reason": "covers_by_model"}]},
        "sufficiency": {"sufficient": status == "supported"},
    }


def test_a_case_requirement_that_names_a_need_is_tested_by_the_alternatives_comparison(tmp_path):
    found = premises_of(tmp_path)
    removal = next(x for x in found if x.get("alternative") == "start:A1" and x["component"] == "P-1.data")
    assert removal["imposes"] == "remove"
    (test,) = removal["need_tests"]
    assert (test["need"], test["requirement"], test["case"], test["outcome"]) == (NEED, "R1", "start", "met")
    assert test["runs"] == ["run-02", "run-05", "run-08"]
    # a dependency claim tests no need, and no combined claim carries the tests
    assert all("need_tests" not in x for x in found if x["type"] == "dependency")
    assert all(
        "need_tests" not in c
        for c in combine.experimental([], found, Vocabulary.load("dpv-purposes"), combine.Numbers())
    )


def test_a_need_confirmed_by_a_reached_requirement_demonstrates_the_alternative(tmp_path):
    (claim,) = combine.tested_needs([alternative(NEED)], premises_of(tmp_path))
    assert claim["needs"][0]["tested"] == {"case": "start", "outcome": "met", "runs": ["run-02", "run-05", "run-08"]}
    assert (claim["status"], claim["strength"], claim["level"]) == ("supported", "run", "demonstrated")
    assert "item:9" in claim["supporting"] and "item:start:P1:A1" in claim["supporting"]
    assert "ex:start" in claim["channels"] and combine.tested_cases(claim) == ["start"]


def test_a_need_refuted_by_a_break_refutes_the_alternative_at_strength_run(tmp_path):
    plan = [(c, {"done": c != "A1"}) for _ in range(3) for c in ("baseline", "A1", "A2")]
    (claim,) = combine.tested_needs([alternative(NEED)], premises_of(tmp_path, plan))
    assert claim["needs"][0]["tested"]["outcome"] == "not_met"
    assert (claim["status"], claim["strength"]) == ("refuted", "run")
    assert claim["supporting"] == [] and claim["challenging"] == ["item:start:P1:A1"]
    assert NEED in claim["reason"] and "(the reasoning: supported)" in claim["reason"]


def test_an_unreached_need_is_not_tested_and_the_status_stands(tmp_path):
    found = premises_of(tmp_path)
    other = f"{CLAIM}:N2"  # no requirement names it
    (claim,) = combine.tested_needs([alternative(NEED, other)], found)
    assert claim["needs"][0]["tested"]["outcome"] == "met" and "tested" not in claim["needs"][1]
    assert (claim["status"], claim["strength"], claim["level"]) == ("supported", "doc", "technically_supported")
    # another change than the case's alternative imposes, or another component: nothing tested
    for unrelated in (alternative(NEED, change_key="replace:x"), alternative(NEED, component="P-2.data")):
        assert combine.tested_needs([unrelated], found) == [unrelated]
    # a case whose requirements name no need tests none
    assert all("need_tests" not in x for x in premises_of(tmp_path / "none", need=None))


# -- select: the needs a candidate carries ---------------------------------------------------------------------------


def test_a_candidate_carries_the_needs_of_typed_alternatives_whose_change_an_experiment_can_impose():
    claims = [
        alternative(NEED),
        {**alternative("claim:P-1:5:N1", change_key="on_device"), "id": "claim:P-1:5"},
        {**alternative("claim:P-1:6:N1"), "id": "claim:P-1:6", "basis": ["claim:P-1:2"]},
    ]
    assert select.needs_of({"claims": claims}, "claim:P-1:1") == [
        {
            "claim": CLAIM,
            "component": "P-1.data",
            "change_key": "remove",
            "alternative": "",
            "needs": [{"id": NEED, "requirement": "start the app"}],
        }
    ]


# -- propose: the needs shown, named and kept -------------------------------------------------------------------------

LOCATION_NEED = "claim:P-1:4:N1"
SELECTION = {
    "created": "2026-11-21T10:00:00+00:00",
    "entries": [
        {
            "id": "selection:P-1:1",
            "kind": select.CHOICE,
            "practice": "P-1",
            "purpose": "claim:P-1:1",
            "node": "ServiceProvision",
            "beneficiary": "user",
            "episodes": ["1"],
            "fields": {"id": "P-1", "claim_type": "transmits", "data": "location.coordinates", "recipient": "tracker"},
            "components": [{"component": "P-1.recipient", "dimension": "R", "alternatives": ["R-tracker"]}],
            "needs": [
                {
                    "claim": "claim:P-1:4",
                    "component": "P-1.recipient",
                    "change_key": "remove",
                    "alternative": "send nothing to the tracker",
                    "needs": [{"id": LOCATION_NEED, "requirement": "know the area the user is in"}],
                }
            ],
        }
    ],
}


def forecast(*named: tuple[int, int, str]) -> dict:
    needs = [{"purpose": p, "requirement": r, "need": n} for p, r, n in named]
    return {"features": [{**ANSWER["features"][0], "needs": needs}]}


class Prompted(FakeProvider):
    def __init__(self, answer):
        super().__init__(answer)
        self.prompts = []

    async def complete(self, model, prompt, **kwargs):
        self.prompts.append(prompt.messages[0]["content"])
        return await super().complete(model, prompt, **kwargs)


def workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    exp = exploration(tmp_path / "runs" / RUN)
    root = tmp_path / "ws"
    (root / "observation" / RUN).mkdir(parents=True)
    (root / "observation" / RUN / "observation_report.json").write_text(json.dumps(report()))
    return exp, root, catalogue_with(tmp_path / "catalogue", FORECAST, LAUNCH)


def test_propose_shows_the_needs_and_refuses_one_it_did_not_show(tmp_path):
    exp, root, catalogue = workspace(tmp_path)
    flow = propose.read(exp).flows[0]
    purposes = Vocabulary.load("dpv-purposes")
    loaded = cat.load(catalogue)

    def refused(*named):
        return propose.feature_problems(forecast(*named)["features"][0], flow, loaded, purposes, (), {LOCATION_NEED})

    assert refused((1, 1, LOCATION_NEED)) == []
    assert refused((1, 1, "claim:P-1:9:N1")) == ["need 'claim:P-1:9:N1' is not one of the needs shown"]
    assert "has no requirement 3" in refused((1, 3, LOCATION_NEED))[0]
    assert "has no purpose 2" in refused((2, 1, LOCATION_NEED))[0]
    assert "names a need already" in refused((1, 1, LOCATION_NEED), (1, 1, LOCATION_NEED))[0]

    provider = Prompted(forecast((1, 1, "claim:P-1:9:N1")))
    summary = propose.propose_model(exp, root, catalogue, "fake", ["verdandi"], provider=provider, selection=SELECTION)
    assert provider.calls == 2 and summary["cases"] == []  # refused twice
    assert f"  - {LOCATION_NEED}: know the area the user is in" in provider.prompts[0]
    assert '"requirements": {"1": "determine an area relevant to the user"' in provider.prompts[0]
    # without a selection's needs the prompt shows none
    assert "# What the purposes need" not in propose.prompt_template().format(
        catalogue="", nodes="", needs=propose.render_needs([]), flow=""
    )


def test_the_case_names_the_need_and_the_merge_keeps_every_proposers_needs(tmp_path):
    exp, root, catalogue = workspace(tmp_path)
    first = forecast((1, 1, LOCATION_NEED))
    second = forecast((1, 1, LOCATION_NEED), (1, 2, LOCATION_NEED))
    propose.propose_model(exp, root, catalogue, "a", ["verdandi"], provider=FakeProvider(first), selection=SELECTION)
    propose.propose_model(exp, root, catalogue, "b", ["verdandi"], provider=FakeProvider(second), selection=SELECTION)
    propose.merge(exp, root, catalogue, ["verdandi"])
    case = yaml.safe_load((root / "cases" / "e1.yaml").read_text(encoding="utf-8"))
    assert [r.get("need") for r in case["purposes"][0]["requirements"]] == [LOCATION_NEED, LOCATION_NEED]
    loaded = inputs.load(root)
    inputs.check_frozen(loaded)  # the frozen inputs carry it
    assert loaded.cases[0].purposes[0].requirements[0]["need"] == LOCATION_NEED
