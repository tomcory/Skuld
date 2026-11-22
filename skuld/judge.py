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
                   the context, a passage of documentation among it; an entry whose alternative names none ("none")
                   states that there is no alternative, and is no Alternative claim (READING 1). Since READING 2, a
                   documented alternative passes three gates (Expectation report 0.9, def:status): (a) its component is
                   identified and the change its text names is less invasive (a removal, or every datum it names
                   coarser than the component's by the data vocabulary: `recognised`, `less_invasive`); (b) a cited
                   passage is about the component (tagged with its datum's node or one above it, or with its
                   recipient's entity or type, never the root); (c) that passage was checked against its source by a
                   person (`verified: {by, date}`). Otherwise the alternative is plausible and not established, with
                   the gate as its reason; gate (d), a majority of the question's samples, is the combination's
                   (combine.alternatives), which from READING 5 counts the samples that propose the same change
                   (`change_key`)

From minimisation prompt version 4 (SCREENS_SINCE) a minimisation context also holds the screens of the episodes the
practice occurred in, as stage 1's batches give them, notices left out (`screens_of`), so that what a purpose needs may
be read from the application.

From minimisation prompt version 5 (TYPED_SINCE, P10 (b)) the question asks for typed arguments, and the context gives
each fact of a documentation passage (corpus.py, `facts`) as a part F<n> right after its passage, with the passage file
as its provenance, worded by its kind ("scope developer", "persists until reinstall": the value is the event that ends
the identifier, "precision 50 m"; `fact_text`). For a data component it also gives, as further F parts after the
documentation, the facts of the corpus's checked passages about each candidate replacement of the datum (`replacements`:
every node configuration.coarser admits, other than the datum and the root), each once, with its own passage as
provenance, so that an alternative can ground what a replacement gives although no passage retrieved for the component
states it (an Android ID's context shows the App Set ID's and the installation ID's facts). From minimisation prompt
version 6 (REPLACEMENTS_SINCE) the practice's part also lists those candidate replacements of its data component as
the admissible ones ("Admissible replacements of P-1.data: <node> (<title>), …", or "none"; `admissible`), and the
prompt says that a REPLACE must name one of them; gate (a) and the refusal still check. Each alternative states:

    change       {kind: REMOVE | REPLACE | ON_DEVICE | NARROWER_RECIPIENT, node?}, node a data node for REPLACE
    alternative  free text, for the reader
    needs        [{id, requirement, kind?, value?, cites}]: what the purpose needs, cited to screens (S) or purposes (H)
    gives        [{property, kind?, value?, cites}]: what the alternative gives, cited to documentation (D) or facts (F)
    covers       {verdict: COVERS | PARTLY | DOES_NOT | UNKNOWN, steps}: whether the gives meet the needs

and reading 5 reads an entry that carries `change` by the typed rule (`typed`), one without it as before:

    gate (a)     from `change`: REMOVE always; REPLACE where its node is coarser than the component's datum
                 (configuration.coarser); ON_DEVICE and NARROWER_RECIPIENT for a recipient, and for a datum only where
                 every gives is grounded. The change key is remove, replace:<node>, on_device or narrower_recipient.
    needs        grounded where each cites screens or purposes only; a cite of the practice or of a declaration is
                 dropped (that the application does something is never a reason it needs to), own knowledge grounds none
    gives        grounded where each cites documentation or facts, a passage among them about the component and
                 checked (gates b, c); a fact about a candidate replacement of the component's datum counts as about
                 the component for gate (b), since it documents the component's alternative, and its passage is the
                 one gate (c) reads; one that cites neither is a fact the fact base lacks (gap reason fact_missing,
                 next step extend_corpus, keyed by the node and the kind, else by the node and the change: gaps 3)
    covers       by rule where the change is a REPLACE, every need has a kind and a value, and the corpus's checked
                 facts give the replacement node a property of each kind (scope: the alternative's reaches the need's;
                 persists: the alternative's lasts at least as long; precision_m: the alternative's is at most the
                 need's): the rule's verdict overrides the model's. Otherwise by the model, with steps that cite the
                 context; the claim's uncertainty is then raised by `covers_by_model`.
    status       supported where gate (a) passes, needs and gives are grounded and covers is COVERS; refuted (a
                 challenging member, no concern) where it is DOES_NOT on grounded needs and gives (and grounded steps
                 or the rule); PARTLY is quality-dependent, which an Alternative claim has no value for: not
                 established, "partly covers"; UNKNOWN not established. The level is technically_supported where
                 supported, else plausible, as before.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ratatoskr import align
from ratatoskr import claims as claim_views
from ratatoskr.vocabularies import Vocabulary

from skuld import ask, combine, config, correspondence, expectation, templates
from skuld import context as ctx
from skuld.assessment import Practice, Subjects
from skuld.common import DATA, OWN, PURPOSES, RECIPIENT_TYPES, cited, ref, vocabulary
from skuld.context import Context, ContextError
from skuld.context import part as _part
from skuld.corpus import FACT_KINDS, ORDERS, Corpus, fact_problems, valid_value
from skuld.inputs import Assessment
from skuld.uncertainty import raised

SPECIFICITY, COMPATIBILITY, MINIMISATION = "specificity", "compatibility", "minimisation"
QUESTIONS = (SPECIFICITY, COMPATIBILITY, MINIMISATION)
#: The context procedure's and the prompt's version per question is the prompt's in force (templates.version; current:
#: specificity 2, compatibility 2, minimisation 3)
#: The readings' own version, apart from the prompts' (the prompts' versions identify the kept samples, so a change of reading must
#: not change them). 1: a minimisation entry whose alternative names none is not an alternative (15 Nov 2026).
#: 2 (18 Nov 2026): specificity first, a declared purpose judged not specific specifies nothing; a documented alternative
#: passes gates (a) to (c) here and (d) in the combination (combine.alternatives). A report names its reading, and a rebuild
#: (`skuld check`) reads with the one it names, so that reports made before a reading changed still rebuild.
#: 3 (20 Nov 2026): a minimisation alternative has the strength and uncertainty of documents only where its steps
#: cite a passage of documentation, not wherever every step cites some part of the context.
#: 4 (20 Nov 2026, the review of 19 Nov): a removal must remove the component and not only shorten its retention
#: ("remove it after the request"), "dropdown" and "without the data … would not work" are none (REMOVAL_4); "no
#: alternatives", "None needed", "No change", "Not applicable – …" and "No alternative is needed; …" name no
#: alternative (_NO_ALTERNATIVE_4); a declared purpose judged not specific specifies nothing only where
#: purpose_specific applies (vague_declarations).
#: 5 (21 Nov 2026, P10 fix 2): each Alternative claim names the change its text makes of the component (`change_key`:
#: "remove", "replace:<node>[,<node>…]" or "other", by `recognised`), and the combination groups alternatives by it as
#: well as by practice, purpose and component, so that gate (d) counts the samples that propose the same change
#: (combine.alternatives). From minimisation prompt 5 (P10 (b), 21 Nov 2026), an entry in the typed form (it carries
#: `change`) is read by `typed`: gate (a) from the change, needs and gives grounded, covers by rule or by the model.
#: Entries of the old form read as before, so that samples of prompts 4 and before are read alike under reading 5.
READING = "5"
READINGS = ("1", "2", "3", "4", "5")


def reading_component(reading: str = READING) -> dict:
    """The reading as a component of a report."""
    if reading not in READINGS:
        raise ValueError(f"unknown reading {reading!r} of skuld.judge (known: {', '.join(READINGS)})")
    return {"role": "method", "id": "skuld.judge.reading", "version": reading}


def gated(reading: str = READING) -> bool:
    """Whether a reading is 2 or later: specificity first, vague declarations, gates (a) to (d). Compared as numbers,
    since "10" sorts before "2" as text."""
    reading_component(reading)
    return int(reading) >= 2


#: Why a documented alternative is not supported, per gate; its sufficiency's reason is the framework's
#: `not_admitted` (documentation that fails a gate is not admitted for the status), and the claim's reason names
#: the gate
GATES = {
    "gate_a_component": "gate (a): the component is not identified "
    "(a datum of unknown kind, or an unresolved recipient)",
    "gate_a_change": "gate (a): the alternative names no change that is less invasive by the configuration's orders "
    "(removing the datum or the recipient, or a datum the vocabulary states to be coarser)",
    "gate_b": "gate (b): no cited passage is about the component (its datum's node or one above it, or its recipient)",
    "gate_c": "gate (c): the cited passage about the component is not checked against its source",
    "gate_a_typed": "gate (a): the change is not less invasive by the configuration's orders (REMOVE; REPLACE by a "
    "data node the vocabulary states to be coarser; ON_DEVICE or NARROWER_RECIPIENT of a recipient, or of a datum only "
    "with every property it gives documented)",
}
#: An alternative that names none: the prompt asks to "give none" for a component without an alternative, which the
#: models wrote as "none", "No less invasive alternative identified." and the like (study 2026-11: gemma 2,411, qwen
#: 560 entries), mostly as plausible, some as technically supported. Not "No recipient: ..." or "No persistent
#: storage; ...", which name one.
_NO_ALTERNATIVE = re.compile(
    r"\s*(none|n/?a|not applicable|nothing|no (?:less invasive |suitable |viable )?alternative\b[^.;]*"
    r"|there is no (?:less invasive )?alternative\b[^.;]*)\s*[.;]?\s*",
    re.IGNORECASE,
)


#: Reading 4 adds what the review of 19 Nov found besides: "no alternatives", "None needed", "No change", "Not
#: applicable – the data is required" and "No alternative is needed; the identifier is essential".
_NO_ALTERNATIVE_4 = re.compile(
    r"\s*(?:none(?: (?:needed|required|necessary))?|n/?a|nothing|no changes?(?: (?:needed|required|necessary))?"
    r"|(?:not applicable|n/?a)(?:\s*[-–—:,;(].*)?"
    r"|no (?:less invasive |suitable |viable |other |further )?alternatives?"
    r"(?: (?:is|are) (?:needed|required|necessary|possible|available|known)\b.*|\b[^.;]*)"
    r"|there (?:is|are) no (?:less invasive )?alternatives?\b[^.;]*)\s*[.;]?\s*",
    re.IGNORECASE | re.DOTALL,
)


def names_alternative(text, reading: str = READING) -> bool:
    """Whether a minimisation entry's alternative names one (see _NO_ALTERNATIVE, from reading 4 _NO_ALTERNATIVE_4)."""
    text = str(text or "")
    pattern = _NO_ALTERNATIVE_4 if int(reading) >= 4 else _NO_ALTERNATIVE
    return bool(text.strip()) and not pattern.fullmatch(text)


REQUIREMENT = {
    SPECIFICITY: "purpose_specific",
    COMPATIBILITY: "purpose_compatible",
    MINIMISATION: "data_minimised",
}
#: The kinds of part a stage-2 context may hold, each with the origins its provenance may have; D's report only as a
#: declaration. A fact of the corpus (F<n>) is a part of kind passage, from its passage's file
KINDS = {
    "application": ("input",),
    "practice": ("o_report",),
    "hypothesis": ("expectation",),
    "declaration": ("d_report",),
    "passage": ("corpus",),
    "screen": ("run",),
    "description": ("run",),  # a screen's description, never cited (DESCRIBED_SINCE)
}
#: The first minimisation prompt version whose context holds the screens of the practice's episodes (P10 fix 1, 21 Nov
#: 2026): what a purpose needs may be read from them. Contexts for an earlier version (a profile's `prompts`) hold none,
#: so that the samples asked with it are found again
SCREENS_SINCE = 4
#: The first minimisation prompt version that asks for typed arguments (`SCHEMAS`, `typed`) and whose context gives the
#: corpus's facts as parts F<n> after their passages (P10 (b), 21 Nov 2026)
TYPED_SINCE = 5
#: The first minimisation prompt version whose context lists, in the practice's part, the admissible replacements of
#: its data component (`admissible`: the nodes `replacements` gives, or none), which a REPLACE must name (P10 trial
#: finding 3, 21 Nov 2026). Contexts for an earlier version list none, so that the samples asked with it are found again
REPLACEMENTS_SINCE = 6
#: The first minimisation prompt version whose context gives, after the screens, their descriptions by the model
#: `expectation.descriptions` names (Loki 0.5.0; never cited: a model's reading of the screen; the rerun plan's D-37,
#: 22 Nov 2026). No screenshots: the minimisation question reads what a purpose needs, which the stage-1 answers and the
#: screens' texts give. Contexts for an earlier version give none, so that the samples asked with it are found again
DESCRIBED_SINCE = 7
#: Statements per specificity batch, characters of the sentence a statement is quoted with
BATCH, SENTENCE = 20, 400
ATTEMPTS = 2


def attempts(question: str) -> int:
    """Attempts per sample of a question: config.json's judge.attempts per question (e.g. {"compatibility": 3}), else
    ATTEMPTS. A later attempt is asked only where the earlier ones were refused, so raising it re-asks only those (12 Nov
    2026: gemma's compatibility answers looping on whitespace to max_tokens)."""
    return int(((config.load().get("judge") or {}).get("attempts") or {}).get(question, ATTEMPTS))


LACKING = ("action", "object", "outcome")
JUDGED = {"COMPATIBLE": "compatible", "NOT_COMPATIBLE": "not_compatible", "UNDECIDED": "undecided"}
#: The uncertainty of a reasoning-tier claim from documents (one that cites none: expectation.FROM_OWN)
FROM_DOC = expectation.FROM_DOC

_CITES = {"type": "array", "items": {"type": "string"}}
#: The typed form's change kinds, as the answer names them and as a claim states them (P10 (b))
CHANGES = {
    "REMOVE": "remove",
    "REPLACE": "replace",
    "ON_DEVICE": "on_device",
    "NARROWER_RECIPIENT": "narrower_recipient",
}
#: Whether an alternative's gives meet its purpose's needs, as the answer names it
VERDICTS = ("COVERS", "PARTLY", "DOES_NOT", "UNKNOWN")
#: The kinds of a need or of what an alternative gives: the fact kinds (corpus.FACT_KINDS), by which a rule compares
#: them, and none
REQUIREMENT_KINDS = (*FACT_KINDS, "none")
_KIND = {"kind": {"enum": list(REQUIREMENT_KINDS)}, "value": {"type": ["string", "number"]}}
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
                    "required": ["purpose", "component", "change", "alternative", "needs", "gives", "covers"],
                    "properties": {
                        "purpose": {"type": "string"},
                        "component": {"type": "string"},
                        "change": {
                            "type": "object",
                            "required": ["kind"],
                            "properties": {"kind": {"enum": list(CHANGES)}, "node": {"type": "string"}},
                        },
                        "alternative": {"type": "string"},
                        "needs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["id", "requirement", "cites"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "requirement": {"type": "string"},
                                    **_KIND,
                                    "cites": _CITES,
                                },
                            },
                        },
                        "gives": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["property", "cites"],
                                "properties": {"property": {"type": "string"}, **_KIND, "cites": _CITES},
                            },
                        },
                        "covers": {
                            "type": "object",
                            "required": ["verdict", "steps"],
                            "properties": {"verdict": {"enum": list(VERDICTS)}, "steps": _STEPS},
                        },
                    },
                },
            }
        },
    },
}
#: The minimisation answer's form up to prompt version 4: free text, an evidence level and free steps
SCHEMA_MINIMISATION_4 = {
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
}


def schema(question: str) -> dict:
    """The answer's form for a question in the prompt version in force: the typed minimisation form from TYPED_SINCE,
    the earlier one before it."""
    if question == MINIMISATION and int(templates.version(MINIMISATION)) < TYPED_SINCE:
        return SCHEMA_MINIMISATION_4
    return SCHEMAS[question]


@dataclass
class Statement:
    """A declared purpose in the provider's words: one text, the channels that state it and their declarations."""

    id: str
    channels: list[str]
    text: str
    sentence: str | None
    declarations: list[str]  # D-n
    pointers: list[str]  # D's claim ids
    nodes: list[str]


@dataclass
class Specified:
    """A specified purpose: a node D declares as a purpose, with the data it is declared for and its statements."""

    node: str
    declarations: list[str]
    pointers: list[str]
    data: list[str]
    texts: list[str]
    unplaced: list[str] = field(default_factory=list)  # its declarations for data D could not place (Urda 2.1.0)


@dataclass
class Question:
    question: str
    subject: str  # the folder under assessment/<question>/
    context: Context
    answers: list[str]  # the context ids the answer must name: statements, specified purposes, or nothing
    record: dict = field(default_factory=dict)  # what the sample records besides: practice, purpose, declarations


def _d_claims(a: Assessment) -> dict[str, dict]:
    """D's claims by id, computed from its derived documents (ratatoskr.claims)."""
    return claim_views.by_id(a.declaration.load()) if a.declaration else {}


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
    """D's declared purposes with a text in the provider's words, one per text (the same words on several channels are
    judged once), in D's order."""
    claims, sentences = _d_claims(a), _sentences(a)
    out: dict[tuple, Statement] = {}
    for d in subjects.declarations:
        if d.type != "declares_purpose":
            continue
        claim = claims[d.claim["claim"]]
        for pointer in claim.get("evidence") or ():
            span = pointer.get("span") or {}
            if not span.get("text"):
                continue
            key = " ".join(span["text"].lower().split())
            s = out.get(key)
            if s is None:
                unit = span.get("unit")
                passages = sentences.get(pointer.get("document"), [])
                sentence = passages[unit].get("passage") if isinstance(unit, int) and unit < len(passages) else None
                s = out[key] = Statement(f"Q{len(out) + 1}", [], span["text"], sentence, [], [], [])
            if d.channel not in s.channels:
                s.channels.append(d.channel)
            if d.id not in s.declarations:
                s.declarations.append(d.id)
                s.pointers.append(d.claim["claim"])
            if isinstance(d.value, str) and d.value not in s.nodes:
                s.nodes.append(d.value)
    return list(out.values())


def specified(
    subjects: Subjects, said: list[Statement], purposes: Vocabulary, vague: frozenset = frozenset()
) -> list[Specified]:
    """The specified purposes: per node D declares as a purpose (not the vocabulary's root, which says only that there
    is one, nor one D could not place), the declarations, the data they are declared for (data D could not place is
    for no data in particular: such declarations are listed apart, `unplaced`) and the statements that say it. A declaration in
    `vague`, whose statement E judged not specific, specifies nothing (E 0.9, def:concern; author 18 Nov 2026)."""
    data_root = vocabulary(DATA).root
    texts: dict[str, list[str]] = {}
    for st in said:
        for d in st.declarations:
            texts.setdefault(d, []).append(st.text)
    found: dict[str, Specified] = {}
    for d in subjects.declarations:
        if d.type != "declares_purpose" or d.polarity != "+" or not isinstance(d.value, str):
            continue
        if d.value == purposes.root or d.id in vague:
            continue
        s = found.setdefault(d.value, Specified(d.value, [], [], [], []))
        s.declarations.append(d.id)
        s.pointers.append(d.claim["claim"])
        if d.unplaced_data(data_root):  # declared for data D could not place: for no data in particular, not all
            s.unplaced.append(d.id)
        elif d.data not in s.data:
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
    # the specified purposes declared for data D could not place, which could be the practice's (Urda 2.1.0): with
    # them, that no purpose is specified for its data, or that none covers it, is undecided
    unplaced: list[Specified] = field(default_factory=list)
    unplaced_covering: list[Specified] = field(default_factory=list)


def limitation(
    subjects: Subjects, said: list[Statement], hypotheses: list[dict], vague: frozenset = frozenset()
) -> list[Limitation]:
    """Per practice and supported inferred purpose, its specified purposes and those covering it (rule part); the
    declarations in `vague` specify nothing."""
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    spec = specified(subjects, said, purposes, vague)
    practices = {p.id: p for p in subjects.practices}
    out = []
    for h in hypotheses:
        if h["type"] != "purpose" or h["status"] != "supported":
            continue
        for_data = relevant(practices[h["subject"]], spec, data)
        covers = covering(h["purpose"], for_data, purposes)
        subject = f"{h['subject']}-{h['id'].rsplit(':', 1)[1]}" if for_data and not covers else None
        unplaced = [s for s in spec if s.unplaced]
        out.append(
            Limitation(h["subject"], h, for_data, covers, subject, unplaced, covering(h["purpose"], unplaced, purposes))
        )
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


def _practice(p: Practice, data: Vocabulary, names: dict[str, str], replaceable: bool = False) -> dict:
    """A practice's part; with `replaceable` (minimisation from REPLACEMENTS_SINCE), followed by the admissible
    replacements of its data component (`admissible`)."""
    components = ", ".join(expectation.components(p))
    text = f"{expectation._describe(p, data, names)} Components: {components}."
    if replaceable:
        text += " " + admissible(p, data)
    return _part(p.id, "practice", text, ("o_report", json.dumps(p.claims[0], sort_keys=True)))


def admissible(p: Practice, data: Vocabulary) -> str:
    """The admissible replacements of a practice's data component, as its part states them: "Admissible replacements
    of P-1.data: <node> (<title>), …." in the vocabulary's order, or "none." where `replacements` gives none."""
    nodes = replacements(p.data, data)
    listed = ", ".join(f"{n.id} ({n.title})" for n in data if n.id in nodes) or "none"
    return f"Admissible replacements of {p.id}.data: {listed}."


def _declaration(pid: str, text: str, pointers: list[str]) -> dict:
    return {
        "id": pid,
        "kind": "declaration",
        "text": text,
        "provenance": [{"origin": "d_report", "record": p} for p in pointers],
    }


def _hypothesis(pid: str, text: str, claim: dict) -> dict:
    return _part(pid, "hypothesis", text, ("expectation", claim["id"]))


def screens_of(a: Assessment, subjects: Subjects, notices: str | None = None) -> dict[str, list[tuple]]:
    """Per practice, the screens of its episodes as the expectation stage's batches give them (expectation.batches:
    the episode's in the first run that has them, notices left out by the notice definition in version `notices`),
    as (run, screen id, text, shown, directory), each screen once (by run and id, and by text), at most
    expectation.MAX_SCREENS; `shown` is the screen's seq, episode and notice flag (expectation.Batch.shown)."""
    out: dict[str, list[tuple]] = {}
    for batch in expectation.batches(a, subjects, notices):
        for p in batch.practices:
            mine = out.setdefault(p.id, [])
            for i, (sid, text) in enumerate(batch.screens):
                if len(mine) < expectation.MAX_SCREENS and not any(
                    (r, s) == (batch.run, sid) or x == text for r, s, x, *_ in mine
                ):
                    shown = batch.shown[i] if i < len(batch.shown) else {}
                    mine.append((batch.run, sid, text, shown, batch.directory))
    return out


def _screens(screens: list[tuple], describer: str | None = None, notices: str | None = None) -> list[dict]:
    """The screens as parts S<n>; with `describer`, each followed by its description by that model, never cited
    (DESCRIBED_SINCE), none of a screen whose texts held a notice nor one that reads a notice."""
    out = []
    found: dict = {}
    for n, (run, sid, text, *rest) in enumerate(screens, 1):
        out.append(_part(f"S{n}", "screen", text, ("run", f"events.jsonl#screen/{sid}"), run))
        shown, directory = (rest + [{}, None])[:2]
        if not describer or not shown or shown.get("notice") or directory is None:
            continue
        if directory not in found:
            found[directory] = expectation.descriptions(directory, describer)
        d = expectation.description_of(shown, found[directory])
        if d is None or expectation.classify([d["screen"], d.get("in_episode") or ""], notices or expectation.NOTICES):
            continue
        body = f"(about S{n}) {d['screen'].strip()} {(d.get('in_episode') or '').strip()}".strip()
        record = f"{expectation.DESCRIPTIONS}#visit/{d.get('visit')}/{describer}"
        out.append(_part(f"S{n}.d", "description", body, ("run", record), run))
    return out


def _passages(passages, prefix: str, folder: str = "", data: Vocabulary | None = None) -> list[dict]:
    """The passages as parts <prefix><n>; with `data`, each followed by its facts as parts F<n> (`_facts`)."""
    out, facts = [], 0
    for n, p in enumerate(passages, 1):
        out.append(
            _part(f"{prefix}{n}", "passage", f"{p.title} ({p.source}): {p.text}", ("corpus", f"{folder}{p.path.name}"))
        )
        if data is not None:
            for part in _facts(p, data, facts, folder):
                facts += 1
                out.append(part)
    return out


def readable_facts(p, data: Vocabulary | None) -> list[tuple[int, object]]:
    """A passage's facts that corpus.problems finds nothing wrong with, with their positions (facts[k])."""
    wrong = {int(x.split("facts[", 1)[1].split("]", 1)[0]) for x in fact_problems(p, data)}
    return [(k, f) for k, f in enumerate(p.facts) if k not in wrong]


def fact_text(f, data: Vocabulary) -> str:
    """A fact in words, by its kind: "scope developer", "persists until reinstall" (the value is the event that ends
    the identifier, not one it survives), "precision 50 m"."""
    title = data[f.about].title if f.about in data else f.about
    said = {
        "scope": f"scope {f.value}",
        "persists": f"persists until {f.value}",
        "precision_m": f"precision {f.value} m",
    }
    return f"{title} ({f.about}): {said.get(f.kind, f'{f.kind} {f.value}')}"


def _facts(p, data: Vocabulary, before: int, folder: str = "", where: str = "the passage before") -> list[dict]:
    """A passage's readable facts as parts F<n>, numbered on from `before`: what the passage states of a datum, its
    kind, value and quote. Their provenance is the passage's file, with the fact's position (`fact`)."""
    return _fact_parts(p, readable_facts(p, data), data, before, folder, where)


def _fact_parts(p, facts, data: Vocabulary, before: int, folder: str = "", where: str = "the passage before") -> list:
    out = []
    for k, f in facts:
        text = f'{fact_text(f, data)}, as {where} states it: "{f.quote}"'
        pointer = {"origin": "corpus", "record": f"{folder}{p.path.name}", "fact": k}
        out.append({"id": f"F{before + len(out) + 1}", "kind": "passage", "text": text, "provenance": [pointer]})
    return out


def replacements(value: str | None, data: Vocabulary) -> set[str]:
    """The candidate replacements of a datum: every node configuration.coarser admits for it, other than the datum
    and the vocabulary's root (an advertising ID's: the App Set ID and the installation ID, and the nodes above it)."""
    from skuld.configuration import coarser

    if not value or value not in data:
        return set()
    return {n.id for n in data if n.id not in (value, data.root) and coarser(n.id, value, data)}


def replacement_facts(corpus: Corpus, documentation: list, values: list[str], data: Vocabulary, before: int) -> list:
    """The facts of the corpus's checked passages about the candidate replacements of the data `values`, as parts
    F<n> numbered on from `before`, each once and none a passage of `documentation` gives already after it; each
    with its own passage as provenance (gates b and c read it by that passage)."""
    nodes = set().union(*(replacements(v, data) for v in values)) if values else set()
    out = []
    for p in corpus.passages:
        if p in documentation or not p.checked:
            continue
        mine = [(k, f) for k, f in readable_facts(p, data) if f.about in nodes]
        out += _fact_parts(p, mine, data, before + len(out), where=f"{p.title} ({p.source})")
    return out


def questions(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    names: dict[str, str] | None = None,
    vague: frozenset = frozenset(),
    kinds: tuple[str, ...] = QUESTIONS,
    notices: str | None = None,
    model: str | None = None,
) -> list[Question]:
    """The questions of the reasoning tier for an assessment, each with its context, of the `kinds` asked for; the
    declarations in `vague` specify no purpose for the compatibility questions. From minimisation prompt version
    SCREENS_SINCE a minimisation context holds the screens of the practice's episodes (`screens_of`, notices left out
    by the notice definition in version `notices`, default expectation.NOTICES)."""
    names = names or {}
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)
    out = []

    found = statements(a, subjects)
    for n in range(0, len(found) if SPECIFICITY in kinds else 0, BATCH):
        batch = found[n : n + BATCH]
        parts = [_application(a)]
        for s in batch:
            quoted = f'"{s.text}" ({", ".join(s.channels)})'
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
    if COMPATIBILITY in kinds and a.declaration is not None and subjects.comparability.get("comparable") is not False:
        for case in limitation(subjects, found, hypotheses, vague):
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

    shown = (
        screens_of(a, subjects, notices)
        if MINIMISATION in kinds and supported and int(templates.version(MINIMISATION)) >= SCREENS_SINCE
        else {}
    )
    for p in subjects.practices if MINIMISATION in kinds else ():
        mine = [h for h in supported if h["subject"] == p.id]
        if not mine:
            continue
        replaceable = int(templates.version(MINIMISATION)) >= REPLACEMENTS_SINCE
        parts, hyp = [_application(a), _practice(p, data, names, replaceable)], {}
        for k, h in enumerate(mine, 1):
            parts.append(_hypothesis(f"H{k}", _purpose_text(h["purpose"]), h))
            hyp[f"H{k}"] = h["id"]
        described = int(templates.version(MINIMISATION)) >= DESCRIBED_SINCE
        parts += _screens(shown.get(p.id, []), expectation.describer(model) if described else None, notices)
        documentation = []
        for kind, value in expectation.components(p).values():
            for passage in corpus.about(value, None, data) if kind == "D" else corpus.about(None, value, data):
                if passage not in documentation:
                    documentation.append(passage)
        typed = int(templates.version(MINIMISATION)) >= TYPED_SINCE
        parts += _passages(documentation, "D", data=data if typed else None)
        if typed:
            values = [v for kind, v in expectation.components(p).values() if kind == "D"]
            shown_facts = sum(1 for x in parts if x["id"].startswith("F"))
            parts += replacement_facts(corpus, documentation, values, data, shown_facts)
        parts += _passages(norms.on(REQUIREMENT[MINIMISATION]), "N", "norms/")
        out.append(
            Question(
                MINIMISATION,
                p.id,
                _checked(parts, notices),
                [],
                {"practice": p.id, "components": list(expectation.components(p)), "purposes": hyp},
            )
        )
    return out


def procedure(question: str) -> dict:
    return {"id": "skuld.judge", "version": templates.version(question)}


def _checked(parts: list[dict], notices: str | None = None) -> Context:
    context = Context(tuple(parts))
    check(context, notices)
    return context


def check(context: Context, notices: str | None = None) -> None:
    """Gate 1 for stage 2: a part of D's report only as a declaration, marked as such; no other kind or origin; a
    screen that is no notice (by the notice definition in version `notices`, default expectation.NOTICES), as in
    stage 1."""
    ctx.check(context, KINDS, "stage 2")
    for p in context.parts:
        if p["kind"] == "screen" and expectation.classify(p["text"].split(" | "), notices or expectation.NOTICES):
            raise ContextError(f"{p['id']}: a notice screen is not given to stage 2")


SECTIONS = [
    ("The application", "application"),
    ("Practices observed", "practice"),
    ("Hypotheses of the expectation stage", "hypothesis"),
    ("Screens of the episodes where the practice occurred", "screen"),
    ("Declarations of the provider", "declaration"),
    ("Documentation and norms", "passage"),
]


def render(context: Context) -> str:
    return context.render(SECTIONS)


def prompt(question: Question, factors: list[str]) -> str:
    template = templates.text(question.question)
    return template.replace("{context}", render(question.context)).replace("{factors}", ", ".join(factors))


def sample_folder(root: Path, question: Question, seed: int, attempt: int = 1) -> Path:
    folder = root / "assessment" / question.question / question.subject / f"s{seed}"
    return folder if attempt == 1 else folder / f"a{attempt}"


def _objects(value) -> list[dict]:
    """The objects of a list an answer gives; nothing for a list the schema did not hold."""
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _cites(item: dict) -> list[str]:
    """The cites of an answer's item: its own and its steps', and in the typed minimisation form its needs', gives'
    and covers' steps'."""
    out = list(item.get("cites") or ()) + [c for s in _objects(item.get("steps")) for c in s.get("cites") or ()]
    for key in ("needs", "gives"):
        out += [c for x in _objects(item.get(key)) for c in x.get("cites") or ()]
    covers = item.get("covers") if isinstance(item.get("covers"), dict) else {}
    return out + [c for s in _objects(covers.get("steps")) for c in s.get("cites") or ()]


def refusals(question: Question, text: str | None, factors: list[str]) -> list[str]:
    """What refuses an answer: not JSON, a statement or specified purpose not answered, an unknown purpose, component
    or factor, a citation of an id the context does not hold; in the typed minimisation form (an entry with `change`)
    an unknown change kind, or a REPLACE without a node of the data vocabulary."""
    try:
        answer = json.loads(text or "")
    except ValueError:
        return ["the answer is not JSON"]
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    ids, out = question.context.ids, []
    section = {SPECIFICITY: "statements", COMPATIBILITY: "pairs", MINIMISATION: "alternatives"}[question.question]
    items = _objects(answer.get(section))
    if len(items) != len(answer.get(section) or ()):
        out.append(f"{section}: not a list of objects")
    key = {SPECIFICITY: "statement", COMPATIBILITY: "specified"}.get(question.question)
    if key:
        answered = {ref(i.get(key)) for i in items}
        out += [f"{x} is not answered" for x in question.answers if x not in answered]
        out += [f"{x} is not in the context" for x in answered - set(question.answers)]
    for i in items:
        cites = _cites(i) + [c for f in _objects(i.get("factors")) for c in f.get("cites") or ()]
        unknown = {ref(c) for c in cites if ref(c).lower() != OWN} - ids
        if unknown:
            out.append(f"{ref(i.get(key)) if key else section}: cites {', '.join(sorted(unknown))}, not in the context")
        if question.question == COMPATIBILITY:
            out += [
                f"{ref(i.get('specified'))}: {f.get('factor')!r} is not a factor ({', '.join(factors)})"
                for f in _objects(i.get("factors"))
                if f.get("factor") not in factors
            ]
        if question.question == MINIMISATION:
            if ref(i.get("purpose")) not in question.record["purposes"]:
                out.append(f"alternatives: {ref(i.get('purpose')) or '(none)'} is not a purpose of the context")
            if ref(i.get("component")) not in question.record["components"]:
                out.append(
                    f"alternatives: {ref(i.get('component')) or '(none)'} is not a component of {question.record['practice']}"
                )
            if "change" in i:
                out += _change_refusals(i.get("change"))
    return sorted(set(out))


def _change_refusals(change) -> list[str]:
    """What refuses a typed entry's change: no change kind of CHANGES, a REPLACE without a node of the data vocabulary."""
    if not isinstance(change, dict) or str(change.get("kind") or "").upper() not in CHANGES:
        kind = change.get("kind") if isinstance(change, dict) else change
        return [f"alternatives: {kind!r} is not a change ({', '.join(CHANGES)})"]
    if str(change["kind"]).upper() == "REPLACE":
        data, node = vocabulary(DATA), ref(change.get("node"))
        if not node or node not in data or node == data.root:
            return [f"alternatives: REPLACE names {node or 'no node'}, not a node of the data vocabulary"]
    return []


def judge(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    factors: list[str],
    seeds: list[int] | None = None,
    model: str | None = None,
    api: str = "openai",
    offline: bool = False,
    provider=None,
    names: dict[str, str] | None = None,
    only: tuple[str, ...] = QUESTIONS,
    reading: str = READING,
    notices: str | None = None,
) -> list[tuple[Question, ask.Sample]]:
    """The samples of the reasoning tier: per question and seed, kept or asked, as many at a time as the server
    takes. From reading 2 the specificity samples come first: a declared purpose they judge not specific specifies
    nothing, so the compatibility questions are formed only after them. `notices`: the notice definition's version
    the minimisation contexts leave notice screens out by (`questions`)."""
    seeds = seeds or config.load()["assessment"]["seeds"]
    think = config.load()["assessment"].get("think")
    model = model or a.models.get("assessment") or a.models["expectation"]
    if gated(reading):
        first = questions(a, subjects, corpus, norms, hypotheses, names, kinds=(SPECIFICITY,), model=model)
        # minimisation reads no specificity answer: asked in the same round when both are asked (0.12.4, the rerun
        # plan's throughput), so that the server is given both questions' requests at once
        early = MINIMISATION in only and SPECIFICITY in only
        alongside = (
            questions(
                a, subjects, corpus, norms, hypotheses, names, kinds=(MINIMISATION,), notices=notices, model=model
            )
            if early
            else []
        )
        asked = _samples(
            a,
            first + alongside,
            factors,
            seeds,
            think,
            model,
            api,
            offline or SPECIFICITY not in only,
            provider,
            corpus,
            norms,
        )
        specific = [(q, x) for q, x in asked if q.question == SPECIFICITY]
        minimised = [(q, x) for q, x in asked if q.question != SPECIFICITY]
        vague = vague_declarations(
            [j for q, sample in specific for j in specificity(_answer(sample), _name(a, sample), q) if sample.text]
        )
        later = tuple(q for q in only if q != SPECIFICITY and not (early and q == MINIMISATION))
        rest = questions(a, subjects, corpus, norms, hypotheses, names, vague, later, notices, model=model)
        out = (
            (specific if SPECIFICITY in only else [])
            + _samples(a, rest, factors, seeds, think, model, api, offline, provider, corpus, norms)
            + minimised
        )
    else:
        qs = questions(a, subjects, corpus, norms, hypotheses, names, kinds=only, notices=notices, model=model)
        out = _samples(a, qs, factors, seeds, think, model, api, offline, provider, corpus, norms)
    if not offline:
        current = {a.root / "assessment" / q.question / q.subject for q, _ in out}
        for question in only:
            ask.supersede(a.root / "assessment" / question, current)
    return out


def _answer(sample) -> dict:
    try:
        answer = json.loads(sample.text)
    except (TypeError, ValueError):
        return {}
    return answer if isinstance(answer, dict) else {}


def _name(a: Assessment, sample) -> str:
    return sample.folder.relative_to(a.root).as_posix()


def vague_declarations(judgements: list[dict], applies: bool = True) -> frozenset:
    """The declarations of the statements whose specificity judgements combine to a supported concern that they are
    not specific (combine.decide, the combination's rule); none where purpose_specific does not apply (`applies`
    False, from reading 4), as concerns.not_specific then states no concern."""
    if not applies:
        return frozenset()
    by_statement: dict[str, list[dict]] = {}
    for j in judgements:
        by_statement.setdefault(j["statement"], []).append(j)
    return frozenset(
        d for mine in by_statement.values() if combine.decide(mine)[0] == "supported" for d in mine[0]["declarations"]
    )


def _samples(a, qs, factors, seeds, think, model, api, offline, provider, corpus, norms):
    """The samples of the questions `qs`, per seed, kept or asked."""
    jobs = []
    for q in qs:
        text = prompt(q, factors)
        for seed in seeds:
            record = {
                "question": q.question,
                "subject": q.subject,
                **q.record,
                "procedure": procedure(q.question),
                "prompt": {"id": q.question, "version": templates.version(q.question), "sha256": ask.sha256(text)},
                "corpus": {"sha256": corpus.sha256},
                "norms": {"sha256": norms.sha256},
                "context": {"sha256": q.context.sha256},
            }

            def one(q=q, seed=seed, record=record, text=text) -> tuple[Question, ask.Sample]:
                sample, refused, _ = ask.ask_with_feedback(
                    lambda attempt: sample_folder(a.root, q, seed, attempt),
                    text,
                    schema(q.question),
                    lambda asked: {**record, "prompt": {**record["prompt"], "sha256": ask.sha256(asked)}},
                    ("question", "subject", "procedure", "prompt", "corpus", "norms", "context"),
                    lambda answer: refusals(q, answer, factors),
                    attempts=attempts(q.question),
                    seed=seed,
                    model=model,
                    api=api,
                    options=config.options("judge", seed=seed),
                    offline=offline,
                    provider=provider,
                    files={"context.json": json.dumps({"parts": list(q.context.parts)}, indent=1, ensure_ascii=False)},
                    think=think,
                )
                if sample.text is not None and refused:
                    sample.record["refused"] = refused
                return q, sample

            jobs.append(one)
    return ask.concurrently(jobs, model)


def kept(
    a: Assessment,
    subjects: Subjects,
    corpus: Corpus,
    norms: Corpus,
    hypotheses: list[dict],
    factors: list[str],
    names: dict[str, str] | None = None,
    reading: str = READING,
    notices: str | None = None,
) -> list[tuple[str, Question, dict]]:
    """The kept samples of the current questions: (sample name, question, answer), without asking."""
    out = []
    for q, sample in judge(
        a, subjects, corpus, norms, hypotheses, factors, offline=True, names=names, reading=reading, notices=notices
    ):
        if sample.text is not None:
            out.append((_name(a, sample), q, _answer(sample)))
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
    for item in _objects(answer.get("statements")):
        sid = ref(item.get("statement"))
        if sid not in q.answers:
            continue
        steps = [[ref(c) for c in s.get("cites") or ()] for s in _objects(item.get("steps"))]
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
    for item in _objects(answer.get("pairs")):
        qid = ref(item.get("specified"))
        if qid not in q.answers:
            continue
        judgement = JUDGED.get(str(item.get("judgement")).upper(), "undecided")
        steps, dropped = [], []
        for n, f in enumerate(item.get("factors") or ()):
            cites = [ref(c) for c in f.get("cites") or ()] if isinstance(f, dict) else []
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


#: Words by which an alternative removes the component; storing less or for shorter is no removal (retention is no
#: dimension the instance imposes)
REMOVAL = re.compile(
    r"\b(?:remov\w*|omit\w*|drop\w*|block\w*|disabl\w*|exclud\w*"
    r"|(?:do not|don't|never|stop|no longer|not|without) (?:send|collect|share|transmit|use|read|access|request)\w*"
    r"|without (?:the |this |that |any |an? )?(?:\w+ )?(?:id|identifier|data|datum|location)s?)\b",
    re.IGNORECASE,
)
#: Reading 4's removal: "drop" but not "dropdown"
REMOVAL_4 = re.compile(
    r"\b(?:remov\w*|omit\w*|drop(?:s|ped|ping)?\b|block\w*|disabl\w*|exclud\w*"
    r"|(?:do not|don't|never|stop|no longer|not|without) (?:send|collect|share|transmit|use|read|access|request)\w*"
    r"|without (?:the |this |that |any |an? )?(?:\w+ )?(?:id|identifier|data|datum|location)s?)\b",
    re.IGNORECASE,
)
#: After a removal, what makes it a shorter retention ("remove it after the request", "drop the stored identifier
#: after 30 days"), not a removal of the component
_RETENTION = re.compile(
    r"\b(?:after|within|once|upon|until|at the end of|older than|expir\w*|when (?:the|a|an|it|they|no)\b"
    r"|\d+\s*(?:hours?|days?|weeks?|months?|years?))",
    re.IGNORECASE,
)
#: After "without the data", what makes it a statement that the feature needs the data, not an alternative
_UNWORKABLE = re.compile(
    r"\b(?:would(?:n't| not)|could(?:n't| not)|cannot|can't|can not|will not|won't|does not|doesn't|is not possible"
    r"|fails?|breaks?|impossible)\b",
    re.IGNORECASE,
)
#: Words by which a removal names a recipient rather than a datum (gate a, reading 4)
_RECIPIENT = re.compile(
    r"\b(?:sdks?|librar(?:y|ies)|recipients?|third[- ]part(?:y|ies)|vendors?|partners?|networks?|services?|"
    r"providers?|trackers?|endpoints?|servers?|integrations?)\b",
    re.IGNORECASE,
)
#: Words by which a removal names data in general
_DATUM = re.compile(r"\b(?:ids?|identifiers?|data|datum|location|information)\b", re.IGNORECASE)
#: Names an alternative may give a datum besides the vocabulary's titles (gate a)
ALIASES = {
    "device-or-other-ids.installation-id": (
        "installation id",
        "firebase installation",
        "fid",
        "guid",
        "uuid",
        "app-generated id",
        "app-generated identifier",
        "app-scoped id",
        "app-scoped identifier",
        "app-specific id",
    ),
    "device-or-other-ids.app-set-id": ("app set id",),
    "device-or-other-ids.advertising-id": ("advertising id", "advertising identifier", "gaid", "aaid", "ad id"),
    "device-or-other-ids.android-id": ("android id", "ssaid", "android_id"),
    "location.approximate-location": ("approximate location", "coarse location", "coarser location"),
    "location.postal-code": ("postal code", "zip code"),
}


def recognised(text, kind: str, value: str, data, reading: str = READING) -> tuple[str, set[str]] | None:
    """
    The change an alternative's text names for its component (gate a): ("replace", nodes) where it names nodes of the
    component's family of the data vocabulary other than the component's own and those above it, by title or alias;
    else ("remove", set()) where it names a removal; else None. A recipient is only removed, never replaced: replacing
    it by another changes no inclusion. From reading 4 a removal is one of the component (`_removes`).
    """
    t = str(text or "")
    if kind == "D" and data is not None and value in data:
        family = value.split(".")[0]
        above = {value, *data.ancestors(value)}
        named = set()
        for node in data:
            if node.id in above or not (node.id == family or node.id.startswith(family + ".")):
                continue
            names = (node.title, *ALIASES.get(node.id, ()))
            if any(re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", t, re.IGNORECASE) for n in names):
                named.add(node.id)
        if named:
            return "replace", named
    if int(reading) >= 4:
        return ("remove", set()) if _removes(t, kind, value, data) else None
    return ("remove", set()) if REMOVAL.search(t) else None


def _removes(text: str, kind: str, value: str, data) -> bool:
    """Reading 4: whether a clause of the text removes the component. The clause names a removal (REMOVAL_4) that no
    retention period follows ("after the request", "after 30 days") and, for "without the data", no statement that
    the feature would then not work; and it names the component: a recipient by its name or as a recipient (an SDK, a
    third party, a service), a datum by its title or alias, one of the nodes above it, or as data. A removal of the
    datum is no removal of the recipient, nor the reverse."""
    if kind == "R":
        general = _RECIPIENT
        words = [w for w in re.split(r"[^a-z0-9]+", str(value).lower()) if len(w) >= 3 and w not in ("domain", "com")]
    else:
        general, words = _DATUM, []
        if data is not None and value in data:
            for node in (value, *data.ancestors(value)):
                if node != data.root:
                    words += [data[node].title, *ALIASES.get(node, ())]

    def names(clause: str) -> bool:
        return bool(general.search(clause)) or any(
            re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", clause, re.IGNORECASE) for w in words if w
        )

    for clause in re.split(r"[.;]\s|[.;]$|\n", text):
        for m in REMOVAL_4.finditer(clause):
            after = clause[m.end() :]
            if _RETENTION.search(after):
                continue
            if m.group(0).lower().startswith("without") and _UNWORKABLE.search(after):
                continue
            if names(clause):
                return True
    return False


#: The change key of an alternative whose text names no change `recognised` reads (reading 5): one key for all of a
#: component's, rather than one per text, since such an alternative fails gate (a) and is never supported; grouping
#: them by their words would only split the not-established alternatives of a component the more, the more the samples'
#: wordings differ
OTHER_CHANGE = "other"


def change_key(change) -> str:
    """The key of a recognised change (reading 5): "remove", "replace:" and the nodes it names in order, or
    OTHER_CHANGE for none."""
    if change is None:
        return OTHER_CHANGE
    how, nodes = change
    return "remove" if how == "remove" else "replace:" + ",".join(sorted(nodes))


def less_invasive(change, value: str, data) -> bool:
    """Whether a recognised change is less invasive than the component (E def:alternative): a removal always; a
    replacement if every node it names is coarser than the component's by the vocabulary (configuration.coarser)."""
    if change is None:
        return False
    how, nodes = change
    if how == "remove":
        return True
    from skuld.configuration import coarser

    return all(n != value and coarser(n, value, data) for n in nodes)


def _unidentified(kind: str | None, value, data) -> bool:
    """Whether a component is not identified (gate a): a datum of no node, the root or an unknown one; a recipient
    known only by its domain."""
    if kind is None or not value or (kind == "D" and (data is None or value == data.root or value not in data)):
        return True
    return kind == "R" and str(value).startswith("domain:")


def gate_a(text, kind: str | None, value, data, reading: str = READING) -> str | None:
    """Gate (a) for a documented alternative: None if passed, else why it failed."""
    if _unidentified(kind, value, data):
        return "gate_a_component"
    return None if less_invasive(recognised(text, kind, value, data, reading), value, data) else "gate_a_change"


def typed_change(item: dict) -> dict | None:
    """A typed entry's change as a claim states it ({kind, node?}, kind in lower case), None for a change of no known
    kind."""
    c = item.get("change")
    if not isinstance(c, dict) or str(c.get("kind") or "").upper() not in CHANGES:
        return None
    out = {"kind": CHANGES[str(c["kind"]).upper()]}
    if ref(c.get("node")):
        out["node"] = ref(c.get("node"))
    return out


def typed_change_key(change: dict | None) -> str:
    """The change key of a typed change: remove, replace:<node>, on_device or narrower_recipient; OTHER_CHANGE for a
    change of no known kind, or a REPLACE that names no node."""
    if change is None or (change["kind"] == "replace" and not change.get("node")):
        return OTHER_CHANGE
    return f"replace:{change['node']}" if change["kind"] == "replace" else change["kind"]


def typed_gate_a(change: dict | None, kind: str | None, value, data, gives_grounded: bool) -> str | None:
    """Gate (a) from a typed change: None if passed, else why it failed. REMOVE is always less invasive; REPLACE where
    its node is coarser than the component's datum (configuration.coarser) and not the datum itself, a recipient never
    replaced; ON_DEVICE and NARROWER_RECIPIENT for a recipient, and for a datum only where what it gives is grounded
    in documentation."""
    from skuld.configuration import coarser

    if _unidentified(kind, value, data):
        return "gate_a_component"
    if change is None:
        return "gate_a_typed"
    how, node = change["kind"], change.get("node")
    if how == "remove":
        return None
    if how == "replace":
        ok = kind == "D" and node in data and node not in (value, data.root) and coarser(node, value, data)
        return None if ok else "gate_a_typed"
    return None if kind == "R" or gives_grounded else "gate_a_typed"


def _rank(kind: str, value) -> float:
    return ORDERS[kind].index(value) if kind in ORDERS else -float(value)


def _number(kind, value):
    """A need's or property's value as the rule compares it: a precision in metres as a number (also where the model
    wrote it as text), anything else as it is."""
    if kind == "precision_m" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _typed_kind(x: dict) -> dict:
    """A need's or property's kind and value as a claim states them: the kind where it is one of REQUIREMENT_KINDS,
    the value where it is one of the kind's (corpus.valid_value)."""
    kind = str(x.get("kind") or "").lower()
    if kind not in REQUIREMENT_KINDS:
        return {}
    value = _number(kind, x.get("value"))
    return {"kind": kind, **({"value": value} if kind in FACT_KINDS and valid_value(kind, value) else {})}


def facts_of(node: str | None, corpus: Corpus | None, context: Context, data) -> dict[str, list[tuple]]:
    """The facts of the corpus's checked passages about a data node, by kind, each as (value, passage id, position,
    the F part of the context that gives it or None)."""
    if not node or corpus is None:
        return {}
    shown = {}
    for p in context.parts:
        pointer = p["provenance"][0]
        if p["kind"] == "passage" and "fact" in pointer:
            shown[(Path(pointer["record"]).name, pointer["fact"])] = p["id"]
    out: dict[str, list[tuple]] = {}
    for passage in corpus.passages:
        if not passage.checked:
            continue
        for k, f in readable_facts(passage, data):
            if f.about == node:
                out.setdefault(f.kind, []).append((f.value, passage.id, k, shown.get((passage.path.name, k))))
    return out


def covers_by_rule(change: dict | None, needs: list[dict], facts: dict[str, list[tuple]]) -> tuple[str, list] | None:
    """The rule's verdict on whether a replacement covers what the purpose needs, with its steps, where it decides:
    the change is a REPLACE, every need has a kind of FACT_KINDS and a value, and the facts give the replacement node a
    property of each kind. A need is met where every fact of its kind meets it: scope, the alternative's reaches the
    need's (SCOPES by containment); persists, the alternative's lasts at least as long (PERSISTS); precision_m, the
    alternative's is at most the need's. COVERS where every need is met, else DOES_NOT; None where the rule does not
    decide."""
    if change is None or change["kind"] != "replace" or not needs:
        return None
    if not all(n.get("kind") in FACT_KINDS and "value" in n and facts.get(n["kind"]) for n in needs):
        return None
    steps, met_all = [], True
    for n in needs:
        found = facts[n["kind"]]
        met = all(_rank(n["kind"], v) >= _rank(n["kind"], n["value"]) for v, *_ in found)
        met_all = met_all and met
        said = "; ".join(f"{v} ({pid}, facts[{k}])" for v, pid, k, _ in found)
        steps.append(
            {
                "text": f"{n['id']} needs {n['kind']} {n['value']}; {change['node']} has {n['kind']} {said}: "
                + ("met" if met else "not met"),
                "cites": sorted({part for *_, part in found if part}),
            }
        )
    return ("covers" if met_all else "does_not"), steps


def typed(
    item: dict,
    cid: str,
    q: Question,
    component: str,
    practice: Practice | None,
    corpus: Corpus | None,
    data,
    types,
) -> dict:
    """The fields and status of a typed entry's Alternative claim (reading 5, minimisation prompt 5; the rule in the
    module's docstring): change, change_key, needs, gives, covers, status, the gap reason and the claim's reason,
    strength, uncertainty and the parts it cites. `cid` is the claim's id, which its needs' ids extend."""
    ids, documentation = q.context.ids, _documentation(q.context)
    practices, declarations = q.context.of_kind("practice"), q.context.of_kind("declaration")
    need_grounds = q.context.of_kind("screen") | q.context.of_kind("hypothesis")
    kind, value = (
        expectation.components(practice).get(component, (None, None)) if practice is not None else (None, None)
    )
    categories = practice.recipient_categories if practice is not None else ()
    change = typed_change(item)
    about = change.get("node") if change and change["kind"] == "replace" else value
    cites: set[str] = set()
    dropped = []

    needs = []
    for k, x in enumerate(_objects(item.get("needs")), 1):
        given = [ref(c) for c in x.get("cites") or ()]
        kept = [c for c in given if c not in practices and c not in declarations]
        if len(kept) < len(given):
            dropped.append(
                {"step": f"N{k}", "reason": "cites the practice or a declaration as a reason that it is needed"}
            )
        grounded = bool(kept) and set(kept) <= need_grounds
        cites |= set(kept)
        needs.append(
            {
                "id": f"{cid}:N{k}",
                "requirement": str(x.get("requirement") or ""),
                **_typed_kind(x),
                "cites": kept,
                "grounded": grounded,
            }
        )
    needs_grounded = bool(needs) and all(n["grounded"] for n in needs)

    gives, missing, failed_bc = [], [], None
    for x in _objects(item.get("gives")):
        given = [ref(c) for c in x.get("cites") or ()]
        documented = cited(given, ids) and bool(set(given) & documentation)
        failed = (
            gate(set(given) & documentation, q.context, kind, value, categories, corpus, data, types)
            if documented
            else None
        )
        failed_bc = failed_bc or failed
        typed_ = _typed_kind(x)
        if not documented:
            prop = typed_.get("kind") if typed_.get("kind") in FACT_KINDS else str(x.get("property") or "").strip()
            missing.append(f"fact: {prop or 'a property'} of {about or component}")
        cites |= set(given) & ids
        gives.append(
            {
                "property": str(x.get("property") or ""),
                **typed_,
                "cites": given,
                "grounded": documented and failed is None,
            }
        )
    gives_grounded = bool(gives) and all(g["grounded"] for g in gives)

    answered = item.get("covers") if isinstance(item.get("covers"), dict) else {}
    said = str(answered.get("verdict") or "").upper()
    said = said if said in VERDICTS else "UNKNOWN"
    steps, step_cites = [], []
    for i, x in enumerate(_objects(answered.get("steps"))):
        given = [ref(c) for c in x.get("cites") or ()]
        if set(given) & declarations:
            dropped.append(
                {"step": f"covers.{i}", "reason": "cites a declaration as a reason that processing is needed"}
            )
            continue
        steps.append({"text": str(x.get("text") or ""), "cites": given})
        step_cites.append(given)
    ruled = covers_by_rule(change, needs, facts_of(about, corpus, q.context, data))
    if ruled is not None:
        verdict, steps = ruled
        covers = {"verdict": verdict, "by": "rule", "steps": steps, "model_verdict": said.lower()}
        argued = True
    else:
        verdict = said.lower()
        covers = {"verdict": verdict, "by": "model", "steps": steps}
        argued = _grounded(step_cites, ids)
        cites |= {c for s in step_cites for c in s} & ids
    cites |= {c for s in covers["steps"] for c in s["cites"]} & ids

    failed_a = typed_gate_a(change, kind, value, data, gives_grounded)
    strong = needs_grounded and gives_grounded and argued
    why = None
    if verdict == "does_not" and strong:
        status, reason = "refuted", "the alternative does not cover what the purpose needs"
    elif failed_a:
        status, why, reason = "not_established", "not_admitted", GATES[failed_a]
    elif missing:
        status, why = "not_established", "fact_missing"
        reason = "a property the alternative gives rests on no documentation: the fact base lacks it"
    elif failed_bc:
        status, why, reason = "not_established", "not_admitted", GATES[failed_bc]
    elif not gives:
        status, why, reason = "not_established", "own_knowledge", "the alternative states nothing it gives"
    elif not needs_grounded:
        status, why = "not_established", "own_knowledge"
        reason = "no need is stated" if not needs else "a need does not rest on the screens or the purposes alone"
    elif verdict == "covers" and argued:
        status, reason = "supported", None
    elif verdict == "covers":
        status, why, reason = "not_established", "own_knowledge", "covers: a step does not cite the context"
    elif verdict == "partly":
        status, reason = "not_established", "partly covers: the alternative meets what the purpose needs only in part"
    elif verdict == "does_not":
        status, why = "not_established", "own_knowledge"
        reason = "does not cover what the purpose needs, by an argument that does not rest on the context"
    else:
        status, reason = "not_established", "whether the alternative covers what the purpose needs is unknown"
    uncertainty = FROM_DOC if strong else expectation.FROM_OWN
    if covers["by"] == "model":
        uncertainty = raised(uncertainty, "covers_by_model")
    return {
        "fields": {
            **({"change": change} if change else {}),
            "change_key": typed_change_key(change),
            "needs": needs,
            "gives": gives,
            "covers": covers,
        },
        "status": status,
        "why": why,
        "reason": reason,
        "missing": missing,
        "strength": "doc" if strong else "own",
        "uncertainty": uncertainty,
        "parts": cites & ids,
        "dropped": dropped,
    }


def gate(citations: set[str], context: Context, kind: str, value, categories, corpus: Corpus | None, data, types):
    """Gates (b) and (c) for a documented alternative of a component: None if passed, else the gate that failed. A
    fact (an F part) about a candidate replacement of the component's datum (`replacements`) is about the component:
    it documents the component's alternative."""
    files = {
        p["id"]: Path(p["provenance"][0]["record"]).name
        for p in context.parts
        if p["kind"] == "passage" and not p["provenance"][0]["record"].startswith("norms/")
    }
    fact_at = {p["id"]: p["provenance"][0]["fact"] for p in context.parts if "fact" in p["provenance"][0]}
    by_file = {p.path.name: p for p in corpus.passages} if corpus is not None else {}
    candidates = replacements(value, data) if kind == "D" and data is not None else set()

    def replaced(c: str, passage) -> bool:
        k = fact_at.get(c)
        return k is not None and k < len(passage.facts) and passage.facts[k].about in candidates

    about = [
        by_file[files[c]]
        for c in citations
        if c in files
        and files[c] in by_file
        and (by_file[files[c]].concerns(kind, value, categories, data, types) or replaced(c, by_file[files[c]]))
    ]
    if not about:
        return "gate_b"
    if not any(p.checked for p in about):
        return "gate_c"
    return None


def minimisation(
    answer: dict,
    name: str,
    q: Question,
    hypotheses: dict[str, dict],
    reading: str = READING,
    practice: Practice | None = None,
    corpus: Corpus | None = None,
) -> list[dict]:
    """The Alternative claims of a minimisation sample, of the assessment stage and the reasoning tier; `reading`
    is the version to read with, and READING 2's gates read the practice's components and the corpus's passages. From
    reading 5 an entry in the typed form (it carries `change`; minimisation prompt 5) is read by `typed`, the corpus's
    facts deciding covers by rule where they can."""
    reading_component(reading)
    gates, keyed = gated(reading), int(reading) >= 5
    parts_of = expectation.components(practice) if practice is not None else {}
    data, types = (vocabulary(DATA), vocabulary(RECIPIENT_TYPES)) if gates else (None, None)
    ids, documentation = q.context.ids, _documentation(q.context)
    declarations = q.context.of_kind("declaration")
    channel = f"reasoning:{name}"
    out = []
    for n, item in enumerate(answer.get("alternatives") or ()):
        if not isinstance(item, dict):  # an answer the schema did not hold; the claims' numbers keep their places
            continue
        label = ref(item.get("purpose"))
        basis = hypotheses.get(q.record["purposes"].get(label, ""))
        component = ref(item.get("component"))
        if basis is None or component not in q.record["components"]:
            continue
        if not names_alternative(item.get("alternative"), reading):  # "none": no alternative (READING 1, 4)
            continue
        if keyed and "change" in item:  # the typed form (minimisation prompt 5)
            out.append(_typed_claim(item, f"{name}:a{n}", channel, q, basis, component, practice, corpus, data, types))
            continue
        steps, dropped = [], []
        for i, s in enumerate(item.get("steps") or ()):
            cites = [ref(c) for c in s.get("cites") or ()] if isinstance(s, dict) else []
            if set(cites) & declarations:
                dropped.append({"step": i, "reason": "cites a declaration as a reason that processing is needed"})
            else:
                steps.append(cites)
        cites = {c for s in steps for c in s}
        technical = str(item.get("level")).upper() == "TECHNICALLY_SUPPORTED"
        grounded = _grounded(steps, ids)
        documented = technical and grounded and bool(cites & documentation)
        strong = grounded and bool(cites & documentation) if int(reading) >= 3 else grounded
        failed = None
        if documented and gates:
            kind, value = parts_of.get(component, (None, None))
            categories = practice.recipient_categories if practice is not None else ()
            failed = gate_a(item.get("alternative"), kind, value, data, reading) or gate(
                cites & documentation, q.context, kind, value, categories, corpus, data, types
            )
            documented = failed is None
        key = None
        if keyed:  # the change it names, by which the combination groups it (reading 5)
            kind, value = parts_of.get(component, (None, None))
            key = change_key(recognised(item.get("alternative"), kind, value, data, reading) if kind else None)
        if basis["purpose"]["specificity"] == "vague":
            status, why, reason = "not_assessable", "purpose_vague", "the purpose is too vague"
        elif failed:
            status, why, reason = "not_established", "not_admitted", GATES[failed]
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
                **({"change_key": key} if key is not None else {}),
                "level": "technically_supported" if documented else "plausible",
                "purpose": basis["purpose"],
                "basis": [basis["id"]],
                "status": status,
                "parts": sorted(cites & ids),
                "supporting": [],
                "challenging": [],
                # from reading 3, an alternative stands on documents only where it cites one, not any part
                "strength": "doc" if strong else "own",
                "uncertainty": FROM_DOC if strong else expectation.FROM_OWN,
                "sufficiency": {"sufficient": status == "supported", **({"reason": why} if why else {})},
                **({"dropped_steps": dropped} if dropped else {}),
                **({"reason": reason} if reason else {}),
            }
        )
    return out


def _typed_claim(item, cid, channel, q, basis, component, practice, corpus, data, types) -> dict:
    """A typed entry's Alternative claim (`typed`)."""
    if data is None:
        data, types = vocabulary(DATA), vocabulary(RECIPIENT_TYPES)
    t = typed(item, cid, q, component, practice, corpus, data, types)
    status, why, reason = t["status"], t["why"], t["reason"]
    if basis["purpose"]["specificity"] == "vague":
        status, why, reason = "not_assessable", "purpose_vague", "the purpose is too vague"
    sufficiency = {"sufficient": status == "supported", **({"reason": why} if why else {})}
    if why == "fact_missing":
        sufficiency["missing"] = t["missing"]
    return {
        "id": cid,
        "type": "alternative",
        "stage": "assessment",
        "tier": "reasoning",
        "channels": [channel],
        "subject": q.record["practice"],
        "component": component,
        "alternative": item.get("alternative", ""),
        **t["fields"],
        "level": "technically_supported" if status == "supported" else "plausible",
        "purpose": basis["purpose"],
        "basis": [basis["id"]],
        "status": status,
        "parts": sorted(t["parts"]),
        "supporting": [],
        "challenging": [],
        "strength": t["strength"],
        "uncertainty": t["uncertainty"],
        "sufficiency": sufficiency,
        **({"dropped_steps": t["dropped"]} if t["dropped"] else {}),
        **({"reason": reason} if reason else {}),
    }


def stage1(a: Assessment, subjects: Subjects, corpus: Corpus, registry=None) -> list[dict]:
    """The expectation stage's hypotheses from its kept samples, as the assessment reads them, with the current notice
    definition (expectation.NOTICES): `skuld judge`, like `skuld assess`, works under the current methods, and only
    `skuld check` rebuilds with the versions a report names."""
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
    problems, notices = [], expectation.notices_of(report)
    for path in sorted((root / "assessment").rglob("context.json")):  # later attempts' too (s<seed>/a<n>/)
        try:
            check(Context(tuple(json.loads(path.read_text(encoding="utf-8"))["parts"])), notices)
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
