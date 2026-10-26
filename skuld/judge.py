"""
The assessment stage's reasoning tier (E def:stages): three questions a model answers about what D specified, against
what O observed and the expectation stage inferred.

    specificity    per batch of D's declared purposes, the statements in the provider's words: whether each is
                   specific, by the norms and guidelines on `purpose_specific`
    compatibility  per practice and inferred purpose that no specified purpose covers (Q7): against each specified
                   purpose of the practice's data, by the factors of compatibility the frame names
    minimisation   per practice with a supported inferred purpose: less invasive alternatives of its components

A context holds the application, the practices as O states them, the expectation stage's combined Purpose claims as
hypotheses (combine.hypotheses), D's declarations of purpose marked as declarations (kind `declaration`, the only kind
that may come from D's report: gate 1) and passages: the norms on the question's requirement (the corpus's norms/),
and for minimisation the corpus's passages on the practice's components. Samples are kept under
assessment/<question>/<subject>/s<seed>/ (ask.py).

The readings apply gate 2: a step citing a declaration may establish what was specified, never that processing is
compatible with a purpose or needed for one, so such a step is dropped, with the reason, from a judgement that a
purpose is compatible and from an alternative. Each reading gives a sample's judgement of one proposition, which the
combination (combine.py) combines across samples like any claim; concerns.py turns the combined judgements into
concerns:

    specificity    not specific, supported if the statement's action, object or outcome is named as lacking and every
                   step cites the context, the statement and a norm among it
    compatibility  per specified purpose: not compatible, supported if a factor step remains and every step cites the
                   context, something other than declarations among it; compatible or undecided names no concern
    minimisation   Alternative claims of the assessment stage: supported if technically supported and every step cites
                   the context, a passage of documentation among it
"""

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ratatoskr import align
from ratatoskr.vocabularies import Vocabulary

from skuld import ask, combine, config, correspondence, expectation
from skuld import context as ctx
from skuld.assessment import Practice, Subjects
from skuld.common import DATA, OWN, PURPOSES, cited, ref, vocabulary
from skuld.context import Context, ContextError
from skuld.context import part as _part
from skuld.corpus import Corpus
from skuld.inputs import Assessment

SPECIFICITY, COMPATIBILITY, MINIMISATION = "specificity", "compatibility", "minimisation"
QUESTIONS = (SPECIFICITY, COMPATIBILITY, MINIMISATION)
#: The context procedure's and the prompt's version per question
VERSIONS = {SPECIFICITY: "1", COMPATIBILITY: "1", MINIMISATION: "2"}
REQUIREMENT = {
    SPECIFICITY: "purpose_specific",
    COMPATIBILITY: "purpose_compatible",
    MINIMISATION: "data_minimised",
}
#: The kinds of part a stage-2 context may hold, each with the origins its provenance may have; D's report only as a
#: declaration
KINDS = {
    "application": ("input",),
    "practice": ("o_report",),
    "hypothesis": ("expectation",),
    "declaration": ("d_report",),
    "passage": ("corpus",),
}
#: Statements per specificity batch, characters of the sentence a statement is quoted with
BATCH, SENTENCE = 20, 400
ATTEMPTS = 2
LACKING = ("action", "object", "outcome")
JUDGED = {"COMPATIBLE": "compatible", "NOT_COMPATIBLE": "not_compatible", "UNDECIDED": "undecided"}
#: The uncertainty of a stage-2 result from documents, and of one the samples disagree on
FROM_DOC = expectation.FROM_DOC

_CITES = {"type": "array", "items": {"type": "string"}}
_STEPS = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["text", "cites"],
        "properties": {"text": {"type": "string"}, "cites": _CITES},
    },
}
SCHEMAS = {
    SPECIFICITY: {
        "type": "object",
        "required": ["statements"],
        "properties": {
            "statements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["statement", "specific", "lacking", "steps"],
                    "properties": {
                        "statement": {"type": "string"},
                        "specific": {"type": "boolean"},
                        "lacking": {"type": "array", "items": {"enum": list(LACKING)}},
                        "steps": _STEPS,
                    },
                },
            }
        },
    },
    COMPATIBILITY: {
        "type": "object",
        "required": ["pairs"],
        "properties": {
            "pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["specified", "judgement", "factors"],
                    "properties": {
                        "specified": {"type": "string"},
                        "judgement": {"enum": list(JUDGED)},
                        "factors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["factor", "text", "cites"],
                                "properties": {
                                    "factor": {"type": "string"},
                                    "text": {"type": "string"},
                                    "cites": _CITES,
                                },
                            },
                        },
                    },
                },
            }
        },
    },
    MINIMISATION: {
        "type": "object",
        "required": ["alternatives"],
        "properties": {
            "alternatives": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["purpose", "component", "alternative", "level", "steps"],
                    "properties": {
                        "purpose": {"type": "string"},
                        "component": {"type": "string"},
                        "alternative": {"type": "string"},
                        "level": {"enum": ["PLAUSIBLE", "TECHNICALLY_SUPPORTED"]},
                        "steps": _STEPS,
                    },
                },
            }
        },
    },
}


@dataclass
class Statement:
    """A declared purpose in the provider's words: one text of a channel, and the declarations that state it."""

    id: str
    channel: str
    text: str
    sentence: str | None
    declarations: list[str]  # D-n
    pointers: list[str]  # /claims/n
    nodes: list[str]


@dataclass
class Specified:
    """A specified purpose: a node D declares as a purpose, with the data it is declared for and its statements."""

    node: str
    declarations: list[str]
    pointers: list[str]
    data: list[str]
    texts: list[str]


@dataclass
class Question:
    question: str
    subject: str  # the folder under assessment/<question>/
    context: Context
    answers: list[str]  # the context ids the answer must name: statements, specified purposes, or nothing
    record: dict = field(default_factory=dict)  # what the sample records besides: practice, purpose, declarations


def _d_claims(a: Assessment) -> list[dict]:
    return a.declaration.load()["claims"] if a.declaration else []


def _sentences(a: Assessment) -> dict[str, list]:
    """The annotated passages of D's documents, by document, where Urda's report keeps them beside itself."""
    out = {}
    folder = a.declaration.path.parent / "annotation" if a.declaration else None
    if folder is None or not folder.is_dir():
        return out
    for path in folder.glob("*.json"):
        try:
            out[path.stem] = json.loads(path.read_text(encoding="utf-8")).get("passages") or []
        except ValueError:
            continue
    return out


def statements(a: Assessment, subjects: Subjects) -> list[Statement]:
    """D's declared purposes with a text in the provider's words, one per channel and text, in D's order."""
    claims, sentences = _d_claims(a), _sentences(a)
    out: dict[tuple, Statement] = {}
    for d in subjects.declarations:
        if d.type != "declares_purpose":
            continue
        claim = claims[int(d.claim["claim"].rsplit("/", 1)[1])]
        for pointer in claim.get("provenance") or ():
            span = pointer.get("span") or {}
            if not span.get("text"):
                continue
            key = (d.channel, span["text"])
            s = out.get(key)
            if s is None:
                unit = span.get("unit")
                passages = sentences.get(pointer.get("document"), [])
                sentence = passages[unit].get("passage") if isinstance(unit, int) and unit < len(passages) else None
                s = out[key] = Statement(f"Q{len(out) + 1}", d.channel, span["text"], sentence, [], [], [])
            if d.id not in s.declarations:
                s.declarations.append(d.id)
                s.pointers.append(d.claim["claim"])
            if isinstance(d.value, str) and d.value not in s.nodes:
                s.nodes.append(d.value)
    return list(out.values())


def specified(subjects: Subjects, said: list[Statement], purposes: Vocabulary) -> list[Specified]:
    """The specified purposes: per node D declares as a purpose (not the vocabulary's root, which says only that there
    is one), the declarations, the data they are declared for and the statements that say it."""
    texts: dict[str, list[str]] = {}
    for st in said:
        for d in st.declarations:
            texts.setdefault(d, []).append(st.text)
    found: dict[str, Specified] = {}
    for d in subjects.declarations:
        if d.type != "declares_purpose" or d.polarity != "+" or not isinstance(d.value, str):
            continue
        if d.value == purposes.root:
            continue
        s = found.setdefault(d.value, Specified(d.value, [], [], [], []))
        s.declarations.append(d.id)
        s.pointers.append(d.claim["claim"])
        if d.data not in s.data:
            s.data.append(d.data)
        for t in texts.get(d.id, []):
            if t not in s.texts:
                s.texts.append(t)
    return list(found.values())


def relevant(practice: Practice, found: list[Specified], data: Vocabulary) -> list[Specified]:
    """The specified purposes declared for the practice's data or a node above it."""
    out = []
    for s in found:
        if any(align.data(practice.data, d, data).kind in (align.EQUAL, align.NARROWER) for d in s.data):
            out.append(s)
    return out


def covering(purpose: dict, found: list[Specified], purposes: Vocabulary) -> list[Specified]:
    """The specified purposes that cover an inferred one: its node, or one above it (E's ≈ toward the nearest node
    above; D's purposes name no beneficiary, so the alignment cannot compare one)."""
    nodes = correspondence.covered(purpose["node"], [s.node for s in found], purposes)
    return [s for s in found if s.node in nodes]


@dataclass
class Limitation:
    """Purpose limitation for a practice and a supported inferred purpose: the specified purposes declared for its
    data, those that cover it, and the compatibility question asked where none does."""

    practice: str
    purpose: dict  # the combined Purpose claim of the expectation stage
    relevant: list[Specified]
    covering: list[Specified]
    question: str | None = None  # the compatibility question's subject


def limitation(subjects: Subjects, said: list[Statement], hypotheses: list[dict]) -> list[Limitation]:
    """Per practice and supported inferred purpose, its specified purposes and those covering it (rule part)."""
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    spec = specified(subjects, said, purposes)
    practices = {p.id: p for p in subjects.practices}
    out = []
    for h in hypotheses:
        if h["type"] != "purpose" or h["status"] != "supported":
            continue
        for_data = relevant(practices[h["subject"]], spec, data)
        covers = covering(h["purpose"], for_data, purposes)
        subject = f"{h['subject']}-{h['id'].rsplit(':', 1)[1]}" if for_data and not covers else None
        out.append(Limitation(h["subject"], h, for_data, covers, subject))
    return out


#: How a purpose's beneficiary reads in a context
WHO = {"user": "the user", "provider": "the provider", "other": "another party"}


def _purpose_text(purpose: dict) -> str:
    who = WHO.get(purpose["beneficiary"], purpose["beneficiary"])
    return (
        f"{purpose['action']} {purpose['object']}, for {who}, in {purpose['context']}, so that "
        f"{purpose['outcome']} (purpose node {purpose['node']}, role {purpose['role']})"
    )


def _application(a: Assessment) -> dict:
    return _part(
        "A1", "application", f"Android application {a.package}, version {a.version}.", ("input", "assessment.yaml")
    )


def _practice(p: Practice, data: Vocabulary, names: dict[str, str]) -> dict:
    components = ", ".join(expectation.components(p))
    text = f"{expectation._describe(p, data, names)} Components: {components}."
    return _part(p.id, "practice", text, ("o_report", json.dumps(p.claims[0], sort_keys=True)))


def _declaration(pid: str, text: str, pointers: list[str]) -> dict:
    return {
        "id": pid,
        "kind": "declaration",
        "text": text,
        "provenance": [{"origin": "d_report", "record": p} for p in pointers],
    }


def _hypothesis(pid: str, text: str, claim: dict) -> dict:
    return _part(pid, "hypothesis", text, ("expectation", claim["id"]))


def _passages(passages, prefix: str, folder: str = "") -> list[dict]:
    return [
        _part(f"{prefix}{n}", "passage", f"{p.title} ({p.source}): {p.text}", ("corpus", f"{folder}{p.path.name}"))
        for n, p in enumerate(passages, 1)
    ]


def questions(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    names: dict[str, str] | None = None,
) -> list[Question]:
    """The questions of the reasoning tier for an assessment, each with its context."""
    names = names or {}
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    out = []

    found = statements(a, subjects)
    for n in range(0, len(found), BATCH):
        batch = found[n : n + BATCH]
        parts = [_application(a)]
        for s in batch:
            quoted = f'"{s.text}" ({s.channel})'
            if s.sentence and s.sentence.strip() != s.text:
                quoted += f', in: "{s.sentence[:SENTENCE]}"'
            parts.append(_declaration(s.id, quoted, s.pointers))
        parts += _passages(norms.on(REQUIREMENT[SPECIFICITY]), "N", "norms/")
        out.append(
            Question(
                SPECIFICITY,
                f"b{n // BATCH + 1}",
                _checked(parts),
                [s.id for s in batch],
                {"statements": {s.id: s.declarations for s in batch}},
            )
        )

    practices = {p.id: p for p in subjects.practices}
    supported = [h for h in hypotheses if h["type"] == "purpose" and h["status"] == "supported"]
    if a.declaration is not None and subjects.comparability.get("comparable") is not False:
        for case in limitation(subjects, found, hypotheses):
            if case.question is None:
                continue
            p, h = practices[case.practice], case.purpose
            parts = [_application(a), _practice(p, data, names), _hypothesis("H1", _purpose_text(h["purpose"]), h)]
            for k, s in enumerate(case.relevant, 1):
                title = purposes[s.node].title if s.node in purposes else s.node
                said = "; ".join(f'"{t}"' for t in s.texts[:3])
                text = f"{title} (purpose node {s.node})" + (f": {said}" if said else "")
                parts.append(_declaration(f"Q{k}", text, s.pointers))
            parts += _passages(norms.on(REQUIREMENT[COMPATIBILITY]), "N", "norms/")
            out.append(
                Question(
                    COMPATIBILITY,
                    case.question,
                    _checked(parts),
                    [f"Q{k}" for k in range(1, len(case.relevant) + 1)],
                    {
                        "practice": p.id,
                        "purpose": h["id"],
                        "specified": {f"Q{k}": s.declarations for k, s in enumerate(case.relevant, 1)},
                    },
                )
            )

    for p in subjects.practices:
        mine = [h for h in supported if h["subject"] == p.id]
        if not mine:
            continue
        parts, hyp = [_application(a), _practice(p, data, names)], {}
        for k, h in enumerate(mine, 1):
            parts.append(_hypothesis(f"H{k}", _purpose_text(h["purpose"]), h))
            hyp[f"H{k}"] = h["id"]
        documentation = []
        for kind, value in expectation.components(p).values():
            for passage in corpus.about(value, None, data) if kind == "D" else corpus.about(None, value, data):
                if passage not in documentation:
                    documentation.append(passage)
        parts += _passages(documentation, "D") + _passages(norms.on(REQUIREMENT[MINIMISATION]), "N", "norms/")
        out.append(
            Question(
                MINIMISATION,
                p.id,
                _checked(parts),
                [],
                {"practice": p.id, "components": list(expectation.components(p)), "purposes": hyp},
            )
        )
    return out


def procedure(question: str) -> dict:
    return {"id": "skuld.judge", "version": VERSIONS[question]}


def _checked(parts: list[dict]) -> Context:
    context = Context(tuple(parts))
    check(context)
    return context


def check(context: Context) -> None:
    """Gate 1 for stage 2: a part of D's report only as a declaration, marked as such; no other kind or origin."""
    ctx.check(context, KINDS, "stage 2")


SECTIONS = [
    ("The application", "application"),
    ("Practices observed", "practice"),
    ("Hypotheses of the expectation stage", "hypothesis"),
    ("Declarations of the provider", "declaration"),
    ("Documentation and norms", "passage"),
]


def render(context: Context) -> str:
    return context.render(SECTIONS)


def prompt(question: Question, factors: list[str]) -> str:
    template = (resources.files("skuld") / "prompts" / f"{question.question}.md").read_text(encoding="utf-8")
    return template.replace("{context}", render(question.context)).replace("{factors}", ", ".join(factors))


def sample_folder(root: Path, question: Question, seed: int, attempt: int = 1) -> Path:
    folder = root / "assessment" / question.question / question.subject / f"s{seed}"
    return folder if attempt == 1 else folder / f"a{attempt}"


def _cites(item: dict) -> list[str]:
    return list(item.get("cites") or ()) + [c for s in item.get("steps") or () for c in s.get("cites") or ()]


def refusals(question: Question, text: str | None, factors: list[str]) -> list[str]:
    """What refuses an answer: not JSON, a statement or specified purpose not answered, an unknown purpose, component
    or factor, a citation of an id the context does not hold."""
    try:
        answer = json.loads(text or "")
    except ValueError:
        return ["the answer is not JSON"]
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    ids, out = question.context.ids, []
    section = {SPECIFICITY: "statements", COMPATIBILITY: "pairs", MINIMISATION: "alternatives"}[question.question]
    items = [i for i in answer.get(section) or () if isinstance(i, dict)]
    key = {SPECIFICITY: "statement", COMPATIBILITY: "specified"}.get(question.question)
    if key:
        answered = {ref(i.get(key)) for i in items}
        out += [f"{x} is not answered" for x in question.answers if x not in answered]
        out += [f"{x} is not in the context" for x in answered - set(question.answers)]
    for i in items:
        cites = _cites(i) + [c for f in i.get("factors") or () for c in f.get("cites") or ()]
        unknown = {ref(c) for c in cites if ref(c).lower() != OWN} - ids
        if unknown:
            out.append(f"{ref(i.get(key)) if key else section}: cites {', '.join(sorted(unknown))}, not in the context")
        if question.question == COMPATIBILITY:
            out += [
                f"{ref(i.get('specified'))}: {f.get('factor')!r} is not a factor ({', '.join(factors)})"
                for f in i.get("factors") or ()
                if f.get("factor") not in factors
            ]
        if question.question == MINIMISATION:
            if ref(i.get("purpose")) not in question.record["purposes"]:
                out.append(f"alternatives: {ref(i.get('purpose')) or '(none)'} is not a purpose of the context")
            if ref(i.get("component")) not in question.record["components"]:
                out.append(
                    f"alternatives: {ref(i.get('component')) or '(none)'} is not a component of {question.record['practice']}"
                )
    return sorted(set(out))


def judge(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    factors: list[str],
    seeds: list[int] | None = None,
    model: str | None = None,
    api: str = "ollama",
    offline: bool = False,
    provider=None,
    names: dict[str, str] | None = None,
    only: tuple[str, ...] = QUESTIONS,
) -> list[tuple[Question, ask.Sample]]:
    """The samples of the reasoning tier: per question and seed, kept or asked."""
    seeds = seeds or config.load()["assessment"]["seeds"]
    model = model or a.models.get("assessment") or a.models["expectation"]
    out = []
    for q in questions(a, subjects, corpus, norms, hypotheses, names):
        if q.question not in only:
            continue
        text = prompt(q, factors)
        for seed in seeds:
            record = {
                "question": q.question,
                "subject": q.subject,
                **q.record,
                "procedure": procedure(q.question),
                "prompt": {"id": q.question, "version": VERSIONS[q.question], "sha256": ask.sha256(text)},
                "corpus": {"sha256": corpus.sha256},
                "norms": {"sha256": norms.sha256},
                "context": {"sha256": q.context.sha256},
            }
            sample, refused, _ = ask.ask_with_feedback(
                lambda attempt, q=q, seed=seed: sample_folder(a.root, q, seed, attempt),
                text,
                SCHEMAS[q.question],
                lambda asked, record=record: {**record, "prompt": {**record["prompt"], "sha256": ask.sha256(asked)}},
                ("question", "subject", "procedure", "prompt", "corpus", "norms", "context"),
                lambda answer, q=q: refusals(q, answer, factors),
                attempts=ATTEMPTS,
                seed=seed,
                model=model,
                api=api,
                options=config.options("judge", seed=seed),
                offline=offline,
                provider=provider,
                files={"context.json": json.dumps({"parts": list(q.context.parts)}, indent=1, ensure_ascii=False)},
            )
            if sample.text is not None and refused:
                sample.record["refused"] = refused
            out.append((q, sample))
    if not offline:
        current = {a.root / "assessment" / q.question / q.subject for q, _ in out}
        for question in only:
            ask.supersede(a.root / "assessment" / question, current)
    return out


def kept(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    factors: list[str],
    names: dict[str, str] | None = None,
) -> list[tuple[str, Question, dict]]:
    """The kept samples of the current questions: (sample name, question, answer), without asking."""
    out = []
    for q, sample in judge(a, subjects, corpus, norms, hypotheses, factors, offline=True, names=names):
        if sample.text is None:
            continue
        try:
            answer = json.loads(sample.text)
        except ValueError:
            answer = {}
        name = str(sample.folder.relative_to(a.root))
        out.append((name, q, answer if isinstance(answer, dict) else {}))
    return out


def _norms(context: Context) -> set[str]:
    return {p["id"] for p in context.parts if p["provenance"][0]["record"].startswith("norms/")}


def _documentation(context: Context) -> set[str]:
    return context.of_kind("passage") - _norms(context)


def _grounded(steps: list[list[str]], ids: set[str]) -> bool:
    return bool(steps) and all(cited(c, ids) for c in steps)


def _judgement(name: str, key: str, status: str, grounded: bool, parts: set[str], reason: str | None, **fields):
    """A sample's judgement of one proposition, as the combination reads it."""
    return {
        "id": f"{name}:{key}",
        "sample": name,
        "channels": [f"reasoning:{name}"],
        "status": status,
        "strength": "doc" if grounded else "own",
        "parts": sorted(parts),
        "reason": reason,
        **fields,
    }


def specificity(answer: dict, name: str, q: Question) -> list[dict]:
    """The judgements of a specificity sample that a statement is not specific, one per statement: supported by the
    rule above; a statement judged specific names no concern (not established)."""
    ids, norms = q.context.ids, _norms(q.context)
    out = []
    for item in answer.get("statements") or ():
        sid = ref(item.get("statement"))
        if sid not in q.answers:
            continue
        steps = [[ref(c) for c in s.get("cites") or ()] for s in item.get("steps") or ()]
        cites = {c for s in steps for c in s}
        lacking = [x for x in item.get("lacking") or () if x in LACKING]
        specific = bool(item.get("specific"))
        grounded = _grounded(steps, ids)
        if specific:
            status, reason = "not_established", "judged specific"
        elif not lacking:
            status, reason = "not_established", "no part of the purpose named as lacking"
        elif not grounded:
            status, reason = "not_established", "a step does not cite the context"
        elif sid not in cites or not cites & norms:
            status, reason = "not_established", "the steps do not cite the statement and a norm"
        else:
            status, reason = "supported", None
        out.append(
            _judgement(
                name,
                sid,
                status,
                grounded,
                cites & ids,
                reason,
                statement=sid,
                declarations=q.record["statements"][sid],
                specific=specific,
                lacking=lacking,
            )
        )
    return out


def compatibility(answer: dict, name: str, q: Question) -> list[dict]:
    """The judgements of a compatibility sample that the inferred purpose is not compatible with a specified one, one
    per specified purpose: supported by the rule above; compatible or undecided names no concern (not established)."""
    ids, declarations = q.context.ids, q.context.of_kind("declaration")
    out = []
    for item in answer.get("pairs") or ():
        qid = ref(item.get("specified"))
        if qid not in q.answers:
            continue
        judgement = JUDGED.get(str(item.get("judgement")).upper(), "undecided")
        steps, dropped = [], []
        for n, f in enumerate(item.get("factors") or ()):
            cites = [ref(c) for c in f.get("cites") or ()]
            if judgement == "compatible" and set(cites) & declarations:
                dropped.append({"step": n, "reason": "cites a declaration as a reason that processing is compatible"})
            else:
                steps.append(cites)
        cited_ = {c for s in steps for c in s}
        grounded = _grounded(steps, ids)
        status, reason = "not_established", f"judged {judgement}"
        if judgement == "not_compatible":
            if not grounded:
                reason = "a factor step does not cite the context"
            elif not cited_ - declarations:
                reason = "the steps cite declarations only"
            else:
                status, reason = "supported", None
        elif judgement == "compatible" and not steps:
            judgement, reason = "undecided", "every step cited a declaration"
        out.append(
            _judgement(
                name,
                qid,
                status,
                grounded,
                cited_ & ids,
                reason,
                specified=qid,
                declarations=q.record["specified"][qid],
                judgement=judgement,
                **({"dropped_steps": dropped} if dropped else {}),
            )
        )
    return out


def minimisation(answer: dict, name: str, q: Question, hypotheses: dict[str, dict]) -> list[dict]:
    """The Alternative claims of a minimisation sample, of the assessment stage and the reasoning tier."""
    ids, documentation = q.context.ids, _documentation(q.context)
    declarations = q.context.of_kind("declaration")
    channel = f"reasoning:{name}"
    out = []
    for n, item in enumerate(answer.get("alternatives") or ()):
        label = ref(item.get("purpose"))
        basis = hypotheses.get(q.record["purposes"].get(label, ""))
        component = ref(item.get("component"))
        if basis is None or component not in q.record["components"]:
            continue
        steps, dropped = [], []
        for i, s in enumerate(item.get("steps") or ()):
            cites = [ref(c) for c in s.get("cites") or ()]
            if set(cites) & declarations:
                dropped.append({"step": i, "reason": "cites a declaration as a reason that processing is needed"})
            else:
                steps.append(cites)
        cites = {c for s in steps for c in s}
        technical = str(item.get("level")).upper() == "TECHNICALLY_SUPPORTED"
        grounded = _grounded(steps, ids)
        documented = technical and grounded and bool(cites & documentation)
        if basis["purpose"]["specificity"] == "vague":
            status, why, reason = "not_assessable", "purpose_vague", "the purpose is too vague"
        elif documented:
            status, why, reason = "supported", None, None
        elif technical:
            status, why = "not_established", "own_knowledge"
            reason = "no step cites documentation of the mechanism, or a step cites nothing"
        else:
            status, why, reason = (
                "not_established",
                "own_knowledge",
                "plausible: no cited document describes the mechanism",
            )
        out.append(
            {
                "id": f"{name}:a{n}",
                "type": "alternative",
                "stage": "assessment",
                "tier": "reasoning",
                "channels": [channel],
                "subject": q.record["practice"],
                "component": component,
                "alternative": item.get("alternative", ""),
                "level": "technically_supported" if documented else "plausible",
                "purpose": basis["purpose"],
                "basis": [basis["id"]],
                "status": status,
                "parts": sorted(cites & ids),
                "supporting": [],
                "challenging": [],
                "strength": "doc" if grounded else "own",
                "uncertainty": FROM_DOC if grounded else expectation.FROM_OWN,
                "sufficiency": {"sufficient": status == "supported", **({"reason": why} if why else {})},
                **({"dropped_steps": dropped} if dropped else {}),
                **({"reason": reason} if reason else {}),
            }
        )
    return out


def stage1(a: Assessment, subjects: Subjects, corpus: Corpus, registry=None) -> list[dict]:
    """The expectation stage's hypotheses from its kept samples, as the assessment reads them."""
    practices = {p.id: p for p in subjects.practices}
    claims = [
        c
        for name, context, answer in expectation.kept(a, subjects, corpus, registry)
        for c in expectation.read(answer, name, context, practices)
    ]
    return combine.hypotheses(claims, combine.Numbers())


def independent(root: Path, report: dict) -> list[str]:
    """Gate 3 for the assessment stage: every kept stage-2 context passes gate 1, and no item supporting an
    assessment-stage claim or a minimisation concern is one of D's. A concern that a purpose is not compatible may
    rest on what D specified; that one is compatible is never stated, and its steps citing declarations are dropped
    by the reading."""
    problems = []
    for path in sorted((root / "assessment").glob("*/*/s*/context.json")):
        try:
            check(Context(tuple(json.loads(path.read_text(encoding="utf-8"))["parts"])))
        except ContextError as e:
            problems.append(f"{path.parent.relative_to(root)}: {e}")
    items = {e["id"]: e for e in report.get("evidence", [])}
    results = [c for c in report.get("claims", []) if c.get("stage") == "assessment"] + [
        c for c in report.get("concerns", []) if c["step"] == "less_invasive_alternative"
    ]
    for c in results:
        for x in c.get("supporting", []):
            if (items.get(x, {}).get("claim") or {}).get("dimension") == "D":
                problems.append(f"{c['id']}: rests on {x}, an item of D's")
    return problems
