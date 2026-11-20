"""The minimisation reading: an entry whose alternative names none is no Alternative claim (judge.READING 1); a
documented alternative passes gates (b) and (c) (READING 2)."""

import copy
from pathlib import Path

import pytest
from ratatoskr.vocabularies import Vocabulary

from skuld import judge
from skuld.assessment import Practice
from skuld.context import Context
from skuld.corpus import Corpus, Passage


@pytest.mark.parametrize(
    "text",
    [
        "none",
        "None.",
        " none ",
        "N/A",
        "not applicable",
        "No less invasive alternative identified.",
        "no less invasive alternative identified;",
        "No less invasive alternative stated.",
        "No alternative",
        "There is no less invasive alternative.",
        "",
        None,
    ],
)
def test_texts_that_name_no_alternative(text):
    assert not judge.names_alternative(text)


@pytest.mark.parametrize(
    "text",
    [
        "No recipient — perform the consent-state check entirely on-device.",
        "No persistent storage; read the Advertising ID from the system on demand.",
        "an app-generated installation ID",
        "coarser data (approximate location)",
        "Nonetheless an app-scoped identifier",
    ],
)
def test_texts_that_name_an_alternative(text):
    assert judge.names_alternative(text)


def _question() -> judge.Question:
    def part(pid, kind, record):
        return {"id": pid, "kind": kind, "text": pid, "provenance": [{"record": record}]}

    context = Context(
        (
            part("P-1.data", "practice", "O"),
            part("H1", "hypothesis", "E"),
            part("D1", "passage", "passages/android-unique-identifiers.yaml"),
        )
    )
    record = {"practice": "P-1", "purposes": {"H1": "claim:P-1:1"}, "components": ["P-1.data"]}
    return judge.Question(judge.MINIMISATION, "P-1", context, [], record)


HYPOTHESES = {"claim:P-1:1": {"id": "claim:P-1:1", "purpose": {"node": "Advertising", "specificity": "sufficient"}}}
STEPS = [{"text": "the purpose [H1]", "cites": ["H1"]}, {"text": "the documentation [D1]", "cites": ["D1"]}]


def _entry(alternative, level):
    return {"purpose": "H1", "component": "P-1.data", "alternative": alternative, "level": level, "steps": STEPS}


def test_a_technically_supported_none_is_no_supported_alternative():
    # the bug of 15 Nov 2026: "none" with level TECHNICALLY_SUPPORTED, citing documentation, was a supported
    # alternative of strength doc and decided the combination
    answer = {"alternatives": [_entry("none", "TECHNICALLY_SUPPORTED")]}
    assert judge.minimisation(answer, "assessment/minimisation/P-1/s1", _question(), HYPOTHESES) == []


def test_a_plausible_none_is_no_open_alternative_either():
    answer = {"alternatives": [_entry("No less invasive alternative identified.", "PLAUSIBLE")]}
    assert judge.minimisation(answer, "assessment/minimisation/P-1/s1", _question(), HYPOTHESES) == []


def test_a_named_alternative_is_still_read():
    answer = {
        "alternatives": [
            _entry("none", "TECHNICALLY_SUPPORTED"),
            _entry("an app-generated installation ID", "TECHNICALLY_SUPPORTED"),
        ]
    }
    out = judge.minimisation(answer, "assessment/minimisation/P-1/s1", _question(), HYPOTHESES, reading="1")
    assert [(c["alternative"], c["status"], c["strength"]) for c in out] == [
        ("an app-generated installation ID", "supported", "doc")
    ]
    assert out[0]["id"].endswith(":a1")  # ids keep the entry's position in the answer


# -- READING 2: gates (b) and (c) ----------------------------------------------------------------------------------

ADID = "device-or-other-ids.advertising-id"
IDS = "device-or-other-ids."


def ordered_data() -> Vocabulary:
    """asgard-data with the identifiers ordered as in its version 1.3.0, which Skuld's pinned Ratatoskr predates."""
    schema = copy.deepcopy(Vocabulary.load("asgard-data").schema)
    order = {
        IDS + "installation-id": [IDS + "app-set-id", IDS + "android-id", IDS + "advertising-id"],
        IDS + "app-set-id": [IDS + "android-id", IDS + "advertising-id"],
    }
    for entry in schema["oneOf"]:
        if entry["const"] in order:
            entry["x-coarser-than"] = order[entry["const"]]
    return Vocabulary(schema, "asgard-data with identifiers ordered")


@pytest.fixture(autouse=True)
def identifiers_ordered(monkeypatch):
    data = ordered_data()
    real = judge.vocabulary
    monkeypatch.setattr(judge, "vocabulary", lambda name: data if name == judge.DATA else real(name))


def _passage(nodes=(), entities=(), types=(), verified=True) -> Passage:
    return Passage(
        id="android-unique-identifiers",
        title="t",
        source="https://example.org",
        kind="platform",
        nodes=tuple(nodes),
        entities=tuple(entities),
        text="x",
        path=Path("passages/android-unique-identifiers.yaml"),
        verified={"by": "assessor", "date": "2026-11-18"} if verified else None,
        recipient_types=tuple(types),
    )


def _practice(data=ADID, recipient=None, categories=()) -> Practice:
    claim_type = "transmits" if recipient else "accesses"
    return Practice("P-1", claim_type, data, recipient, "app", [], [], [], [], recipient_categories=list(categories))


def _read(passage, practice=None, component="P-1.data", alternative="an app-generated installation ID"):
    entry = {**_entry(alternative, "TECHNICALLY_SUPPORTED"), "component": component}
    q = _question()
    q.record["components"] = ["P-1.data", "P-1.recipient"]
    corpus = Corpus((passage,), "0" * 64)
    out = judge.minimisation({"alternatives": [entry]}, "s", q, HYPOTHESES, "2", practice or _practice(), corpus)
    return out[0]


def test_a_checked_passage_about_the_datum_supports_the_alternative():
    c = _read(_passage(nodes=[ADID]))
    assert (c["status"], c["level"]) == ("supported", "technically_supported")


def test_a_passage_tagged_above_the_datum_is_about_it_but_never_the_root():
    assert _read(_passage(nodes=["device-or-other-ids"]))["status"] == "supported"
    c = _read(_passage(nodes=["data"]))
    assert (c["status"], c["sufficiency"]["reason"]) == ("not_established", "not_admitted")
    assert c["reason"].startswith("gate (b)")


def test_a_passage_about_another_datum_fails_gate_b():
    c = _read(_passage(nodes=["device-or-other-ids.android-id"]))
    assert (c["status"], c["level"]) == ("not_established", "plausible") and c["reason"].startswith("gate (b)")


def test_an_unchecked_passage_fails_gate_c():
    c = _read(_passage(nodes=[ADID], verified=False))
    assert c["status"] == "not_established" and c["reason"].startswith("gate (c)")


def test_a_recipient_is_concerned_by_its_entity_or_a_type_at_or_above_its_category():
    practice = _practice(recipient="adco", categories=["advertising"])

    def read(passage):
        return _read(passage, practice, "P-1.recipient", "Remove the AdCo SDK and attribute installs on the server.")

    assert read(_passage(entities=["adco"]))["status"] == "supported"
    assert read(_passage(types=["advertising"]))["status"] == "supported"
    assert read(_passage(types=["recipient"]))["reason"].startswith("gate (b)")
    assert read(_passage(entities=["other"]))["reason"].startswith("gate (b)")


def test_gate_a_admits_a_coarser_identifier_or_a_removal_and_nothing_else():
    checked = _passage(nodes=["device-or-other-ids"])
    assert _read(checked, alternative="an identifier of narrower scope (app-generated installation ID)")["status"] == (
        "supported"
    )
    assert _read(checked, alternative="Do not send the advertising ID to the partner.")["status"] == "supported"
    assert _read(checked, alternative="match installs without the identifier")["status"] == "supported"
    # the Android ID and the advertising ID are not ordered; a finer identifier is no alternative
    android = _practice(data=IDS + "android-id")
    assert _read(checked, android, alternative="Use an advertising ID.")["reason"].startswith("gate (a)")
    # a disjunction is less invasive only if every identifier it names is
    assert _read(checked, android, alternative="an advertising ID or an app-generated installation ID")[
        "reason"
    ].startswith("gate (a)")
    # storing it for less long changes no dimension the instance imposes
    on_demand = "Request the Advertising ID from Google Play services on-demand instead of storing it."
    assert _read(checked, alternative=on_demand)["reason"].startswith("gate (a)")


def test_gate_a_needs_an_identified_component():
    checked = _passage(nodes=["device-or-other-ids"], entities=["adco"])
    unknown = _practice(data="data")
    assert _read(checked, unknown, alternative="Do not send it.")["reason"] == judge.GATES["gate_a_component"]
    unresolved = _practice(recipient="domain:example.org")
    assert _read(checked, unresolved, "P-1.recipient", "Remove the SDK.")["reason"] == judge.GATES["gate_a_component"]
    # a recipient is removed, never replaced by another
    adco = _practice(recipient="adco")
    assert _read(checked, adco, "P-1.recipient", "Use AdCo's competitor.")["reason"] == judge.GATES["gate_a_change"]


def test_reading_1_has_no_gates_and_an_unknown_reading_is_an_error():
    entry = _entry("an app-generated installation ID", "TECHNICALLY_SUPPORTED")
    out = judge.minimisation({"alternatives": [entry]}, "s", _question(), HYPOTHESES, "1")
    assert out[0]["status"] == "supported"
    with pytest.raises(ValueError):
        judge.minimisation({"alternatives": [entry]}, "s", _question(), HYPOTHESES, "4")


def test_from_reading_3_only_cited_documentation_gives_an_alternative_the_strength_of_documents():
    # every step cites a part of the context (the hypothesis), none a passage of documentation
    entry = _entry("an app-generated installation ID", "PLAUSIBLE")
    entry["steps"] = [{"text": "the purpose", "cites": ["H1"]}]
    for reading, strength in (("2", "doc"), ("3", "own")):
        [claim] = judge.minimisation({"alternatives": [entry]}, "s", _question(), HYPOTHESES, reading, _practice())
        assert claim["strength"] == strength, reading
