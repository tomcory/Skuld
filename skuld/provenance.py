"""
The provenance check of a report (EV-E-PROV): every digest verifies and every pointer resolves. `check` checks a case
report (report.json), `check_assessment` the assessment's (assessment.json), and that it rebuilds (EV-E-REPLAY).

For a case report, digests: the named inputs (their last recorded digest is that of the file), each run's record files
and its observation report. Pointers: a record of a run (a file of its folder), of its capture (a file of its export),
of its observation report (an evidence item or claim, or the report's claims and statuses), and a named input by
digest.
"""

import hashlib
import json
from pathlib import Path

from ratatoskr import claims as claim_views

from skuld.inputs import ASSESSMENT, Workspace, digest, frozen


def check(workspace: Workspace, report: dict) -> list[str]:
    """The problems found; none if the report's provenance is complete."""
    root = workspace.root
    problems = []
    runs = {e.id: e.directory for e in workspace.runs}
    recorded = frozen(root)["inputs"]
    for name, entry in recorded.items():
        current = entry["changes"][-1]["sha256"] if entry["changes"] else entry["sha256"]
        if not (root / name).is_file() or digest(root / name) != current:
            problems.append(f"input {name}: its digest does not verify")

    observations = {}
    for run in report["runs"]:
        folder = runs.get(run["id"])
        for f in run.get("files") or ():
            if folder is None or not (folder / f["path"]).is_file() or digest(folder / f["path"]) != f["sha256"]:
                problems.append(f"run {run['id']}: {f['path']} does not verify")
        o = run.get("observation_report") or {}
        path = root / o.get("path", "")
        if not path.is_file() or digest(path) != o.get("sha256"):
            problems.append(f"run {run['id']}: its observation report does not verify")
        else:
            observations[run["id"]] = json.loads(path.read_text(encoding="utf-8"))
    for item in report["evidence"]:
        for pointer in item.get("provenance") or ():
            problem = _resolve(pointer, runs, observations, recorded)
            if problem:
                problems.append(f"{item['id']}: {problem}")
        if not item.get("provenance") and not item.get("premises"):
            problems.append(f"{item['id']}: neither provenance nor premises")
    ids = {i["id"] for i in report["evidence"]}
    for item in report["evidence"]:
        problems += [f"{item['id']}: premise {p} is no item" for p in item.get("premises") or () if p not in ids]
    for k in report["comparisons"]:
        if k["evidence"] not in ids:
            problems.append(f"comparison {k['id']}: its item {k['evidence']} is missing")
    return problems


def _resolve(pointer: dict, runs, observations, recorded) -> str | None:
    if "input" in pointer:
        entry = recorded.get(pointer["input"])
        digests = [entry["sha256"], *(c["sha256"] for c in entry["changes"])] if entry else []
        return None if pointer.get("sha256") in digests else f"input {pointer['input']} is not fixed with that digest"
    kind, _, owner = pointer.get("source", "").partition(":")
    record = pointer.get("record", "")
    if kind == "run":
        folder = runs.get(owner)
        return None if folder and (folder / record).is_file() else f"run record {owner}/{record} is missing"
    if kind == "capture":
        folder = runs.get(owner)
        if folder is None:
            return f"run {owner} is unknown"
        meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        export = folder / (meta.get("capture") or {}).get("export", "")
        return None if (export / record).is_file() else f"capture record {owner}/{record} is missing"
    if kind == "observation":
        report = observations.get(owner)
        if report is None:
            return f"the observation report of {owner} is not read"
        known = (
            {e["id"] for e in report["evidence"]}
            | {c["id"] for c in report["claims"]}
            | {"claims", "statuses", "scopes"}
        )
        return None if record in known else f"{record} is not in the observation report of {owner}"
    return f"a pointer of unknown source {pointer.get('source')!r}"


# -- the assessment's report ------------------------------------------------------------------------------------------


def _samples(root: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """Every kept sample's context parts by its name, and the problems of their digests."""
    contexts, problems = {}, []
    for record in sorted([*root.glob("expectation/**/record.json"), *root.glob("assessment/**/record.json")]):
        folder = record.parent
        rel = folder.relative_to(root).as_posix()
        meta = json.loads(record.read_text(encoding="utf-8"))
        if not (folder / "context.json").is_file():
            problems.append(f"sample {rel}: its context is missing")
            continue
        parts = json.loads((folder / "context.json").read_text(encoding="utf-8"))["parts"]
        if hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != (
            meta.get("context") or {}
        ).get("sha256"):
            problems.append(f"sample {rel}: its context does not verify")
        answer = folder / "answer.json"
        named = (meta.get("answer") or {}).get("sha256")
        if not answer.is_file():
            if named:
                problems.append(f"sample {rel}: its answer is missing")
        # the bytes as written: reading text would turn a "\r" in the answer into "\n"
        elif named != hashlib.sha256(answer.read_bytes()).hexdigest():
            problems.append(f"sample {rel}: its answer does not verify")
        contexts[rel] = parts
        contexts[rel.removeprefix("expectation/")] = parts
    return contexts, problems


def _o_ref(cid) -> dict | None:
    """A traffic part's citation id: the O claim it shows, written as JSON ({"claim", "dimension": "O", "report"});
    None for any other id."""
    if not isinstance(cid, str) or not cid.startswith("{"):
        return None
    try:
        ref = json.loads(cid)
    except ValueError:
        return None
    return ref if isinstance(ref, dict) and ref.get("dimension") == "O" and {"claim", "report"} <= ref.keys() else None


def component_changes(report: dict, rebuilt: dict) -> list[str]:
    """The method components whose version differs between a report and its rebuild (`skuld.combine 1, now 2`), and
    Skuld's and Ratatoskr's own versions (`skuld 0.5.0, now 0.6.0`)."""

    def versions(r: dict) -> dict[str, str]:
        methods = {
            c["id"]: str(c.get("version"))
            for c in r["report"].get("components", [])
            if c.get("role") == "method" and c.get("id")
        }
        return methods | {k: str(r["report"][k]) for k in ("skuld", "ratatoskr") if r["report"].get(k)}

    then, now = versions(report), versions(rebuilt)
    # a report that names no notice definition was made with 1.1.0, and is rebuilt with it: no change
    from skuld.expectation import NOTICES_UNNAMED, notice_rules

    then.setdefault(notice_rules.COMPONENT["id"], NOTICES_UNNAMED)
    changed = [f"{k} {then[k]}, now {now[k]}" for k in sorted(then) if k in now and then[k] != now[k]]
    # a method the report names no version of came later (skuld.judge.reading, after the study's first runs)
    return changed + [f"{k} (none), now {now[k]}" for k in sorted(now) if k not in then]


def check_assessment(
    a,
    report: dict,
    rebuilt: dict | None = None,
    members: list[dict] | None = None,
    notes: list[str] | None = None,
) -> list[str]:
    """
    The problems of an assessment report (EV-E-PROV, EV-E-REPLAY); none if its provenance is complete:
    every report and named input it names verifies by digest, every kept sample's context and answer verify, every
    evidence item resolves (O's claim in O's report, D's pointer into D's report, a passage of the corpus, a screen of
    a run read, a comparison of the case report, a part of the context of the sample it is of), every id a claim,
    concern, relation, coverage entry, open condition or gap names exists, a combined claim's claims (`of`) are
    claims of the samples, of the case report's experiments (`members`, from the rebuild) or of the report, every O–E
    outcome is the one its claims give, the independence gates hold, and, given the rebuilt report, it is identical.
    A report assessed under earlier versions of Skuld's methods (the study's runs under combination rule A,
    skuld.combine 1) cannot be rebuilt identically by the current ones: that is no problem but a note, appended to
    `notes`, naming the components that changed.
    """
    from skuld import corpus, expectation, inputs, judge, relations, select
    from skuld.assess import identity

    root = a.root
    problems = []
    o_reports = {}
    for r in a.observations:
        if digest(r.path) != r.sha256:
            problems.append(f"O report {r.path.name}: does not verify")
        o_reports[r.sha256] = json.loads(r.path.read_text(encoding="utf-8"))
    d_report = None
    if a.declaration is not None:
        if digest(a.declaration.path) != a.declaration.sha256:
            problems.append("D's report does not verify")
        d_report = json.loads(a.declaration.path.read_text(encoding="utf-8"))
    o_ids = {sha: {c["id"] for c in o["claims"]} for sha, o in o_reports.items()}
    d_claims = claim_views.by_id(d_report) if d_report is not None else {}
    case_report = None
    for ref in report.get("cases", []):
        path = root / ref["path"]
        if not path.is_file() or digest(path) != ref["sha256"]:
            problems.append(f"case report {path.name}: does not verify")
        else:
            case_report = json.loads(path.read_text(encoding="utf-8"))
    if corpus.load(a.corpus).sha256 != a.corpus_sha256:
        problems.append("the corpus does not verify")
    named = {n["id"]: n["sha256"] for n in select.named(root) + inputs.version_compatibility(a)}
    for n in report["inputs"]["named"]:
        if named.get(n["id"]) != n["sha256"]:
            problems.append(f"named input {n['id']}: does not verify")

    passages = {
        key
        for found in (corpus.load(a.corpus), corpus.load(a.corpus / corpus.NORMS))
        for p in found.passages
        for key in (p.id, p.path.relative_to(a.corpus).as_posix())
    }
    runs = {r.run for r in a.observations if r.run} | ({a.exploration.name} if a.exploration else set())
    comparisons = {k["id"] for k in (case_report or {}).get("comparisons", [])}
    contexts, sample_problems = _samples(root)
    problems += sample_problems

    def claim_ref(ref: dict) -> str | None:
        if ref["dimension"] == "E":
            return None if ref["claim"] in claims | concerns else f"E claim {ref['claim']} is unknown"
        if ref["dimension"] == "O":
            o = o_reports.get(ref["report"])
            if o is None:
                return "an O report the assessment does not read"
            return None if ref["claim"] in o_ids[ref["report"]] else f"O claim {ref['claim']} is unknown"
        if d_report is None or a.declaration.sha256 != ref["report"]:
            return "a D report the assessment does not read"
        return None if ref["claim"] in d_claims else f"D claim {ref['claim']} is unknown"

    items = {e["id"]: e for e in report["evidence"]}
    claims = {c["id"] for c in report["claims"]}
    concerns = {c["id"] for c in report["concerns"]}
    relation_ids = {r["id"] for r in report["relations"]}
    for e in report["evidence"]:
        problem = None
        if e["kind"] == "claim":
            problem = claim_ref(e["claim"])
        elif e["kind"] == "run":
            if case_report is None:
                problem = "no case report is read"
            else:
                problem = next(
                    (f"{p} is no comparison of the case report" for p in e["premises"] if p not in comparisons), None
                )
        elif e.get("citation"):
            cid = e["citation"]["id"]
            o_ref = _o_ref(cid)
            if o_ref is not None:
                problem = claim_ref(o_ref)
            elif cid not in passages and cid not in runs and cid != ASSESSMENT:
                problem = f"{cid} is neither a passage of the corpus, a run read nor the assessment's inputs"
        elif e.get("premises") is not None:
            problem = next((f"premise {p} is no item" for p in e["premises"] if p not in items), None)
        else:
            problem = "neither a pointer nor premises"
        sample = (e.get("channel") or "").removeprefix("reasoning:")
        if problem is None and e.get("channel", "").startswith("reasoning:"):
            parts = contexts.get(sample)
            if parts is None:
                problem = f"sample {sample} is not kept"
            elif "text" in e and e["text"] not in {p["text"] for p in parts}:
                problem = f"its text is no part of the context of {sample}"
        if problem:
            problems.append(f"{e['id']}: {problem}")

    combined = claims | {m["id"] for m in members or ()}
    for c in report["claims"] + report["concerns"]:
        problems += [
            f"{c['id']}: {i} is no item" for i in c.get("supporting", []) + c.get("challenging", []) if i not in items
        ]
        problems += [f"{c['id']}: basis {b} is no claim" for b in c.get("basis", []) if b not in claims]
    if members is not None:
        uncombined = [
            f"{c['id']}: {m} is no claim it could combine"
            for c in report["claims"]
            for m in c["of"]
            if m not in combined
        ]
        # the samples are read again by the current reading: one read otherwise cites what it no longer gives
        reading = next(
            (
                c
                for c in (rebuilt or {}).get("report", {}).get("components", [])
                if c.get("id") == "skuld.judge.reading"
            ),
            None,
        )
        then = next((c for c in report["report"].get("components", []) if c.get("id") == "skuld.judge.reading"), None)
        if uncombined and reading and notes is not None and (then or {}).get("version") != reading.get("version"):
            notes.append(
                f"{len(uncombined)} combined claims cite sample claims the current reading (skuld.judge.reading "
                f"{reading['version']}; the report's: {(then or {}).get('version', 'none')}) no longer gives"
            )
        else:
            problems += uncombined
    for c in report["concerns"]:
        if c.get("purpose") and c["purpose"] not in claims:
            problems.append(f"{c['id']}: purpose {c['purpose']} is no claim")
        problems += [f"{c['id']}: relation {i} is unknown" for i in c.get("relations", []) if i not in relation_ids]
    by_id = {c["id"]: c for c in report["claims"]}
    for r in report["relations"]:
        for ref in [r["of"], *r.get("to", [])]:
            if problem := claim_ref(ref):
                problems.append(f"{r['id']}: {problem}")
        if r["type"] == "O-E":
            read = [
                by_id[t["claim"]] for t in r["to"] if t["claim"] in by_id and by_id[t["claim"]]["type"] != "purpose"
            ]
            derived = relations.outcome(r.get("aspect") or "data", read)[0]
            if read and derived != r["outcome"]:
                problems.append(f"{r['id']}: its claims give {derived}, not {r['outcome']}")
    findings = {f["id"] for f in (d_report or {}).get("findings", [])}
    for x in report["passed_on"]:
        if "finding" in x:
            if d_report is None or x["finding"]["report"] != a.declaration.sha256:
                problems.append("passed on: a finding of a D report the assessment does not read")
            elif x["finding"]["finding"] not in findings:
                problems.append(f"passed on: D finding {x['finding']['finding']} is unknown")
            continue
        if problem := claim_ref(x["claim"]):
            problems.append(f"passed on: {problem}")
        problems += [f"passed on: relation {i} is unknown" for i in x.get("relations", []) if i not in relation_ids]
    requirements = set(a.frame.requirements)
    problems += [
        f"coverage: {e['requirement']} is no requirement"
        for e in report["coverage"]
        if e["requirement"] not in requirements
    ]
    known = claims | concerns | relation_ids
    d_open = {o["id"] for o in (d_report or {}).get("open", [])}
    for o in report["open"]:
        # a condition passed on from D qualifies D's claims, by their ids
        names = known | set(d_claims) if o.get("from") == "D" else known
        problems += [f"{o['id']}: qualifies {q}, which is unknown" for q in o["qualifies"] if q not in names]
        if "of" in o and o["of"]["open"] not in d_open:
            problems.append(f"{o['id']}: continues {o['of']['open']}, which D's report does not state")
    # a condition E decided continues D's, and what decides it resolves; none is both decided and open
    passed = {o["of"]["open"] for o in report["open"] if "of" in o}
    for x in report.get("decided", []):
        if x["of"]["open"] not in d_open:
            problems.append(f"{x['id']}: continues {x['of']['open']}, which D's report does not state")
        if x["of"]["open"] in passed:
            problems.append(f"{x['id']}: is decided and passed on as open")
        problems += [f"{x['id']}: {p}" for ref in x["by"].get("claims", []) if (p := claim_ref(ref))]
        problems += [
            f"{x['id']}: relation {i} is unknown" for i in x["by"].get("relations", []) if i not in relation_ids
        ]
    for g in report["gaps"]:
        # a gap may concern a result, the collection, a requirement, or a practice E established no purpose for
        practices = {x["id"] for x in report["subjects"]["practices"]}
        if g.get("of") and g["of"] not in known | {"collection"} | requirements | practices:
            problems.append(f"{g['id']}: of {g['of']}, which is unknown")
    problems += expectation.independent(root, report) + judge.independent(root, report)
    if rebuilt is not None and not any(
        c.get("id") == expectation.notice_rules.COMPONENT["id"] for c in report["report"].get("components", [])
    ):
        # a report that names no notice definition was made with 1.1.0, which the rebuild names: no difference
        rebuilt = json.loads(json.dumps(rebuilt))
        rebuilt["report"]["components"] = [
            c for c in rebuilt["report"]["components"] if c.get("id") != expectation.notice_rules.COMPONENT["id"]
        ]
    if rebuilt is not None and identity(rebuilt) != identity(report):
        changed = component_changes(report, rebuilt)
        if changed and notes is not None:
            notes.append(f"assessed under earlier components ({'; '.join(changed)}): not rebuilt with the current ones")
        else:
            problems.append(
                "the report rebuilt from the same inputs and kept samples differs"
                + (f" (and the components changed: {'; '.join(changed)})" if changed else "")
            )
    return problems
