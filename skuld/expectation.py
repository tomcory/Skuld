"""
The expectation stage (E def:stages): what each practice can be expected to serve and need, from what O observed, the
screens around it and documentation, without anything the provider says.

One batch per episode in which a practice first occurred, so that each practice is asked about once; practices of no
known episode form the batch `launch`. The batch's screens are those of every episode its practices occurred in, in
the first run that has them, with the screens the notice classifier (Ratatoskr's `notices`, R-7) takes for consent dialogs or privacy notices
left out and recorded as left out, so that what D collects as declarations never reaches this stage (gate 1). The
context holds no part of D's report: `check` refuses one.

A sample per batch and seed (`skuld expect`) is kept under expectation/<batch>/s<seed>/ (ask.py); `read` turns an
answer into Purpose and Alternative claims of the expectation stage by E's status rules; the occurrence of a practice,
which the context states, is evidence of neither (gate 2).

    Purpose      supported if specific and a screen or passage of the context shows its outcome, what the processing
                 is for (the practice gives its action and object, and its occurrence shows nothing of what it is
                 for, so citing it does not count); strength own otherwise
    Alternative  per purpose and component, a less invasive way to achieve the purpose: technically supported, and
                 supported, if it cites only the context and a passage among it describes the mechanism; plausible and
                 not established otherwise; a purpose too vague makes it not assessable
"""

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ratatoskr.notices import classify
from ratatoskr.vocabularies import Vocabulary

from skuld import ask, config
from skuld import context as ctx
from skuld.assessment import Practice, Subjects
from skuld.common import DATA, OWN, PURPOSES, cited, ref, vocabulary
from skuld.context import Context, ContextError
from skuld.context import part as _part
from skuld.corpus import Corpus
from skuld.inputs import Assessment
from skuld.runs import RunRefused, load

VERSION = "5"
PROMPT = "expectation"
PROMPT_VERSION = "5"
PROCEDURE = {"id": "skuld.expectation", "version": VERSION}
#: The kinds of part a stage-1 context may hold, each with the origins its provenance may have; never D's report
KINDS = {"application": ("input",), "practice": ("o_report",), "screen": ("run",), "passage": ("corpus",)}
#: Characters of a screen's text shown, and screens of a batch shown at most
SCREEN_TEXT, MAX_SCREENS = 600, 30
#: Attempts per sample: a refused answer is asked once more, with the refusal
ATTEMPTS = 2
#: The answer's beneficiaries as a purpose names them
BENEFICIARY = {"USER": "user", "PROVIDER": "provider", "OTHER": "other"}
#: The screens a batch of practices of no known episode is given: the first ones of the run
LAUNCH_SCREENS = 6
LAUNCH = "launch"

_CITES = {"type": "array", "items": {"type": "string"}}
#: The parts of a purpose (E's tuple); the practice gives its action and object, and the context must show its outcome,
#: what the processing is for, by a screen or a passage (the occurrence of the processing shows nothing of that)
PARTS = ("action", "object", "beneficiary", "context", "outcome")
SHOWN = ("outcome",)
GROUNDS = ("screen", "passage")
ANSWER_SCHEMA = {
    "type": "object",
    "required": ["purposes", "alternatives"],
    "properties": {
        "purposes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["practice", "id", *PARTS, "node", "role", "specific", "cites"],
                "properties": {
                    **{
                        k: {"type": "string"}
                        for k in ("practice", "id", "action", "object", "context", "outcome", "node")
                    },
                    "beneficiary": {"enum": list(BENEFICIARY)},
                    "role": {"enum": ["FUNCTIONAL", "ANCILLARY"]},
                    "specific": {"type": "boolean"},
                    "cites": {"type": "object", "required": list(SHOWN), "properties": {k: _CITES for k in SHOWN}},
                },
            },
        },
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["practice", "purpose", "component", "alternative", "level", "cites"],
                "properties": {
                    "practice": {"type": "string"},
                    "purpose": {"type": "string"},
                    "component": {"type": "string"},
                    "alternative": {"type": "string"},
                    "level": {"enum": ["PLAUSIBLE", "TECHNICALLY_SUPPORTED"]},
                    "cites": _CITES,
                },
            },
        },
    },
}
#: The uncertainty of a stage-1 claim: semantic uncertainty moderate from documents, high from the model's own
#: knowledge; no technique is measured, and a premise claim reads no norm (U_n is its concern's)
FROM_DOC = {"t": "not_applicable", "s": "moderate", "n": "not_applicable"}
FROM_OWN = {**FROM_DOC, "s": "high"}


@dataclass
class Batch:
    key: str
    practices: list[Practice]
    run: str | None
    screens: list[tuple[str, str]] = field(default_factory=list)
    left_out: list[dict] = field(default_factory=list)  # notice screens, with their kind and terms


def components(practice: Practice) -> dict[str, tuple[str, str]]:
    """A practice's components: its data, and for a transmission to a known recipient its recipient."""
    out = {f"{practice.id}.data": ("D", practice.data)}
    if practice.claim_type == "transmits" and practice.recipient not in (None, "?"):
        out[f"{practice.id}.recipient"] = ("R", practice.recipient)
    return out


def _runs(a: Assessment) -> list:
    """The runs of the assessment's O reports, in order: the exploration, or the case workspace's runs."""
    out = []
    for report in a.observations:
        directory = None
        if a.exploration is not None and report.run == a.exploration.name:
            directory = a.exploration
        elif a.cases is not None:
            directory = next((e.directory for e in a.cases.runs if e.id == report.run), None)
        if directory is None:
            continue
        try:
            out.append(load(directory, capture=False))
        except RunRefused:
            continue
    return out


def _screens(run, episode: str | None, first: int | None = None) -> list[tuple[str, str]]:
    graph = json.loads((run.directory / "graph.json").read_text(encoding="utf-8")).get("screens", {})
    shown = []
    for event in run.events:
        if event.get("type") != "screen":
            continue
        if episode is not None and str(event.get("episode")) != episode:
            continue
        sid = event.get("screen_id")
        text = " | ".join(event["texts"]) if event.get("texts") else ctx.screen_text(graph.get(sid) or {})
        if text and (not shown or shown[-1] != (sid, text)):
            shown.append((sid, text[:SCREEN_TEXT]))
        if first is not None and len(shown) >= first:
            break
    return shown


def _order(episode: str) -> tuple:
    return (episode == "?", len(episode), episode)


def batches(a: Assessment, subjects: Subjects) -> list[Batch]:
    """One batch per episode in which a practice first occurred, each practice in one batch only; the batch's screens
    are those of every episode its practices occurred in, the first episode's first, notices left out."""
    runs = _runs(a)
    first: dict[str, list[Practice]] = {}
    for p in subjects.practices:
        episodes = sorted(p.episodes or ["?"], key=_order)
        first.setdefault(episodes[0], []).append(p)
    out = []
    for key in sorted(first, key=_order):
        practices = first[key]
        episodes = [key] + sorted({e for p in practices for e in p.episodes} - {key}, key=_order)
        screens, run_id = [], None
        for run in runs:
            found = []
            for episode in episodes:
                for screen in _screens(run, None, LAUNCH_SCREENS) if episode == "?" else _screens(run, episode):
                    if screen not in found:
                        found.append(screen)
            if found:
                screens, run_id = found, run.run_id
                break
        kept, left_out = [], []
        for sid, text in screens:
            notice = classify(text.split(" | "))
            if notice:
                left_out.append({"screen": sid, "kind": notice[0], "terms": notice[1]})
            else:
                kept.append((sid, text))
        out.append(Batch(LAUNCH if key == "?" else f"e{key}", practices, run_id, kept[:MAX_SCREENS], left_out))
    return out


def _describe(p: Practice, data: Vocabulary, names: dict[str, str]) -> str:
    what = data[p.data].title if p.data in data else p.data
    actor = p.actor.removeprefix("component:") if p.actor.startswith("component:") else p.actor
    by = f", by the embedded component {actor}" if p.actor.startswith("component:") else ""
    if p.claim_type == "transmits":
        if p.recipient in (None, "?"):
            to = "an unidentified recipient"
        elif p.recipient.startswith("domain:"):
            to = f"the domain {p.recipient.removeprefix('domain:')}"
        else:
            kinds = f"; registered as {', '.join(p.recipient_categories)}" if p.recipient_categories else ""
            to = f"{names.get(p.recipient, p.recipient)} (register entity {p.recipient}{kinds})"
        return f"The application sends {what} (data type {p.data}) to {to}{by}."
    verb = {"accesses": "reads", "stores": "stores", "performs": "processes"}.get(p.claim_type, p.claim_type)
    return f"The application {verb} {what} (data type {p.data}) on the device{by}."


def assemble(
    batch: Batch, a: Assessment, corpus: Corpus, data: Vocabulary, names: dict[str, str] | None = None
) -> Context:
    """The stage-1 context of a batch: the application, its practices as O states them, its screens, passages."""
    names = names or {}
    parts = [
        _part(
            "A1", "application", f"Android application {a.package}, version {a.version}.", ("input", "assessment.yaml")
        )
    ]
    passages = []
    for p in batch.practices:
        part = _part(p.id, "practice", _describe(p, data, names), ("o_report", json.dumps(p.claims[0], sort_keys=True)))
        parts.append(part)
        entity = p.recipient if p.recipient and not p.recipient.startswith("domain:") and p.recipient != "?" else None
        for passage in corpus.about(p.data, entity, data):
            if passage not in passages:
                passages.append(passage)
    for n, (sid, text) in enumerate(batch.screens, 1):
        parts.append(_part(f"S{n}", "screen", text, ("run", f"events.jsonl#screen/{sid}"), batch.run))
    for n, p in enumerate(passages, 1):
        parts.append(_part(f"D{n}", "passage", f"{p.title} ({p.source}): {p.text}", ("corpus", p.path.name)))
    context = Context(tuple(parts))
    check(context)
    return context


def check(given: Context) -> None:
    """Gate 1: refuses a part of a kind or origin stage 1 may not give a model, and a screen that is a notice."""
    ctx.check(given, KINDS, "stage 1")
    for p in given.parts:
        if p["kind"] == "screen" and classify(p["text"].split(" | ")):
            raise ContextError(f"{p['id']}: a notice screen is not given to stage 1")


SECTIONS = [
    ("The application", "application"),
    ("Practices observed", "practice"),
    ("Screens of this part of the application", "screen"),
    ("Documentation", "passage"),
]


def render(given: Context) -> str:
    return given.render(SECTIONS)


def prompt_template() -> str:
    return (resources.files("skuld") / "prompts" / f"{PROMPT}.md").read_text(encoding="utf-8")


def sample_folder(root: Path, batch: Batch, seed: int, attempt: int = 1) -> Path:
    """A sample's folder: the first attempt in s<seed>/, a later one in s<seed>/a<attempt>/."""
    folder = root / "expectation" / batch.key / f"s{seed}"
    return folder if attempt == 1 else folder / f"a{attempt}"


def refusals(text: str | None, batch: Batch, ids: set[str]) -> list[str]:
    """What refuses an answer: not JSON, a practice of the batch without a purpose, an unknown practice or component,
    or a citation of an id the context does not hold."""
    try:
        answer = json.loads(text or "")
    except ValueError:
        return ["the answer is not JSON"]
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    practices = {p.id: p for p in batch.practices}
    out = []
    answered = {ref(p.get("practice")) for p in answer.get("purposes") or ()}
    out += [f"practice {pid} has no purpose" for pid in practices if pid not in answered]
    for section in ("purposes", "alternatives"):
        for item in answer.get(section) or ():
            pid = ref(item.get("practice"))
            if pid not in practices:
                out.append(f"{section}: {pid or '(none)'} is not a practice of the context")
                continue
            component = ref(item.get("component"))
            if section != "purposes" and component not in components(practices[pid]):
                out.append(f"{section}: {component or '(none)'} is not a component of {pid}")
            cites = _citations(item.get("cites")) + [c for s in item.get("steps") or () for c in s.get("cites") or ()]
            unknown = {ref(c) for c in cites if ref(c).lower() != OWN} - ids
            if unknown:
                out.append(f"{section} of {pid}: cites {', '.join(sorted(unknown))}, not in the context")
    return sorted(set(out))


def expect(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    seeds: list[int] | None = None,
    model: str | None = None,
    api: str = "ollama",
    offline: bool = False,
    provider=None,
    names: dict[str, str] | None = None,
) -> list[ask.Sample]:
    """The samples of the expectation stage: per batch and seed, kept or asked, as many at a time as the server
    takes."""
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    template = prompt_template()
    seeds = seeds or config.load()["expectation"]["seeds"]
    think = config.load()["expectation"].get("think")
    model = model or a.models["expectation"]
    jobs = []
    for batch in batches(a, subjects):
        context = assemble(batch, a, corpus, data, names)
        prompt = template.format(context=render(context), nodes=", ".join(n.id for n in purposes))
        ids = context.ids
        for seed in seeds:
            record = {
                "batch": batch.key,
                "practices": [p.id for p in batch.practices],
                "run": batch.run,
                "left_out": batch.left_out,
                "procedure": PROCEDURE,
                "prompt": {"id": PROMPT, "version": PROMPT_VERSION, "sha256": ask.sha256(prompt)},
                "corpus": {"sha256": corpus.sha256},
                "context": {"sha256": context.sha256},
            }

            def one(batch=batch, seed=seed, record=record, prompt=prompt, ids=ids, context=context) -> ask.Sample:
                sample, refused, _ = ask.ask_with_feedback(
                    lambda attempt: sample_folder(a.root, batch, seed, attempt),
                    prompt,
                    ANSWER_SCHEMA,
                    lambda asked: {**record, "prompt": {**record["prompt"], "sha256": ask.sha256(asked)}},
                    ("batch", "practices", "procedure", "prompt", "corpus", "context"),
                    lambda text: refusals(text, batch, ids),
                    attempts=ATTEMPTS,
                    seed=seed,
                    model=model,
                    api=api,
                    options=config.options("expect", seed=seed),
                    offline=offline,
                    provider=provider,
                    files={"context.json": json.dumps({"parts": list(context.parts)}, indent=1, ensure_ascii=False)},
                    think=think,
                )
                if sample.text is not None and refused:
                    sample.record["refused"] = refused
                return sample

            jobs.append(one)
    out = ask.concurrently(jobs, model)
    if not offline:
        ask.supersede(a.root / "expectation", {a.root / "expectation" / b.key for b in batches(a, subjects)})
    return out


def _citations(cites) -> list[str]:
    """Every id an item cites: a list, or a purpose's lists per part."""
    if isinstance(cites, dict):
        return [c for k in PARTS for c in cites.get(k) or ()]
    return list(cites or ())


def read(answer: dict, sample: str, context: Context, practices: dict[str, Practice]) -> list[dict]:
    """The claims of one stage-1 sample, by E's status rules, with the citation rule applied."""
    ids = context.ids
    practice_parts = context.of_kind("practice")
    kinds = {p["id"]: p["kind"] for p in context.parts}
    channel = f"reasoning:{sample}"
    claims, purposes = [], {}

    def claim(
        kind: str, subject: str, n: int, status: str, documented: bool, why: str | None, prose: str | None, **fields
    ):
        supported = status == "supported"
        c = {
            "id": f"{sample}:{kind[0]}{n}",
            "type": kind,
            "stage": "expectation",
            "channels": [channel],
            "subject": subject,
            "status": status,
            "supporting": [],
            "challenging": [],
            "strength": "doc" if documented else "own",
            "uncertainty": FROM_DOC if documented else FROM_OWN,
            "sufficiency": {"sufficient": supported, **({} if supported else {"reason": why})},
            **({"reason": prose} if prose and not supported else {}),
            **fields,
        }
        claims.append(c)
        return c

    for n, p in enumerate(answer.get("purposes") or ()):
        practice = ref(p.get("practice"))
        if practice not in practices or not p.get("id"):
            continue
        parts = {k: p.get(k) or "?" for k in PARTS}
        parts["beneficiary"] = BENEFICIARY.get(str(parts["beneficiary"]).upper(), "?")
        specific = bool(p.get("specific")) and all(parts[k] != "?" for k in ("action", "object", "outcome"))
        by_part = p.get("cites") if isinstance(p.get("cites"), dict) else {}
        outcome = [ref(x) for x in by_part.get("outcome") or ()]
        grounds = [x for x in outcome if x in ids and kinds.get(x) in GROUNDS]
        shown = cited(outcome, ids) and bool(grounds)
        purpose = {
            **parts,
            "id": p["id"],
            "node": p.get("node") or "?",
            "role": str(p.get("role") or "?").lower(),
            "specificity": "sufficient" if specific else "vague",
            "provenance": "inferred",
        }
        if not specific:
            status, why, prose = "not_established", "purpose_vague", "too vague"
        elif not shown:
            status, why = "not_established", "own_knowledge"
            prose = "no screen or passage shows its outcome"
        else:
            status, why, prose = "supported", None, None
        c = claim(
            "purpose",
            practice,
            n,
            status,
            shown,
            why,
            prose,
            purpose=purpose,
            parts=sorted(set(grounds)),
        )
        purposes[(practice, p["id"])] = c

    for n, alt in enumerate(answer.get("alternatives") or ()):
        practice, component = ref(alt.get("practice")), ref(alt.get("component"))
        basis = purposes.get((practice, alt.get("purpose")))
        if basis is None or component not in components(practices[practice]):
            continue
        cites = [ref(c) for c in alt.get("cites") or ()]
        documentation = [c for c in cites if kinds.get(c) == "passage"]
        technical = str(alt.get("level")).upper() == "TECHNICALLY_SUPPORTED"
        grounded = cited([c for c in cites if c not in practice_parts], ids)
        documented = technical and grounded and bool(documentation)
        if basis["purpose"]["specificity"] == "vague":
            status, why, prose = "not_assessable", "purpose_vague", "the purpose is too vague"
        elif documented:
            status, why, prose = "supported", None, None
        else:
            status, why, prose = "not_established", "own_knowledge", "no cited document describes the mechanism"
        claim(
            "alternative",
            practice,
            n,
            status,
            grounded,
            why,
            prose,
            component=component,
            alternative=alt.get("alternative", ""),
            level="technically_supported" if documented else "plausible",
            purpose=basis["purpose"],
            basis=[basis["id"]],
            parts=sorted(set(documentation)),
        )
    return claims


def names(registry) -> dict[str, str]:
    """The display names of the register's entities, as stage-1 contexts name recipients; {} without a register.
    `expect` and `kept` must use the same, since the names are part of the context and so of a sample's identity."""
    return {e.id: e.name for e in registry.entities.values()} if registry is not None else {}


def kept(a: Assessment, subjects: Subjects, corpus: Corpus, registry=None) -> list[tuple[str, Context, dict]]:
    """The kept samples of the current batches: (sample name, context, answer), without asking."""
    out = []
    for sample in expect(a, subjects, corpus, offline=True, names=names(registry)):
        if sample.text is None:
            continue
        context = Context(tuple(json.loads((sample.folder / "context.json").read_text(encoding="utf-8"))["parts"]))
        try:
            answer = json.loads(sample.text)
        except ValueError:
            answer = {}
        name = str(sample.folder.relative_to(a.root / "expectation"))
        out.append((name, context, answer if isinstance(answer, dict) else {}))
    return out


class IndependenceError(Exception):
    """Gate 3: a stage-1 sample or claim that reaches anything of D's."""


def independent(root: Path, report: dict) -> list[str]:
    """
    Gate 3 for the expectation stage: every kept stage-1 sample's context holds only parts stage 1 may give (none of
    D's report, no notice screen), and no expectation-stage claim of the report rests on an item of D's.
    """
    problems = []
    for path in sorted((root / "expectation").glob("*/s*/context.json")):
        try:
            check(Context(tuple(json.loads(path.read_text(encoding="utf-8"))["parts"])))
        except ContextError as e:
            problems.append(f"{path.parent.relative_to(root)}: {e}")
    items = {e["id"]: e for e in report.get("evidence", [])}
    for c in report.get("claims", []):
        if c.get("stage") != "expectation":
            continue
        for x in c.get("supporting", []) + c.get("challenging", []):
            if (items.get(x, {}).get("claim") or {}).get("dimension") == "D":
                problems.append(f"{c['id']}: rests on {x}, an item of D's")
    return problems
