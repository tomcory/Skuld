"""The reasoning setting in the provenance (12 Nov 2026): the same model with reasoning off and on are two
configurations, so the assessment's model components, the calibration's identity and its model family tell them
apart; a sample asked without a setting records none, as before."""

from skuld import assess, calibrate


def record(think=None, seed=1):
    options = {"temperature": 0.4, "seed": seed, **({"think": think} if think is not None else {})}
    return {
        "prompt": {"id": "expectation", "version": "1", "sha256": "a" * 64},
        "model": {"api": "ollama", "name": "qwen3.8:27b", "digest": "b" * 64},
        "options": options,
    }


def models(*records):
    components = {}
    for r in records:
        assess._record_components(components, r, "assessment")
    return [c for c in components.values() if c["role"] == "model"]


def test_the_model_component_names_the_reasoning_setting_where_one_was_set():
    [off] = models(record(False))
    [low] = models(record("low"))
    [unset] = models(record())
    assert off["think"] is False and low["think"] == "low" and "think" not in unset
    # two settings of one model and seed are two components, not one
    assert len(models(record(False), record("low"))) == 2


def test_the_calibration_identity_and_family_tell_the_settings_apart():
    def report(*records):
        return {"report": {"components": models(*records)}}

    off, low, unset = (
        calibrate.identity(report(r)["report"]["components"]) for r in (record(False), record("low"), record())
    )
    assert off != low and len({tuple(map(tuple, x)) for x in (off, low, unset)}) == 3
    assert calibrate._family(report(record(False))) == "qwen3.8:27b (think false)"
    assert calibrate._family(report(record("low"))) == "qwen3.8:27b (think low)"
    assert calibrate._family(report(record())) == "qwen3.8:27b"
    # one assessment asked with two settings is no single family
    assert calibrate._family(report(record(False), record("low", seed=2))) is None
