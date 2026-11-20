"""Tests of the assessment stage's reasoning tier: stage hypotheses, stage-2 contexts (gate 1), readings (gate 2),
concerns (ii), (iv) and (v) and gate 3, end to end."""

import json
import re

import pytest
from ratatoskr.llm import LLMResponse, Provider

from skuld import assessment, combine, corpus, expectation, inputs, judge
from skuld.assess import assess
from skuld.context import Context, ContextError
from tests.test_expectation import PACKAGE, FakeModel, o_report, run_folder
from tests.test_expectation import corpus as corpus_folder

FACTORS = ["link", "context", "nature", "consequences", "safeguards"]


def purpose(text, node, data="data", unit=None):
    span = {"text": text, **({"unit": unit} if unit is not None else {})}
    return {
        "type": "declares_purpose",
        "kind": "justification",
        "channels": ["policy"],
        "datum": {"node": data},
        "value": node,
        "polarity": "+",
        "qualifiers": {},
        "evidence": [{"channel": "policy", "document": "policy", "span": span}],
    }


def d_report():
    claims = [
        {"type": "declares_collection", "kind": "practice", "channels": ["policy"], "datum": {"node": "data"}},
        purpose("provide and improve the Service", "ImproveExistingProductsAndServices", unit=0),
        purpose("process your payments", "PaymentManagement"),
        purpose("market our products", "Marketing", data="device-or-other-ids"),  # covers the identifier only
        purpose("respond to signals", "Purpose"),  # the vocabulary's root: covers nothing
    ]
    channels = [
        {"channel": "policy", "document": "policy", "status": "analysed", "accessible": True, "annotations": []}
    ]
    for n, c in enumerate(claims):
        c["id"] = f"policy:/dataDisclosed/{n}"
        c.setdefault("polarity", "+")
    return {"collection": {"package": PACKAGE, "store_version": "1.0"}, "channels": channels, "claims": claims}


def norm(folder, pid, requirements, text):
    (folder / f"{pid}.yaml").write_text(
        f"id: {pid}\ntitle: {pid}\nsource: https://example.org/{pid}\nkind: norm\n"
        f"about: {{requirements: [{', '.join(requirements)}]}}\ntext: {text}\n"
    )


@pytest.fixture
def workspace(tmp_path):
    run = run_folder(tmp_path)
    report = tmp_path / "o.json"
    report.write_text(json.dumps(o_report(run.name)))
    d = tmp_path / "d" / "report.json"
    (d.parent / "annotation").mkdir(parents=True)
    d.write_text(json.dumps(d_report()))
    (d.parent / "annotation" / "policy.json").write_text(
        json.dumps({"passages": [{"passage": "We use Your Personal data to provide and improve the Service."}]})
    )
    docs = corpus_folder(tmp_path)
    # the passage speaks of the advertising ID and was checked against its source, as gates (b) and (c) require
    passage = (docs / "a.yaml").read_text()
    (docs / "a.yaml").write_text(
        passage.replace(
            "about: {entities: [adco]}",
            "about: {entities: [adco], nodes: [device-or-other-ids.advertising-id]}\n"
            "verified: {by: assessor, date: 2026-11-18}",
        )
    )
    (docs / "norms").mkdir()
    norm(docs / "norms", "specific", ["purpose_specific"], "A purpose must say what processing it includes.")
    norm(docs / "norms", "compatible", ["purpose_compatible"], "Compatibility is judged by the link and the context.")
    norm(docs / "norms", "minimised", ["data_minimised"], "Data are limited to what the purpose needs.")
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", [(report, run.name)], d, run, docs)
    with (root / "assessment.yaml").open("a") as f:
        f.write("models: {expectation: fake}\n")
    a = inputs.load_assessment(root)
    built = assessment.build(a, None)
    expectation.expect(a, built, corpus.load(a.corpus), seeds=[1], provider=FakeModel())
    return a, built


def tools(a, built):
    found, norms = corpus.load(a.corpus), corpus.load(a.corpus / corpus.NORMS)
    return found, norms, judge.stage1(a, built, found)


class FakeJudge(Provider):
    """Answers each question of the reasoning tier as `answers` says; records every prompt."""

    api = "fake"

    def __init__(self, compatible="NOT_COMPATIBLE"):
        super().__init__()
        self.prompts, self.compatible = [], compatible

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        text = prompt.messages[0]["content"]
        self.prompts.append(text)
        ids = re.findall(r"^\[([^\]]+)\]", text, re.M)
        statements = [i for i in ids if re.fullmatch(r"Q\d+", i)]
        norms = [i for i in ids if i.startswith("N")]
        if "are\nspecific, from the context" in text:
            answer = {
                "statements": [
                    {
                        "statement": q,
                        "specific": q != "Q1",
                        "lacking": [] if q != "Q1" else ["object", "outcome"],
                        "steps": [{"text": "Read against the norm.", "cites": [q, *norms[:1]]}],
                    }
                    for q in statements
                ]
            }
        elif "is\ncompatible with the purposes" in text:
            cites = ["Q1"] if self.compatible == "COMPATIBLE" else ["H1", norms[0]]
            answer = {
                "pairs": [
                    {
                        "specified": q,
                        "judgement": self.compatible,
                        "factors": [{"factor": "link", "text": "No link.", "cites": cites}],
                    }
                    for q in statements
                ]
            }
        else:
            practice = next(i for i in ids if i.startswith("P-"))
            docs = [i for i in ids if re.fullmatch(r"D\d+", i)]
            answer = {
                "alternatives": [
                    {
                        "purpose": "H1",
                        "component": f"{practice}.data",
                        "alternative": "match installs without the identifier",
                        "level": "TECHNICALLY_SUPPORTED" if docs else "PLAUSIBLE",
                        "steps": [{"text": "The documentation describes it.", "cites": docs[:1] or ["own knowledge"]}],
                    }
                ]
            }
        return LLMResponse(text=json.dumps(answer))


def test_stage_hypotheses_combine_aligned_purposes_across_samples(workspace):
    a, built = workspace
    expectation.expect(a, built, corpus.load(a.corpus), seeds=[2], provider=FakeModel())
    practices = {p.id: p for p in built.practices}
    claims = [
        c
        for name, context, answer in expectation.kept(a, built, corpus.load(a.corpus))
        for c in expectation.read(answer, name, context, practices)
    ]
    hypotheses = combine.hypotheses(claims, combine.Numbers())
    combined = [h for h in hypotheses if h["type"] == "purpose"]
    assert len(combined) == 2 and all(len(h["of"]) == 2 and h["status"] == "supported" for h in combined)
    dependencies = [h for h in hypotheses if h["type"] == "dependency"]
    assert all(h["basis"][0] in {c["id"] for c in combined} for h in dependencies)


def test_stage_2_contexts_mark_declarations_and_ask_compatibility_only_where_nothing_covers(workspace):
    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    questions = {(q.question, q.subject): q for q in judge.questions(a, built, found, norms, hypotheses)}
    (spec,) = [q for (kind, _), q in questions.items() if kind == "specificity"]
    statements = [p for p in spec.context.parts if p["kind"] == "declaration"]
    assert len(statements) == 4 and all(p["provenance"][0]["origin"] == "d_report" for p in statements)
    assert 'in: "We use Your Personal data' in statements[0]["text"]  # quoted with its sentence
    # the identifier's marketing purpose is covered by D's; the interactions' is not, nor by the root purpose
    by_data = {p.data: p.id for p in built.practices}
    compatibility = [q for (kind, _), q in questions.items() if kind == "compatibility"]
    assert [q.record["practice"] for q in compatibility] == [by_data["app-activity.app-interactions"]]
    texts = [p["text"] for p in compatibility[0].context.parts if p["kind"] == "declaration"]
    assert len(texts) == 2 and not any("Purpose)" in t for t in texts)
    assert len([q for (kind, _), q in questions.items() if kind == "minimisation"]) == 2
    # gate 1: a part of D's report that is not marked as a declaration is refused
    passage = {
        "id": "X1",
        "kind": "passage",
        "text": "t",
        "provenance": [{"origin": "d_report", "record": "/claims/1"}],
    }
    with pytest.raises(ContextError, match="only as a declaration"):
        judge.check(Context(spec.context.parts + (passage,)))


def test_readings_apply_the_citation_rule(workspace):
    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    (q,) = [q for q in judge.questions(a, built, found, norms, hypotheses) if q.question == "compatibility"]
    pair = {"specified": "Q1", "factors": [{"factor": "link", "text": "It was declared.", "cites": ["Q1"]}]}
    compatible = judge.compatibility({"pairs": [{**pair, "judgement": "COMPATIBLE"}]}, "s", q)[0]
    assert compatible["judgement"] == "undecided" and compatible["dropped_steps"][0]["step"] == 0
    # a step may cite what was specified to say it is not compatible, but not rest on declarations alone
    incompatible = judge.compatibility({"pairs": [{**pair, "judgement": "NOT_COMPATIBLE"}]}, "s", q)[0]
    assert incompatible["status"] == "not_established" and not incompatible.get("dropped_steps")
    pair["factors"][0]["cites"] = ["Q1", "N1"]
    assert judge.compatibility({"pairs": [{**pair, "judgement": "NOT_COMPATIBLE"}]}, "s", q)[0]["status"] == "supported"


def test_a_refused_answer_names_what_is_missing(workspace):
    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    spec = next(q for q in judge.questions(a, built, found, norms, hypotheses) if q.question == "specificity")
    refused = judge.refusals(
        spec, json.dumps({"statements": [{"statement": "Q1", "steps": [{"cites": ["Z9"]}]}]}), FACTORS
    )
    assert "Q2 is not answered" in refused and any("Z9" in r for r in refused)


def test_the_assessment_states_concerns_ii_to_iv_and_gate_3_holds(workspace):
    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    model = FakeJudge()
    samples = judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=model)
    assert len(samples) == len(model.prompts) == 4  # specificity, one compatibility, two minimisation
    assert all("Personal data to provide" not in p for p in model.prompts if "less invasive" in p)
    report = assess(a.root)
    assert report["report"]["cost"]["model_calls"] == 0
    stated = {(c["step"], c["subject"]): c for c in report["concerns"]}
    interactions = next(p.id for p in built.practices if p.data == "app-activity.app-interactions")
    identifier = next(p.id for p in built.practices if p.data.endswith("advertising-id"))
    vague = stated[("not_specific", "D-1")]
    assert (vague["status"], vague["tier"], vague["observability"]) == ("supported", "reasoning", "E2")
    items = {e["id"]: e for e in report["evidence"]}
    assert {items[x]["kind"] for x in vague["supporting"]} == {"claim", "doc"}  # the declaration and the norm
    assert ("not_specific", "D-2") not in stated
    assessed = {(x, e["requirement"]) for e in report["coverage"] for x in e["assessed"]}
    assert ("D-2", "purpose_specific") in assessed and (identifier, "purpose_specified") in assessed
    # specified purposes for its data, none covering it, judged not compatible: one concern. D-1's statement is judged
    # not specific, so from reading 2 it specifies nothing, and one specified purpose remains (E 0.9, author 18 Nov)
    limited = stated[("no_specified_purpose", interactions)]
    assert (limited["status"], limited["tier"], limited["requirement"]) == (
        "supported",
        "reasoning",
        "purpose_compatible",
    )
    assert len(limited["specified"]) == 1
    minimised = stated[("less_invasive_alternative", identifier)]
    assert minimised["status"] == "supported" and minimised["purpose"].startswith("claim:")
    assert all(items[x]["claim"]["dimension"] == "O" for x in minimised["supporting"] if items[x]["kind"] == "claim")
    assert any(c["role"] == "prompt" and c["stage"] == "assessment" for c in report["report"]["components"])

    # judged compatible, the purpose has no specified purpose concern: compatibility rests on a declaration, dropped
    for path in (a.root / "assessment" / "compatibility").glob("*/s1"):
        for f in path.iterdir():
            f.unlink() if f.is_file() else None
    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=FakeJudge("COMPATIBLE"))
    concern = next(c for c in assess(a.root)["concerns"] if c["step"] == "no_specified_purpose")
    assert concern["status"] == "not_established" and "undecided" in concern["reason"]

    # a tampered stage-2 context that gives D's report other than as a declaration fails the report
    path = next((a.root / "assessment" / "minimisation").glob("*/s1/context.json"))
    parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
    parts.append(
        {"id": "X1", "kind": "passage", "text": "t", "provenance": [{"origin": "d_report", "record": "/claims/1"}]}
    )
    path.write_text(json.dumps({"parts": parts}))
    with pytest.raises(expectation.IndependenceError, match="d_report"):
        assess(a.root)


def test_without_kept_samples_the_tier_is_a_gap(workspace):
    a, _ = workspace
    report = assess(a.root)
    absent = {g["of"] for g in report["gaps"] if g["reason"] == "source_absent"}
    assert absent >= {"purpose_specific", "purpose_compatible", "data_minimised"}
    assert not any(c["tier"] == "reasoning" and c["status"] == "supported" for c in report["concerns"])


def test_the_assessments_provenance_is_complete_its_rebuild_identical_and_tampering_is_found(workspace):
    from skuld import uncertainty
    from skuld.assess import build, identity
    from skuld.provenance import check_assessment

    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=FakeJudge())
    report = assess(a.root)
    rebuilt, members = build(a.root, write=False)
    assert check_assessment(a, report, rebuilt, members) == []
    assert identity(report) == identity(rebuilt)

    # U_n: low for the rule tier, moderate for a judgement citing the norms; premises read no norm
    by_step = {c["step"]: c for c in report["concerns"]}
    assert by_step["information_not_given"]["uncertainty"]["n"] == "low"
    assert by_step["not_specific"]["uncertainty"]["n"] == "moderate"
    # a claim's uncertainty is not stored: the header names the function that determines it
    assert not any("uncertainty" in c for c in report["claims"])
    assert report["report"]["claims"]["determined"]["uncertainty"] == uncertainty.CLAIMS

    # a traffic part's citation names the O claim it shows (as JSON): it resolves like an O claim pointer
    o_ref = next(e["claim"] for e in report["evidence"] if e["kind"] == "claim" and e["claim"]["dimension"] == "O")
    shown = json.loads(json.dumps(report))
    for n, ref_ in enumerate((o_ref, {**o_ref, "claim": "c998"})):
        cid = json.dumps(ref_, sort_keys=True)
        shown["evidence"].append(
            {"id": f"item:t{n}", "kind": "doc", "channel": "rule", "citation": {"id": cid, "at": cid}}
        )
    problems = check_assessment(a, shown)
    assert not any("item:t0" in p for p in problems)
    assert any("item:t1: O claim c998 is unknown" in p for p in problems)

    tampered = json.loads(json.dumps(report))
    o_item = next(e for e in tampered["evidence"] if e["kind"] == "claim" and e["claim"]["dimension"] == "O")
    o_item["claim"]["claim"] = "c999"
    d_item = next(e for e in tampered["evidence"] if e["kind"] == "claim" and e["claim"]["dimension"] == "D")
    d_item["claim"]["claim"] = "policy:/dataDisclosed/999"
    tampered["concerns"][0].setdefault("supporting", []).append("item:9999")
    tampered["claims"][0]["of"].append("launch/s1:p99")
    problems = check_assessment(a, tampered, report, members)
    assert any("O claim c999 is unknown" in p for p in problems)
    assert any("D claim policy:/dataDisclosed/999 is unknown" in p for p in problems)
    assert any("item:9999 is no item" in p for p in problems)
    assert any("launch/s1:p99 is no claim it could combine" in p for p in problems)
    assert any("rebuilt" in p for p in problems)

    answer = next(a.root.glob("assessment/*/*/s1/answer.json"))
    answer.write_text(answer.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert any("its answer does not verify" in p for p in check_assessment(a, report))


def test_the_same_words_on_two_channels_are_one_statement(tmp_path):
    report = d_report()
    notice = json.loads(json.dumps(report["claims"][1]))
    notice["channels"] = ["in_app"]
    notice["evidence"][0]["channel"] = "in_app"
    notice["id"] = "in_app:/dataDisclosed/0"
    report["claims"].append(notice)
    report["channels"].append(
        {"channel": "in_app", "document": "notice", "status": "analysed", "accessible": True, "annotations": []}
    )
    run = run_folder(tmp_path)
    o = tmp_path / "o.json"
    o.write_text(json.dumps(o_report(run.name)))
    d = tmp_path / "d" / "report.json"
    d.parent.mkdir()
    d.write_text(json.dumps(report))
    root = tmp_path / "ws"
    inputs.describe_assessment(root, PACKAGE, "1.0", [(o, run.name)], d, run, corpus_folder(tmp_path))
    a = inputs.load_assessment(root)
    found = judge.statements(a, assessment.build(a, None))
    (shared,) = [s for s in found if s.text == "provide and improve the Service"]
    assert shared.channels == ["policy", "in_app"] and len(shared.declarations) == 2


def test_a_report_of_earlier_components_is_noted_not_failed(workspace):
    """The study's runs under combination rule A (skuld.combine 1) no longer rebuild identically (plan/archive/POST_PAPER_FIXES 3)."""
    import copy

    from skuld.assess import build
    from skuld.provenance import check_assessment, component_changes

    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=FakeJudge())
    report = assess(a.root)
    rebuilt, members = build(a.root, write=False)
    earlier = copy.deepcopy(report)
    combine_ = next(c for c in earlier["report"]["components"] if c["id"] == "skuld.combine")
    combine_["version"] = "1"
    earlier["claims"] = earlier["claims"][1:]  # what the earlier rule gave differs
    assert component_changes(earlier, rebuilt) == [f"skuld.combine 1, now {combine.VERSION}"]
    notes: list[str] = []
    problems = check_assessment(a, earlier, rebuilt, members, notes)
    assert not any("rebuilt" in p for p in problems)
    assert notes == [
        f"assessed under earlier components (skuld.combine 1, now {combine.VERSION}): not rebuilt with the current ones"
    ]
    # with the same components, a difference stays a problem
    same = copy.deepcopy(report)
    same["claims"] = same["claims"][1:]
    assert any("rebuilt from the same inputs" in p for p in check_assessment(a, same, rebuilt, members, []))


def test_check_notes_a_report_of_other_versions_and_rebuilds_one_without_a_notice_definition(workspace):
    """A report that names no notice definition was made with 1.1.0 and rebuilds with it identically; one made by
    another Skuld or Ratatoskr is noted, not refused."""
    from skuld.assess import build
    from skuld.provenance import check_assessment

    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=FakeJudge())
    report = assess(a.root)
    unnamed = json.loads(json.dumps(report))
    unnamed["report"]["components"] = [c for c in unnamed["report"]["components"] if c["id"] != "ratatoskr.notices"]
    rebuilt, members = build(a.root, write=False, notices="1.1.0")
    notes: list[str] = []
    assert check_assessment(a, unnamed, rebuilt, members, notes) == [] and notes == []

    older = json.loads(json.dumps(report))
    older["report"]["skuld"] = "0.0.1"
    rebuilt, members = build(a.root, write=False)
    assert check_assessment(a, older, rebuilt, members, notes) == []
    assert notes and "skuld 0.0.1, now" in notes[0]


def test_readings_compare_as_numbers():
    assert judge.gated("2") and not judge.gated("1")
    with pytest.raises(ValueError):
        judge.gated("10")  # not a known reading; were it one, it would be gated, which "10" >= "2" is not


def test_check_reports_a_folder_with_nothing_to_check_and_an_assessment_not_yet_made(workspace, tmp_path, capsys):
    from skuld import cli

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["check", str(empty)]) == 1
    assert "nothing to check" in capsys.readouterr().err
    a, _ = workspace
    assert cli.main(["check", str(a.root)]) == 1  # assessment.yaml, but no assessment.json yet
    assert "assessment.json: absent" in capsys.readouterr().out
