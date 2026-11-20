"""
The review of the expectation stage's predictions (author, 12 Nov 2026): beside the review of aggregated concerns
(skuld.review), two reviewers check a sample of what stage 1 (skuld.expectation) predicted for a practice, its
purposes and their dependencies, non-blind and blind to the model run, as the review of concerns is.

A unit is one practice of one run: its data, recipient and episodes; what the stage read with it (the screens of its
episodes and the corpus passages, each once; never the provider's documents, which the stage does not see, gate 1);
and every purpose claim of the stage for it, combined over seeds and batches as the assessment uses them, each with
its dependency claims. A dependency shows its reasoning steps, as the samples' answers gave them, with the texts they
cite. The reviewer judges the predictions against that context: whether they are plausible given what E saw, not
whether the provider says the same (author: "judged against E's context").

Per purpose:

    plausible    a plausible purpose for this flow, given the context: yes, partly, no, unsure
    node         the DPV purpose node: exact, too_broad, too_narrow, wrong, unsure (with a better node, if any)
    beneficiary  user, provider or other: right, wrong, unsure
    role         functional or ancillary: right, wrong, unsure
    cites        a supported purpose only: the cited screens or passages show its outcome: yes, partly, no

Per dependency the stage stated (supported, not established or conflicted; not one not assessable, whose purpose was
too vague to judge one):

    relationship essential or quality_dependent is plausible: yes, partly, no, unsure
    steps        the steps follow from what they cite: yes, partly, no

Per practice: the purposes E missed (a note each; a functional one marked so), a note, and `done`.

Units are drawn per run, stratified by run, role (functional if any of the practice's purposes is) and status
(supported if any is), up to `per_stratum` per stratum, independently of the review of concerns, practices without a
concern included, and interleaved (skuld.review.interleave: every prefix of the review order covers the strata in
proportion to their drawn sizes; until 20 Nov 2026 they were shuffled); the sample never names the run, which only
key.json holds. With `per_app` (`--per-app`), a draw takes at most about that many units of one application per run,
shared out over the run's strata in proportion to their sizes, without changing any stratum's size (`capped`; in the
study, two applications had 18 and 15 of a run's 66 units). `expect-score` reports which strata a partial return
reached. The review of the stage
comes before the review of concerns, whose units show the later reasoning and D's declarations.

A unit also shows what the stage was told of the practice: its sentence and, where the stage was shown the traffic
(expectation.traffic, the re-run of 12 Nov 2026), the practice's messages as O annotated them. Practices whose datum O
did not identify (`data`: encrypted, unreadable, a connection only) are not drawn: what was sent was not observed
(author, 12 Nov 2026). A sample may be drawn in parts, one per run as its results come in, each with its own id prefix
and a name that does not name the run (`--prefix`).

The sample folder holds manifest.json, sample.json, key.json, reviews.json (the review tool writes it),
scores.json (`skuld review expect-score`) and agreement.json (`skuld review expect-agree`), as skuld.review's does.
"""

import json
import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import skuld
from skuld import inputs
from skuld.assess import REPORT
from skuld.calibrate import decisions, file_sha256, kappa, model_identity, read_json, stage_one, wilson, write_json
from skuld.expectation import listed
from skuld.review import ReviewError, _given, _uncited, coverage, interleave, source

#: 2 since the drawn units are interleaved by stratum instead of shuffled (every prefix of the sample covers the strata
#: in proportion), and a draw may cap the units of one application (`per_app`; the manifest records the applications'
#: units per run) (20 Nov 2026)
VERSION = "2"
#: What a unit's stratum is made of
STRATUM = ("run", "role", "status")
KIND = "expectation-review"
MANIFEST, SAMPLE, KEY, REVIEWS, SCORES, AGREEMENT = (
    "manifest.json",
    "sample.json",
    "key.json",
    "reviews.json",
    "scores.json",
    "agreement.json",
)
#: The questions per purpose and per dependency, with their values; the first value is the one that agrees with E
PURPOSE_QUESTIONS = {
    "plausible": ("yes", "partly", "no", "unsure"),
    "node": ("exact", "too_broad", "too_narrow", "wrong", "unsure"),
    "beneficiary": ("right", "wrong", "unsure"),
    "role": ("right", "wrong", "unsure"),
    "cites": ("yes", "partly", "no"),
}
DEPENDENCY_QUESTIONS = {
    "relationship": ("yes", "partly", "no", "unsure"),
    "steps": ("yes", "partly", "no"),
}
#: The dependency claims a reviewer judges: those that state a relationship
STATED = ("supported", "not_established", "conflicted")
ASK = (
    "Given what the expectation stage saw (the practice, its traffic, screens and passages; not the provider's "
    "documents), are its predicted purposes and dependencies right?"
)


def settings() -> dict:
    """config.json's `expectation_review`: practices drawn per stratum, the cap per application (none), and the
    seed."""
    from skuld import config

    return {"per_stratum": 8, "per_app": None, "seed": 1, **(config.load().get("expectation_review") or {})}


def asked(purpose: dict) -> list[str]:
    """The questions a purpose of a unit asks: `cites` only for a supported one."""
    return [q for q in PURPOSE_QUESTIONS if q != "cites" or purpose["status"] == "supported"]


# -- units ------------------------------------------------------------------------------------------------------------


def _sample_part(root: Path, ref: str) -> tuple[dict, dict] | None:
    """The answer and context of the sample a claim's `of` entry names ('e1/s3/a2:d0' -> expectation/e1/s3/a2); a
    keyed answer as the list it stands for, which the claims' numbers count in (`expectation.listed`)."""
    folder = ref.rpartition(":")[0]
    path = root / "expectation" / folder
    if not (path / "answer.json").is_file():
        return None
    answer = listed(json.loads((path / "answer.json").read_text(encoding="utf-8")))
    context = (
        json.loads((path / "context.json").read_text(encoding="utf-8")) if (path / "context.json").is_file() else {}
    )
    return answer, {p["id"]: p for p in context.get("parts", [])}


def _steps(root: Path, claim: dict) -> list[dict]:
    """A dependency claim's reasoning steps as its samples gave them, each once, with the texts they cite."""
    out, seen = [], set()
    for ref in claim.get("of", []):
        index = ref.rpartition(":")[2]
        if not index.startswith("d") or not index[1:].isdigit():
            continue
        found = _sample_part(root, ref)
        if not found:
            continue
        answer, parts = found
        dependencies = answer.get("dependencies") or []
        if int(index[1:]) >= len(dependencies):
            continue
        for step in dependencies[int(index[1:])].get("steps") or []:
            text = _uncited(step.get("text"))
            if not text or text in seen:
                continue
            seen.add(text)
            cites = [
                {"id": c, "kind": parts[c]["kind"], "text": parts[c]["text"]}
                for c in step.get("cites") or []
                if c in parts
            ]
            out.append({"text": text, "cites": cites})
    return out


def _evidence(claim: dict, evidence: dict) -> list[dict]:
    out, seen = [], set()
    for i in claim.get("supporting", []):
        e = evidence.get(i)
        if not e or not e.get("text") or e["text"] in seen:
            continue
        seen.add(e["text"])
        out.append({**{k: e[k] for k in ("id", "kind", "text", "method", "citation") if e.get(k)}, "source": source(e)})
    return out


def _purpose(claim: dict) -> dict:
    p = claim.get("purpose") or {}
    shown = {k: _uncited(p.get(k)) for k in ("action", "object", "context", "outcome")}
    return {
        **{k: v for k, v in shown.items() if v},
        "node": p.get("node"),
        "beneficiary": p.get("beneficiary"),
        "role": p.get("role"),
        "specificity": p.get("specificity"),
    }


def _told(root: Path) -> dict[str, dict]:
    """Per practice, what stage 1 was told of it beside the screens and passages: the practice's sentence and, where the
    stage was shown the traffic (expectation.traffic), its messages as O annotated them, each once."""
    out: dict[str, dict] = {}
    for path in sorted(root.glob("expectation/*/s*/context.json")):
        for part in json.loads(path.read_text(encoding="utf-8"))["parts"]:
            if part["kind"] == "practice":
                out.setdefault(part["id"], {"sentence": part["text"], "traffic": []})
            elif part["kind"] == "traffic":
                pid, _, text = part["text"].partition(": ")
                entry = out.setdefault(pid, {"sentence": None, "traffic": []})
                if text not in entry["traffic"]:
                    entry["traffic"].append(text)
    return out


def units(root: Path, known_data_only: bool = True) -> list[dict]:
    """The units of one workspace: one per practice the expectation stage gave a purpose, as the reviewer sees it."""
    report = read_json(root / REPORT)
    evidence = {e["id"]: e for e in report.get("evidence", [])}
    stage = [c for c in report.get("claims", []) if c.get("stage") == "expectation"]
    read = stage_one(root)
    told = _told(root)
    out = []
    for p in report["subjects"].get("practices", []):
        if known_data_only and p.get("data") == "data":
            continue  # the datum was not identified (encrypted, unreadable, a connection only): not observed data
        purposes = [c for c in stage if c["subject"] == p["id"] and c["type"] == "purpose"]
        if not purposes:
            continue
        shown = []
        for n, c in enumerate(purposes, 1):
            dependencies = []
            for m, d in enumerate(
                (
                    d
                    for d in stage
                    if d["subject"] == p["id"] and d["type"] == "dependency" and c["id"] in d.get("basis", [])
                ),
                1,
            ):
                dependencies.append(
                    {
                        "key": f"p{n}d{m}",
                        "claim": d["id"],
                        "component": str(d.get("component") or "").rsplit(".", 1)[-1] or None,
                        "relationship": d.get("relationship"),
                        "status": d["status"],
                        "reason": d.get("reason"),
                        "asked": d["status"] in STATED,
                        "steps": _steps(root, d),
                        "evidence": _evidence(d, evidence),
                    }
                )
            shown.append(
                {
                    "key": f"p{n}",
                    "claim": c["id"],
                    **_purpose(c),
                    "status": c["status"],
                    "reason": c.get("reason"),
                    "samples": len(c.get("of", [])),
                    "evidence": _evidence(c, evidence),
                    "dependencies": dependencies,
                }
            )
        party = p.get("party") or {}
        out.append(
            {
                "practice": {
                    "id": p["id"],
                    "type": p.get("claim_type"),
                    "data": p.get("data"),
                    "recipient": p.get("recipient"),
                    "relation": party.get("relation"),
                    "episodes": p.get("episodes", []),
                },
                "told": told.get(p["id"], {}).get("sentence"),
                "context": {
                    **read.get(p["id"], {"screens": [], "passages": []}),
                    "traffic": told.get(p["id"], {}).get("traffic", []),
                },
                "purposes": shown,
                "_role": "functional" if any(x["role"] == "functional" for x in shown) else "ancillary",
                "_status": "supported" if any(x["status"] == "supported" for x in shown) else "not_supported",
            }
        )
    return out


# -- drawing ----------------------------------------------------------------------------------------------------------


def _skey(s: dict) -> tuple:
    return tuple(s[k] for k in STRATUM)


def capped(strata: dict, sizes: dict, per_app: int, rng: random.Random) -> dict:
    """
    Each stratum's units, `sizes[k]` of them, with at most about `per_app` units of one application per run: the cap
    is shared out over a run's strata in proportion to their sizes, each stratum's share rounded and at least one.
    Within a stratum, its units are taken in random order, passing over a unit whose application has its share of
    the stratum already; if that leaves the stratum short of its size, the units passed over fill it, in the same
    random order (the cap gives way where a stratum has too few other applications). Each stratum keeps its size, so
    the stratification and its weights are unchanged; within a stratum, a unit of an application with many units in
    it is less likely to be drawn than one of an application with few, so a stratum's rate leans towards the average
    over its applications rather than over its units.
    """
    total = defaultdict(int)
    for k, n in sizes.items():
        total[k[0]] += n
    out = {}
    for k in sorted(strata):
        share = max(1, round(per_app * sizes[k] / total[k[0]])) if total[k[0]] else 1
        order = rng.sample(strata[k], len(strata[k]))
        taken, passed, per = [], [], defaultdict(int)
        for u in order:
            if len(taken) == sizes[k]:
                break
            if per[u["application"]] < share:
                taken.append(u)
                per[u["application"]] += 1
            else:
                passed.append(u)
        out[k] = taken + passed[: sizes[k] - len(taken)]
    return out


def draw(
    folder: str | Path,
    workspaces: list[str | Path],
    per_stratum: int | None = None,
    seed: int | None = None,
    prefix: str = "x",
    per_app: int | None = None,
) -> dict:
    """Draws the review's units from the workspaces' assessments and fixes them in `folder`, which must not exist:
    `per_stratum` per stratum, and with `per_app`, at most about that many of one application per run (`capped`)."""
    folder = Path(folder)
    if folder.exists():
        raise ReviewError(f"{folder} exists: a drawn sample is fixed, draw a new one into another folder")
    s = settings()
    per_stratum = s["per_stratum"] if per_stratum is None else per_stratum
    per_app = s["per_app"] if per_app is None else per_app
    if per_app is not None and per_app < 1:
        raise ReviewError("per_app must be at least 1")
    seed = s["seed"] if seed is None else seed

    every, workspaces_out = [], []
    for n, root in enumerate(map(Path, workspaces), 1):
        if not (root / REPORT).is_file():
            raise ReviewError(f"{root}: no {REPORT}; run `skuld assess` first")
        report = read_json(root / REPORT)
        app = f"{report['application']['package']}@{report['application']['version']}"
        run = root.resolve().parent.name
        models = sorted({model_identity(c) for c in report["report"].get("components", []) if c["role"] == "model"})
        workspaces_out.append(
            {
                "key": f"w{n}",
                "run": run,
                "models": models,
                "application": app,
                "workspace": str(root.resolve()),
                "assessment": inputs.digest(root / REPORT),
            }
        )
        for u in units(root):
            u["_run"], u["_workspace"], u["application"] = run, f"w{n}", app
            every.append(u)
    runs = sorted({w["run"] for w in workspaces_out})
    for run in runs:
        named = {tuple(w["models"]) for w in workspaces_out if w["run"] == run and w["models"]}
        if len(named) > 1:
            raise ReviewError(
                f"run {run}: its workspaces name different models ({'; '.join(map(', '.join, sorted(named)))})"
            )
    for app in {w["application"] for w in workspaces_out}:
        have = sorted(w["run"] for w in workspaces_out if w["application"] == app)
        if len(set(have)) != len(have):
            raise ReviewError(f"{app}: two workspaces of the same run ({', '.join(have)})")

    def stratum(u):
        return {"run": u["_run"], "role": u["_role"], "status": u["_status"]}

    rng = random.Random(seed)
    strata = defaultdict(list)
    for u in every:
        strata[_skey(stratum(u))].append(u)
    if per_app:
        chosen = capped(strata, {k: min(len(v), per_stratum) for k, v in strata.items()}, per_app, rng)
    else:
        chosen = {
            k: strata[k] if len(strata[k]) <= per_stratum else rng.sample(strata[k], per_stratum)
            for k in sorted(strata)
        }
    # every prefix covers the strata in proportion, so that a partial return is a smaller stratified sample
    drawn = interleave([chosen[k] for k in sorted(chosen)], rng)

    folder.mkdir(parents=True)
    items, key = [], {}
    for n, u in enumerate(drawn, 1):
        iid = f"{prefix}{n:03d}"
        key[iid] = {
            "run": u["_run"],
            "workspace": u["_workspace"],
            "practice": u["practice"]["id"],
            "claims": {p["key"]: p["claim"] for p in u["purposes"]}
            | {d["key"]: d["claim"] for p in u["purposes"] for d in p["dependencies"]},
            "stratum": stratum(u),
        }
        item = {k: v for k, v in u.items() if not k.startswith("_")}
        for p in item["purposes"]:
            p.pop("claim")
            for d in p["dependencies"]:
                d.pop("claim")
        items.append({"id": iid, "ask": ASK, **item})
    write_json(
        folder / SAMPLE,
        {"kind": KIND, "items": items, "questions": _questions(), "vocabularies": vocabularies()},
    )
    write_json(folder / KEY, key)
    manifest = {
        "id": folder.name,
        "kind": KIND,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": skuld.__version__,
        "method": {"id": "skuld.review_expectation", "version": VERSION},
        "seed": seed,
        "per_stratum": per_stratum,
        **({"per_app": per_app} if per_app else {}),
        "runs": runs,
        "run_models": {
            run: next((w["models"] for w in workspaces_out if w["run"] == run and w["models"]), []) for run in runs
        },
        "workspaces": workspaces_out,
        "strata": [
            {
                **stratum(strata[k][0]),
                "population": len(strata[k]),
                "drawn": sum(1 for u in drawn if _skey(stratum(u)) == k),
            }
            for k in sorted(strata)
        ],
        # per run and application, its units and those drawn: what the cap (per_app) did
        "applications": [
            {
                "run": run,
                "application": app,
                "population": sum(1 for u in every if (u["_run"], u["application"]) == (run, app)),
                "drawn": sum(1 for u in drawn if (u["_run"], u["application"]) == (run, app)),
            }
            for run, app in sorted({(u["_run"], u["application"]) for u in every})
        ],
        "files": {SAMPLE: file_sha256(folder / SAMPLE), KEY: file_sha256(folder / KEY)},
    }
    write_json(folder / MANIFEST, manifest)
    return manifest


def _nodes(name: str) -> list[dict]:
    from skuld.common import vocabulary

    return [
        {"id": n.id, "title": n.title, "description": n.description, "parents": list(n.parents)}
        for n in sorted(vocabulary(name), key=lambda n: n.id)
    ]


def purpose_vocabulary() -> list[dict]:
    """The DPV purpose nodes: id, title, description and parents."""
    from skuld.common import PURPOSES

    return _nodes(PURPOSES)


def vocabularies() -> dict:
    """The vocabularies a sample carries for the review tool, which needs nothing beyond the sample: the DPV purposes
    (the values of purposes, the node pickers) and Skuld's data types (the values of practices), each shown as a tree
    when a value is clicked."""
    from skuld.common import DATA

    return {"purpose": purpose_vocabulary(), "data": _nodes(DATA)}


def _questions() -> dict:
    return {
        "purpose": {k: list(v) for k, v in PURPOSE_QUESTIONS.items()},
        "dependency": {k: list(v) for k, v in DEPENDENCY_QUESTIONS.items()},
    }


# -- checking a review ------------------------------------------------------------------------------------------------


def problems(item: dict, review: dict) -> list[str]:
    """What keeps a unit's review from being complete: a question left open or a value not allowed."""
    out = []
    answers = review.get("purposes") or {}
    for p in item["purposes"]:
        a = answers.get(p["key"]) or {}
        for q in asked(p):
            if a.get(q) not in PURPOSE_QUESTIONS[q]:
                out.append(f"{p['key']}: {q}")
        for d in p["dependencies"]:
            if not d["asked"]:
                continue
            b = (review.get("dependencies") or {}).get(d["key"]) or {}
            for q, values in DEPENDENCY_QUESTIONS.items():
                if b.get(q) not in values:
                    out.append(f"{d['key']}: {q}")
    return out


# -- scores -----------------------------------------------------------------------------------------------------------


def _judgments(item: dict, review: dict):
    """(level, part, question, answer, role) of every question a unit's review answered, purposes and dependencies;
    a dependency takes its purpose's role."""
    for p in item["purposes"]:
        role = p.get("role") or "?"
        a = (review.get("purposes") or {}).get(p["key"]) or {}
        for q in asked(p):
            if a.get(q) in PURPOSE_QUESTIONS[q]:
                yield "purpose", p, q, a[q], role
        for d in p["dependencies"]:
            b = (review.get("dependencies") or {}).get(d["key"]) or {}
            if d["asked"]:
                for q, values in DEPENDENCY_QUESTIONS.items():
                    if b.get(q) in values:
                        yield "dependency", d, q, b[q], role


def _asks(item: dict):
    """(level, question, role) of every question a unit asks, answered or not."""
    for p in item["purposes"]:
        role = p.get("role") or "?"
        for q in asked(p):
            yield "purpose", q, role
        for d in p["dependencies"]:
            if d["asked"]:
                for q in DEPENDENCY_QUESTIONS:
                    yield "dependency", q, role


def _agrees(level: str, question: str, answer: str) -> bool:
    values = (PURPOSE_QUESTIONS if level == "purpose" else DEPENDENCY_QUESTIONS)[question]
    return answer == values[0]


def _weighted(by: dict, population: dict) -> float | None:
    """The strata's rates weighted by their populations, over the strata with a judged answer."""
    n = sum(population[sk] for sk, (_, judged) in by.items() if judged)
    return round(sum(population[sk] * k / judged for sk, (k, judged) in by.items() if judged) / n, 3) if n else None


def score(folder: str | Path) -> dict:
    """
    Agreement with the stage's predictions from one reviewer's judgments, per question: per run and role, unweighted
    with a Wilson interval and weighted by the strata's populations; `partly` counts as not agreeing and `unsure` is
    left out. The node's answers and the purposes noted as missed are reported as they were given. For a partial
    return, `strata` gives per stratum the units drawn, reviewed (done) and judged, and `coverage` the strata it did
    not reach, which the weighted rates do not represent.
    """
    folder = Path(folder)
    manifest = read_json(folder / MANIFEST)
    for name, sha in manifest["files"].items():
        if file_sha256(folder / name) != sha:
            raise ReviewError(f"{name} is not the file drawn (digest differs)")
    key = read_json(folder / KEY)
    items = {i["id"]: i for i in read_json(folder / SAMPLE)["items"]}
    reviews = decisions(folder / REVIEWS, missing_ok=True)
    population = {_skey(s): s["population"] for s in manifest["strata"]}

    # per stratum k and n, combined as the strata's populations weight their rates: a stratum with unsure answers or
    # units not yet done counts for its whole population
    totals = defaultdict(lambda: {"k": 0, "n": 0, "by": defaultdict(lambda: [0, 0]), "answers": defaultdict(int)})
    missed, done, done_in, judged_in = [], 0, defaultdict(int), defaultdict(int)
    for iid, entry in key.items():
        r = reviews.get(iid) or {}
        if not r.get("done"):
            continue
        done += 1
        s = entry["stratum"]
        sk = _skey(s)
        # a unit done is reviewed; it is judged where at least one of its answers is not unsure
        done_in[sk] += 1
        judged_in[sk] += any(a != "unsure" for *_, a, _ in _judgments(items[iid], r))
        for level, _, q, answer, role in _judgments(items[iid], r):
            for scope in ((s["run"], level, q, role), (s["run"], level, q, "all")):
                t = totals[scope]
                t["answers"][answer] += 1
                if answer == "unsure":
                    continue
                ok = _agrees(level, q, answer)
                t["k"] += ok
                t["n"] += 1
                t["by"][sk][0] += ok
                t["by"][sk][1] += 1
        for m in r.get("missed") or []:
            missed.append({"run": s["run"], "practice": entry["practice"], **m})
    # per estimate, the strata whose drawn units ask its question: the population a weighted rate could stand for
    asking = defaultdict(set)
    for iid, entry in key.items():
        sk = _skey(entry["stratum"])
        for level, q, role in _asks(items[iid]):
            asking[(sk[0], level, q, role)].add(sk)
            asking[(sk[0], level, q, "all")].add(sk)
    strata = [{**s, "reviewed": done_in[_skey(s)], "judged": judged_in[_skey(s)]} for s in manifest["strata"]]
    out = {
        "review": manifest["id"],
        "scored": datetime.now(UTC).isoformat(timespec="seconds"),
        "measure": "agreement with the expectation stage's predictions (non-blind; judged against E's context)",
        "units": len(key),
        "done": done,
        "estimates": [
            {
                "run": run,
                "level": level,
                "question": q,
                "role": role,
                "judged": t["n"],
                "rate": round(t["k"] / t["n"], 3) if t["n"] else None,
                "interval": [round(x, 3) for x in wilson(t["k"], t["n"])] if t["n"] else None,
                "weighted_rate": _weighted(t["by"], population),
                # of the population of the strata whose units ask the question, the share in strata with an answer
                # judged: what the weighted rate stands for
                "population_covered": round(
                    sum(population[sk] for sk, (_, n) in t["by"].items() if n)
                    / sum(population[sk] for sk in asking[(run, level, q, role)]),
                    3,
                ),
                "answers": dict(t["answers"]),
            }
            for (run, level, q, role), t in sorted(totals.items())
        ],
        "strata": strata,
        "coverage": coverage(strata, STRATUM, len(key), done),
        "missed": missed,
        "missed_functional": sum(1 for m in missed if m.get("functional")),
    }
    write_json(folder / SCORES, out)
    return out


# -- two reviewers ----------------------------------------------------------------------------------------------------


def agree(folder: str | Path, first: str | Path, second: str | Path) -> dict:
    """
    Two reviewers' independent judgments on one sample: Cohen's κ per question over the purposes and dependencies both
    answered, overall and per run; the answers they differ on, for adjudication. Where the sample has no reviews.json
    yet, it is seeded with the answers both gave alike (not done), so that adjudication fills in the rest.
    """
    folder = Path(folder)
    key = read_json(folder / KEY)
    items = {i["id"]: i for i in read_json(folder / SAMPLE)["items"]}
    a, b = _given(first, second)

    pairs = defaultdict(list)  # (run or "all", level, question) -> [(x, y)]
    differ = []
    for iid in sorted(key):
        ra, rb = a.get(iid) or {}, b.get(iid) or {}
        if not (ra.get("done") and rb.get("done")):
            continue
        ja = {(lv, p["key"], q): v for lv, p, q, v, _ in _judgments(items[iid], ra)}
        jb = {(lv, p["key"], q): v for lv, p, q, v, _ in _judgments(items[iid], rb)}
        for k in sorted(set(ja) & set(jb)):
            level, part, q = k
            for scope in (key[iid]["stratum"]["run"], "all"):
                pairs[(scope, level, q)].append((ja[k], jb[k]))
            if ja[k] != jb[k]:
                differ.append({"id": iid, "part": part, "question": q, "first": ja[k], "second": jb[k]})

    def summary(p):
        k = kappa(p)
        return {"items": len(p), "agreed": sum(x == y for x, y in p), "kappa": round(k, 3) if k is not None else None}

    out = {
        "review": folder.name,
        "compared": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviews": [str(Path(first)), str(Path(second))],
        "note": "kappa measures reliability, not validity: both reviewers see E's predictions and share their anchor",
        "questions": {f"{scope} {level} {q}": summary(p) for (scope, level, q), p in sorted(pairs.items())},
        "differences": differ,
    }
    write_json(folder / AGREEMENT, out)
    if not (folder / REVIEWS).exists():
        seeded = {}
        for iid in key:
            ra, rb = a.get(iid) or {}, b.get(iid) or {}
            if not (ra.get("done") and rb.get("done")):
                continue
            merged = {"purposes": {}, "dependencies": {}}
            for part in ("purposes", "dependencies"):
                for k, va in (ra.get(part) or {}).items():
                    vb = (rb.get(part) or {}).get(k) or {}
                    same = {q: v for q, v in va.items() if vb.get(q) == v}
                    if same:
                        merged[part][k] = same
            notes = " | ".join(n for n in (ra.get("note"), rb.get("note")) if n)
            # both reviewers' missed purposes, an identical one once; the adjudicator merges those worded differently
            missed = []
            for m in (ra.get("missed") or []) + (rb.get("missed") or []):
                if m not in missed:
                    missed.append(m)
            seeded[iid] = {**merged, "missed": missed, "note": notes}
        write_json(folder / REVIEWS, seeded)
        out["seeded"] = len(seeded)
    return out
