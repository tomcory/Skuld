"""
The expectation stage (E def:stages): what each practice can be expected to serve and need, from what O observed, the
screens around it and documentation, without anything the provider says.

One batch per episode (Q2): the practices that occurred in it, answered each in its own part of the schema; practices
of no known episode form the batch `launch`. From prompt version 6 (KEYED_SINCE, 21 Nov 2026) the answer's purposes and
dependencies are objects keyed by the batch's practice ids, every id required and given at least one purpose
(`answer_schema`), so that constrained decoding (vLLM's guided JSON, Ollama's `format`) makes the model answer every
practice (qwen3.8 answered only the first in 27 of the study's 72 batches); `listed` reads a keyed answer back into the
list shape of earlier prompts' answers, which are still read as they are. The batch's screens are those of the episode in the first run that has
them, with what the notice classifier (Ratatoskr's `notices`, R-7) takes for a notice left out and recorded as left
out: a consent dialog's whole screen, a privacy notice's texts that speak of data, the rest of whose screen is kept.
What D collects as declarations, the same texts, never reaches this stage (gate 1). The
context holds no part of D's report: `check` refuses one.

A sample per batch and seed (`skuld expect`) is kept under expectation/<batch>/s<seed>/ (ask.py); `read` turns an
answer into Purpose and Dependency claims of the expectation stage by E's status rules, with the citation rule (gate
2): a step that cites a practice, the occurrence of the processing, as a reason it is needed is dropped, with the
reason. Alternatives are the reasoning tier's (judge.py).

    Purpose      supported if specific and a screen or passage of the context shows its outcome, what the processing
                 is for (the practice gives its action and object, and its occurrence shows nothing of what it is
                 for, so citing it does not count); strength own otherwise
    Dependency   one value per purpose and component: essential or quality_dependent, supported if steps remain and
                 each cites the context; not_dependent needs a run, so it is never supported here; no dependency
                 identified is silence and makes no claim; a purpose too vague makes it not assessable
"""

import base64
import functools
import json
import re
import urllib.parse
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from ratatoskr import notices as notice_rules
from ratatoskr.notices import classify, notice_texts
from ratatoskr.vocabularies import Vocabulary

from skuld import ask, config, templates, uncertainty
from skuld import context as ctx
from skuld.assessment import Practice, Subjects
from skuld.common import DATA, OWN, PURPOSES, cited, ref, vocabulary
from skuld.context import Context, ContextError
from skuld.context import part as _part
from skuld.corpus import Corpus
from skuld.inputs import Assessment
from skuld.runs import RunRefused, load

#: The procedure's version, part of every sample's identity. Not raised on 20 Nov 2026, when a long screen shown again
#: in a row came to be shown once (the context's digest, also part of the identity, re-asks the batches that changes)
#: and a dependency came to name its purpose by id or by a node only one purpose of its practice has (a reading,
#: which re-asks nothing)
VERSION = "4"
PROMPT = "expectation"
PROCEDURE = {"id": "skuld.expectation", "version": VERSION}
#: How the samples' answers are read, apart from VERSION (which identifies the kept samples): 2 since a purpose at no
#: node of the vocabulary has the gap reason purpose_not_in_vocabulary, not purpose_vague (20 Nov 2026); 3: an answer
#: keyed by practice id (prompt version 6) is read as the list it stands for (`listed`, 21 Nov 2026)
READING = "3"
READING_COMPONENT = {"role": "method", "id": "skuld.expectation.reading", "version": READING}
#: The kinds of part a stage-1 context may hold, each with the origins its provenance may have; never D's report
KINDS = {
    "application": ("input",),
    "practice": ("o_report",),
    "traffic": ("o_report",),
    "screen": ("run",),
    "passage": ("corpus",),
}
#: With `expectation.traffic` (a trial, 12 Nov 2026): per practice, up to this many of its messages as O annotated them
TRAFFIC_MESSAGES, TRAFFIC_EXCERPT, TRAFFIC_PATH = 3, 110, 160
TRAFFIC_PROMPT = "expectation_traffic"
#: Characters of a screen's text shown, and screens of a batch shown at most
SCREEN_TEXT, MAX_SCREENS = 600, 30
#: Attempts per sample: a refused answer is asked once more, with the refusal
ATTEMPTS = 2
#: The answer's dependencies as a Dependency claim's value; NO_DEPENDENCY_IDENTIFIED is silence and makes no claim
ANSWERED = {"ESSENTIAL": "essential", "QUALITY_DEPENDENT": "quality_dependent", "NOT_DEPENDENT": "not_dependent"}
SILENT = "NO_DEPENDENCY_IDENTIFIED"
#: Values a document can establish; not_dependent needs a run
FROM_DOCUMENTS = ("essential", "quality_dependent")
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
GROUNDS = ("screen", "passage", "traffic")  # traffic parts exist only with expectation.traffic
_STEPS = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["text", "cites"],
        "properties": {"text": {"type": "string"}, "cites": _CITES},
    },
}
ANSWER_SCHEMA = {
    "type": "object",
    "required": ["purposes", "dependencies"],
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
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["practice", "purpose", "component", "relationship", "steps"],
                "properties": {
                    "practice": {"type": "string"},
                    "purpose": {"type": "string"},
                    "component": {"type": "string"},
                    "relationship": {"enum": [*ANSWERED, SILENT]},
                    "steps": _STEPS,
                },
            },
        },
    },
}
#: The first version of the stage-1 prompts whose answer is keyed by practice id (`answer_schema`); a sample asked with an
#: earlier one (a profile's `prompts`) is asked again with the list shape it was asked with (ANSWER_SCHEMA)
KEYED_SINCE = 6


def _without_practice(item: dict) -> dict:
    """An item of the list shape without its practice, which a keyed answer's key gives."""
    return {
        **item,
        "required": [k for k in item["required"] if k != "practice"],
        "properties": {k: v for k, v in item["properties"].items() if k != "practice"},
    }


def keyed(prompt_version: str) -> bool:
    """Whether answers to a stage-1 prompt version are keyed by practice id."""
    return str(prompt_version).isdigit() and int(prompt_version) >= KEYED_SINCE


def answer_schema(practices: list[str], prompt_version: str | None = None) -> dict:
    """The answer schema of a batch: for a prompt version from KEYED_SINCE on, purposes and dependencies each an object
    whose properties are the batch's practice ids, all required and no other, each a list of the list shape's items
    without `practice` (a practice's purposes at least one); for an earlier version, ANSWER_SCHEMA. Constrained decoders
    enforce required properties, where they often ignore `contains`/`minContains`."""
    if not keyed(prompt_version if prompt_version is not None else templates.version(prompt_id())):
        return ANSWER_SCHEMA
    ids = list(dict.fromkeys(practices))

    def by_practice(section: str, at_least: int) -> dict:
        item = _without_practice(ANSWER_SCHEMA["properties"][section]["items"])
        each = {"type": "array", **({"minItems": at_least} if at_least else {}), "items": item}
        return {
            "type": "object",
            "required": ids,
            "additionalProperties": False,
            "properties": dict.fromkeys(ids, each),
        }

    return {
        "type": "object",
        "required": ["purposes", "dependencies"],
        "properties": {"purposes": by_practice("purposes", 1), "dependencies": by_practice("dependencies", 0)},
    }


def listed(answer):
    """An answer in the list shape: a keyed answer's items each with the practice its key names, in the keys' order;
    an answer in the list shape (an earlier prompt's, as the study's kept samples) as it is."""
    if not isinstance(answer, dict):
        return answer
    out = dict(answer)
    for section in ("purposes", "dependencies"):
        value = answer.get(section)
        if isinstance(value, dict):
            out[section] = [
                {**item, "practice": pid} if isinstance(item, dict) else item
                for pid, items in value.items()
                for item in (items if isinstance(items, list) else [items])
            ]
    return out


#: The uncertainty of a stage-1 claim: moderate from documents, high from the model's own knowledge; no technique is
#: measured, and a premise claim reads no norm (an open judgement is its concern's)
FROM_DOC = uncertainty.of("from_documents")
FROM_OWN = uncertainty.of("own_knowledge")


@dataclass
class Batch:
    key: str
    practices: list[Practice]
    run: str | None
    screens: list[tuple[str, str]] = field(default_factory=list)
    left_out: list[dict] = field(default_factory=list)  # notices, with their kind, terms and whether the whole screen


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
        text = text[:SCREEN_TEXT] if text else text
        if text and (not shown or shown[-1] != (sid, text)):  # a screen shown again in a row is shown once
            shown.append((sid, text))
        if first is not None and len(shown) >= first:
            break
    return shown


#: The version of Ratatoskr's notice definition a new stage-1 context is made with
NOTICES = notice_rules.VERSION
#: The version a report that names none was made with: the reports before Skuld named the definition (19 Nov 2026)
#: were made with 1.1.0 (Ratatoskr up to 0.23.0)
NOTICES_UNNAMED = "1.1.0"


def notices_of(report: dict) -> str:
    """The version of the notice definition a report's stage-1 contexts were made with."""
    named = [
        c.get("version")
        for c in report.get("report", {}).get("components", [])
        if c.get("id") == notice_rules.COMPONENT["id"]
    ]
    return named[0] if named else NOTICES_UNNAMED


def batches(a: Assessment, subjects: Subjects, notices: str | None = None) -> list[Batch]:
    """One batch per episode, with its practices and screens, notices left out (by Ratatoskr's notice definition in
    version `notices`, default NOTICES)."""
    notices = notices or NOTICES
    runs = _runs(a)
    keys = sorted({e for p in subjects.practices for e in p.episodes}, key=lambda e: (e == "?", len(e), e))
    out = []
    for key in keys:
        practices = [p for p in subjects.practices if key in p.episodes]
        screens, run_id = [], None
        for run in runs:
            screens = _screens(run, None, LAUNCH_SCREENS) if key == "?" else _screens(run, key)
            if screens:
                run_id = run.run_id
                break
        kept, left_out = [], []
        for sid, text in screens:
            texts = text.split(" | ")
            notice = classify(texts, notices)
            if not notice:
                kept.append((sid, text))
                continue
            declared = notice_texts(texts, notices)
            rest = [t for t in texts if t not in declared]
            left_out.append({"screen": sid, "kind": notice[0], "terms": notice[1], "whole": not rest})
            if rest:
                kept.append((sid, " | ".join(rest)))
        base = LAUNCH if key == "?" else f"e{key}"
        size = batch_size()
        chunks = [practices[i : i + size] for i in range(0, len(practices), size)] if size else [practices]
        for n, chunk in enumerate(chunks, 1):
            name = base if len(chunks) == 1 else f"{base}.{n}"
            out.append(Batch(name, chunk, run_id, kept[:MAX_SCREENS], left_out))
    return out


def batch_size() -> int | None:
    """config.json's `expectation.batch_size`: at most this many practices per batch, an episode's practices split in
    order into batches `e<episode>.<n>` with the same screens; unset (the default), one batch per episode. qwen3.8
    answered only the first practice of 27 of the study's 72 batches; smaller batches are one remedy to measure."""
    size = config.load()["expectation"].get("batch_size")
    return int(size) if size else None


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


def traffic_enabled() -> bool:
    return bool(config.load()["expectation"].get("traffic"))


def assemble(
    batch: Batch,
    a: Assessment,
    corpus: Corpus,
    data: Vocabulary,
    names: dict[str, str] | None = None,
    traffic: bool | None = None,
    notices: str | None = None,
) -> Context:
    """The stage-1 context of a batch: the application, its practices as O states them, its screens, passages; with
    `traffic` (config `expectation.traffic`), also each practice's messages as O annotated them."""
    names = names or {}
    traffic = traffic_enabled() if traffic is None else traffic
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
    if traffic:
        shown = _Traffic(a)
        n = 0
        for p in batch.practices:
            for text, ref_ in shown.of(p, batch.key):
                n += 1
                parts.append(_part(f"T{n}", "traffic", f"{p.id}: {text}", ("o_report", ref_)))
    for n, (sid, text) in enumerate(batch.screens, 1):
        parts.append(_part(f"S{n}", "screen", text, ("run", f"events.jsonl#screen/{sid}"), batch.run))
    for n, p in enumerate(passages, 1):
        parts.append(_part(f"D{n}", "passage", f"{p.title} ({p.source}): {p.text}", ("corpus", p.path.name)))
    context = Context(tuple(parts))
    check(context, notices)
    return context


class _Traffic:
    """A practice's messages as O annotated them: its O claims' evidence, read back from the exploration's capture."""

    def __init__(self, a: Assessment):
        self.reports = {}
        for ref_ in a.observations:
            try:
                self.reports[ref_.sha256] = ref_.load()
            except OSError:
                continue
        self.messages = {}
        if a.exploration is not None:
            for path in sorted(a.exploration.glob("capture/*/messages.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        m = json.loads(line)
                        self.messages[m["id"]] = m
        self._evidence = {sha: {e["id"]: e for e in r.get("evidence", [])} for sha, r in self.reports.items()}
        self._claims = {sha: {c["id"]: c for c in r.get("claims", [])} for sha, r in self.reports.items()}

    def of(self, practice: Practice, batch: str) -> list[tuple[str, str]]:
        """Up to TRAFFIC_MESSAGES (text, provenance) of a practice, its batch's episode first, one per endpoint and
        path; the connections whose content could not be read, in one line."""
        episode = batch.removeprefix("e").split(".")[0]  # e3.2: the second batch of episode 3
        found, unreadable = [], {}
        for ref_ in practice.claims:
            claim = self._claims.get(ref_.get("report"), {}).get(ref_.get("claim"))
            if not claim:
                continue
            times = {
                c.get("time")
                for c in (claim.get("qualifiers") or {}).get("contexts", [])
                if str(c.get("episode")) == episode
            }
            for eid in claim.get("evidence", []):
                e = self._evidence[ref_["report"]].get(eid)
                p = (e or {}).get("proposition") or {}
                if p.get("kind") != "datum":
                    continue
                if not p.get("message"):
                    if p.get("connection"):
                        host = (p.get("endpoint") or {}).get("host") or "?"
                        unreadable.setdefault(host, p.get("reason") or "not readable")
                    continue
                found.append((p.get("time") not in times, e, json.dumps(ref_, sort_keys=True)))
        out, seen = [], set()
        for _, e, ref_ in sorted(found, key=lambda x: x[0]):
            m = self.messages.get(e["proposition"]["message"])
            if not m:
                continue
            rq = m["http_request"]
            key = (rq.get("host"), (rq.get("path") or "").split("?")[0])
            if key in seen:
                continue
            seen.add(key)
            out.append((_message_text(rq, e), ref_))
            if len(out) >= TRAFFIC_MESSAGES:
                break
        if unreadable:
            ref_ = json.dumps(practice.claims[0], sort_keys=True)
            hosts = ", ".join(f"{h} ({r})" for h, r in sorted(unreadable.items())[:6])
            out.append((f"connections whose content could not be read: {hosts}", ref_))
        return out


def _decoded(rq: dict, field_: str) -> str | None:
    """A field of a request as O's evidence counts its span, for reports made before O's pointers carried excerpts: the
    body base64-decoded and gunzipped, a '#url' field percent-decoded."""
    name, _, how = field_.partition("#")
    if name == "body":
        raw = rq.get("body") or ""
        data = base64.b64decode(raw) if rq.get("body_encoding") == "base64" else raw.encode("utf-8", "replace")
        if data[:2] == b"\x1f\x8b":  # what there is of it: the capture may have truncated a long body
            try:
                data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data)
            except zlib.error:
                pass
        text = data.decode("utf-8", "replace")
    elif name == "path":
        text = rq.get("path") or ""
    elif name.startswith("header:"):
        headers = rq.get("headers") or []
        i = int(name.split(":")[1])
        text = headers[i]["value"] if i < len(headers) else ""
    else:
        return None
    return urllib.parse.unquote_plus(text) if how == "url" else text


def _printable(text: str) -> str:
    return re.sub(r"\s+", " ", "".join(c if c.isprintable() else "·" for c in text))


def _message_text(rq: dict, evidence: dict) -> str:
    """One message: method and URL, and the field with the datum O found marked, or why its content is unknown."""
    p = evidence["proposition"]
    path = rq.get("path") or ""
    head = f"{rq.get('method', '?')} https://{rq.get('host', '?')}{path[:TRAFFIC_PATH]}{'…' if len(path) > TRAFFIC_PATH else ''}"
    provenance = (evidence.get("provenance") or [{}])[0]
    span = provenance.get("span")
    field_ = p.get("field") or provenance.get("field") or "body"
    excerpt = provenance.get("excerpt")
    if excerpt is not None and p.get("identified") is not False:
        # O's excerpt of the decoded text (Verðandi 3.4, Ratatoskr 0.30.0): nothing to decode here
        left = excerpt.get("before", "")[-TRAFFIC_EXCERPT:]
        value, right = excerpt["text"], excerpt.get("after", "")[:TRAFFIC_EXCERPT]
        return f"{head} · {field_}: …{_printable(left)}«{_printable(value)}»{_printable(right)}… ({p.get('node')})"
    text = _decoded(rq, field_)
    if p.get("identified") is False:
        why = {"encrypted_by_application": "encrypted by the application", "binary": "binary", "damaged": "damaged"}
        what = why.get(p.get("reason"), p.get("reason") or "not readable")
        if text is not None and span:
            a, b = span
            return f"{head} · {field_}: …{_printable(text[max(0, a - TRAFFIC_EXCERPT) : a])}«{what}»…"
        return f"{head} · content {what}"
    if text is None or not span:
        return f"{head} · {p.get('node')} found in {field_}"
    a, b = span
    left, value, right = text[max(0, a - TRAFFIC_EXCERPT) : a], text[a:b], text[b : b + TRAFFIC_EXCERPT]
    return f"{head} · {field_.split('#')[0]}: …{_printable(left)}«{_printable(value)}»{_printable(right)}… ({p.get('node')})"


def check(given: Context, notices: str | None = None) -> None:
    """Gate 1: refuses a part of a kind or origin stage 1 may not give a model, and a screen that is a notice (by the
    notice definition in version `notices`, default NOTICES)."""
    ctx.check(given, KINDS, "stage 1")
    for p in given.parts:
        if p["kind"] == "screen" and classify(p["text"].split(" | "), notices or NOTICES):
            raise ContextError(f"{p['id']}: a notice screen is not given to stage 1")


SECTIONS = [
    ("The application", "application"),
    ("Practices observed", "practice"),
    ("Traffic of the practices (as captured; the data the observation found is marked «»)", "traffic"),
    ("Screens of this part of the application", "screen"),
    ("Documentation", "passage"),
]


def render(given: Context) -> str:
    return given.render(SECTIONS)


def prompt_id() -> str:
    return TRAFFIC_PROMPT if traffic_enabled() else PROMPT


def prompt_template() -> str:
    return templates.text(prompt_id())


def topup_enabled() -> bool:
    return bool(config.load()["expectation"].get("topup"))


def topup_folder(root: Path, batch: Batch, seed: int, practice: str, attempt: int = 1) -> Path:
    """A top-up's folder: below its batch's sample, one per practice, a later attempt in a<attempt>/."""
    folder = root / "expectation" / batch.key / f"s{seed}" / "topup" / practice
    return folder if attempt == 1 else folder / f"a{attempt}"


def answered(text: str | None) -> set[str]:
    """The practices an answer gives a purpose for (none for an answer that is not JSON)."""
    try:
        answer = json.loads(text or "")
    except ValueError:
        return set()
    if not isinstance(answer, dict):
        return set()
    return {ref(p.get("practice")) for p in (listed(answer).get("purposes") or ()) if isinstance(p, dict)}


def sample_folder(root: Path, batch: Batch, seed: int, attempt: int = 1) -> Path:
    """A sample's folder: the first attempt in s<seed>/, a later one in s<seed>/a<attempt>/."""
    folder = root / "expectation" / batch.key / f"s{seed}"
    return folder if attempt == 1 else folder / f"a{attempt}"


def refusals(text: str | None, batch: Batch, ids: set[str]) -> list[str]:
    """What refuses an answer: not JSON, a practice of the batch without a purpose, an unknown practice or component,
    a dependency on a purpose the answer does not give its practice, or a citation of an id the context does not
    hold."""
    try:
        answer = json.loads(text or "")
    except ValueError:
        return ["the answer is not JSON"]
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    answer = listed(answer)
    practices = {p.id: p for p in batch.practices}
    out = []
    answered = {ref(p.get("practice")) for p in _items(answer.get("purposes"))}
    given = _purpose_keys(_items(answer.get("purposes")))
    out += [
        f"dependencies of {ref(d.get('practice'))}: {ref(d.get('purpose')) or '(none)'} is not one of its purposes"
        for d in _items(answer.get("dependencies"))
        if ref(d.get("practice")) in practices and (ref(d.get("practice")), ref(d.get("purpose"))) not in given
    ]
    out += [f"practice {pid} has no purpose" for pid in practices if pid not in answered]
    for section in ("purposes", "dependencies"):
        if not isinstance(answer.get(section) or [], list):
            out.append(f"{section} is not a list")
            continue
        for i, item in enumerate(answer.get(section) or ()):
            if not isinstance(item, dict):
                out.append(f"{section}: item {i + 1} is not an object")
                continue
            pid = ref(item.get("practice"))
            if pid not in practices:
                out.append(f"{section}: {pid or '(none)'} is not a practice of the context")
                continue
            component = ref(item.get("component"))
            if section != "purposes" and component not in components(practices[pid]):
                out.append(f"{section}: {component or '(none)'} is not a component of {pid}")
            cites = _citations(item.get("cites")) + [c for s in _items(item.get("steps")) for c in s.get("cites") or ()]
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
    notices: str | None = None,
) -> list[ask.Sample]:
    """The samples of the expectation stage: per batch and seed, kept or asked, as many at a time as the server
    takes. With `expectation.topup` (author, 13 Nov 2026), a batch whose last answer leaves practices without a purpose
    is asked again for each of them alone, with the same screens, passages and prompt (a top-up, below the batch's
    sample): a model may answer only the first practice of a batch, again when asked a second time. The screens are
    those the notice definition in version `notices` (default NOTICES) does not take for notices."""
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    template = prompt_template()
    seeds = seeds or config.load()["expectation"]["seeds"]
    think = config.load()["expectation"].get("think")
    model = model or a.models["expectation"]
    jobs = []
    topups = []  # (batch, seed) of each job, in order, for the top-ups
    made = batches(a, subjects, notices)
    for batch in made:
        context = assemble(batch, a, corpus, data, names, notices=notices)
        prompt = template.format(context=render(context), nodes=", ".join(n.id for n in purposes))
        ids = context.ids
        for seed in seeds:
            record = {
                "batch": batch.key,
                "practices": [p.id for p in batch.practices],
                "run": batch.run,
                "left_out": batch.left_out,
                "procedure": PROCEDURE,
                "prompt": {"id": prompt_id(), "version": templates.version(prompt_id()), "sha256": ask.sha256(prompt)},
                "corpus": {"sha256": corpus.sha256},
                "context": {"sha256": context.sha256},
            }

            def one(batch=batch, seed=seed, record=record, prompt=prompt, ids=ids, context=context) -> ask.Sample:
                sample, refused, _ = ask.ask_with_feedback(
                    lambda attempt: sample_folder(a.root, batch, seed, attempt),
                    prompt,
                    answer_schema(record["practices"], record["prompt"]["version"]),
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
            topups.append((batch, seed))
    out = ask.concurrently(jobs, model)
    if topup_enabled():
        out += _topups(
            a,
            corpus,
            data,
            purposes,
            template,
            names,
            list(zip(topups, out, strict=True)),
            model,
            api,
            offline,
            provider,
            think,
            notices,
        )
    if not offline:
        ask.supersede(a.root / "expectation", {a.root / "expectation" / b.key for b in made})
    return out


def _topups(
    a, corpus, data, purposes, template, names, done, model, api, offline, provider, think, notices=None
) -> list[ask.Sample]:
    """The top-ups of the batches whose last answer leaves practices without a purpose: one per practice and seed."""
    jobs = []
    for (batch, seed), sample in done:
        if sample.text is None:
            continue
        given = answered(sample.text)
        for practice in (p for p in batch.practices if p.id not in given):
            single = Batch(batch.key, [practice], batch.run, batch.screens, batch.left_out)
            context = assemble(single, a, corpus, data, names, notices=notices)
            prompt = template.format(context=render(context), nodes=", ".join(n.id for n in purposes))
            record = {
                "batch": batch.key,
                "practices": [practice.id],
                "topup_of": f"{batch.key}/s{seed}",
                "run": batch.run,
                "left_out": batch.left_out,
                "procedure": PROCEDURE,
                "prompt": {"id": prompt_id(), "version": templates.version(prompt_id()), "sha256": ask.sha256(prompt)},
                "corpus": {"sha256": corpus.sha256},
                "context": {"sha256": context.sha256},
            }

            def one(
                single=single, seed=seed, record=record, prompt=prompt, context=context, pid=practice.id
            ) -> ask.Sample:
                sample, refused, _ = ask.ask_with_feedback(
                    lambda attempt: topup_folder(a.root, single, seed, pid, attempt),
                    prompt,
                    answer_schema(record["practices"], record["prompt"]["version"]),
                    lambda asked: {**record, "prompt": {**record["prompt"], "sha256": ask.sha256(asked)}},
                    ("batch", "practices", "topup_of", "procedure", "prompt", "corpus", "context"),
                    lambda text: refusals(text, single, context.ids),
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
    return ask.concurrently(jobs, model) if jobs else []


def _purpose_keys(purposes: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """How a dependency may name its purpose, to the purpose's (practice, id): by its id, or by its node where only
    one purpose of the practice has that node (the prompt names no purpose id, and the models named about one
    dependency in thirty by the purpose's node, study 2026-11)."""
    keys = {(ref(p.get("practice")), ref(p.get("id"))): (ref(p.get("practice")), ref(p.get("id"))) for p in purposes}
    nodes: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for p in purposes:
        nodes.setdefault((ref(p.get("practice")), ref(p.get("node"))), []).append(
            (ref(p.get("practice")), ref(p.get("id")))
        )
    for k, found in nodes.items():
        if len(set(found)) == 1:
            keys.setdefault(k, found[0])
    return keys


def _items(value) -> list[dict]:
    """The objects of a list an answer gives; nothing for a list the schema did not hold."""
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _citations(cites) -> list[str]:
    """Every id an item cites: a list, or a purpose's lists per part."""
    if isinstance(cites, dict):
        return [c for k in PARTS for c in cites.get(k) or ()]
    return list(cites or ())


@functools.cache
def _purpose_map_file() -> tuple[dict, str | None]:
    named = config.file("purpose_map")  # a path, or {path, sha256} checked against it
    if named is None:
        return {}, None
    path, digest = named
    return json.loads(path.read_text(encoding="utf-8")).get("entries", {}), digest


def purpose_map() -> dict:
    """{invented node: {node, similarity, …}}: config.json's purpose_map file, or none."""
    return _purpose_map_file()[0]


def purpose_map_sha256() -> str | None:
    return _purpose_map_file()[1]


def read(answer: dict, sample: str, context: Context, practices: dict[str, Practice]) -> list[dict]:
    """The claims of one stage-1 sample, by E's status rules, with the citation rule applied; a keyed answer as the list
    it stands for (`listed`)."""
    answer = listed(answer)
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
        if not isinstance(p, dict):  # an answer the schema did not hold; the claims' numbers keep their places
            continue
        practice = ref(p.get("practice"))
        if practice not in practices or not ref(p.get("id")):
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
            "id": ref(p["id"]),
            "node": p.get("node") or "?",
            "role": str(p.get("role") or "?").lower(),
            "specificity": "sufficient" if specific else "vague",
            "provenance": "inferred",
        }
        if purpose["node"] not in vocabulary(PURPOSES) and purpose["node"] != "?":
            # a node the model made up (e.g. "Profiling"): the nearest vocabulary node, where config.json's
            # purpose_map names one (by semantic similarity, study 11 Nov 2026)
            mapped = purpose_map().get(purpose["node"])
            if mapped and mapped.get("node") in vocabulary(PURPOSES):
                purpose["node_given"], purpose["node"] = purpose["node"], mapped["node"]
                purpose["node_mapping"] = {"similarity": mapped.get("similarity"), "map": purpose_map_sha256()}
        if not specific:
            status, why, prose = "not_established", "purpose_vague", "too vague"
        elif purpose["node"] not in vocabulary(PURPOSES):
            # a node the model made up (e.g. "Profiling") that the purpose map does not place can't be related to D's
            # purposes (study 11 Nov 2026); its gap reason since Ratatoskr 0.32.0 (before: purpose_vague)
            status, why, prose = (
                "not_established",
                "purpose_not_in_vocabulary",
                f"{purpose['node']} is not a purpose node",
            )
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
        purposes[(practice, ref(p["id"]))] = c

    by_key = _purpose_keys(_items(answer.get("purposes")))
    for n, d in enumerate(answer.get("dependencies") or ()):
        if not isinstance(d, dict):
            continue
        practice, component = ref(d.get("practice")), ref(d.get("component"))
        value = ANSWERED.get(str(d.get("relationship")).upper())
        key = by_key.get((practice, ref(d.get("purpose"))))
        basis = purposes.get(key) if key else None
        if basis is None or value is None or component not in components(practices[practice]):
            continue
        steps, dropped = [], []
        for i, s in enumerate(d.get("steps") or ()):
            cites = [ref(c) for c in s.get("cites") or ()] if isinstance(s, dict) else []
            if set(cites) & practice_parts:
                dropped.append({"step": i, "reason": "cites the occurrence of a practice as a reason it is needed"})
            else:
                steps.append(cites)
        documented = bool(steps) and all(cited(c, ids) for c in steps)
        if basis["purpose"]["specificity"] == "vague":
            status, why, prose = "not_assessable", "purpose_vague", "the purpose is too vague"
        elif value not in FROM_DOCUMENTS:
            status, why, prose = "not_established", "needs_run", "not dependent needs a run without the component"
        elif documented:
            status, why, prose = "supported", None, None
        else:
            status, why, prose = "not_established", "own_knowledge", "a step does not cite the context"
        claim(
            "dependency",
            practice,
            n,
            status,
            documented,
            why,
            prose,
            component=component,
            relationship=value,
            purpose=basis["purpose"],
            basis=[basis["id"]],
            parts=sorted({x for c in steps for x in c if x in ids}),
            **({"dropped_steps": dropped} if dropped else {}),
        )
    return claims


def names(registry) -> dict[str, str]:
    """The display names of the register's entities, as stage-1 contexts name recipients; {} without a register.
    `expect` and `kept` must use the same, since the names are part of the context and so of a sample's identity."""
    return {e.id: e.name for e in registry.entities.values()} if registry is not None else {}


def kept(
    a: Assessment, subjects: Subjects, corpus: Corpus, registry=None, notices: str | None = None
) -> list[tuple[str, Context, dict]]:
    """The kept samples of the current batches: (sample name, context, answer in the list shape, `listed`), without
    asking; the batches' screens by the notice definition in version `notices` (default NOTICES), as the samples were
    made."""
    out = []
    for sample in expect(a, subjects, corpus, offline=True, names=names(registry), notices=notices):
        if sample.text is None:
            continue
        context = Context(tuple(json.loads((sample.folder / "context.json").read_text(encoding="utf-8"))["parts"]))
        try:
            answer = json.loads(sample.text)
        except ValueError:
            answer = {}
        name = sample.folder.relative_to(a.root / "expectation").as_posix()
        out.append((name, context, listed(answer) if isinstance(answer, dict) else {}))
    return out


class IndependenceError(Exception):
    """Gate 3: a stage-1 sample or claim that reaches anything of D's."""


def independent(root: Path, report: dict) -> list[str]:
    """
    Gate 3 for the expectation stage: every kept stage-1 sample's context holds only parts stage 1 may give (none of
    D's report, no notice screen), and no expectation-stage claim of the report rests on an item of D's.
    """
    problems, notices = [], notices_of(report)
    # every kept context: a batch's per seed, its top-ups' (s<seed>/topup/<practice>/) and the re-asked attempts'
    for path in sorted((root / "expectation").rglob("context.json")):
        try:
            check(Context(tuple(json.loads(path.read_text(encoding="utf-8"))["parts"])), notices)
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
