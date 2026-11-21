"""Tests of the assessment stage's reasoning tier: stage hypotheses, stage-2 contexts (gate 1), readings (gate 2),
concerns (ii), (iv) and (v) and gate 3, end to end."""

import json
import re

import pytest
from ratatoskr.llm import LLMResponse, Provider

from skuld import assessment, combine, corpus, expectation, gaps, inputs, judge
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
    return make_workspace(tmp_path)


def make_workspace(tmp_path, facts: str = ""):
    """The fixtures' workspace; `facts` is added to the documentation passage a.yaml (YAML, its `facts:` key)."""
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
        + facts
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
    assert (vague["status"], vague["tier"]) == ("supported", "reasoning") and "observability" not in vague
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

    # the rule tier: no open judgement, but a silence on channels not exhaustive for the requirement; a judgement of an
    # open term citing the norms: from documents and open
    by_step = {c["step"]: c for c in report["concerns"]}
    assert by_step["information_not_given"]["uncertainty"] == uncertainty.of("silence_not_exhaustive")
    assert by_step["not_specific"]["uncertainty"] == uncertainty.of("from_documents", "open_judgement")
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


def test_a_minimisation_context_holds_the_screens_of_the_practices_episodes_without_notices(workspace, monkeypatch):
    """P10 fix 1 (minimisation prompt 4): what a purpose needs may be read from the screens, which stage 1's batches give
    (the consent dialog and the sign-up form's policy line left out); a context for prompt 3 holds none."""
    from skuld import config, templates
    from tests.test_expectation import CONSENT

    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    by_data = {p.data: p.id for p in built.practices}

    def minimisation():
        return {
            q.subject: q for q in judge.questions(a, built, found, norms, hypotheses) if q.question == "minimisation"
        }

    assert int(templates.version("minimisation")) >= judge.SCREENS_SINCE
    questions = minimisation()
    launch = questions[by_data["device-or-other-ids.advertising-id"]].context
    screens = [p for p in launch.parts if p["kind"] == "screen"]
    assert [p["id"] for p in screens] == ["S1", "S2", "S3"]
    assert [p["text"] for p in screens] == [
        "Welcome | Start your first workout",
        "Create account | Email address",
        "Your plan | Week 1: three sessions",
    ]
    assert all(
        p["provenance"] == [{"origin": "run", "record": p["provenance"][0]["record"], "run": "run-1"}] for p in screens
    )
    assert screens[0]["provenance"][0]["record"] == "events.jsonl#screen/s-home"
    rendered = judge.render(launch)
    assert "## Screens of the episodes where the practice occurred" in rendered
    assert CONSENT[0] not in rendered and "Privacy Policy" not in rendered
    episode = questions[by_data["app-activity.app-interactions"]].context
    assert [p["text"] for p in episode.parts if p["kind"] == "screen"] == ["Your plan | Week 1: three sessions"]
    # gate 1 refuses a notice screen in a stage-2 context, as in stage 1
    notice = {
        "id": "S9",
        "kind": "screen",
        "text": " | ".join(CONSENT),
        "provenance": [{"origin": "run", "record": "x"}],
    }
    with pytest.raises(ContextError, match="notice"):
        judge.check(Context(launch.parts + (notice,)))
    # at most MAX_SCREENS
    monkeypatch.setattr(expectation, "MAX_SCREENS", 2)
    assert len([p for p in minimisation()[launch.parts[1]["id"]].context.parts if p["kind"] == "screen"]) == 2
    # a profile pinning minimisation prompt 3 gets the context without screens, so that its samples are found again
    loaded = dict(config.load())
    monkeypatch.setattr(config, "load", lambda: {**loaded, "prompts": {"minimisation": "3"}})
    assert not [p for q in minimisation().values() for p in q.context.parts if p["kind"] == "screen"]


def test_reading_5_names_each_alternatives_change_and_reading_4_none(workspace):
    """P10 fix 2: the change key the combination groups alternatives by, read from the alternative's text."""
    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    by_id = {h["id"]: h for h in hypotheses}
    by_data = {p.data: p for p in built.practices}
    practice = by_data["device-or-other-ids.advertising-id"]
    (q,) = [
        q
        for q in judge.questions(a, built, found, norms, hypotheses)
        if q.question == "minimisation" and q.subject == practice.id
    ]

    def entry(text):
        return {
            "purpose": "H1",
            "component": f"{practice.id}.data",
            "alternative": text,
            "level": "PLAUSIBLE",
            "steps": [],
        }

    texts = [
        "use an app-generated installation ID instead",
        "remove the advertising ID",
        "store less",
        "use the Android ID or an installation ID",
    ]
    claims = judge.minimisation({"alternatives": [entry(t) for t in texts]}, "s", q, by_id, "5", practice, found)
    assert [c["change_key"] for c in claims] == [
        "replace:device-or-other-ids.installation-id",
        "remove",
        judge.OTHER_CHANGE,
        "replace:device-or-other-ids.android-id,device-or-other-ids.installation-id",
    ]
    old = judge.minimisation({"alternatives": [entry(t) for t in texts]}, "s", q, by_id, "4", practice, found)
    assert not [c for c in old if "change_key" in c]
    assert [{k: v for k, v in c.items() if k != "change_key"} for c in claims] == old


def test_check_rebuilds_a_report_under_the_readings_it_names(workspace, capsys):
    """A report made under judge reading 4 and expectation reading 4 (before P10) is rebuilt by `skuld check` under
    them, not under the current ones, and so identically."""
    from skuld import cli
    from skuld.assess import build

    a, built = workspace
    found, norms, hypotheses = tools(a, built)
    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1], provider=FakeJudge())
    assess(a.root)
    report, _ = build(a.root, reading="4", expectation_reading="4")
    named = {c["id"]: c["version"] for c in report["report"]["components"] if c["id"].endswith(".reading")}
    assert named == {"skuld.judge.reading": "4", "skuld.expectation.reading": "4"}
    assert expectation.reading_of(report) == "4" and expectation.reading_of({"report": {"components": []}}) == "4"
    assert not [c for c in report["claims"] if "change_key" in c]
    capsys.readouterr()
    code = cli.main(["check", str(a.root)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "rebuilt from the same inputs" not in out and "earlier components" not in out


class TypedJudge(FakeJudge):
    """FakeJudge, answering the minimisation question in the typed form (prompt 5): per practice, a removal whose one
    property rests on own knowledge, and for a context with facts processing on the device, whose property cites the
    first fact."""

    async def complete(self, model, prompt, response_format="text", params=None, model_options=None, on_text=None):
        text = prompt.messages[0]["content"]
        if '"gives"' not in text:
            return await super().complete(model, prompt, response_format, params, model_options, on_text)
        self.prompts.append(text)
        ids = re.findall(r"^\[([^\]]+)\]", text, re.M)
        practice = next(i for i in ids if i.startswith("P-"))
        facts = [i for i in ids if re.fullmatch(r"F\d+", i)]

        def alternative(gives, change="REMOVE"):
            return {
                "purpose": "H1",
                "component": f"{practice}.data",
                "change": {"kind": change},
                "alternative": "match installs without the identifier",
                "needs": [{"id": "N1", "requirement": "attribute the install", "cites": ["H1"]}],
                "gives": gives,
                "covers": {"verdict": "COVERS", "steps": [{"text": "met", "cites": ["H1", *facts[:1]]}]},
            }

        # the models word one property differently from seed to seed (P10 trial finding 4): one gap, both as examples
        asked = sum(f"[{practice}]" in p for p in self.prompts)
        wording = ("attribution by campaign", "the campaign of the install")[(asked - 1) % 2]
        answer = [
            alternative(
                [
                    {"property": wording, "cites": ["own knowledge"]},
                    {"property": "lasts until the app is removed", "kind": "persists", "cites": ["own knowledge"]},
                ]
            )
        ]
        if facts:
            answer.append(
                alternative([{"property": "reset by the user", "kind": "persists", "cites": facts[:1]}], "ON_DEVICE")
            )
        return LLMResponse(text=json.dumps({"alternatives": answer}))


def test_a_minimisation_context_for_prompt_5_lists_no_admissible_replacements(workspace, monkeypatch):
    """Minimisation prompt 6 (P10 trial finding 3) adds the admissible replacements to the practice's part, and only
    that; a profile pinning prompt 5 gets the context as 0.12.0 made it, so that its kept samples are found again."""
    from skuld import config

    a, built = workspace
    found, norms, hypotheses = tools(a, built)

    def contexts():
        return {
            q.subject: q.context
            for q in judge.questions(a, built, found, norms, hypotheses)
            if q.question == judge.MINIMISATION
        }

    six = contexts()
    loaded = dict(config.load())
    monkeypatch.setattr(config, "load", lambda: {**loaded, "prompts": {"minimisation": "5"}})
    five = contexts()
    assert six.keys() == five.keys() and six
    data = judge.vocabulary(judge.DATA)
    practices = {p.id: p for p in built.practices}
    for subject, context in five.items():
        assert "Admissible replacements" not in judge.render(context)
        line = " " + judge.admissible(practices[subject], data)
        unlisted = [
            {**p, "text": p["text"].removesuffix(line)} if p["id"] == subject else p for p in six[subject].parts
        ]
        assert six[subject].parts != context.parts and tuple(unlisted) == context.parts
    interactions = next(p.id for p in built.practices if p.data == "app-activity.app-interactions")
    assert f"Admissible replacements of {interactions}.data: app-activity (" in judge.render(six[interactions])


def test_typed_alternatives_from_facts_end_to_end(tmp_path, capsys):
    """Minimisation prompt 5: the context gives a passage's readable facts as F parts after it (a fact whose quote the
    text lacks is left out), the typed answers read into claims with change, needs, gives and covers that the schema
    takes, a give from own knowledge is a fact_missing gap that extends the corpus (gaps 3: one per node and kind, else
    per node and change, its wordings kept as examples), and `skuld check` rebuilds it."""
    from skuld import cli

    a, built = make_workspace(
        tmp_path,
        "facts:\n"
        "  - {about: device-or-other-ids.advertising-id, kind: persists, value: reset, quote: the  advertising ID}\n"
        "  - {about: device-or-other-ids.advertising-id, kind: scope, value: cross-app, quote: not in the text}\n",
    )
    assert [x.split(": ", 1)[1] for x in corpus.problems(corpus.load(a.corpus)) if "facts" in x] == [
        "facts[1]: its quote is not in the passage's text"
    ]
    found, norms, hypotheses = tools(a, built)
    identifier = next(p.id for p in built.practices if p.data.endswith("advertising-id"))
    interactions = next(p.id for p in built.practices if p.data == "app-activity.app-interactions")
    (q,) = [x for x in judge.questions(a, built, found, norms, hypotheses) if x.subject == identifier]
    passages = [p for p in q.context.parts if p["kind"] == "passage"]
    assert [p["id"] for p in passages][:2] == ["D1", "F1"] and "F2" not in q.context.ids
    assert passages[1]["provenance"] == [{"origin": "corpus", "record": "a.yaml", "fact": 0}]
    assert 'persists until reset, as the passage before states it: "the  advertising ID"' in judge.render(q.context)
    assert judge.refusals(q, json.dumps({"alternatives": []}), []) == []
    # prompt 6: the practice lists the admissible replacements of its data component, or none
    shown = q.context.parts[1]
    assert shown["id"] == identifier and f"Admissible replacements of {identifier}.data: " in shown["text"]
    assert "device-or-other-ids.app-set-id (" in shown["text"]
    observed = next(p for p in built.practices if p.id == identifier)
    assert shown["text"].endswith(" " + judge.admissible(observed, judge.vocabulary(judge.DATA)))

    judge.judge(a, built, found, norms, hypotheses, FACTORS, seeds=[1, 2], provider=TypedJudge())
    report = assess(a.root)  # validated against expectation_assessment
    typed = {(c["subject"], c["change_key"]): c for c in report["claims"] if c["type"] == "alternative"}
    assert {(identifier, "remove"), (identifier, "on_device"), (interactions, "remove")} <= set(typed)
    assert typed[(identifier, "on_device")]["status"] == "supported"
    assert typed[(identifier, "on_device")]["change"] == {"kind": "on_device"}
    assert typed[(identifier, "remove")]["sufficiency"]["reason"] == "fact_missing"
    typed = list(typed.values())
    for c in typed:
        assert [n["id"] for n in c["needs"]] == [f"{c['id']}:N1"]
    missing = [g for g in report["gaps"] if g["reason"] == "fact_missing"]
    assert missing and all(g["next"]["kind"] == "extend_corpus" for g in missing)
    # gaps 3: keyed by (node, kind), else by (node, change), the wordings of both seeds kept as examples
    adid = "device-or-other-ids.advertising-id"
    mine = {tuple(sorted((k, v) for k, v in g["fact"].items() if k != "examples")): g for g in missing}
    by_change = mine[(("change", "remove"), ("node", adid))]
    assert sorted(by_change["fact"]["examples"]) == ["attribution by campaign", "the campaign of the install"]
    assert by_change["proposition"].startswith(f"the properties of {adid} that an alternative (remove) gives")
    by_kind = mine[(("kind", "persists"), ("node", adid))]
    assert by_kind["fact"]["examples"] == ["lasts until the app is removed"]
    assert len([g for g in missing if g["fact"]["node"] == adid]) == 2  # not one per wording
    assert all(len(g["fact"].get("examples", [])) <= gaps.EXAMPLES for g in missing)
    from skuld.qualify import nextsteps

    class Index:
        concerns, claims, practices, requirements = {}, {}, {}, {}

    assert nextsteps._gap_step(Index(), by_kind)["target"] == {"node": adid, "kind": "persists"}
    assert nextsteps._gap_step(Index(), by_change)["target"] == {"node": adid, "change": "remove"}
    capsys.readouterr()
    code = cli.main(["check", str(a.root)])
    out = capsys.readouterr().out
    assert code == 0, out
