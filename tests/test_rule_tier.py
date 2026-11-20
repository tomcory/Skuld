"""Tests of the rule tier: O–D correspondence, transparency statuses, concern (i), pass-through, the report."""

import json

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
    for n, c in enumerate(claims):
        c.setdefault("id", f"{c['channels'][0]}:/dataDisclosed/{n}")
    return {
        "collection": {"package": "com.example.app", "store_version": version},
        "channels": channels,
        "claims": claims,
    }


def d_claim(ctype, data, polarity="+", channel="policy", value=None, kind="practice", **qualifiers):
    c = declared(ctype, polarity=polarity, value=value, kind=kind)
    c.update(
        channels=[channel],
        datum={"node": data},
        definitions="google-play-data-safety" if channel == "data_safety" else None,
    )
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


def test_an_o_d_relation_takes_the_uncertainty_of_its_claims_and_ds_leniently(tmp_path):
    o = claim("c1", "personal-info.name", "adco")
    o["uncertainty"] = {"f": "low", "t": "moderate", "s": "low", "n": "not_applicable"}
    d = d_claim("declares_collection", "personal-info.name")
    d["uncertainty"] = {"f": "low", "t": "not_applicable", "s": "high", "n": "not_applicable"}  # a model's placement
    built, rel = relate(tmp_path, [o], [d])
    data = [r for r in by_aspect(rel, "data") if r.outcome == correspondence.EXACTLY]
    # the highest of both per factor, D's semantic uncertainty read as at most moderate until D's model is measured
    assert data and data[0].uncertainty == {"t": "moderate", "s": "moderate", "n": "not_applicable"}


def test_a_mismatch_that_reads_ds_silence_holds_only_under_its_unread_channels(tmp_path):
    o = [claim("c1", "location.coordinates", "adco"), claim("c2", "personal-info.name", "adco")]
    d = [d_claim("declares_collection", "location.approximate-location", channel="data_safety")]

    def relations_with(policy_status):
        channels = d_report([])["channels"]
        channels[0]["status"] = policy_status
        (tmp_path / policy_status).mkdir()
        a = workspace(tmp_path / policy_status, [o_report(o)], d_report(d, channels=channels))
        built = assessment.build(a, REGISTRY)
        return built, correspondence.relate(built, a.declaration.load(), [], REGISTRY, DATA, TYPES)

    built, rel = relations_with("not_analysable")
    related = [r for r in by_aspect(rel, "data") if r.partial == "related"]
    observed_only = [r for r in by_aspect(rel, "data") if r.outcome == correspondence.OBSERVED_ONLY]
    assert related and observed_only
    for r in related + observed_only:
        assert (r.condition, r.condition_kind) == ("analysed:policy", "source")
    open_ = relations.open_conditions(built, rel, [], None, [], [], [])
    (source,) = [x for x in open_ if x["kind"] == "source"]
    assert source["text"] == "whether the policy, which no stage analysed, declares the practice"

    _, rel = relations_with("analysed")
    assert all(r.condition is None for r in by_aspect(rel, "data"))


def test_a_silence_is_closed_only_on_a_channel_exhaustive_for_the_predicate():
    assert assessment.exhaustive("data_safety", "collection") and assessment.exhaustive("data_safety", "sharing")
    assert not assessment.exhaustive("policy", "collection")
    assert not assessment.exhaustive("data_safety", "information:right_to_restrict")


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


def test_a_denial_contradicts_a_transmission_only(tmp_path):
    """Google Play counts only data that leaves the device as collected: an access on the device contradicts no
    denial (plan/archive/POST_PAPER_FIXES 3, Peacock's "Camera" denied and contradicted by every on-device access)."""
    built, rel = relate(
        tmp_path,
        [claim("c1", "photos-videos.photos", ctype="accesses"), claim("c2", "personal-info.name", "adco")],
        [d_claim("declares_collection", "photos-videos", "-"), d_claim("declares_collection", "personal-info", "-")],
    )
    practices = {p.id: p for p in built.practices}
    contradicted = [practices[r.subject].data for r in rel if r.outcome == "contradicts"]
    assert contradicted == ["personal-info.name"]  # the transmission; the photo accessed on the device is not


def _fresh(path):
    path.mkdir()
    return path


def test_a_denial_naming_a_recipient_contradicts_only_a_transmission_to_it(tmp_path):
    """ "We do not share your name with othercorp" (or with payment providers) says nothing of a transmission to adco."""
    _, rel = relate(
        tmp_path,
        [claim("c1", "personal-info.name", "adco")],
        [
            d_claim("declares_recipient", "personal-info.name", "-", value={"entity": "othercorp"}),
            d_claim("declares_recipient", "personal-info.name", "-", value={"category": "payment"}),
        ],
    )
    assert not [r for r in rel if r.outcome == "contradicts"]
    _, rel = relate(
        _fresh(tmp_path / "named"),
        [claim("c1", "personal-info.name", "adco")],
        [d_claim("declares_recipient", "personal-info.name", "-", value={"entity": "adco"})],
    )
    assert [r.aspect for r in rel if r.outcome == "contradicts"] == ["recipient"]


def test_a_denial_labelled_only_with_the_root_category_contradicts_under_a_condition(tmp_path):
    _, rel = relate(
        tmp_path,
        [claim("c1", "personal-info.name", "adco")],
        [d_claim("declares_collection", "data", "-")],  # "we never collect or store those informations"
    )
    (contradiction,) = [r for r in rel if r.outcome == "contradicts"]
    assert contradiction.condition == "the denial, labelled only data, means the data observed"
    assert contradiction.condition_kind == "fact"


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


def test_transparency_reads_ds_annotations_on_analysed_documents_only(tmp_path):
    channels = [
        {
            "channel": "policy",
            "document": "p",
            "status": "analysed",
            "tilt": {"controller": {"name": "Example GmbH", "_provenance": []}},
        },
        {
            "channel": "in_app",
            "document": "n",
            "status": "not_analysable",
            "tilt": {"rightToRestriction": {"available": True, "_provenance": []}},
        },
    ]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d_report([], channels))
    built = assessment.build(a, REGISTRY)
    f = Frame.load("gdpr-art5")
    decided = frame.decisions(f, frame.evidence(built, [r.load() for r in a.observations], a.declaration.load()))
    by = {s.requirement: s for s in transparency.statuses(f, built, decided, a.declaration.sha256)}
    assert (
        by["controller_name"].status == "addressed"
        and by["controller_name"].addressed_by[0]["claim"] == "policy:/controller/name"
    )
    # only a document D could not analyse says it, so the information may be there: missing only under that condition
    assert (by["right_to_restrict"].status, by["right_to_restrict"].conditions) == ("missing_if", ["analysed:in_app"])
    assert by["dpo_contact"].conditions == ["dpo_designated", "analysed:in_app"]
    stated, covered = concerns.information_not_given(f, list(by.values()), {})
    k = {c.requirement: c for c in stated}
    assert k["right_to_restrict"].status == "supported" and k["right_to_restrict"].condition == ["analysed:in_app"]
    assert ("controller_name", "collection", True) in {(c.requirement, c.subject, c.applies) for c in covered}
    assert not any(c.requirement == "controller_name" for c in stated)
    # D's silence: no channel is exhaustive for a transparency requirement, so "not found" is never certain
    assert by["right_to_restrict"].silent == ["policy"]
    assert k["right_to_restrict"].uncertainty["s"] == "moderate"
    assert any("not exhaustive" in x for x in k["right_to_restrict"].silence)
    # without the notice at all (absent), the provider gives none: missing, under no condition
    channels[1] = {"channel": "in_app", "status": "absent"}
    (tmp_path / "absent").mkdir()
    a = workspace(tmp_path / "absent", [o_report([claim("c1", "personal-info.name", "adco")])], d_report([], channels))
    built = assessment.build(a, REGISTRY)
    decided = frame.decisions(f, frame.evidence(built, [r.load() for r in a.observations], a.declaration.load()))
    by = {s.requirement: s for s in transparency.statuses(f, built, decided, a.declaration.sha256)}
    assert (by["right_to_restrict"].status, by["right_to_restrict"].conditions) == ("missing", [])


def test_an_incomplete_documents_silence_is_missing_only_under_a_condition(tmp_path):
    from skuld.assess import build

    channels = [
        {
            "channel": "policy",
            "document": "p",
            "status": "analysed",
            "complete": False,
            "incomplete": "the policy's later chapters failed to load",
            "tilt": {"controller": {"name": "Example GmbH", "_provenance": []}},
        },
    ]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d_report([], channels))
    report, _ = build(a.root, write=False)
    validate("expectation_assessment", report)
    status = {t["requirement"]: t for t in report["subjects"]["collection"]["transparency"]}
    # as D's rules: the information may be in the part Sága did not acquire
    assert status["right_to_restrict"]["status"] == "missing_if"
    assert "complete:policy" in status["right_to_restrict"]["conditions"]
    assert status["controller_name"]["status"] == "addressed"  # what the acquired part gives still counts
    concern = next(c for c in report["concerns"] if c["requirement"] == "right_to_restrict")
    assert "complete:policy" in concern["condition"] and concern["uncertainty"]["n"] == "moderate"
    opened = next(o for o in report["open"] if o["text"].startswith("whether the part of the policy"))
    assert concern["id"] in opened["qualifies"]
    assert report["subjects"]["collection"]["documents"][0]["complete"] is False


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
    assert set(out) == {"c1", "c2", "policy:/dataDisclosed/0", "policy:/dataDisclosed/1"}
    assert out["c1"]["relations"] and out["policy:/dataDisclosed/0"]["relations"]
    assert out["c2"]["not_related"] == "not_assessable" and "not a practice" in out["c2"]["reason"]
    assert out["policy:/dataDisclosed/1"]["reason"] == "E's expectation stage has no claims"


def test_ds_findings_and_open_conditions_are_passed_on_and_checked(tmp_path):
    from skuld.assess import build
    from skuld.provenance import check_assessment

    d = d_report([d_claim("declares_recipient", "personal-info.name", value={"entity": "adco"})])
    d["report"] = {"urda": "2.0.0"}
    d["channels"][0]["tilt"] = {"_asgard": {"analysis": [{"role": "module:units", "id": "model", "version": "abc"}]}}
    cid = d["claims"][0]["id"]
    d["findings"] = [
        {
            "id": "f1",
            "rule": "label.shared_not_in_label",
            "template": "omission",
            "channels": ["policy"],
            "declarations": [cid],
            "explanation": "",
            "uncertainty": {},
        }
    ]
    d["open"] = [{"id": "o1", "text": "adco receives data as a third party", "qualifies": [cid], "predicate": "share"}]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d)
    report, members = build(a.root, write=False)
    validate("expectation_assessment", report)
    assert {"finding": {"report": a.declaration.sha256, "finding": "f1"}} in report["passed_on"]
    passed = [o for o in report["open"] if o.get("from") == "D"]
    assert passed == [
        {
            "id": "open:D:o1",
            "text": "adco receives data as a third party",
            "qualifies": [cid],
            "kind": "fact",
            "from": "D",
            "of": {"report": a.declaration.sha256, "open": "o1"},
        }
    ]
    analysis = {
        c["id"]: c.get("version") for c in report["report"]["components"] if c["role"] == "declaration_analysis"
    }
    assert analysis == {"urda": "2.0.0", "policy:module:units:model": "abc"}
    assert check_assessment(a, report, report, members) == []
    # what D's report does not state is a problem
    passed[0]["qualifies"] = ["policy:/nowhere"]
    passed[0]["of"]["open"] = "o2"
    next(x for x in report["passed_on"] if "finding" in x)["finding"]["finding"] = "f2"
    problems = check_assessment(a, report, None, members)
    assert "passed on: D finding f2 is unknown" in problems
    assert "open:D:o1: qualifies policy:/nowhere, which is unknown" in problems
    assert "open:D:o1: continues o2, which D's report does not state" in problems


def test_e_decides_ds_conditions_that_os_practices_or_the_parties_settle_and_passes_on_the_rest(tmp_path):
    from skuld.assess import build
    from skuld.provenance import check_assessment

    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "entities": [
                    {"id": "adco", "name": "AdCo", "domains": ["adco.example"], "types": ["advertising"]},
                    {"id": "exampleco", "name": "Example Co", "domains": ["example.com"]},  # the provider's own
                ]
            }
        )
    )
    claims = [
        d_claim("declares_collection", "personal-info.name"),
        d_claim(
            "declares_recipient", "personal-info.email-address", value={"entity": "exampleco", "name": "our group"}
        ),
        d_claim("declares_recipient", "personal-info.email-address", value={"entity": "adco", "name": "AdCo"}),
        d_claim("declares_collection", "location.precise-location"),
    ]
    d = d_report(claims)
    ids = [c["id"] for c in d["claims"]]
    d["open"] = [
        {"id": "o1", "text": "whether the name leaves the device", "qualifies": [ids[0]], "predicate": "collect"},
        {
            "id": "o2",
            "text": "whether our group receives it as a third party",
            "qualifies": [ids[1]],
            "predicate": "share",
        },
        {"id": "o3", "text": "whether AdCo receives it as a third party", "qualifies": [ids[2]], "predicate": "share"},
        {"id": "o4", "text": "whether the location leaves the device", "qualifies": [ids[3]], "predicate": "collect"},
    ]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d)
    report, members = build(a.root, registry, write=False)
    validate("expectation_assessment", report)
    decided = {x["of"]["open"]: x for x in report["decided"]}
    passed = {o["of"]["open"] for o in report["open"] if o.get("from") == "D"}
    # the name: O saw it transmitted, so it leaves the device
    assert decided["o1"]["outcome"] == "holds" and decided["o1"]["by"]["claims"] and decided["o1"]["by"]["relations"]
    # the provider's own group company receives no data as another company
    assert decided["o2"]["outcome"] == "fails"
    # whether AdCo acts as a service provider no register states; O saw no location: neither is decided
    assert passed == {"o3", "o4"} and not ({"o3", "o4"} & set(decided))
    assert check_assessment(a, report, report, members) == []


def test_a_declared_necessity_is_refuted_by_a_run_never_supported_and_not_compared_for_no_data(tmp_path):
    from skuld.common import PURPOSES, vocabulary

    claims = [
        d_claim("declares_legal_basis", "personal-info.name", value="GDPR-6-1-b", kind="justification"),
        d_claim("declares_legal_basis", "data", value="GDPR-6-1-b", kind="justification"),  # a list of bases
        d_claim("declares_legal_basis", "personal-info.email-address", value="GDPR-6-1-b", kind="justification"),
        d_claim("declares_legal_basis", "personal-info.name", value="GDPR-6-1-a", kind="justification"),  # consent
    ]
    a = workspace(tmp_path, [o_report([claim("c1", "personal-info.name", "adco")])], d_report(claims))
    built = assessment.build(a, REGISTRY)
    p = built.practices[0]
    user = {"beneficiary": "user", "provenance": "case"}
    tested = [
        {
            "id": "claim:x:1",
            "type": "dependency",
            "subject": p.id,
            "relationship": "not_dependent",
            "status": "supported",
            "strength": "run",
            "purpose": user,
            "case": "launch",
        },
        {
            "id": "claim:x:2",
            "type": "dependency",
            "subject": p.id,
            "relationship": "not_dependent",
            "status": "supported",
            "strength": "doc",
            "purpose": user,
            "case": "launch",
        },  # a document refutes no necessity
    ]
    out = {r.subject: r for r in relations.d_e(built, [], {}, DATA, vocabulary(PURPOSES), tested)}
    by_value = {d.id: (d.data, d.value) for d in built.declarations}
    refuted = [r for r in out.values() if r.outcome == relations.NECESSITY_REFUTED]
    assert [by_value[r.subject] for r in refuted] == [("personal-info.name", "GDPR-6-1-b")]
    assert [t["claim"] for t in refuted[0].to] == ["claim:x:1"]
    assert any(r.outcome == "not_comparable" and by_value[r.subject][0] == "data" for r in out.values())
    # no run for the e-mail address, and consent declares no necessity: no relation, the claim is passed on
    assert not any(
        by_value[r.subject] in {("personal-info.email-address", "GDPR-6-1-b"), ("personal-info.name", "GDPR-6-1-a")}
        for r in out.values()
    )


@pytest.fixture
def fixtures_profile(monkeypatch):
    """The setup the fixtures were asked with (profile fixtures-2026-10), under which their kept samples are found."""
    from skuld import config

    monkeypatch.setenv("SKULD_PROFILE", "fixtures-2026-10")
    monkeypatch.delenv("SKULD_CONFIG", raising=False)
    config.load.cache_clear()
    yield
    monkeypatch.undo()
    config.load.cache_clear()


FIXTURES = [
    "pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4",
    "air.nn.mobile.app.main@3.8.96",
    "de.wetteronline.wetterapp@2026.20",
]


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixtures_reports_are_valid_and_pilates_reproduces_the_worked_example(name, fixtures_profile):
    root = ROOT / "cases" / name
    if not (root / "assessment.yaml").is_file():
        pytest.skip("the case study's workspaces are not in this checkout")
    kept = {
        n: (root / n).read_text(encoding="utf-8")
        for n in ("subjects.json", REPORT, "assessment.md")
        if (root / n).is_file()
    }
    try:
        report = assess(root)
    finally:
        for n, text in kept.items():
            (root / n).write_text(text, encoding="utf-8", newline="")
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
        # one decimal of the location preserves the forecast (ServiceProvision), but E's purposes of the location are
        # RequestedServiceProvision, a narrower node: a preserved purpose reaches hypotheses at its own node only, while
        # a broken one (no location: the forecast for another place) also reaches those below (C1, author 14 Nov 2026)
        located = {p["id"] for p in report["subjects"]["practices"] if p["data"] == "location.coordinates"}
        case = [c for c in report["claims"] if c.get("case") == "forecast" and c["subject"] in located]
        kept = [c for c in case if c["type"] == "alternative" and c["status"] == "supported"]
        broken = [c for c in case if c["type"] == "alternative" and c["status"] == "refuted"]
        assert kept and all(c["basis"] == [] for c in kept)
        assert broken and all(c["basis"] for c in broken)
        assert not [
            c
            for c in report["concerns"]
            if c["step"] == "less_invasive_alternative"
            and c["subject"] in located
            and "forecast:G1" in c.get("reason", "")
        ]
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
    # the reasoning tier: "provide and improve the Service" not specific
    vague = [c for c in report["concerns"] if c["step"] == "not_specific" and "provide and improve" in c["reason"]]
    assert vague and vague[0]["status"] == "supported"
    # a less invasive identifier for advertising, documented by the fixture's corpus (cd73311d), whose passages no
    # person has checked: gate (c) holds every documented alternative at not established (E 0.9's worked example)
    identifier = {pid for pid, p in practices.items() if p["data"] == "device-or-other-ids.advertising-id"}
    assert not [
        c
        for c in report["concerns"]
        if c["step"] == "less_invasive_alternative"
        and c["status"] == "supported"
        and c["subject"] in identifier
        and "run" not in str(c.get("strength"))
    ]
    reasoned = [
        c
        for c in report["claims"]
        if c["type"] == "alternative" and c.get("tier") == "reasoning" and c["subject"] in identifier
    ]
    assert reasoned and all(c["status"] != "supported" for c in reasoned)
    assert any("gate (" in str(c.get("reason")) for c in reasoned)
