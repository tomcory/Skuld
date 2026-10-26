"""Tests of the rule tier: O–D correspondence, transparency statuses, concern (i), pass-through, the report."""

import pytest
from ratatoskr.frames import Frame
from ratatoskr.registry import Registry
from ratatoskr.schemas import validate
from ratatoskr.vocabularies import Vocabulary

from skuld import assessment, concerns, correspondence, frame, inputs, relations, transparency
from skuld.assess import REPORT, assess
from tests.test_assess import ROOT, claim, declared, o_report, workspace

REGISTRY = Registry(
    {
        "entities": [
            {"id": "adco", "name": "AdCo", "domains": ["adco.example"], "types": ["advertising", "analytics"]},
            {"id": "adco-measure", "name": "AdCo Measure", "parent": "adco", "domains": ["m.adco.example"]},
        ]
    }
)
DATA, TYPES = Vocabulary.load("asgard-data"), Vocabulary.load("recipient-types")


def d_report(claims, channels=None, version="1.0", documents=None):
    channels = channels or [
        {"channel": "policy", "document": "p", "status": "analysed", "accessible": True, "annotations": [], "tilt": {}},
        {
            "channel": "data_safety",
            "document": "ds",
            "status": "analysed",
            "accessible": True,
            "annotations": [],
            "tilt": {},
        },
    ]
    return {
        "collection": {"package": "com.example.app", "store_version": version},
        "channels": channels,
        "claims": claims,
    }


def d_claim(ctype, data, polarity="+", channel="policy", value=None, kind="practice", **qualifiers):
    c = declared(ctype, polarity=polarity, value=value, kind=kind)
    c.update(channel=channel, data=data, definitions="google-play-data-safety" if channel == "data_safety" else None)
    c["qualifiers"].update(qualifiers)
    return c


def relate(tmp_path, o_claims, d_claims, d_version="1.0"):
    a = workspace(tmp_path, [o_report(o_claims)], d_report(d_claims, version=d_version))
    built = assessment.build(a, REGISTRY)
    d = a.declaration.load()
    return built, correspondence.relate(built, d, [], REGISTRY, DATA, TYPES)


def by_aspect(relations_, aspect):
    return [r for r in relations_ if r.aspect == aspect and r.subject and r.subject.startswith("P-")]


def test_an_observation_corresponds_to_a_declaration_above_it(tmp_path):
    _, rel = relate(
        tmp_path,
        [claim("c1", "device-or-other-ids.advertising-id", "adco", "AdSDK")],
        [
            d_claim("declares_collection", "device-or-other-ids"),
            d_claim("declares_recipient", "data", value={"name": "analytics tools", "category": "analytics"}),
        ],
    )
    (data,) = by_aspect(rel, "data")
    (recipient,) = by_aspect(rel, "recipient")
    assert (data.outcome, data.alignment) == ("corresponds_hierarchically", "narrower")
    assert (recipient.outcome, recipient.alignment) == ("corresponds_hierarchically", "by category (analytics)")


def test_a_named_entity_corresponds_exactly_and_a_root_category_only_partially(tmp_path):
    named = d_claim(
        "declares_recipient", "personal-info.name", value={"name": "AdCo", "category": "advertising", "entity": "adco"}
    )
    _, rel = relate(tmp_path, [claim("c1", "personal-info.name", "adco")], [named])
    assert by_aspect(rel, "recipient")[0].outcome == "corresponds_exactly"
    vague = d_claim("declares_recipient", "data", value={"name": "service providers", "category": "recipient"})
    _, rel = relate(tmp_path, [claim("c1", "personal-info.name", "adco")], [vague])
    assert (by_aspect(rel, "recipient")[0].outcome, by_aspect(rel, "recipient")[0].alignment) == (
        "corresponds_partially",
        "by the root category only",
    )


def test_a_denial_contradicts_only_under_what_o_cannot_observe(tmp_path):
    _, rel = relate(
        tmp_path,
        [claim("c1", "personal-info.name", "adco")],
        [
            d_claim("declares_recipient", "data", "-", channel="data_safety", value={"role": "ThirdParty"}),
            d_claim(
                "declares_recipient",
                "data",
                "-",
                value={"name": "third parties", "role": "ThirdParty"},
                condition={"type": "user_action", "text": "registering"},
            ),
            d_claim("declares_recipient", "data", "-", value={"role": "ThirdParty", "sale": True}),  # O sees no sale
            d_claim("declares_recipient", "location", "-", channel="data_safety", value={"role": "ThirdParty"}),
        ],
    )
    contradictions = [r for r in rel if r.outcome == "contradicts"]
    assert len(contradictions) == 2  # neither the sale nor the denial of another node
    assert contradictions[0].condition.startswith("the recipient is not a service provider")
    assert "third party" in contradictions[1].condition and "registering" in contradictions[1].condition


def test_without_a_declaration_and_without_an_observation(tmp_path):
    built, rel = relate(
        tmp_path,
        [claim("c1", "location.precise-location", "adco")],
        [d_claim("declares_collection", "personal-info.email-address")],
    )
    assert by_aspect(rel, "data")[0].outcome == "observed_without_declaration"
    declared_only = [r for r in rel if r.outcome == "declared_without_observation"]
    assert [r.subject for r in declared_only] == ["D-0"]


def test_o_and_d_of_different_versions_are_not_comparable(tmp_path):
    _, rel = relate(
        tmp_path, [claim("c1", "personal-info.name", "adco")], [d_claim("declares_collection", "data")], "2.0"
    )
    assert {r.outcome for r in rel} == {"not_comparable"}


def test_transparency_reads_ds_annotations_on_accessible_documents_only(tmp_path):
    channels = [
        {
            "channel": "policy",
            "document": "p",
            "status": "analysed",
            "accessible": True,
            "tilt": {},
            "annotations": [{"requirement": "controller_name", "path": "$.controller.name", "polarity": "+"}],
        },
        {
            "channel": "in_app",
            "document": "n",
            "status": "analysed",
            "accessible": False,
            "tilt": {},
            "annotations": [{"requirement": "right_to_restrict", "path": "$.rightToRestriction", "polarity": "+"}],
        },
    ]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d_report([], channels))
    built = assessment.build(a, REGISTRY)
    f = Frame.load("gdpr-art5")
    decided = frame.decisions(f, frame.evidence(built, [r.load() for r in a.observations], a.declaration.load()))
    by = {s.requirement: s for s in transparency.statuses(f, built, decided, a.declaration.sha256)}
    assert (
        by["controller_name"].status == "addressed"
        and by["controller_name"].addressed_by[0]["claim"] == "/channels/0/annotations/0"
    )
    assert by["right_to_restrict"].status == "missing"  # only an inaccessible document says it
    assert (by["dpo_contact"].status, by["dpo_contact"].conditions) == ("missing_if", ["dpo_designated"])
    stated, covered = concerns.information_not_given(f, list(by.values()), {})
    k = {c.requirement: c for c in stated}
    assert k["right_to_restrict"].status == "supported" and not k["right_to_restrict"].condition
    assert k["dpo_contact"].condition == ["dpo_designated"]
    assert ("controller_name", "collection", True) in {(c.requirement, c.subject, c.applies) for c in covered}
    assert not any(c.requirement == "controller_name" for c in stated)
    # D's silence: the policy's analysis has no established recall, so "not found" is not certain
    assert by["right_to_restrict"].silent == ["policy"]
    assert k["right_to_restrict"].uncertainty["s"] == "moderate"
    assert any("no established recall" in x for x in k["right_to_restrict"].silence)
    stated, _ = concerns.information_not_given(f, list(by.values()), {}, recall={"policy"})
    assert {c.requirement: c for c in stated}["right_to_restrict"].uncertainty["s"] == "low"


def test_every_claim_is_passed_on_with_its_relations_or_a_reason(tmp_path):
    o = o_report(
        [claim("c1", "personal-info.name", "adco"), claim("c2", "personal-info.name", "adco", status="not_established")]
    )
    a = workspace(
        tmp_path,
        [o],
        d_report(
            [
                d_claim("declares_collection", "personal-info.name"),
                d_claim("declares_purpose", "data", kind="justification"),
            ]
        ),
    )
    built = assessment.build(a, REGISTRY)
    rel = correspondence.relate(built, a.declaration.load(), [], REGISTRY, DATA, TYPES)
    out = {e["claim"]["claim"]: e for e in relations.passed_on(built, a.observations, a.declaration, rel)}
    assert set(out) == {"c1", "c2", "/claims/0", "/claims/1"}
    assert out["c1"]["relations"] and out["/claims/0"]["relations"]
    assert out["c2"]["not_related"] == "not_assessable" and "not a practice" in out["c2"]["reason"]
    assert out["/claims/1"]["reason"] == "E's expectation stage has no claims"


FIXTURES = [
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4",
    "air.nn.mobile.app.main@3.8.96",
    "de.wetteronline.wetterapp@2026.20",
]


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixtures_reports_are_valid_and_pilates_reproduces_the_worked_example(name):
    root = ROOT / "cases" / name
    if not (root / "assessment.yaml").is_file():
        pytest.skip("the case study's workspaces are not in this checkout")
    kept = {n: (root / n).read_text() for n in ("subjects.json", REPORT, "assessment.md") if (root / n).is_file()}
    try:
        report = assess(root)
    finally:
        for n, text in kept.items():
            (root / n).write_text(text)
    validate("expectation_assessment", report)
    assert report["report"]["cost"]["model_calls"] == 0
    from skuld.assess import build
    from skuld.provenance import check_assessment

    rebuilt, members = build(root, write=False)
    assert check_assessment(inputs.load_assessment(root), report, rebuilt, members) == []
    # a proposition of class E3 or E4 is never supported or refuted (framework, observability)
    assert not [
        c["id"]
        for c in report["concerns"]
        if c["status"] in ("supported", "refuted") and c["observability"] in ("E3", "E4")
    ]
    claims = {c["id"]: c for c in report["claims"]}
    # the D analysis read is named, since the transparency concerns' calibration holds for it alone
    if inputs.load_assessment(root).declaration is not None:
        assert [c for c in report["report"]["components"] if c["role"] == "declaration_analysis"]
    # a claim has a strength only if it is supported or refuted, and it is doc or run: own knowledge decides nothing
    assert all(
        ("strength" in c) == (c["status"] in ("supported", "refuted")) and c.get("strength", "doc") in ("doc", "run")
        for c in claims.values()
    )
    if name.startswith("de.wetteronline") and (root / "expectation").is_dir():
        # one decimal of the location preserves the forecast: a demonstrated minimisation concern, still a judgement
        # of what is necessary; its O–E relation reads the run
        located = {p["id"] for p in report["subjects"]["practices"] if p["data"] == "location.coordinates"}
        demonstrated = [
            c
            for c in report["concerns"]
            if c["step"] == "less_invasive_alternative"
            and c["subject"] in located
            and c["status"] == "supported"
            and "forecast:G1 demonstrated" in c["reason"]
        ]
        assert demonstrated and all(c["uncertainty"]["n"] == "moderate" for c in demonstrated)
        relations = {r["id"]: r for r in report["relations"]}
        for c in demonstrated:
            shown = [relations[i] for i in c["relations"] if relations[i]["outcome"].startswith("alternative")]
            assert [r["outcome"] for r in shown] == ["alternative_demonstrated"]
            read = [claims[t["claim"]] for r in shown for t in r["to"]]
            assert any((x["level"], x.get("strength")) == ("demonstrated", "run") for x in read)
    if not name.startswith("pilates"):
        return
    practices = {p["id"]: p for p in report["subjects"]["practices"]}
    outcomes = {
        (practices[r["subject"]]["data"], practices[r["subject"]]["recipient"], r.get("aspect"), r["outcome"])
        for r in report["relations"]
        if r.get("subject") in practices
    }
    # the observed advertising identifier lies below the declared device or other identifiers
    assert ("device-or-other-ids.advertising-id", None, "data", "corresponds_hierarchically") in outcomes
    # AppsFlyer corresponds by category to the policy's tools
    assert ("data", "appsflyer", "recipient", "corresponds_hierarchically") in outcomes
    texts = [o["text"] for o in report["open"]]
    assert any(t.startswith("the recipient is not a service provider") for t in texts)  # Data safety's sharing
    assert {"a data protection officer is designated", "automated decision-making takes place"} <= set(texts)
    stated = {c["requirement"]: c for c in report["concerns"] if c["tier"] == "rule"}
    assert stated["right_to_restrict"]["status"] == "supported" and "condition" not in stated["right_to_restrict"]
    # the dry run's comparisons decide where reasoning is silent: the identifier is not needed for the user's launch
    launch = [
        c
        for c in report["claims"]
        if c.get("case")
        and practices[c["subject"]]["data"] == "device-or-other-ids.advertising-id"
        and c["purpose"]["id"] == "P-L1"
    ]
    assert all(c["basis"] == [] for c in launch)
    assert {(c["type"], c.get("relationship"), c["status"], c.get("strength")) for c in launch} >= {
        ("dependency", "not_dependent", "supported", "run"),
        ("alternative", None, "supported", "run"),
    }
    if not (root / "assessment").is_dir():
        return
    # the reasoning tier: "provide and improve the Service" not specific; a less invasive identifier for advertising
    vague = [c for c in report["concerns"] if c["step"] == "not_specific" and "provide and improve" in c["reason"]]
    assert vague and vague[0]["status"] == "supported"
    assert any(
        c["step"] == "less_invasive_alternative"
        and c["status"] == "supported"
        and practices[c["subject"]]["data"] == "device-or-other-ids.advertising-id"
        for c in report["concerns"]
    )
