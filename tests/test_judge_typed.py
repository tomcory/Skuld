"""The typed minimisation form (P10 (b), minimisation prompt 5, judge reading 5): gate (a) from the change, needs and
gives grounded, covers by rule over the corpus's facts or by the model, and the status each path gives."""

from pathlib import Path

import pytest

from skuld import combine, gaps, judge
from skuld.assessment import Practice
from skuld.context import Context
from skuld.corpus import Corpus, Fact, Passage
from skuld.qualify import nextsteps
from tests.test_judge_reading import ordered_data

IDS = "device-or-other-ids."
ADID, SETID, ANDROID = IDS + "advertising-id", IDS + "app-set-id", IDS + "android-id"
FILE = "android-unique-identifiers.yaml"
TEXT = (
    "The App Set ID is shared by the apps of the same developer on a device. It is reset when the last app of the "
    "developer is uninstalled."
)
FACTS = (
    Fact(SETID, "scope", "developer", "shared by the apps of the same developer"),
    Fact(SETID, "persists", "reinstall", "reset when the last app of the developer is uninstalled"),
)
HYPOTHESES = {"claim:P-1:1": {"id": "claim:P-1:1", "purpose": {"node": "Advertising", "specificity": "sufficient"}}}


@pytest.fixture(autouse=True)
def identifiers_ordered(monkeypatch):
    data = ordered_data()
    real = judge.vocabulary
    monkeypatch.setattr(judge, "vocabulary", lambda name: data if name == judge.DATA else real(name))


def passage(nodes=(ADID,), verified=True, facts=FACTS, entities=()) -> Passage:
    return Passage(
        id="android-unique-identifiers",
        title="t",
        source="https://example.org",
        kind="platform",
        nodes=tuple(nodes),
        entities=tuple(entities),
        text=TEXT,
        path=Path("passages") / FILE,
        verified={"by": "assessor", "date": "2026-11-21"} if verified else None,
        facts=tuple(facts),
    )


def question(facts_shown=True) -> judge.Question:
    def part(pid, kind, record, **extra):
        return {"id": pid, "kind": kind, "text": pid, "provenance": [{"origin": "x", "record": record, **extra}]}

    parts = [
        part("P-1", "practice", "O"),
        part("H1", "hypothesis", "E"),
        part("S1", "screen", "events.jsonl#screen/s1"),
        part("D1", "passage", FILE),
    ]
    if facts_shown:
        parts += [part("F1", "passage", FILE, fact=0), part("F2", "passage", FILE, fact=1)]
    parts.append(part("N1", "passage", "norms/minimised.yaml"))
    record = {"practice": "P-1", "purposes": {"H1": "claim:P-1:1"}, "components": ["P-1.data", "P-1.recipient"]}
    return judge.Question(judge.MINIMISATION, "P-1", Context(tuple(parts)), [], record)


def practice(data=ADID, recipient=None) -> Practice:
    claim_type = "transmits" if recipient else "accesses"
    return Practice("P-1", claim_type, data, recipient, "app", [], [], [], [], recipient_categories=[])


NEEDS = [
    {"id": "N1", "requirement": "tell the user's installs of the provider's apps apart", "kind": "scope",
     "value": "app", "cites": ["S1"]},
    {"id": "N2", "requirement": "recognise the installation until it is removed", "kind": "persists",
     "value": "reinstall", "cites": ["H1"]},
]  # fmt: skip
GIVES = [{"property": "shared by the developer's apps", "kind": "scope", "value": "developer", "cites": ["F1"]}]


def entry(change=None, needs=None, gives=None, verdict="COVERS", steps=None, component="P-1.data"):
    return {
        "purpose": "H1",
        "component": component,
        "change": change or {"kind": "REPLACE", "node": SETID},
        "alternative": "use the App Set ID",
        "needs": NEEDS if needs is None else needs,
        "gives": GIVES if gives is None else gives,
        "covers": {"verdict": verdict, "steps": [{"text": "met", "cites": ["S1", "F1"]}] if steps is None else steps},
    }


def read(*entries, p=None, reading="5", found=None, q=None):
    corpus = Corpus((found or passage(),), "0" * 64)
    return judge.minimisation(
        {"alternatives": list(entries)}, "s", q or question(), HYPOTHESES, reading, p or practice(), corpus
    )


def test_supported_by_rule_where_facts_give_the_replacement_each_needed_kind():
    [c] = read(entry(verdict="UNKNOWN"))  # the rule decides, over the model's verdict
    assert (c["status"], c["level"], c["strength"]) == ("supported", "technically_supported", "doc")
    assert c["change"] == {"kind": "replace", "node": SETID} and c["change_key"] == f"replace:{SETID}"
    assert c["covers"]["by"] == "rule" and c["covers"]["verdict"] == "covers"
    assert c["covers"]["model_verdict"] == "unknown"
    assert [s["cites"] for s in c["covers"]["steps"]] == [["F1"], ["F2"]]
    assert "covers_by_model" not in {r["reason"] for r in c["uncertainty"]["reasons"]}
    assert [(n["id"], n["grounded"]) for n in c["needs"]] == [("s:a0:N1", True), ("s:a0:N2", True)]
    assert c["gives"][0]["grounded"] and c["sufficiency"] == {"sufficient": True}
    assert set(c["parts"]) >= {"S1", "H1", "F1"} and "level" in c


def test_the_rule_overrides_the_model_and_a_grounded_does_not_is_a_challenging_member():
    needs = [{**NEEDS[0], "value": "cross-app"}, NEEDS[1]]  # the purpose needs more reach than the developer's apps
    [c] = read(entry(needs=needs, verdict="COVERS"))
    assert c["covers"]["by"] == "rule" and (c["covers"]["verdict"], c["covers"]["model_verdict"]) == (
        "does_not",
        "covers",
    )
    assert c["status"] == "refuted" and c["strength"] == "doc" and c["level"] == "plausible"
    assert c["covers"]["steps"][0]["text"].endswith("not met")
    # it is no concern: the combination keeps it as a refuted member, never as a supported alternative
    [combined] = combine.alternatives([{**c, "supporting": [], "challenging": ["item:1"]}], combine.Numbers())
    assert combined["status"] == "refuted" and combined["challenging"] == ["item:1"]


def test_persistence_and_precision_compare_by_their_orders():
    [longer] = read(entry(needs=[{**NEEDS[1], "value": "reset"}], verdict="COVERS"))  # must survive reinstalls
    assert (longer["status"], longer["covers"]["verdict"]) == ("refuted", "does_not")
    assert judge._rank("precision_m", 50) >= judge._rank("precision_m", 3000)  # 50 m serves a need of 3 km
    assert judge._rank("scope", "developer") >= judge._rank("scope", "app")


def test_supported_by_the_model_with_grounded_steps_raises_covers_by_model():
    needs = [{"id": "N1", "requirement": "show the ad once", "cites": ["S1"]}]  # no kind: no rule
    gives = [{"property": "contextual ads need no identifier", "cites": ["D1"]}]
    [c] = read(entry(change={"kind": "REMOVE"}, needs=needs, gives=gives))
    assert (c["status"], c["covers"]["by"], c["change_key"]) == ("supported", "model", "remove")
    assert "covers_by_model" in {r["reason"] for r in c["uncertainty"]["reasons"]}
    [c] = read(
        entry(change={"kind": "REMOVE"}, needs=needs, gives=gives, steps=[{"text": "x", "cites": ["own knowledge"]}])
    )
    assert (c["status"], c["sufficiency"]["reason"]) == ("not_established", "own_knowledge")
    assert c["reason"].startswith("covers:") and c["strength"] == "own"


def test_needs_from_own_knowledge_or_the_practice_ground_nothing():
    own = [{"id": "N1", "requirement": "x", "kind": "scope", "value": "app", "cites": ["own knowledge"]}]
    [c] = read(entry(needs=own))
    assert (c["status"], c["sufficiency"]["reason"]) == ("not_established", "own_knowledge")
    assert c["needs"][0]["grounded"] is False and c["reason"].startswith("a need")
    practice_only = [{"id": "N1", "requirement": "x", "kind": "scope", "value": "app", "cites": ["P-1"]}]
    [c] = read(entry(needs=practice_only))
    assert c["needs"][0]["cites"] == [] and c["dropped_steps"][0]["step"] == "N1" and c["status"] == "not_established"
    documented = [{"id": "N1", "requirement": "x", "cites": ["D1"]}]  # needs are read from S and H only
    assert read(entry(needs=documented))[0]["needs"][0]["grounded"] is False
    assert read(entry(needs=[]))[0]["reason"] == "no need is stated"


def test_a_give_from_own_knowledge_is_a_fact_the_corpus_lacks():
    gives = [{"property": "reset with the app", "kind": "persists", "value": "reinstall", "cites": ["own knowledge"]}]
    [c] = read(entry(gives=gives, verdict="COVERS"))
    assert (c["status"], c["sufficiency"]["reason"]) == ("not_established", "fact_missing")
    assert c["sufficiency"]["missing"] == [f"fact: persists of {SETID}"] and c["gives"][0]["grounded"] is False
    # its gap extends the corpus, never asks the controller; the next step targets the fact, not the practice
    step = gaps.reason_step("fact_missing", f"the persists of {SETID}")
    assert step["kind"] == gaps.EXTEND
    g = {
        "id": "gap:P-1:1",
        "of": c["id"],
        "reason": "fact_missing",
        "proposition": "p",
        "next": step,
        "fact": {"node": SETID, "property": "persists"},
    }

    class Index:
        concerns, claims, practices, requirements = {}, {}, {"P-1": {"id": "P-1"}}, {}

    s = nextsteps._gap_step(Index(), g)
    assert (s["kind"], s["by"], s["target"]) == ("extend_corpus", "skuld", {"node": SETID, "property": "persists"})


def test_gates_b_and_c_read_a_fact_by_its_passage():
    # a passage about another datum documents nothing of the component, nor does a fact of it about no replacement
    about_other = passage(nodes=[ANDROID], facts=[Fact(ANDROID, "scope", "app", "shared by the apps")])
    [c] = read(entry(gives=[{**GIVES[0], "cites": ["F1"]}]), found=about_other)
    assert c["status"] == "not_established" and c["reason"] == judge.GATES["gate_b"]
    [c] = read(entry(gives=[{**GIVES[0], "cites": ["D1"]}]), found=passage(nodes=[ANDROID]))
    assert c["reason"] == judge.GATES["gate_b"]
    # a fact about a candidate replacement of the component's datum (the App Set ID for the advertising ID) is about
    # the component, whatever its passage is tagged with: it documents the component's alternative
    [c] = read(entry(), found=passage(nodes=[ANDROID]))
    assert c["status"] == "supported" and c["gives"][0]["grounded"]
    [c] = read(entry(), found=passage(verified=False))
    assert c["reason"] == judge.GATES["gate_c"]
    # an unchecked passage's facts decide nothing by rule either
    assert c["covers"]["by"] == "model"


def test_partly_unknown_and_an_ungrounded_does_not_are_not_established():
    needs = [{"id": "N1", "requirement": "x", "cites": ["S1"]}]
    for verdict, reason in (
        ("PARTLY", "partly covers"),
        ("UNKNOWN", "whether the alternative covers"),
        ("DOES_NOT", "does not cover"),
    ):
        [c] = read(entry(needs=needs, verdict=verdict, steps=[] if verdict == "DOES_NOT" else None))
        assert c["status"] == "not_established" and c["reason"].startswith(reason), verdict
        assert c["covers"] == {"verdict": verdict.lower(), "by": "model", "steps": c["covers"]["steps"]}


def test_gate_a_from_the_typed_change():
    # a replacement by an identifier that is not coarser, or by none, fails gate (a)
    [c] = read(entry(change={"kind": "REPLACE", "node": ANDROID}))
    assert c["reason"] == judge.GATES["gate_a_typed"] and c["change_key"] == f"replace:{ANDROID}"
    [c] = read(entry(change={"kind": "REPLACE"}))
    assert c["reason"] == judge.GATES["gate_a_typed"] and c["change_key"] == judge.OTHER_CHANGE
    # on the device: a datum only with documented gives, a recipient always
    needs = [{"id": "N1", "requirement": "x", "cites": ["S1"]}]
    gives = [{"property": "the device computes it", "cites": ["D1"]}]
    [c] = read(entry(change={"kind": "ON_DEVICE"}, needs=needs, gives=gives))
    assert (c["status"], c["change_key"]) == ("supported", "on_device")
    [c] = read(entry(change={"kind": "ON_DEVICE"}, needs=needs, gives=[{"property": "x", "cites": ["S1"]}]))
    assert c["reason"] == judge.GATES["gate_a_typed"]
    adco = practice(recipient="adco")
    recipient = passage(entities=["adco"])
    [c] = read(
        entry(change={"kind": "NARROWER_RECIPIENT"}, needs=needs, gives=gives, component="P-1.recipient"),
        p=adco,
        found=recipient,
    )
    assert (c["status"], c["change_key"]) == ("supported", "narrower_recipient")
    # an unknown change kind is no change
    [c] = read(entry(change={"kind": "SHRINK"}))
    assert "change" not in c and c["change_key"] == judge.OTHER_CHANGE and c["reason"] == judge.GATES["gate_a_typed"]


def test_gate_d_counts_the_samples_that_propose_the_same_typed_change_and_needs_take_the_claims_id():
    remove = entry(change={"kind": "REMOVE"}, needs=[{"id": "N1", "requirement": "x", "cites": ["S1"]}])
    members = []
    for seed, e in ((1, entry()), (2, entry()), (3, remove)):
        members += read(e)
        members[-1] = {**members[-1], "id": f"s{seed}:a0", "channels": [f"reasoning:s{seed}"], "supporting": ["i"]}
        members[-1].pop("parts")
    out = combine.alternatives(members, combine.Numbers(), {"P-1": {"s1", "s2", "s3"}})
    by_key = {c["change_key"]: c for c in out}
    assert by_key[f"replace:{SETID}"]["status"] == "supported"  # two of three samples propose it
    assert by_key["remove"]["status"] == "not_established" and "gate (d)" in by_key["remove"]["reason"]
    replaced = by_key[f"replace:{SETID}"]
    assert [n["id"] for n in replaced["needs"]] == [f"{replaced['id']}:N1", f"{replaced['id']}:N2"]
    assert replaced["change"] == {"kind": "replace", "node": SETID} and replaced["covers"]["by"] == "rule"


def test_refusals_of_the_typed_form():
    q = question()
    ok = entry()
    assert judge.refusals(q, _json({"alternatives": [ok]}), []) == []
    found = judge.refusals(
        q,
        _json(
            {
                "alternatives": [
                    {**ok, "purpose": "H9"},
                    {**ok, "component": "P-2.data"},
                    {**ok, "change": {"kind": "SHRINK"}},
                    {**ok, "change": {"kind": "REPLACE"}},
                    {**ok, "change": {"kind": "REPLACE", "node": "no-such-node"}},
                    {**ok, "needs": [{"id": "N1", "requirement": "x", "cites": ["S9"]}]},
                    {**ok, "gives": [{"property": "x", "cites": ["F9"]}]},
                    {**ok, "covers": {"verdict": "COVERS", "steps": [{"text": "x", "cites": ["D7"]}]}},
                ]
            }
        ),
        [],
    )
    assert "alternatives: H9 is not a purpose of the context" in found
    assert "alternatives: P-2.data is not a component of P-1" in found
    assert "alternatives: 'SHRINK' is not a change (REMOVE, REPLACE, ON_DEVICE, NARROWER_RECIPIENT)" in found
    assert "alternatives: REPLACE names no node, not a node of the data vocabulary" in found
    assert "alternatives: REPLACE names no-such-node, not a node of the data vocabulary" in found
    assert "alternatives: cites S9, not in the context" in found
    assert "alternatives: cites F9, not in the context" in found
    assert "alternatives: cites D7, not in the context" in found


def test_reading_4_reads_a_typed_entry_as_the_old_form_and_reading_5_an_old_entry_as_before():
    [old] = read(entry(), reading="4")
    assert not {"change", "needs", "gives", "covers", "change_key"} & set(old)
    assert (old["status"], old["level"]) == ("not_established", "plausible")
    plain = {"purpose": "H1", "component": "P-1.data", "alternative": "remove the advertising ID",
             "level": "TECHNICALLY_SUPPORTED", "steps": [{"text": "x", "cites": ["D1"]}]}  # fmt: skip
    [now] = read(plain)
    assert now["change_key"] == "remove" and not {"change", "needs", "gives", "covers"} & set(now)
    assert now["status"] == "supported"


def _json(x) -> str:
    import json

    return json.dumps(x)


def test_a_fact_reads_by_its_kind_persists_until_the_event_that_ends_it():
    data = judge.vocabulary(judge.DATA)
    assert judge.fact_text(FACTS[1], data).endswith(": persists until reinstall")
    assert judge.fact_text(FACTS[0], data).endswith(": scope developer")
    assert judge.fact_text(Fact("location.approximate-location", "precision_m", 3000, "q"), data).endswith(
        ": precision 3000 m"
    )
    prompt = (Path(judge.__file__).parent / "prompts" / "minimisation.md").read_text(encoding="utf-8")
    assert '"persists until reset"' in prompt


def test_the_context_gives_the_facts_of_the_candidate_replacements_of_a_datum():
    data = judge.vocabulary(judge.DATA)
    assert {SETID, IDS + "installation-id"} <= judge.replacements(ADID, data)
    assert ADID not in judge.replacements(ADID, data) and data.root not in judge.replacements(ADID, data)
    assert SETID not in judge.replacements(IDS + "installation-id", data)
    setid = passage(nodes=[SETID])
    unchecked = Passage(**{**setid.__dict__, "id": "u", "path": Path("passages") / "u.yaml", "verified": None})
    other = Passage(
        **{
            **setid.__dict__,
            "id": "o",
            "path": Path("passages") / "o.yaml",
            "facts": (Fact(ANDROID, "scope", "app", "q"),),
        }
    )
    corpus = Corpus((setid, unchecked, other), "0" * 64)
    parts = judge.replacement_facts(corpus, [], [ADID], data, 2)
    assert [p["id"] for p in parts] == ["F3", "F4"]  # numbered on, of the checked passage, about the replacement only
    assert parts[0]["provenance"] == [{"origin": "corpus", "record": FILE, "fact": 0}]
    assert "persists until reinstall" in parts[1]["text"] and "as t (https://example.org) states it" in parts[1]["text"]
    assert judge.replacement_facts(corpus, [setid], [ADID], data, 0) == []  # given after its passage already, once
