"""
The expectation stage (E def:stages): what each practice can be expected to serve and need, from what O observed, the
screens around it and documentation, without anything the provider says.

One batch per episode (Q2): the practices that occurred in it, answered each in its own part of the schema; practices
of no known episode form the batch `launch`. From prompt version 6 (KEYED_SINCE, 21 Nov 2026) the answer's purposes and
dependencies are objects keyed by the batch's practice ids, every id required and given at least one purpose
(`answer_schema`), so that constrained decoding (vLLM's guided JSON, Ollama's `format`) makes the model answer every
practice (qwen3.8 answered only the first in 27 of the study's 72 batches); `listed` reads a keyed answer back into the
list shape of earlier prompts' answers, which are still read as they are. From prompt version 7 (ACHIEVED_SINCE) each purpose says
where it is achieved (`achieved_on`: on the device or on a server), which decides the next step of a purpose without
an observable oracle (gaps.oracle_step); a case's purpose may state it, and its statement wins. The batch's screens are those of the episode in the first run that has
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
import logging
import re
import urllib.parse
import zlib
from dataclasses import dataclass, field, replace
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
from skuld.runs import RunRefused, capture_source, load

log = logging.getLogger(__name__)

#: The procedure's version, part of every sample's identity. Not raised on 20 Nov 2026, when a long screen shown again
#: in a row came to be shown once (the context's digest, also part of the identity, re-asks the batches that changes)
#: and a dependency came to name its purpose by id or by a node only one purpose of its practice has (a reading,
#: which re-asks nothing)
VERSION = "4"
PROMPT = "expectation"
PROCEDURE = {"id": "skuld.expectation", "version": VERSION}
#: How the samples' answers are read, apart from VERSION (which identifies the kept samples): 2 since a purpose at no
#: node of the vocabulary has the gap reason purpose_not_in_vocabulary, not purpose_vague (20 Nov 2026); 3: an answer
#: keyed by practice id (prompt version 6) is read as the list it stands for (`listed`, 21 Nov 2026); 4: a purpose says
#: where it is achieved (`achieved_on`, prompt version 7; 21 Nov 2026); 5: a dependency step that cites only the observed
#: traffic (T) is dropped like one citing a practice, since traffic shows that the processing happens, not that it is
#: needed, and a dependency left with no grounded step is own knowledge, at essential and quality_dependent alike (P10
#: fix 3, 21 Nov 2026). A report names its reading, and `skuld check` rebuilds with the one it names (`reading_of`);
#: readings 1 to 4 read as 4 does, as before 5 (their changes were made before a report could name them apart)
READING = "5"
READINGS = ("1", "2", "3", "4", "5")
READING_COMPONENT = {"role": "method", "id": "skuld.expectation.reading", "version": READING}


def reading_component(reading: str = READING) -> dict:
    """The stage-1 reading as a component of a report."""
    if reading not in READINGS:
        raise ValueError(f"unknown reading {reading!r} of skuld.expectation (known: {', '.join(READINGS)})")
    return {**READING_COMPONENT, "version": reading}


def reading_of(report: dict) -> str:
    """The stage-1 reading a report was made with; 4 for one that names none, as the readings before 5 read alike."""
    named = [
        c.get("version")
        for c in report.get("report", {}).get("components", [])
        if c.get("id") == READING_COMPONENT["id"]
    ]
    return named[0] if named else "4"


#: The kinds of part a stage-1 context may hold, each with the origins its provenance may have; never D's report
KINDS = {
    "application": ("input",),
    "practice": ("o_report",),
    # a traffic part read from the capture's latest snapshot also names the snapshot, and why (22 Nov 2026)
    "traffic": ("o_report", "run"),
    "screen": ("run",),
    # from prompt version 10 (DESCRIBED_SINCE): a model's description of a screen (Loki 0.5.0), never cited, and the
    # list of the screenshots attached
    "description": ("run",),
    "images": ("run",),
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
#: The first version of the stage-1 prompts that asks where each purpose is achieved (`achieved_on`: DEVICE or SERVER,
#: required in its answer schema; 21 Nov 2026); an earlier version's purposes do not say, and a case's purpose may
ACHIEVED_SINCE = 7
#: The first version of the stage-1 prompts whose context names, at each passage, the practices of the batch it was
#: retrieved for, and which says that a passage documents only those (21 Nov 2026: 78% of the passages a practice saw
#: in its batch had been retrieved for other practices of the batch); an earlier version's contexts do not
LABELED_SINCE = 8
#: The first version of the stage-1 prompts whose context gives the screens' descriptions (Loki 0.5.0's
#: descriptions.jsonl, by the model `expectation.descriptions` names: "own" for the model asked) as parts never cited,
#: and attaches screenshots of up to 8 of the batch's screens (rerun plan D-37, author 22 Nov 2026); an earlier version's
#: contexts are made as they were
DESCRIBED_SINCE = 10
#: Loki's file of screen descriptions, one line per visit and model
DESCRIPTIONS = "descriptions.jsonl"
#: Why a dependency step is dropped from reading 5: it cites the observed traffic only
TRAFFIC_ONLY = "cites the observed traffic only, which shows that the processing happens, not that it is needed"
#: Where a purpose is achieved, as the answer names it
ACHIEVED_ON = {"DEVICE": "device", "SERVER": "server"}


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


#: The label before a passage of a labelled stage-1 context; `retrieved_for` reads it back (calibrate.stage_one)
RETRIEVED_FOR = re.compile(r"^\(retrieved for ([^)]*)\) ")


def retrieved_label(practices: list[str], text: str) -> str:
    """A passage's text with the practices it was retrieved for named before it."""
    return f"(retrieved for {', '.join(practices)}) {text}"


def retrieved_for(text: str) -> tuple[list[str] | None, str]:
    """The practices a labelled passage names and its text without the label; (None, text) for an unlabelled one."""
    found = RETRIEVED_FOR.match(text)
    if not found:
        return None, text
    return [x.strip() for x in found.group(1).split(",")], text[found.end() :]


def described(prompt_version: str) -> bool:
    """Whether a stage-1 context for a prompt version gives the screens' descriptions and screenshots."""
    return str(prompt_version).isdigit() and int(prompt_version) >= DESCRIBED_SINCE


def describer(model: str | None) -> str | None:
    """The model whose screen descriptions a context gives: config `expectation.descriptions` ("own": the model asked;
    a model's name; unset or null: none)."""
    named = config.load()["expectation"].get("descriptions")
    if not named:
        return None
    return model if named == "own" else str(named)


def descriptions(directory: Path | None, model: str) -> list[dict]:
    """The screen descriptions a run's describer wrote with `model` (Loki 0.5.0's descriptions.jsonl), those without
    an error, in their order; [] where the run has none."""
    path = Path(directory) / DESCRIPTIONS if directory else None
    if path is None or not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("model") == model and not record.get("error") and (record.get("screen") or "").strip():
            out.append(record)
    return out


def description_of(shown: dict, found: list[dict]) -> dict | None:
    """The description of a shown screen: the one of its own visit (`screen_seq` the screen's `seq`), else the latest
    earlier visit of the same screen in the same episode; never one of a visit that is a notice (the shown screen's
    `noticed`, `_notice_visits`), and none for a shown screen whose own visit is one."""
    # gate 1 on the described visit, not only on the shown one (22 Nov 2026): an earlier visit of the same screen may be
    # a notice that Loki recorded, or whose own texts are one
    noticed = shown.get("noticed") or frozenset()
    if shown.get("seq") in noticed:
        return None
    found = [d for d in found if d.get("screen_seq") not in noticed]
    exact = [d for d in found if d.get("screen_seq") == shown.get("seq")]
    if exact:
        return exact[0]
    earlier = [
        d
        for d in found
        if d.get("screen_id") == shown.get("sid")
        and str(d.get("episode")) == str(shown.get("episode"))
        and isinstance(d.get("screen_seq"), int)
        and isinstance(shown.get("seq"), int)
        and d["screen_seq"] < shown["seq"]
    ]
    return max(earlier, key=lambda d: d["screen_seq"]) if earlier else None


def labeled(prompt_version: str) -> bool:
    """Whether a stage-1 context for a prompt version names, at each passage, the practices it was retrieved for."""
    return str(prompt_version).isdigit() and int(prompt_version) >= LABELED_SINCE


def answer_schema(practices: list[str], prompt_version: str | None = None) -> dict:
    """The answer schema of a batch: for a prompt version from KEYED_SINCE on, purposes and dependencies each an object
    whose properties are the batch's practice ids, all required and no other, each a list of the list shape's items
    without `practice` (a practice's purposes at least one); for an earlier version, ANSWER_SCHEMA. Constrained decoders
    enforce required properties, where they often ignore `contains`/`minContains`."""
    version = prompt_version if prompt_version is not None else templates.version(prompt_id())
    if not keyed(version):
        return ANSWER_SCHEMA
    ids = list(dict.fromkeys(practices))
    placed = str(version).isdigit() and int(version) >= ACHIEVED_SINCE

    def by_practice(section: str, at_least: int) -> dict:
        item = _without_practice(ANSWER_SCHEMA["properties"][section]["items"])
        if section == "purposes" and placed:
            item = {
                **item,
                "required": [*item["required"], "achieved_on"],
                "properties": {**item["properties"], "achieved_on": {"enum": list(ACHIEVED_ON)}},
            }
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
    # 0.12.4: per screen of `screens`, its event's seq, episode and screenshot, and whether its texts held a notice
    shown: list[dict] = field(default_factory=list)
    directory: Path | None = None  # the run's folder, for its screenshots and descriptions


def components(practice: Practice) -> dict[str, tuple[str, str]]:
    """A practice's components: its data, and for a transmission to a known recipient its recipient."""
    out = {f"{practice.id}.data": ("D", practice.data)}
    if practice.claim_type == "transmits" and practice.recipient not in (None, "?"):
        out[f"{practice.id}.recipient"] = ("R", practice.recipient)
    return out


def _runs(a: Assessment) -> list:
    """The runs of the assessment's O reports, in order: the exploration, or the case workspace's runs."""
    out, refused = [], []
    for report in a.observations:
        directory = None
        if a.exploration is not None and report.run == a.exploration.name:
            directory = a.exploration
        elif a.cases is not None:
            directory = next((e.directory for e in a.cases.runs if e.id == report.run), None)
        if directory is None:
            continue
        try:
            # an exploration Loki stopped on an error is read if its traffic is usable (22 Nov 2026: com.gamma.scan)
            out.append(load(directory, capture=False, errored=True))
        except RunRefused as e:
            # not silently (22 Nov 2026): a skipped run gives its batches no screens
            log.warning("stage 1 does not use run %s: %s", report.run, e)
            refused.append(f"{report.run} ({e})")
    if refused and not out:
        raise ContextError(f"no run of the assessment can be read, so no batch has its screens: {'; '.join(refused)}")
    return out


def _screens(run, episode: str | None, first: int | None = None) -> list[tuple[str, str]]:
    return [(s["sid"], s["text"]) for s in _shown(run, episode, first)]


def _visit_texts(event: dict, graph: dict) -> list[str]:
    return (
        event["texts"] if event.get("texts") else ctx.screen_text(graph.get(event.get("screen_id")) or {}).split(" | ")
    )


def _notice_visits(run, notices: str | None = None, graph: dict | None = None) -> frozenset:
    """
    The seqs of a run's screen visits that are notices (gate 1): a visit Loki recorded as a notice (a `notice_capture`'s
    `screen_seq`), every visit of the same structure and content keys (Loki records a notice once by the pair, and a
    later visit of it is the same notice), and a visit whose own texts Skuld's notice classifier (by the definition in
    version `notices`) takes for one, whole or in part. Loki's classifier reads the screen scrolled to its end and
    differs from Skuld's, so either suffices (22 Nov 2026: Weather e7 attached a screenshot of a screen Loki recorded as
    a notice, whose first texts held none).
    """
    if graph is None:
        graph = json.loads((run.directory / "graph.json").read_text(encoding="utf-8")).get("screens", {})
    captured = [e for e in run.events if e.get("type") == "notice_capture"]
    seqs = {e.get("screen_seq") for e in captured} - {None}
    pairs = {
        (e.get("exact_key"), e.get("content_key")) for e in captured if e.get("exact_key") and e.get("content_key")
    }
    out = set()
    for event in run.events:
        if event.get("type") != "screen" or event.get("seq") is None:
            continue
        if (
            event["seq"] in seqs
            or (event.get("exact_key"), event.get("content_key")) in pairs
            or classify(_visit_texts(event, graph), notices or NOTICES)
        ):
            out.add(event["seq"])
    return frozenset(out)


def _same_content(event: dict) -> tuple | None:
    """What makes two visits of a screen show the same: its id, Loki's structure and content keys (the content key
    leaves out the texts of lists, so it alone does not do) and its texts; None if a visit lacks any of them."""
    same = (event.get("screen_id"), event.get("exact_key"), event.get("content_key"), event.get("texts"))
    return same if all(same) else None


def _screenshot(event: dict, visits: list[dict], noticed: frozenset) -> str | None:
    """The screenshot of a visit: its own, else the first of another visit that shows the same (`_same_content`);
    none of a visit that is a notice, nor one taken on such a visit (`_notice_visits`)."""
    if event.get("seq") in noticed:
        return None
    if event.get("screenshot"):
        return event["screenshot"]
    same = _same_content(event)
    if same is None:
        return None
    return next(
        (
            v["screenshot"]
            for v in visits
            if v.get("screenshot") and v.get("seq") not in noticed and _same_content(v) == same
        ),
        None,
    )


def _shown(
    run, episode: str | None, first: int | None = None, noticed: frozenset | None = None, notices: str | None = None
) -> list[dict]:
    """The screens of an episode (or the run's first ones) as shown: {sid, text, seq, episode, screenshot, noticed}; a
    screen shown again in a row is shown once, with its first event's seq. The screenshot is one taken on that visit,
    else on another visit that showed the same (`_screenshot`), never of a notice; `noticed` are the run's visits that
    are notices (`_notice_visits`, by the notice definition in version `notices`), whose descriptions are not given."""
    graph = json.loads((run.directory / "graph.json").read_text(encoding="utf-8")).get("screens", {})
    if noticed is None:
        noticed = _notice_visits(run, notices, graph)
    visits = [e for e in run.events if e.get("type") == "screen"]
    shown: list[dict] = []
    for event in visits:
        if episode is not None and str(event.get("episode")) != episode:
            continue
        sid = event.get("screen_id")
        text = " | ".join(event["texts"]) if event.get("texts") else ctx.screen_text(graph.get(sid) or {})
        text = text[:SCREEN_TEXT] if text else text
        if text and (not shown or (shown[-1]["sid"], shown[-1]["text"]) != (sid, text)):
            # 22 Nov 2026: no longer graph.json's screenshot of the screen's first visit, which showed other content
            # where one screen id has many (AccuWeather's WebView home: 82% of the images showed another page)
            shot = _screenshot(event, visits, noticed)
            shown.append(
                {
                    "sid": sid,
                    "text": text,
                    "seq": event.get("seq"),
                    "episode": event.get("episode"),
                    "screenshot": shot,
                    "noticed": noticed,
                }
            )
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
    noticed = {}  # per run, its visits that are notices
    keys = sorted({e for p in subjects.practices for e in p.episodes}, key=lambda e: (e == "?", len(e), e))
    out = []
    for key in keys:
        practices = [p for p in subjects.practices if key in p.episodes]
        screens, run_id, directory = [], None, None
        for run in runs:
            if run.run_id not in noticed:
                noticed[run.run_id] = _notice_visits(run, notices)
            seen = noticed[run.run_id]
            screens = _shown(run, None, LAUNCH_SCREENS, noticed=seen) if key == "?" else _shown(run, key, noticed=seen)
            if screens:
                run_id, directory = run.run_id, run.directory
                break
        kept, shown, left_out = [], [], []
        for screen in screens:
            sid, text = screen["sid"], screen["text"]
            texts = text.split(" | ")
            notice = classify(texts, notices)
            if not notice:
                kept.append((sid, text))
                shown.append({**screen, "notice": False})
                continue
            declared = notice_texts(texts, notices)
            rest = [t for t in texts if t not in declared]
            left_out.append({"screen": sid, "kind": notice[0], "terms": notice[1], "whole": not rest})
            if rest:
                kept.append((sid, " | ".join(rest)))
                # its screenshot and description would show the notice: given its remaining texts only
                shown.append({**screen, "text": " | ".join(rest), "notice": True})
        base = LAUNCH if key == "?" else f"e{key}"
        size = batch_size()
        chunks = [practices[i : i + size] for i in range(0, len(practices), size)] if size else [practices]
        for n, chunk in enumerate(chunks, 1):
            name = base if len(chunks) == 1 else f"{base}.{n}"
            out.append(Batch(name, chunk, run_id, kept[:MAX_SCREENS], left_out, shown[:MAX_SCREENS], directory))
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
    prompt_version: str | None = None,
    model: str | None = None,
) -> Context:
    """The stage-1 context of a batch: the application, its practices as O states them, its screens, passages; with
    `traffic` (config `expectation.traffic`), also each practice's messages as O annotated them. From prompt version 8
    (LABELED_SINCE; `prompt_version`, default the one in force) each passage names the practices it was retrieved for
    (`labeled`); an earlier version's contexts are made as they were, so that its kept samples are found again.

    From version 10 (DESCRIBED_SINCE) the screens come with their descriptions by `describer(model)` (parts of kind
    `description`, never cited: a model's reading of the screen, not what it shows) and with screenshots of up to
    `images.MAX_IMAGES` of them, spread over the batch's screens, never of a screen whose texts held a notice (gate 1):
    each such screen's provenance names its screenshot and the file's digest, and a part of kind `images` lists the
    screens the attached images show, in order (`images_of` reads them back for the request)."""
    names = names or {}
    traffic = traffic_enabled() if traffic is None else traffic
    version = prompt_version if prompt_version is not None else templates.version(prompt_id())
    parts = [
        _part(
            "A1", "application", f"Android application {a.package}, version {a.version}.", ("input", "assessment.yaml")
        )
    ]
    passages: dict = {}  # a passage's file: the passage and the ids of the practices it was retrieved for, in order
    for p in batch.practices:
        part = _part(p.id, "practice", _describe(p, data, names), ("o_report", json.dumps(p.claims[0], sort_keys=True)))
        parts.append(part)
        entity = p.recipient if p.recipient and not p.recipient.startswith("domain:") and p.recipient != "?" else None
        for passage in corpus.about(p.data, entity, data):
            retrieved_for = passages.setdefault(passage.path, (passage, []))[1]
            if p.id not in retrieved_for:
                retrieved_for.append(p.id)
    if traffic:
        shown = _Traffic(a)
        n = 0
        for p in batch.practices:
            for text, ref_, message in shown.of(p, batch.key):
                n += 1
                parts.append(_part(f"T{n}", "traffic", f"{p.id}: {text}", ("o_report", ref_)))
                if pointer := shown.pointer(message):
                    parts[-1]["provenance"].append(pointer)
    screen_parts = []
    for n, (sid, text) in enumerate(batch.screens, 1):
        screen_parts.append(_part(f"S{n}", "screen", text, ("run", f"events.jsonl#screen/{sid}"), batch.run))
    if described(version) and batch.shown and batch.directory is not None:
        parts += _described(batch, screen_parts, describer(model), notices)
    else:
        parts += screen_parts
    for n, (p, retrieved_for) in enumerate(passages.values(), 1):
        text = f"{p.title} ({p.source}): {p.text}"
        if labeled(version):
            text = retrieved_label(retrieved_for, text)
        parts.append(_part(f"D{n}", "passage", text, ("corpus", p.path.name)))
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
        self.snapshot = None  # the snapshot the messages are read from, and why; None for the final export
        self.exploration = a.exploration
        if a.exploration is not None:
            paths = sorted(a.exploration.glob("capture/*/messages.jsonl"))
            if not paths:
                # a run whose final export failed: its latest snapshot, which O annotated (22 Nov 2026: com.gamma.scan)
                meta = _json_or_none(a.exploration / "run.json") or {}
                source = capture_source(a.exploration, meta.get("capture"), _capture_events(a.exploration))
                if source is not None and source["source"] == "snapshot":
                    self.snapshot = source
                    paths = [a.exploration / source["folder"] / "messages.jsonl"]
            for path in paths:
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
            out.append((_message_text(rq, e), ref_, m["id"]))
            if len(out) >= TRAFFIC_MESSAGES:
                break
        if unreadable:
            ref_ = json.dumps(practice.claims[0], sort_keys=True)
            hosts = ", ".join(f"{h} ({r})" for h, r in sorted(unreadable.items())[:6])
            out.append((f"connections whose content could not be read: {hosts}", ref_, None))
        return out

    def pointer(self, message: str | None) -> dict | None:
        """The provenance of a message read from a snapshot: the snapshot, and why; None for the final export's."""
        if self.snapshot is None or message is None:
            return None
        record = f"{self.snapshot['folder']}/messages.jsonl#{message}"
        run = self.exploration.name
        return {"origin": "run", "record": record, "run": run, "capture": "snapshot", "why": self.snapshot["why"]}


def _json_or_none(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _capture_events(directory: Path) -> list[dict]:
    """The `capture` events of a run's events.jsonl, which name its snapshots."""
    try:
        lines = (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [e for e in (json.loads(x) for x in lines if '"capture"' in x) if e.get("type") == "capture"]


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


def _described(batch: Batch, screen_parts: list[dict], model: str | None, notices: str | None) -> list[dict]:
    """The screen parts with their screenshots' digests, each followed by nothing; then the descriptions (never cited)
    and the list of the attached images (DESCRIBED_SINCE)."""
    from skuld import images

    shown = batch.shown[: len(screen_parts)]
    usable, given = [], set()
    for i, s in enumerate(shown):
        if s.get("notice") or not s.get("screenshot") or not (batch.directory / s["screenshot"]).is_file():
            continue
        # one file once per request (22 Nov 2026: AccuWeather sent one screenshot as S2 to S8): the spread is over the
        # screens with a screenshot not given before. By file, not by content: two visits' identical screenshots are
        # each its own screen's
        if s["screenshot"] not in given:
            usable.append(i)
            given.add(s["screenshot"])
    chosen = [usable[j] for j in images.spread(len(usable))]
    for i in chosen:
        path = shown[i]["screenshot"]
        screen_parts[i]["provenance"].append(
            {"origin": "run", "record": path, "run": batch.run, "sha256": images.digest(batch.directory / path)}
        )
    out = list(screen_parts)
    if model:
        found = descriptions(batch.directory, model)
        for i, s in enumerate(shown):
            if s.get("notice"):
                continue  # its description would read the notice (gate 1)
            d = description_of(s, found)
            if d is None:
                continue
            text = f"(about S{i + 1}) {d['screen'].strip()} {(d.get('in_episode') or '').strip()}".strip()
            if classify([d["screen"], d.get("in_episode") or ""], notices or NOTICES):
                continue
            record = f"{DESCRIPTIONS}#visit/{d.get('visit')}/{model}"
            out.append(_part(f"S{i + 1}.d", "description", text, ("run", record), batch.run))
    if chosen:
        ids = ", ".join(f"S{i + 1}" for i in chosen)
        text = (
            f"{len(chosen)} screenshot{'s are' if len(chosen) > 1 else ' is'} attached after this text, in this order: "
            f"{ids}. A screenshot shows its screen as the user saw it; cite the screen's id."
        )
        out.append(_part("images", "images", text, ("run", "screenshots"), batch.run))
    return out


def images_of(given: Context, directory: Path | None) -> list[dict]:
    """The screenshots a context names, in the order its screens list them: {path, sha256, data} with the data shrunk
    for the request (skuld.images.prepare); [] for a context without any."""
    from skuld import images

    if directory is None:
        return []
    named = [
        (pointer["record"], pointer["sha256"])
        for p in given.parts
        if p["kind"] == "screen"
        for pointer in p["provenance"]
        if pointer.get("sha256")
    ]
    if not named:
        return []
    for path, digest in named:
        if images.digest(Path(directory) / path) != digest:
            raise ContextError(f"{path}: the screenshot differs from the one its context names")
    data = images.prepare([Path(directory) / path for path, _ in named])
    return [{"path": path, "sha256": digest, "data": d} for (path, digest), d in zip(named, data, strict=True)]


def check(given: Context, notices: str | None = None) -> None:
    """Gate 1: refuses a part of a kind or origin stage 1 may not give a model, and a screen or a screen's description
    that is a notice (by the notice definition in version `notices`, default NOTICES)."""
    ctx.check(given, KINDS, "stage 1")
    for p in given.parts:
        if p["kind"] == "screen" and classify(p["text"].split(" | "), notices or NOTICES):
            raise ContextError(f"{p['id']}: a notice screen is not given to stage 1")
        if p["kind"] == "description" and classify([p["text"]], notices or NOTICES):
            raise ContextError(f"{p['id']}: a description that reads a notice is not given to stage 1")


SECTIONS = [
    ("The application", "application"),
    ("Practices observed", "practice"),
    ("Traffic of the practices (as captured; the data the observation found is marked «»)", "traffic"),
    ("Screens of this part of the application", "screen"),
    (
        "Descriptions of the screens (a model's reading of each screen in its flow, for orientation only: never cite "
        "a description; cite the screen it is about)",
        "description",
    ),
    ("Screenshots", "images"),
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
    api: str = "openai",
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
        context = assemble(batch, a, corpus, data, names, notices=notices, model=model)
        prompt = template.format(context=render(context), nodes=", ".join(n.id for n in purposes))
        ids = context.ids
        shots = images_of(context, batch.directory) if not offline else _offline_images(context)
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

            def one(
                batch=batch, seed=seed, record=record, prompt=prompt, ids=ids, context=context, shots=shots
            ) -> ask.Sample:
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
                    images=shots,
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
            single = replace(batch, practices=[practice])
            context = assemble(single, a, corpus, data, names, notices=notices, model=model)
            shots = images_of(context, single.directory) if not offline else _offline_images(context)
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
                single=single, seed=seed, record=record, prompt=prompt, context=context, pid=practice.id, shots=shots
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
                    images=shots,
                )
                if sample.text is not None and refused:
                    sample.record["refused"] = refused
                return sample

            jobs.append(one)
    return ask.concurrently(jobs, model) if jobs else []


def _offline_images(given: Context) -> list[dict]:
    """Offline nothing is asked: the images are named (their digests are in the context) but not read."""
    return []


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


def read(
    answer: dict, sample: str, context: Context, practices: dict[str, Practice], reading: str = READING
) -> list[dict]:
    """The claims of one stage-1 sample, by E's status rules, with the citation rule applied; a keyed answer as the list
    it stands for (`listed`); `reading` is the version to read with (READINGS; from 5 a step citing only traffic is
    dropped)."""
    reading_component(reading)
    traffic_only = int(reading) >= 5
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
        if ACHIEVED_ON.get(str(p.get("achieved_on")).upper()):  # prompt version 7 on: where it is achieved
            purpose["achieved_on"] = ACHIEVED_ON[str(p["achieved_on"]).upper()]
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
            elif traffic_only and cites and all(kinds.get(c) == "traffic" for c in cites):
                dropped.append({"step": i, "reason": TRAFFIC_ONLY})
            else:
                steps.append(cites)
        documented = bool(steps) and all(cited(c, ids) for c in steps)
        if basis["purpose"]["specificity"] == "vague":
            status, why, prose = "not_assessable", "purpose_vague", "the purpose is too vague"
        elif value not in FROM_DOCUMENTS:
            status, why, prose = "not_established", "needs_run", "not dependent needs a run without the component"
        elif documented:
            status, why, prose = "supported", None, None
        elif traffic_only and dropped and not steps:
            status, why, prose = "not_established", "own_knowledge", "no step is left that grounds the need"
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
