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
                    measurements, per practice whose component a case varies (experiments.premises), combined with
                    the hypotheses of aligned purposes (combine.experimental)
    reasoning tier  the judgements of its kept samples (judge.py), combined across samples: concerns (ii), (iii)
                    and (v) (concerns.py), the reasoning tier's Alternative claims (combine.alternatives)
    relations       O–E and D–E (relations.py), which concern (v) cites; pass-through and open conditions
    report          the combined claims (the claims they combine stay in the samples and the case report), the
                    concerns, E's coverage, the gaps someone could act on, the provenance check (provenance.py)

Ids are `<kind>:<subject>:<n>`: claim, concern, relation, gap; evidence items `item:<n>`, open conditions `open:<n>`.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import ratatoskr
from ratatoskr.registry import Registry
from ratatoskr.schemas import validate

import skuld
from skuld import (
    assessment,
    combine,
    concerns,
    correspondence,
    expectation,
    experiments,
    frame,
    inputs,
    judge,
    relations,
    select,
    transparency,
    uncertainty,
)
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
    built, decided = _subjects(a, load_registry(registry_path))
    out = {
        **built.to_json(),
        "frame": a.frame.reference(),
        "reports": {
            "observation": [{"path": str(r.path), "sha256": r.sha256, "run": r.run} for r in a.observations],
            "declaration": {"path": str(a.declaration.path), "sha256": a.declaration.sha256} if a.declaration else None,
        },
        "conditions": frame.to_json(decided),
        "applicability": frame.applicability(a.frame, decided),
    }
    if write:
        (Path(root) / SUBJECTS).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _subjects(a: inputs.Assessment, registry: Registry | None):
    built = assessment.build(a, registry)
    e = frame.evidence(built, [r.load() for r in a.observations], a.declaration.load() if a.declaration else None)
    return built, frame.decisions(a.frame, e)


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


def build(root: str | Path, registry_path: str | Path | None = None, write: bool = True) -> tuple[dict, list[dict]]:
    """The report, and the claims its combined claims combine (`of`): the samples' and the experiments'."""
    started = time.monotonic()
    root = Path(root)
    subjects(root, registry_path, write)
    a = inputs.load_assessment(root)
    registry = load_registry(registry_path)
    built, decided = _subjects(a, registry)
    d_report = a.declaration.load() if a.declaration else None
    o_reports = [r.load() for r in a.observations]
    data, purposes = vocabulary(DATA), vocabulary(PURPOSES)

    related = correspondence.relate(
        built,
        d_report,
        [s for r in o_reports for s in r.get("statuses", [])],
        registry,
        data,
        vocabulary(RECIPIENT_TYPES),
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

    evidence_of = {
        s.requirement: [
            rule_item(ref)
            for cid in a.frame.requirement(s.requirement).applies_if
            for side in ("holds", "fails")
            for ref in refs([x for v in decided[cid].__dict__[side].values() for x in v])
        ]
        for s in statuses
    }
    stated, covered = concerns.information_not_given(a.frame, statuses, evidence_of)
    number = combine.Numbers()
    stage1, components = _expectation(a, built, item, registry)
    hypotheses = combine.hypotheses(stage1, number)
    applicability = frame.applicability(a.frame, decided)
    tier = _reasoning_tier(a, built, hypotheses, item, registry, applicability, number)
    premises = experiments.premises(a.cases, root, built.practices, item)
    tested = combine.experimental(hypotheses, premises, purposes, number)
    more, cover = concerns.less_invasive_alternative(
        a.frame, hypotheses, tier["alternatives"], tier["judged"], applicability, tested
    )
    stated += tier["concerns"] + more
    covered += tier["covered"] + cover
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
        expected += relations.d_e(built, hypotheses, vague, data, purposes)
    every = related + expected
    correspondence.number(every)
    for c in stated:
        if c.step == "less_invasive_alternative":
            c.relations = [r.id for r in expected if r.type == "O-E" and {t["claim"] for t in r.to} & set(c.basis)]
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
                relations.COMPONENT,
                concerns.COMPONENT,
                *_declaration_analysis(a),
                {"role": "frame", "id": a.frame.id, "version": a.frame.version, "sha256": a.frame.digest()},
                {"role": "vocabulary", "id": DATA, "version": data.version},
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
            "named": select.named(root),
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
                    "episodes": p.episodes,
                    "u0": p.u0,
                    "claims": p.claims,
                }
                for p in built.practices
            ],
            "declarations": [{"id": d.id, "claim": d.claim, "kind": d.kind} for d in built.declarations],
            "collection": _collection(built, statuses),
        },
        "features": _features(built, o_reports),
        "evidence": item.items,
        "relations": correspondence.to_json(every),
        "claims": [{k: v for k, v in c.items() if k != "uncertainty"} for c in claims],
        "concerns": concerns.to_json(stated),
        "coverage": concerns.coverage(a.frame, covered),
        "passed_on": relations.passed_on(built, a.observations, a.declaration, every, expected=bool(hypotheses)),
        "cases": _cases(a),
        "open": open_,
        "decided": settled,
        "gaps": _gaps(stated, claims, tested, a, tier["absent"], item),
    }
    validate("expectation_assessment", report)
    problems = expectation.independent(root, report) + judge.independent(root, report)
    if problems:
        raise expectation.IndependenceError("; ".join(problems))
    if write:
        (root / REPORT).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (root / MARKDOWN).write_text(markdown(report, built), encoding="utf-8")
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


def _expectation(a: inputs.Assessment, built, item: Evidence, registry) -> tuple[list[dict], list[dict]]:
    """The expectation stage's claims from the kept samples, with an evidence item per context part a supported claim
    rests on, and the samples' components."""
    claims, components = [], {}
    practices = {p.id: p for p in built.practices}
    for name, context, answer in expectation.kept(a, built, load_corpus(a.corpus), registry):
        record = json.loads((a.root / "expectation" / name / "record.json").read_text(encoding="utf-8"))
        _record_components(components, record, "expectation")
        parts = {p["id"]: p for p in context.parts}
        for c in expectation.read(answer, name, context, practices):
            cited = c.pop("parts", [])
            if c["status"] == "supported":
                c["supporting"] = [i for x in cited for i in _part_items(item, name, parts[x])]
            claims.append(c)
    components["procedure"] = {"role": "method", **expectation.PROCEDURE, "stage": "expectation"}
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
    components[f"model:{stage}:{model['name']}:{record['options']['seed']}"] = {
        "role": "model",
        "id": model["name"],
        **({"sha256": model["digest"].removeprefix("sha256:")} if _sha(model.get("digest")) else {}),
        "stage": stage,
        "seed": record["options"]["seed"],
    }


def _reasoning_tier(
    a: inputs.Assessment, built, hypotheses: list[dict], item: Evidence, registry, applicability, number
) -> dict:
    """The reasoning tier's combined Alternative claims, its concerns (ii) and (iii) and their coverage from its kept
    samples, the samples' components, and the questions expected but not asked."""
    corpus = load_corpus(a.corpus)
    norms = load_corpus(a.corpus / NORMS)
    factors = [f.id for f in a.frame.requirement("purpose_compatible").factors]
    by_id = {h["id"]: h for h in hypotheses}
    d_sha = a.declaration.sha256 if a.declaration else None
    contexts, components = {}, {}
    specific, compatible, members, judged, asked = [], [], [], set(), {q: 0 for q in judge.QUESTIONS}
    for name, q, answer in judge.kept(a, built, corpus, norms, hypotheses, factors, expectation.names(registry)):
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
            members += judge.minimisation(answer, name, q, by_id)

    def items(sample: str, ids: list[str]) -> list[str]:
        parts = contexts[sample]
        return [i for x in ids if x in parts for i in _part_items(item, sample, parts[x], "assessment", d_sha, by_id)]

    for c in members:
        cited = c.pop("parts", [])
        if c["status"] == "supported":
            c["supporting"] = items(c["channels"][0].removeprefix("reasoning:"), cited)
    said = judge.statements(a, built) if a.declaration else []
    stated, covered = concerns.not_specific(a.frame, said, specific, items, applicability)
    if a.declaration is not None and built.comparability.get("comparable") is not False:
        more, cover = concerns.purpose_limitation(
            a.frame,
            judge.limitation(built, said, hypotheses),
            compatible,
            items,
            applicability,
            {d.id: d.uncertainty for d in built.declarations},
        )
        stated += more
        covered += cover
    expected = {q.question for q in judge.questions(a, built, corpus, norms, hypotheses, expectation.names(registry))}
    return {
        "alternatives": combine.alternatives(members, number),
        "members": members,
        "judged": judged,
        "vague": {s.declarations[0]: s.declarations for s in said},
        "concerns": stated,
        "covered": covered,
        "components": list(components.values()),
        "absent": [q for q in judge.QUESTIONS if q in expected and not asked[q]],
    }


#: What a gap's reason asks for next
NEXT = {
    "applicability_unknown": "ask the provider, or an expert reading the documents and the processing",
    "own_knowledge": "documentation of the feature or the component in the corpus, and the stage asked again",
    "purpose_vague": "state the purpose's action, object and outcome",
    "needs_run": "an experiment that removes the component (skuld select)",
    "search_space_not_run": "run the alternative's condition",
    "intervention_not_verified": "repeat the runs with an intervention that verifies",
    "substitution_not_verifiable": "hook every identifier source with pass",
    "not_covered": "record those connections",
    "oracle_not_observable": "none from outside the recipient's servers",
    "requirements_not_reached": "extend the feature's path and the oracle",
    "precondition_failed": "correct the alternative against the baseline",
    "not_admitted": "repeat the comparison, or ask the reasoning tier again",
    "source_absent": "skuld judge",
}


def _gaps(
    stated: list, claims: list[dict], tested: list[dict], a: inputs.Assessment, absent: list[str], item: Evidence
) -> list[dict]:
    """The gaps someone could act on: the conditions of concerns whose applicability is unknown; the premises of
    concerns not established; what the experiments could not settle; questions not asked; D's report absent."""
    out: list[dict] = []
    by_id = {c["id"]: c for c in claims}
    n: dict[str, int] = {}

    def gap(subject: str, reason: str, proposition: str, required: str, observability: str = "E2", **fields) -> None:
        n[subject] = n.get(subject, 0) + 1
        out.append(
            {
                "id": f"gap:{subject}:{n[subject]}",
                **fields,
                "proposition": proposition,
                "required": required,
                "reason": reason,
                "observability": observability,
                "next": NEXT.get(reason, ""),
            }
        )

    def of_claim(c: dict, reason: str | None = None, required: str | None = None) -> None:
        reason = reason or c["sufficiency"].get("reason") or "not_admitted"
        what = c.get("relationship") or c.get("alternative") or c["purpose"].get("node")
        gap(
            c["subject"],
            reason,
            f"{c['type']} of {c['subject']}" + (f" ({c['component']})" if c.get("component") else "") + f": {what}",
            required or "; ".join(c["sufficiency"].get("missing", [])) or c.get("reason") or "a supporting item",
            "E3" if reason == "oracle_not_observable" else "E2",
            of=c["id"],
        )

    for c in stated:
        if c.condition:
            gap(
                c.subject,
                "applicability_unknown",
                f"{c.requirement} applies",
                f"whether {', '.join(c.condition)} holds",
                "E4",
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
                of_claim(p)
        if not premises:
            gap(c.subject, "not_admitted", f"{c.step.replace('_', ' ')}: {c.requirement}", c.reason or "", of=c.id)
    for x in tested:
        if x["status"] not in combine.DECISIVE and x["id"] not in seen:
            seen.add(x["id"])
            of_claim(x)
    measured = experiments.case_report(a.cases, a.root) or {"cases": [], "comparisons": []}
    for k in measured["comparisons"]:
        parts = k.get("unverifiable") or []
        if parts and any(item.ids.get(k["id"]) in x["supporting"] + x["challenging"] for x in tested):
            substitution = any(u.startswith("substitution") for u in parts)
            gap(
                k["case"],
                "substitution_not_verifiable" if substitution else "not_covered",
                f"whether the runs of comparison {k['id']} ran under {k['alternative']} alone",
                "; ".join(parts),
            )
    if a.cases is not None:
        for case in a.cases.cases:
            for purpose in case.purposes:
                oracle = a.cases.oracles.get(purpose.oracle) if purpose.oracle else None
                unreached = [r["id"] for r in purpose.requirements if oracle and r["id"] not in oracle.reach]
                if unreached and any(x["case"] == case.id and x["purpose"]["id"] == purpose.id for x in tested):
                    gap(
                        case.id,
                        "requirements_not_reached",
                        f"whether {purpose.id} of case {case.id} achieves {', '.join(unreached)}",
                        f"an oracle that reaches {', '.join(unreached)}, on a path that exercises them",
                    )
        for c in measured["cases"]:
            for alt in c["scope"]["search_space"]:
                if alt.get("problems"):
                    gap(
                        c["id"],
                        "precondition_failed",
                        f"whether {alt['id']} preserves the purposes of case {c['id']}",
                        "an alternative less invasive than the baseline in its component's dimension: "
                        + "; ".join(alt["problems"]),
                    )
    for question in absent:
        gap(
            judge.REQUIREMENT[question],
            "source_absent",
            f"{judge.REQUIREMENT[question]}: the reasoning tier's judgement",
            f"kept samples of the {question} question",
            of=judge.REQUIREMENT[question],
        )
    if a.declaration is None:
        requirements = [r.id for r in a.frame.requirements.values() if r.subject in ("collection", "declaration")]
        out.append(
            {
                "id": "gap:collection:1",
                "of": "collection",
                "proposition": f"the collection gives the information of {len(requirements)} requirements, declared "
                "purposes are specific",
                "required": "D's report on the version's declarations",
                "reason": "source_absent",
                "observability": "E1",
                "next": "collect and analyse the app's declarations (Sága, Urda)",
            }
        )
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
    """The collection's documents and transparency statuses; what decided each condition is in subjects.json. Every
    analysed document is accessible; whether it was acquired complete is D's."""
    if built.collection is None:
        return None
    documents = [
        {"channel": d["channel"], "document": d["document"], "accessible": True, "complete": d.get("complete", True)}
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


def _what(report: dict, built):
    practices = {p.id: p for p in built.practices}

    def what(subject: str) -> str:
        p = practices.get(subject)
        return f"{p.claim_type} {p.data} → {p.recipient or '–'}" if p else subject

    return what


def markdown(report: dict, built) -> str:
    """The report for a reader: the relations, the concerns, the experiments and the open conditions."""
    app = report["application"]
    what = _what(report, built)
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
        lines += ["", "## Open conditions, for the Investigator", ""]
        lines += [f"- {o['text']} (qualifies {', '.join(o['qualifies'])})" for o in report["open"]]
    return "\n".join(lines) + "\n"
