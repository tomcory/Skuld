"""
skuld assess: E's report on an application version (Ratatoskr's `expectation_assessment`), from what is kept; no model
is asked here (`skuld expect` and `skuld judge` ask).

    subjects        practices, declarations and the collection (assessment.py), the recipients' parties
                    (parties.py), the frame's conditions and every requirement's applicability (frame.py), written
                    to subjects.json
    rule tier       O–D correspondence (correspondence.py), the collection's transparency statuses
                    (transparency.py), concern (i)
    expectation     stage 1's claims from its kept samples (expectation.py), combined across samples into the
                    assessment stage's hypotheses (combine.hypotheses)
    experiments     the experimental channel's claims, read by the status rule (rules.py) from the case report's
                    measurements, per practice whose component an experimental case varies (experiments.premises),
                    combined with the hypotheses of aligned purposes (combine.experimental)
    reasoning tier  the judgements of its kept samples (judge.py), combined across samples: concerns (ii), (iv)
                    and (v) (concerns.py), the reasoning tier's Alternative claims (combine.alternatives)
    relations       O–E and D–E (relations.py), which concern (v) cites; pass-through and open conditions
    report          the combined claims (the claims they combine stay in the samples and the case report), the
                    concerns, E's coverage, the gaps someone could act on, the provenance check (provenance.py)
    qualification   the last stage (skuld.qualify, S-25): cases with their attributes, patterns and qualified
                    results, next steps, review triggers and the result profile

Ids are `<kind>:<subject>:<n>`: claim, concern, relation, gap; evidence items `item:<n>`, open conditions `open:<n>`.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import ratatoskr
from ratatoskr import notices as notice_rules
from ratatoskr.registry import Registry
from ratatoskr.schemas import validate

import skuld
from skuld import (
    assessment,
    combine,
    concerns,
    config,
    correspondence,
    expectation,
    experiments,
    frame,
    gaps,
    inputs,
    judge,
    qualify,
    relations,
    rules,
    select,
    transparency,
    uncertainty,
)
from skuld import scope as run_scope
from skuld.common import DATA, PURPOSES, RECIPIENT_TYPES, vocabulary
from skuld.corpus import NORMS
from skuld.corpus import load as load_corpus
from skuld.parties import load_registry

SUBJECTS = "subjects.json"
REPORT = "assessment.json"
MARKDOWN = "assessment.md"


def subjects(root: str | Path, registry_path: str | Path | None = None, write: bool = True) -> dict:
    """Builds the subjects of an assessment workspace and writes subjects.json; returns what it wrote."""
    a = inputs.load_assessment(root)
    return _subjects_json(root, a, _subjects(a, load_registry(registry_path)), write)


def _subjects_json(root: str | Path, a: inputs.Assessment, made: tuple, write: bool) -> dict:
    """subjects.json from what _subjects made, written if `write`."""
    built, decided, _, left_out = made
    out = {
        **built.to_json(),
        **(
            {"left_out": [{"id": p.id, "data": p.data, "recipient": p.recipient} for p in left_out]} if left_out else {}
        ),
        "frame": a.frame.reference(),
        "reports": {
            "observation": [{"path": str(r.path), "sha256": r.sha256, "run": r.run} for r in a.observations],
            "declaration": {"path": str(a.declaration.path), "sha256": a.declaration.sha256} if a.declaration else None,
        },
        "conditions": frame.to_json(decided),
        "applicability": frame.applicability(a.frame, decided),
    }
    if write:
        (Path(root) / SUBJECTS).write_text(
            json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
    return out


def known_data_only() -> bool:
    """config.json's `assessment.known_data_only`: leave out the practices whose datum O could not identify."""
    return bool((config.load().get("assessment") or {}).get("known_data_only"))


def _subjects(a: inputs.Assessment, registry: Registry | None):
    """The subjects the assessment judges, the frame's decisions on them, every practice (the expectation stage's
    batches are made of all of them), and the practices left out."""
    every = assessment.build(a, registry)
    built, left_out = assessment.known_data(every) if known_data_only() else (every, [])
    e = frame.evidence(built, [r.load() for r in a.observations], a.declaration.load() if a.declaration else None)
    return built, frame.decisions(a.frame, e), every, left_out


class Evidence:
    """The report's evidence items, `item:<n>`, each made once per key."""

    def __init__(self):
        self.items: list[dict] = []
        self.ids: dict[str, str] = {}

    def __call__(self, key: str, fields: dict) -> str:
        if key not in self.ids:
            self.ids[key] = f"item:{len(self.items) + 1}"
            self.items.append({"id": self.ids[key], **fields})
        return self.ids[key]


def assess(root: str | Path, registry_path: str | Path | None = None, write: bool = True) -> dict:
    """The assessment from what is kept: writes subjects.json, assessment.json and assessment.md (unless `write` is
    False, as for a replay); returns the report."""
    report, _ = build(root, registry_path, write)
    return report


def declared_text(d_report: dict | None, pointer: str) -> str | None:
    """A declaration's text as D annotated it (its description), by its claim pointer `<channel>:/<path>`, or None."""
    if not d_report or ":" not in pointer:
        return None
    channel, path = pointer.split(":", 1)
    node = next((c.get("tilt") for c in d_report.get("channels", []) if c.get("channel") == channel), None)
    for key in path.strip("/").split("/"):
        if isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        elif isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    text = node.get("description") if isinstance(node, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else None


def build(
    root: str | Path,
    registry_path: str | Path | None = None,
    write: bool = True,
    reading: str = judge.READING,
    notices: str = expectation.NOTICES,
) -> tuple[dict, list[dict]]:
    """The report, and the claims its combined claims combine (`of`): the samples' and the experiments'. `reading`
    is the version of the reasoning tier's reading (judge.READINGS), `notices` the version of Ratatoskr's notice
    definition the stage-1 contexts leave notice screens out by; a rebuild passes the ones its report names."""
    judge.reading_component(reading)
    notice_rules.component(notices)
    started = time.monotonic()
    root = Path(root)
    a = inputs.load_assessment(root)
    registry = load_registry(registry_path)
    made = _subjects(a, registry)
    _subjects_json(root, a, made, write)
    built, decided, every_practice, left_out = made
    d_report = a.declaration.load() if a.declaration else None
    o_reports = [r.load() for r in a.observations]
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)

    scope = run_scope.of_reports(o_reports)
    settled: list[dict] = []  # the denials' scopes and conditions the run's scope settles (D3)
    related = correspondence.relate(
        built,
        d_report,
        [s for r in o_reports for s in r.get("statuses", [])],
        registry,
        data,
        vocabulary(RECIPIENT_TYPES),
        scope,
        settled,
    )
    statuses = transparency.statuses(a.frame, built, decided, a.declaration.sha256 if a.declaration else "")
    item = Evidence()

    def refs(found: list) -> list[dict]:
        out = []
        for x in found:
            if isinstance(x, dict) and "dimension" in x:
                out.append(x)
            elif isinstance(x, str) and x.startswith("P-"):
                out.append(built.practice(x).claims[0])
        return out

    def rule_item(ref: dict) -> str:
        return item(
            json.dumps(ref, sort_keys=True), {"kind": "claim", "stage": "assessment", "channel": "rule", "claim": ref}
        )

    def decided_item(cid: str, side: str, dimension: str, x) -> list[str]:
        """What decided a condition, as evidence: a claim, or what a decision cites that is none (a derived document
        of D, a legal basis D references, an absence O established)."""
        found = refs([x])
        if found:
            return [rule_item(ref) for ref in found]
        said = x if isinstance(x, str) else json.dumps(x, sort_keys=True, ensure_ascii=False)
        method = f"{cid} {side} by {dimension}: {said}"
        key = json.dumps([cid, side, dimension, x], sort_keys=True)
        # cited from the assessment's inputs (the O and D reports assessment.yaml names), where it is found
        citation = {"id": inputs.ASSESSMENT, "at": f"{dimension}: {said}"}
        fields = {"kind": "doc", "stage": "assessment", "channel": "rule", "method": method, "citation": citation}
        return [item(key, fields)]

    evidence_of = {
        s.requirement: [
            i
            for cid in a.frame.requirement(s.requirement).applies_if
            for side in ("holds", "fails")
            for dimension, found in decided[cid].__dict__[side].items()
            for x in found
            for i in decided_item(cid, side, dimension, x)
        ]
        for s in statuses
    }
    stated, covered = concerns.information_not_given(a.frame, statuses, evidence_of)
    number = combine.Numbers()
    stage1, components = _expectation(a, every_practice, item, registry, {p.id for p in built.practices}, notices)
    hypotheses = combine.hypotheses(stage1, number)
    applicability = frame.applicability(a.frame, decided)
    tier = _reasoning_tier(a, built, hypotheses, item, registry, applicability, number, reading)
    premises = experiments.premises(a.cases, root, built.practices, item)
    tested = combine.experimental(hypotheses, premises, purposes, number)
    more, cover = concerns.less_invasive_alternative(
        a.frame, hypotheses, tier["alternatives"], tier["judged"], applicability, tested
    )
    stated += tier["concerns"] + more
    covered += tier["covered"] + cover
    # (iii): a declaration O contradicts (author, 14 Nov 2026)
    contradicted: dict[str, list] = {}

    def contradiction_items(d: str, rels: list) -> list[str]:
        contradicted[d] = rels
        declaration = next(x for x in built.declarations if x.id == d)
        said = declared_text(d_report, declaration.claim["claim"])
        out = [
            item(
                "declared:" + json.dumps(declaration.claim, sort_keys=True),
                {
                    "kind": "claim",
                    "stage": "assessment",
                    "channel": "rule",
                    "claim": declaration.claim,
                    **({"text": said} if said else {}),
                    "method": "the declaration as D annotated it",
                },
            )
        ]
        return out + sorted({rule_item(rel.of) for rel in rels}, key=lambda i: int(i.split(":")[1]))

    more, cover = concerns.declaration_contradicted(
        a.frame,
        [r for r in related if r.type == "O-D" and r.outcome == correspondence.CONTRADICTS],
        {d.claim["claim"]: d.id for d in built.declarations},
        contradiction_items,
        applicability,
        {d.id: t for d in built.declarations if (t := declared_text(d_report, d.claim["claim"]))},
    )
    stated += more
    covered += cover
    # purpose specificity is a requirement of declared purposes: a legal basis is no subject of it (8.6)
    covered += [
        concerns.Covered("purpose_specific", d.id, "rule", False)
        for d in built.declarations
        if d.kind == "justification" and d.type != "declares_purpose"
    ]
    concerns.number(stated)
    components += [c for c in tier["components"] if c not in components]

    expected = relations.o_e(built, hypotheses, tier["alternatives"], tested)
    if a.declaration is not None:
        vague = {
            d: c.id
            for c in stated
            if c.step == "not_specific" and c.status == "supported"
            for d in tier["vague"].get(c.subject, [])
        }
        expected += relations.d_e(built, hypotheses, vague, data, purposes, tested)
    every = related + expected
    correspondence.number(every)
    for c in stated:
        if c.step == "less_invasive_alternative":
            c.relations = [r.id for r in expected if r.type == "O-E" and {t["claim"] for t in r.to} & set(c.basis)]
        elif c.step == "declaration_contradicted":
            c.relations = [r.id for r in contradicted.get(c.subject, [])]
    claims = hypotheses + tier["alternatives"] + tested
    case_features = sorted({c.feature.id for c in a.cases.cases}) if a.cases else []
    open_ = relations.open_conditions(built, every, statuses, a.frame, stated, tested, case_features)
    from_d, settled = relations.from_declaration(a.declaration, built, every, registry)
    open_ += from_d

    report = {
        "report": {
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "skuld": skuld.__version__,
            "ratatoskr": ratatoskr.__version__,
            # what every claim of E has, stated once; its uncertainty is determined by its kind and premises
            "claims": {"attributes": {"polarity": "+"}, "determined": {"uncertainty": uncertainty.CLAIMS}},
            "components": [
                *built.components,
                correspondence.COMPONENT,
                combine.COMPONENT,
                rules.COMPONENT,
                judge.reading_component(reading),
                notice_rules.component(notices),
                relations.COMPONENT,
                concerns.COMPONENT,
                gaps.COMPONENT,
                *_declaration_analysis(a),
                {"role": "frame", "id": a.frame.id, "version": a.frame.version, "sha256": a.frame.digest()},
                {"role": "vocabulary", "id": DATA, "version": data.version},
                {"role": "vocabulary", "id": PURPOSES, "version": purposes.version},
                {"role": "vocabulary", "id": RECIPIENT_TYPES, "version": vocabulary(RECIPIENT_TYPES).version},
                *components,
            ],
            "cost": {
                "model_calls": 0,
                "seconds": round(time.monotonic() - started, 3),
                "device_seconds": experiments.device_seconds(a.cases, root),
            },
        },
        "application": {
            "package": a.package,
            "version": a.version,
            "store_version": (d_report or {}).get("collection", {}).get("store_version"),
        },
        "frame": a.frame.reference(),
        "inputs": {
            "observation": [
                {"id": r.run, "path": str(r.path), "sha256": r.sha256, "schema": "observation_report"}
                for r in a.observations
            ],
            "declaration": (
                {"path": str(a.declaration.path), "sha256": a.declaration.sha256, "schema": "declaration_report"}
                if a.declaration
                else None
            ),
            "exploration": str(a.exploration) if a.exploration else None,
            **({"comparability": built.comparability} if a.declaration else {}),
            "named": select.named(root) + inputs.version_compatibility(a),
        },
        "sources": _sources(a),
        "subjects": {
            "practices": [
                {
                    "id": p.id,
                    "claim_type": p.claim_type,
                    "data": p.data,
                    "recipient": p.recipient,
                    "actor": p.actor,
                    "party": p.party,
                    "episodes": p.episodes,
                    "u0": p.u0,
                    "claims": p.claims,
                }
                for p in built.practices
            ],
            "declarations": [_declaration(d, tier["statement_of"]) for d in built.declarations],
            "collection": _collection(built, statuses),
        },
        "features": _features(built, o_reports),
        "evidence": item.items,
        "relations": correspondence.to_json(every),
        "claims": [{k: v for k, v in c.items() if k != "uncertainty"} for c in claims],
        "concerns": concerns.to_json(stated),
        "coverage": concerns.coverage(a.frame, covered),
        "passed_on": relations.passed_on(
            built, a.observations, a.declaration, every, expected=bool(hypotheses), left_out=left_out
        ),
        "cases": _cases(a),
        "open": open_,
        "decided": settled,
        "gaps": _gaps(
            stated,
            claims,
            tested,
            a,
            tier["absent"],
            item,
            built,
            hypotheses,
            left_out,
            o_reports,
            load_corpus(a.corpus),
        ),
    }
    report["qualification"] = qualify.qualify(
        report,
        {r.id: r.subject for r in a.frame.requirements.values()},
        data,
        registry,
        {cid for r in a.frame.requirements.values() for cid in r.applies_if},
        a.frame,
    )
    report["report"]["components"] += qualify.COMPONENTS
    validate("expectation_assessment", report)
    problems = expectation.independent(root, report) + judge.independent(root, report)
    if problems:
        raise expectation.IndependenceError("; ".join(problems))
    if write:
        (root / REPORT).write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        (root / MARKDOWN).write_text(markdown(report, built, a.frame, settled, scope), encoding="utf-8", newline="\n")
    return report, stage1 + tier["members"] + premises


#: What a rebuilt report may differ in: when it was made and how long it took
VOLATILE = (("report", "created"), ("report", "cost", "seconds"))


def identity(report: dict) -> dict:
    """The report without what a rebuild from the same inputs and kept samples may change (EV-E-REPLAY)."""
    out = json.loads(json.dumps(report))
    for path in VOLATILE:
        node = out
        for key in path[:-1]:
            node = node.get(key, {})
        node.pop(path[-1], None)
    return out


def _expectation(
    a: inputs.Assessment,
    built,
    item: Evidence,
    registry,
    judged: set[str] | None = None,
    notices: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """The expectation stage's claims from the kept samples, with an evidence item per context part a supported claim
    rests on, and the samples' components. The samples are read with all practices (`built`), as they were asked;
    only the claims about the practices `judged` (all, if None) are kept."""
    claims, components = [], {}
    practices = {p.id: p for p in built.practices}
    for name, context, answer in expectation.kept(a, built, load_corpus(a.corpus), registry, notices):
        record = json.loads((a.root / "expectation" / name / "record.json").read_text(encoding="utf-8"))
        _record_components(components, record, "expectation")
        parts = {p["id"]: p for p in context.parts}
        for c in expectation.read(answer, name, context, practices):
            if judged is not None and c["subject"] not in judged:
                continue
            cited = c.pop("parts", [])
            if c["status"] == "supported":
                c["supporting"] = [i for x in cited for i in _part_items(item, name, parts[x])]
            claims.append(c)
    components["procedure"] = {"role": "method", **expectation.PROCEDURE, "stage": "expectation"}
    components["reading"] = {**expectation.READING_COMPONENT, "stage": "expectation"}
    return claims, list(components.values()) if claims else []


def _sha(digest) -> bool:
    return isinstance(digest, str) and len(digest.removeprefix("sha256:")) == 64


def _part_items(
    item: Evidence,
    sample: str,
    part: dict,
    stage: str = "expectation",
    d_report: str | None = None,
    hypotheses: dict[str, dict] | None = None,
) -> list[str]:
    """The evidence items of a context part a sample's claim cites: O's claim of a practice, a passage, a declaration
    by D's claims (one item per claim), a hypothesis with its premises, or a screen."""
    base = {"stage": stage, "channel": f"reasoning:{sample}", "text": part["text"]}
    pointer = part["provenance"][0]
    key = f"{sample}#{part['id']}"
    if part["kind"] == "declaration":
        return [
            item(
                f"{key}#{n}",
                {**base, "kind": "claim", "claim": {"dimension": "D", "report": d_report, "claim": p["record"]}},
            )
            for n, p in enumerate(part["provenance"])
            if p.get("origin") == "d_report"
        ]
    if part["kind"] == "practice":
        return [item(key, {**base, "kind": "claim", "claim": json.loads(pointer["record"])})]
    if part["kind"] == "passage":
        return [item(key, {**base, "kind": "doc", "citation": {"id": pointer["record"]}})]
    if part["kind"] == "hypothesis":
        h = (hypotheses or {}).get(pointer["record"], {})
        fields = {"kind": "doc", "method": f"hypothesis of the expectation stage ({pointer['record']})"}
        return [item(key, {**base, **fields, "premises": h.get("supporting", [])})]
    run = pointer.get("run") or pointer["record"]
    fields = {"kind": "doc", "method": f"{part['kind']} of {run}", "citation": {"id": run, "at": pointer["record"]}}
    return [item(key, {**base, **fields})]


def _declaration_analysis(a: inputs.Assessment) -> list[dict]:
    """The D analysis whose report the assessment read: the transparency concerns' error rates depend on it, so a
    calibration holds for it alone. D's version and report, and the modules and mappings each channel's derived
    document names (its `analysis` components), by channel and D's role."""
    if a.declaration is None:
        return []
    report = a.declaration.load()
    out = [
        {
            "role": "declaration_analysis",
            "id": "urda",
            "version": report.get("report", {}).get("urda", ""),
            "sha256": a.declaration.sha256,
        }
    ]
    for ch in report.get("channels", []):
        for m in ((ch.get("tilt") or {}).get("_asgard") or {}).get("analysis") or ():
            if "id" not in m:
                continue
            entry = {"role": "declaration_analysis", "id": f"{ch['channel']}:{m.get('role', '?')}:{m['id']}"}
            if isinstance(m.get("version"), str):
                entry["version"] = m["version"]
            out.append(entry)
    return out


def _record_components(components: dict, record: dict, stage: str) -> None:
    components[record["prompt"]["sha256"]] = {
        "role": "prompt",
        "id": record["prompt"]["id"],
        "version": record["prompt"]["version"],
        "sha256": record["prompt"]["sha256"],
        "stage": stage,
    }
    model = record["model"]
    # the reasoning setting the sample was asked with (ask.py records it where it was set): the same model with
    # reasoning off and on is two configurations, which the report must tell apart
    # unset in the options, the sample may say it was the model's default (asked from 20 Nov 2026), else nothing
    think = record["options"].get("think", record["model"].get("think"))
    components[f"model:{stage}:{model['name']}:{record['options']['seed']}:{think}"] = {
        "role": "model",
        "id": model["name"],
        **({"sha256": model["digest"].removeprefix("sha256:")} if _sha(model.get("digest")) else {}),
        "stage": stage,
        "seed": record["options"]["seed"],
        **({"think": think} if think is not None else {}),
    }


def _reasoning_tier(
    a: inputs.Assessment,
    built,
    hypotheses: list[dict],
    item: Evidence,
    registry,
    applicability,
    number,
    reading: str = judge.READING,
) -> dict:
    """The reasoning tier's combined Alternative claims, its concerns (ii) and (iv) and their coverage from its kept
    samples, the samples' components, and the questions expected but not asked."""
    corpus = load_corpus(a.corpus)
    norms = load_corpus(a.corpus / NORMS)
    factors = [f.id for f in a.frame.requirement("purpose_compatible").factors]
    by_id = {h["id"]: h for h in hypotheses}
    d_sha = a.declaration.sha256 if a.declaration else None
    contexts, components = {}, {}
    specific, compatible, members, judged, asked = [], [], [], set(), {q: 0 for q in judge.QUESTIONS}
    minimisation_samples: dict[str, set[str]] = {}  # per practice, the kept samples of its question (gate d)
    for name, q, answer in judge.kept(
        a, built, corpus, norms, hypotheses, factors, expectation.names(registry), reading
    ):
        record = json.loads((a.root / name / "record.json").read_text(encoding="utf-8"))
        _record_components(components, record, "assessment")
        components[f"procedure:{q.question}"] = {"role": "method", **judge.procedure(q.question), "stage": "assessment"}
        contexts[name] = {p["id"]: p for p in q.context.parts}
        asked[q.question] += 1
        if q.question == judge.SPECIFICITY:
            specific += judge.specificity(answer, name, q)
        elif q.question == judge.COMPATIBILITY:
            compatible += judge.compatibility(answer, name, q)
        else:
            judged.add(q.record["practice"])
            minimisation_samples.setdefault(q.record["practice"], set()).add(name)
            practice = next((p for p in built.practices if p.id == q.record["practice"]), None)
            members += judge.minimisation(answer, name, q, by_id, reading, practice, corpus)

    def items(sample: str, ids: list[str]) -> list[str]:
        parts = contexts[sample]
        return [i for x in ids if x in parts for i in _part_items(item, sample, parts[x], "assessment", d_sha, by_id)]

    for c in members:
        cited = c.pop("parts", [])
        if c["status"] == "supported":
            c["supporting"] = items(c["channels"][0].removeprefix("reasoning:"), cited)
    said = judge.statements(a, built) if a.declaration else []
    # from reading 2, a declared purpose judged not specific specifies nothing (E 0.9, def:concern)
    # from reading 4, only where purpose_specific applies (concerns.not_specific states no concern otherwise)
    applies = concerns._applies(applicability, "purpose_specific") if int(reading) >= 4 else True
    vague = judge.vague_declarations(specific, applies) if judge.gated(reading) else frozenset()
    stated, covered = concerns.not_specific(a.frame, said, specific, items, applicability)
    if a.declaration is not None and built.comparability.get("comparable") is not False:
        more, cover = concerns.purpose_limitation(
            a.frame,
            judge.limitation(built, said, hypotheses, vague),
            compatible,
            items,
            applicability,
            {d.id: d.uncertainty for d in built.declarations},
        )
        stated += more
        covered += cover
    expected = {
        q.question for q in judge.questions(a, built, corpus, norms, hypotheses, expectation.names(registry), vague)
    }
    return {
        "alternatives": combine.alternatives(members, number, minimisation_samples if judge.gated(reading) else None),
        "members": members,
        "judged": judged,
        "vague": {s.declarations[0]: s.declarations for s in said},
        "statement_of": {d: s.id for s in said for d in s.declarations},
        "concerns": stated,
        "covered": covered,
        "components": list(components.values()),
        "absent": [q for q in judge.QUESTIONS if q in expected and not asked[q]],
    }


def _declaration(d, statement_of: dict[str, str]) -> dict:
    """A declaration as the report states it: by reference, with what qualification's case attributes read (S-24), and
    for a declared purpose the statement it is said in (8.8)."""
    out = {"id": d.id, "claim": d.claim, "kind": d.kind, "type": d.type, "channel": d.channel, "polarity": d.polarity}
    if d.id in statement_of:
        out["statement"] = statement_of[d.id]
    if d.data:
        out["data"] = d.data
    if d.type == "declares_recipient" and d.value is not None:
        out["recipient"] = d.value
    elif d.kind == "justification" and isinstance(d.value, str | int | float):
        out["value"] = d.value
    return out


def own_knowledge_exhausted() -> bool:
    """config.json's `gaps.own_knowledge_exhausted` (default off: D4, adopted only after its effect is measured): a
    practice without a purpose whose recipient's or actor's documentation the corpus holds ends in an audit request."""
    return bool((config.load().get("gaps") or {}).get("own_knowledge_exhausted"))


def _documented(corpus, practice) -> bool:
    """Whether the corpus holds documentation of a practice's recipient or actor (a passage about its entity)."""
    if corpus is None:
        return False
    names = {str(x).removeprefix("component:").lower() for x in (practice.recipient, practice.actor) if x}
    names -= {"?", "", "none"}
    return any(str(e).lower() in names for passage in corpus.passages for e in passage.entities)


def _payload_reasons(practice, o_reports: list[dict], by_sha: dict[str, dict]) -> list[str]:
    """O's reasons the payloads of a practice's claims could not be read: the reasons of their unidentified data items,
    else the scopes' payload exclusions (`payload_<reason>`) of the reports the claims are in."""
    reasons, reports = set(), []
    for ref in practice.claims:
        report = by_sha.get(ref.get("report"))
        if report is None:
            continue
        reports.append(report)
        claim = next((c for c in report.get("claims", []) if c.get("id") == ref.get("claim")), None)
        items = {e["id"]: e for e in report.get("evidence", [])}
        for i in (claim or {}).get("evidence") or ():
            prop = (items.get(i) or {}).get("proposition") or {}
            if prop.get("identified") is False and prop.get("reason"):
                reasons.add(str(prop["reason"]))
    if not reasons:
        for report in reports or o_reports:
            for scope in report.get("scopes", []):
                excluded = scope.get("exclusions") if isinstance(scope.get("exclusions"), dict) else {}
                for counts in excluded.values():
                    if isinstance(counts, dict):
                        reasons |= {k.removeprefix("payload_") for k in counts if k.startswith("payload_")}
    return sorted(reasons)


def _achieved_on(x: dict, hypotheses: list[dict], purposes) -> str | None:
    """Where an experimental claim's purpose is achieved: as its case states it, else as the stage-1 hypotheses of its
    practice aligned with it agree (combine.aligned), else None."""
    said = (x.get("purpose") or {}).get("achieved_on")
    if said:
        return said
    own = [h for h in hypotheses if h["subject"] == x.get("subject") and h["type"] == "purpose"]
    found = {
        h["purpose"].get("achieved_on")
        for h in own
        if h["id"] in combine.aligned(own, [x.get("purpose") or {}], purposes) and h["purpose"].get("achieved_on")
    }
    return found.pop() if len(found) == 1 else None


def _gaps(
    stated: list,
    claims: list[dict],
    tested: list[dict],
    a: inputs.Assessment,
    absent: list[str],
    item: Evidence,
    built=None,
    hypotheses: list[dict] = (),
    left_out: list = (),
    o_reports: list[dict] = (),
    corpus=None,
) -> list[dict]:
    """The gaps someone could act on, each with the propositions it bears on and its next step (gaps.py): the frame's
    applicability conditions of concerns that no dimension decided; the premises of concerns not established; what the
    experiments could not settle; questions not asked; D's report absent; and every practice E established no purpose
    for, which is therefore assessed for no requirement of practices (S-23). A concern's source conditions (a document
    not analysed, or acquired incomplete) and its fact conditions (a channel's definition, a role, a reading, the
    denial's scope) are open conditions with their own steps, no gaps (relations.open_conditions)."""
    out: list[dict] = []
    by_id = {c["id"]: c for c in claims}
    n: dict[str, int] = {}
    frame = a.frame
    applicability = {cid for r in frame.requirements.values() for cid in r.applies_if}
    of_subject = {r.id for r in frame.requirements.values() if r.subject == "practice"}
    purposes = vocabulary(PURPOSES)
    exhausted = own_knowledge_exhausted()

    def requirement(rid: str) -> dict:
        r = frame.requirements.get(rid)
        return gaps.bearing(f"requirement:{rid}", f"{rid}: {r.title}" if r is not None else rid)

    def gap(subject: str, reason: str, proposition: str, required: str, bears_on: list, next_: dict, **fields):
        n[subject] = n.get(subject, 0) + 1
        g = {
            "id": f"gap:{subject}:{n[subject]}",
            **fields,
            "proposition": proposition,
            "required": required,
            "reason": reason,
            "bears_on": bears_on,
            "next": next_,
        }
        gaps.check(g, frame, by_id)
        out.append(g)

    def of_claim(c: dict, requirements: list[str], reason: str | None = None) -> None:
        reason = reason or c["sufficiency"].get("reason") or "not_admitted"
        what = c.get("relationship") or c.get("alternative") or c["purpose"].get("node")
        said = f"{c['type']} of {c['subject']}" + (f" ({c['component']})" if c.get("component") else "") + f": {what}"
        gap(
            c["subject"],
            reason,
            said,
            "; ".join(c["sufficiency"].get("missing", [])) or c.get("reason") or "a supporting item",
            [gaps.bearing(f"claim:{c['id']}", said), *(requirement(r) for r in requirements)],
            gaps.reason_step(
                reason,
                said,
                claim_type=c["type"],
                achieved_on=_achieved_on(c, list(hypotheses), purposes) if reason == "oracle_not_observable" else None,
            ),
            of=c["id"],
        )

    for c in stated:
        for cid in c.condition:
            if cid not in applicability or cid not in frame.conditions:
                continue  # a source or fact condition: an open condition with its own step
            text = frame.conditions[cid].text
            gap(
                c.subject,
                "applicability_unknown",
                text,
                f"whether {cid} holds, for {c.requirement} to apply",
                [gaps.bearing(f"condition:{cid}", text)],
                gaps.condition_step(f"condition:{cid}", gaps.frame_level(frame, "condition", cid), text),
                of=c.id,
            )
    seen = set()
    for c in stated:
        if c.status == "supported":
            continue
        premises = [by_id[b] for b in c.basis if b in by_id and by_id[b]["status"] not in combine.DECISIVE]
        for p in premises:
            if p["id"] not in seen:
                seen.add(p["id"])
                of_claim(p, [c.requirement])
        if not premises:
            said = f"{c.step.replace('_', ' ')}: {c.requirement}"
            gap(
                c.subject,
                "not_admitted",
                said,
                c.reason or "",
                [requirement(c.requirement)],
                gaps.reason_step("not_admitted", said, requirement=c.requirement),
                of=c.id,
            )
    for x in tested:
        if x["status"] not in combine.DECISIVE and x["id"] not in seen:
            seen.add(x["id"])
            of_claim(x, ["data_minimised"])
    measured = experiments.case_report(a.cases, a.root) or {"cases": [], "comparisons": []}
    for k in measured["comparisons"]:
        parts = k.get("unverifiable") or []
        citing = [x for x in tested if item.ids.get(k["id"]) in x["supporting"] + x["challenging"]]
        if parts and citing:
            substitution = any(u.startswith("substitution") for u in parts)
            said = f"whether the runs of comparison {k['id']} ran under {k['alternative']} alone"
            gap(
                k["case"],
                "substitution_not_verifiable" if substitution else "not_covered",
                said,
                "; ".join(parts),
                [gaps.bearing(f"claim:{x['id']}", f"{x['type']} of {x['subject']}") for x in citing],
                gaps.step(
                    gaps.EXPERIMENT,
                    "repeat the runs with every identifier source hooked with pass"
                    if substitution
                    else "repeat the runs with those connections recorded",
                ),
            )
    if a.cases is not None:
        for case in a.cases.cases:
            for purpose in case.purposes:
                oracle = a.cases.oracles.get(purpose.oracle) if purpose.oracle else None
                unreached = [r["id"] for r in purpose.requirements if oracle and r["id"] not in oracle.reach]
                mine = [x for x in tested if x["case"] == case.id and x["purpose"]["id"] == purpose.id]
                if unreached and mine:
                    said = f"whether {purpose.id} of case {case.id} achieves {', '.join(unreached)}"
                    gap(
                        case.id,
                        "requirements_not_reached",
                        said,
                        f"an oracle that reaches {', '.join(unreached)}, on a path that exercises them",
                        [gaps.bearing(f"claim:{x['id']}", f"{x['type']} of {x['subject']}") for x in mine],
                        gaps.step(gaps.EXPLORE, f"a goal-directed run of {case.feature.id} that reaches them"),
                        feature=case.feature.id,  # what a goal-directed exploration would reach (L-10)
                    )
        for c in measured["cases"]:
            for alt in c["scope"]["search_space"]:
                if alt.get("problems"):
                    said = f"whether {alt['id']} preserves the purposes of case {c['id']}"
                    gap(
                        c["id"],
                        "precondition_failed",
                        said,
                        "an alternative less invasive than the baseline in its component's dimension: "
                        + "; ".join(alt["problems"]),
                        [requirement("data_minimised")],
                        gaps.step(gaps.EXPERIMENT, f"correct {alt['id']} against the baseline and run it"),
                    )
    for question in absent:
        rid = judge.REQUIREMENT[question]
        gap(
            rid,
            "source_absent",
            f"{rid}: the reasoning tier's judgement",
            f"kept samples of the {question} question",
            [requirement(rid)],
            gaps.step(gaps.ACQUIRE, f"kept samples of the {question} question (skuld judge)"),
            of=rid,
        )
    if built is not None and hypotheses:
        purposeful = {h["subject"] for h in hypotheses if h["type"] == "purpose" and h["status"] == "supported"}
        for p in built.practices:
            if p.id in purposeful:
                continue
            what = p.recipient or p.actor
            said = f"the purposes of {p.claim_type} {p.data}" + (f" to {p.recipient}" if p.recipient else "")
            # D4: external means exhausted where the corpus documents the recipient or actor (off by default)
            next_ = gaps.reason_step("own_knowledge", said, exhausted=exhausted and _documented(corpus, p))
            gap(
                p.id,
                "own_knowledge",
                said,
                f"documentation of {what} in the corpus, so that the expectation stage can establish a purpose",
                [requirement(r) for r in ("purpose_specified", "data_minimised") if r in frame.requirements],
                next_,
                of=p.id,
            )
    by_sha = {r.sha256: rep for r, rep in zip(a.observations, o_reports, strict=False)}
    for p in left_out:
        said = (
            f"what practice {p.id} ({p.claim_type} {p.data}"
            + (f" to {p.recipient}" if p.recipient else "")
            + ") carries"
        )
        gap(
            p.id,
            "source_not_analysable",
            said,
            "the datum identified: O saw the connection, but its content is encrypted, binary or damaged; the practice "
            "is left out of the assessment",
            [requirement(r) for r in sorted(of_subject)],
            gaps.reason_step("source_not_analysable", said, payloads=_payload_reasons(p, list(o_reports), by_sha)),
        )
    if a.declaration is None:
        requirements = [r.id for r in frame.requirements.values() if r.subject in ("collection", "declaration")]
        g = {
            "id": "gap:collection:1",
            "of": "collection",
            "proposition": f"the collection gives the information of {len(requirements)} requirements, declared "
            "purposes are specific",
            "required": "D's report on the version's declarations",
            "reason": "source_absent",
            "bears_on": [requirement(r) for r in requirements],
            "next": gaps.step(gaps.ACQUIRE, "collect and analyse the app's declarations (Sága, Urda)"),
        }
        gaps.check(g, frame, by_id)
        out.append(g)
    return out


def _sources(a: inputs.Assessment) -> dict:
    items = [
        {
            "id": r.run or f"o{n}",
            "type": "observation_report",
            "path": str(r.path),
            "sha256": r.sha256,
            "analysable": True,
        }
        for n, r in enumerate(a.observations)
    ]
    if a.declaration:
        items.append(
            {
                "id": "d",
                "type": "declaration_report",
                "path": str(a.declaration.path),
                "sha256": a.declaration.sha256,
                "analysable": True,
            }
        )
    if a.exploration:
        items.append({"id": a.exploration.name, "type": "exploration", "path": str(a.exploration), "analysable": True})
    items.append(
        {"id": "corpus", "type": "corpus", "path": str(a.corpus), "sha256": a.corpus_sha256, "analysable": True}
    )
    return {
        "items": items,
        "acquisition": {
            "observation_report": "acquired",
            "declaration_report": "acquired" if a.declaration else "absent",
            "exploration": "acquired" if a.exploration else "absent",
            "corpus": "acquired",
        },
    }


def _collection(built, statuses) -> dict | None:
    """The collection's documents and transparency statuses; what decided each condition is in subjects.json. Whether
    a document was acquired complete is D's."""
    if built.collection is None:
        return None
    documents = [
        {"channel": d["channel"], "document": d["document"], "complete": d.get("complete", True)}
        for d in built.collection["documents"]
        if d["status"] == "analysed" and d.get("document")
    ]
    return {
        "documents": documents,
        "transparency": [
            {
                "requirement": s.requirement,
                "applicability": s.applicability,
                "status": s.status,
                **({"conditions": s.conditions} if s.conditions else {}),
                **({"addressed_by": s.addressed_by} if s.addressed_by else {}),
            }
            for s in statuses
        ],
    }


def _features(built, o_reports: list[dict]) -> list[dict]:
    titles = {}
    for report in o_reports:
        for scope in report.get("scopes", []):
            for e in (scope.get("context") or {}).get("exercise", {}).get("episodes", []):
                titles[str(e.get("episode"))] = e.get("flow")
    episodes = sorted({e for p in built.practices for e in p.episodes if e != "?"}, key=lambda e: (len(e), e))
    return [
        {
            "id": f"episode-{e}",
            **({"title": titles[e]} if titles.get(e) else {}),
            "episodes": [e],
            "practices": [p.id for p in built.practices if e in p.episodes],
        }
        for e in episodes
    ]


def _cases(a: inputs.Assessment) -> list[dict]:
    path = a.root / "report.json"
    if a.cases is None or not path.is_file():
        return []
    return [{"path": experiments.CASE_REPORT, "sha256": inputs.digest(path), "schema": "expectation_report"}]


def _what(built):
    practices = {p.id: p for p in built.practices}

    def what(subject: str) -> str:
        p = practices.get(subject)
        return f"{p.claim_type} {p.data} → {p.recipient or '–'}" if p else subject

    return what


def _gaps_markdown(found: list[dict]) -> list[str]:
    """The gaps counted by the kind of their next step, with the unit each counts (a practice, a claim, a condition of
    a concern), and the audit requests by what they request (`held`)."""
    if not found:
        return []
    counted: dict[str, dict[str, int]] = {}
    for g in found:
        kind = g["next"]["kind"] + (f" ({g['next']['held']})" if g["next"].get("held") else "")
        units = counted.setdefault(kind, {})
        units[gaps.unit(g)] = units.get(gaps.unit(g), 0) + 1
    lines = ["", "## Gaps by next step", "", "| Next step | Gaps | Unit |", "|---|---|---|"]
    for kind in sorted(counted, key=lambda k: (gaps.KINDS.index(k.split(" ")[0]), k)):
        units = counted[kind]
        lines.append(
            f"| {kind} | {sum(units.values())} | " + ", ".join(f"{u} {v}" for u, v in sorted(units.items())) + " |"
        )
    return lines


def _coverage_markdown(frame) -> list[str]:
    """The coverage statement (Frame.coverage, from the frame alone): per requirement, how far a concern and a silence
    can be established from outside; a frame that declares no level is read with the current frame's (gaps.py)."""
    lines = [
        "",
        "## Coverage statement",
        "",
        "What any assessment under the frame can establish from outside: per requirement, the level of a concern and of a "
        "silence (no concern identified).",
        "",
        "| Requirement | Concern | Silence |",
        "|---|---|---|",
    ]

    def said(level: dict | None) -> str:
        if not level:
            return "–"
        return f"{level['level']} ({level['reach']}{', ' + level['held'] if level.get('held') else ''})"

    for entry in frame.coverage():
        rid = entry["requirement"]
        concern = entry["concern"] or gaps.frame_level(frame, "requirement", rid, "concern")
        silence = entry["silence"] or gaps.frame_level(frame, "requirement", rid, "silence")
        lines.append(f"| {rid} | {said(concern)} | {said(silence)} |")
    return lines


def markdown(report: dict, built, frame=None, settled: list | None = None, scope=None) -> str:
    """The report for a reader: the relations, the concerns, the experiments, the open conditions, what the run's
    scope settled, the gaps by next step and the frame's coverage statement."""
    app = report["application"]
    what = _what(built)
    claims = {c["id"]: c for c in report["claims"]}
    lines = [f"# Assessment of {app['package']} {app['version']}", ""]
    lines += [
        f"Frame {report['frame']['id']} {report['frame']['version']}; {len(built.practices)} practices, "
        f"{len(built.declarations)} declarations; from the samples kept (no model asked here).",
        "",
        "## O–D correspondence",
        "",
        "| Practice | Aspect | Outcome | Alignment or condition |",
        "|---|---|---|---|",
    ]
    for r in report["relations"]:
        if r["type"] == "O-D":
            lines.append(
                f"| {what(r.get('subject', ''))} | {r.get('aspect', '')} | {r['outcome']} | "
                f"{r.get('condition') or r.get('alignment') or ''} |"
            )
    o_e = [r for r in report["relations"] if r["type"] == "O-E"]
    if o_e:
        lines += [
            "",
            "## O–E: practices against E's expectation",
            "",
            "| Practice | Purpose | Aspect | Outcome | Deciding claim |",
            "|---|---|---|---|---|",
        ]
        for r in o_e:
            read = [claims[t["claim"]] for t in r["to"] if t["claim"] in claims]
            purpose = next((c["purpose"] for c in read), {})
            name = f"{purpose.get('id', '–')} ({purpose.get('node', '?')})" if purpose else "–"
            found = relations.outcome(r.get("aspect") or "data", [c for c in read if c["type"] != "purpose"])[1]
            decided = (
                f"{found['status']}, {found.get('level') or found.get('relationship') or ''} ({found['strength']})"
                if found
                else r.get("reason", "–")
            )
            lines.append(f"| {what(r['subject'])} | {name} | {r.get('aspect') or '–'} | {r['outcome']} | {decided} |")
    d_e = [r for r in report["relations"] if r["type"] == "D-E"]
    if d_e:
        declarations = {d.id: d for d in built.declarations}
        lines += ["", "## D–E: declared purposes against E's expectation", "", "| Declared | Outcome | Reason |"]
        lines.append("|---|---|---|")
        lines += [
            f"| {declarations[r['subject']].value} for {declarations[r['subject']].data} | {r['outcome']} | "
            f"{r.get('reason', '')} |"
            for r in d_e
        ]
    lines += ["", "## Concerns", ""]
    if report["concerns"]:
        lines += [
            f"- {c['requirement']} ({c['tier']}), {c['subject']}: {c['step'].replace('_', ' ')} ({c['status']}"
            + (f", if {', '.join(c['condition'])}" if c.get("condition") else "")
            + ")"
            + (f": {c['reason']}" if c["tier"] == "reasoning" and c.get("reason") else "")
            for c in report["concerns"]
        ]
    else:
        lines.append("No concern identified.")
    tested = [c for c in report["claims"] if c.get("case")]
    if tested:
        lines += [
            "",
            "## Experiments",
            "",
            "| Practice | Case purpose | Claim | Status | Reasoning |",
            "|---|---|---|---|---|",
        ]
        for c in tested:
            claim = f"{c['type']} {c.get('relationship') or c.get('alternative') or ''}".strip()
            status = c["status"] + (f" ({c['strength']})" if c.get("strength") else "")
            spoke = ", ".join(c["basis"]) or "silent"
            lines.append(
                f"| {c['subject']} | {c['purpose']['id']} ({c['purpose']['node']}) of {c['case']} | {claim} | {status} | {spoke} |"
            )
    if report["open"]:
        lines += ["", "## Open conditions", ""]
        lines += [f"- {o['text']} (qualifies {', '.join(o['qualifies'])})" for o in report["open"]]
    if settled:
        lines += ["", "## Settled by the run's scope", "", f"The run's scope: {run_scope.described(scope)}.", ""]
        lines += [
            f"- {x['declaration']}, limited to {x['limit']}: {'applies' if x['outcome'] == 'holds' else 'does not apply'}"
            for x in settled
        ]
    lines += _gaps_markdown(report["gaps"])
    if frame is not None:
        lines += _coverage_markdown(frame)
    if report.get("qualification"):
        lines += _qualification_markdown(report["qualification"], what)
    return "\n".join(lines) + "\n"


RESULT_NAMES = {
    "externally_established_discrepancy": "externally established discrepancy",
    "externally_supported_concern": "externally supported concern",
    "insufficient_or_conflicting_evidence": "insufficient or conflicting evidence",
    "not_externally_assessable": "not externally assessable",
    "no_concern_detected": "no concern detected within the tested scope",
    "not_applicable": "not applicable (no requirement applies)",
}


def _qualification_markdown(q: dict, what) -> list[str]:
    """The qualification for a reader: the profile, the cases, the sections and the next steps."""
    from skuld.qualify.symbols import SIGN

    p = q["profile"]
    lines = [
        "",
        "## Qualification",
        "",
        "Result profile: cases per qualified result, a fact about this application, not a rank.",
        "",
    ]
    lines += ["| Result | Practices | Declaration-only | Declared purposes | Collection |", "|---|---|---|---|---|"]
    for key, name in RESULT_NAMES.items():
        counts = [p[g].get(key, 0) for g in ("practice", "declaration", "declared_purposes", "collection")]
        lines.append(f"| {name} | " + " | ".join(str(c) for c in counts) + " |")
    lines += ["", "### Cases", "", "| Case | O–D, O–E, D–E | Result | Reason | Triggers that weigh |"]
    lines.append("|---|---|---|---|---|")
    for c in q["cases"]:
        pattern = ", ".join(SIGN[c["pattern"][k]["symbol"]] for k in ("O-D", "O-E", "D-E"))
        weighs = [t["trigger"].replace("_", " ") for t in c["triggers"] if t["weighs"]]
        subject = what(c["subject"]) if c["kind"] == "practice" else f"{c['subject']} (declared only)"
        reason = c["reason"].replace("|", "/")
        lines.append(f"| {subject} | {pattern} | {RESULT_NAMES[c['result']]} | {reason} | {', '.join(weighs) or '–'} |")
    for name, section in (("Declared purposes", q["declared_purposes"]), ("Collection", q["collection"])):
        lines += ["", f"### {name}", ""]
        if not section["assessed"]:
            lines.append(section.get("reason", "not assessed"))
            continue
        counts: dict[str, int] = {}
        for r in section["rows"]:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
        lines.append("; ".join(f"{RESULT_NAMES[k]}: {v}" for k, v in counts.items()) or "none")
    lines += ["", "### Next steps", "", "| Step | Kind | By | Could change a result | Cases | Decides |"]
    lines.append("|---|---|---|---|---|---|")
    for s in q["next_steps"]:
        kind = s["kind"] + (f" ({s['held']})" if s.get("held") else "")
        change = "yes" if s["could_change"] else "no"
        lines.append(
            f"| {s['id']} | {kind} | {s['by']} | {change} | {len(s['cases'])} | {s['decides'].replace('|', '/')} |"
        )
    if q["unplaced"]:
        lines += ["", "### Unplaced", ""] + [f"- {u['id']}: {u['reason']}" for u in q["unplaced"]]
    lines += ["", "### Limitations", ""] + [f"- {x}" for x in q["limitations"]]
    return lines
