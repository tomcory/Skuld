"""O's annotators in E: every run of a workspace analysed alike, and O's excerpts read instead of decoding."""

from types import SimpleNamespace

from skuld.expectation import _message_text
from skuld.experiments import _refuse_other_annotators
from skuld.observe import annotators


def report(methods=(), model=None, classifier=None):
    components = [{"role": "method", "id": m} for m in ("capture", "value_matching", *methods)]
    if model:
        components.append({"role": "model", "id": model, "reasoning": "off"})
    if classifier:
        components.append({"role": "classifier", "id": "tc", "sha256": classifier})
    return {"report": {"components": components}}


def test_the_annotators_of_a_report():
    assert annotators(report()) == ()
    assert annotators(report(("content_inference",), "gemma4:31b")) == (
        ("content_inference",),
        ("gemma4:31b", "off"),
        None,
    )


def test_a_run_analysed_with_other_annotators_is_refused():
    states = {
        "baseline": SimpleNamespace(report=report(("content_inference",), "gemma4:31b"), refused=None),
        "replay": SimpleNamespace(report=report(), refused=None),
        "alike": SimpleNamespace(report=report(("content_inference",), "gemma4:31b"), refused=None),
    }
    _refuse_other_annotators(states)
    assert states["replay"].refused.startswith("its observation report was made with other annotators")
    assert states["alike"].refused is None and states["baseline"].refused is None


def test_an_excerpt_of_o_is_shown_without_decoding():
    evidence = {
        "proposition": {"kind": "datum", "node": "personal-info.email-address", "field": "body"},
        "provenance": [
            {
                "field": "body",
                "span": [5, 21],
                "excerpt": {"before": '{"e":"', "text": "jane@example.com", "after": '"}'},
            }
        ],
    }
    request = {
        "method": "POST",
        "host": "api.example.com",
        "path": "/v1",
        "body": "not decodable",
        "body_encoding": "base64",
    }
    text = _message_text(request, evidence)
    assert "«jane@example.com»" in text and "(personal-info.email-address)" in text
