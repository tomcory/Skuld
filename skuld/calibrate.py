"""
E's calibration (EV-E9): a stratified sample of assessments' results, reviewed blind by an expert against the frame.

A unit is a requirement for one subject of one assessment, at the grain of E's concerns: the collection (transparency
information), a declared purpose statement (specificity), or a practice and one of its supported purposes (purpose
limitation, minimisation). E's outcome for a unit is the status of its concern, `silent` where E assessed the unit and
stated none, or `not_applicable` where E found the requirement not to apply. Units are stratified by principle, tier,
step and outcome, and up to `per_stratum` of each stratum are drawn with a recorded seed (config.json, `calibration`).

The expert sees the unit (the requirement, the subject, the purpose it serves and the collection's documents), never
E's outcome or reasoning, and decides whether the subject fails the requirement at the step: `fails`, `holds` or
`unsure`. Comparing the decisions with E's outcomes gives, per stratum, the precision of the concerns, the misses among
the silences, and how many of the concerns E could not establish are concerns.

The sample folder:

    manifest.json   the assessments by path and digest, with the components a calibration holds for; the seed, the
                    strata (population and drawn), and the digests of sample.json and key.json
    sample.json     the items the expert reviews, without E's outcomes (the review tool reads only this)
    key.json        E's outcome per item, with the concerns it rests on
    documents/      each assessment's collection as the expert reads it, copied from Sága's collection
    reviews.json    the expert's decision per item, written by the review tool (Skuld/tools/calibration-review)
    scores.json     error rates per stratum and per principle and step (`skuld calibrate score`)
"""

import hashlib
import json
import math
import random
import re
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import skuld
from skuld import assessment, config, inputs, judge
from skuld.assess import REPORT
from skuld.expectation import retrieved_for
from skuld.parties import load_registry

VERSION = "1"
MANIFEST, SAMPLE, KEY, REVIEWS, SCORES = "manifest.json", "sample.json", "key.json", "reviews.json", "scores.json"
DOCUMENTS = "documents"
DECISIONS = ("fails", "holds", "unsure")
#: E's outcomes whose units should hold (a review that says `fails` is a miss)
SILENT = ("silent", "not_applicable")

#: The question the expert answers per step, in the frame's terms
QUESTIONS = {
    "information_not_given": "Does the app's collection of documents fail to give this information, where the "
    "requirement applies to the app?",
    "not_specific": "Is this declared purpose too vague for a data subject to understand what is done with their data "
    "and why?",
    "no_specified_purpose": "Does the practice serve this purpose although no purpose the provider specifies for its "
    "data covers it or is compatible with it?",
    "less_invasive_alternative": "Could the practice achieve this purpose with less: less or coarser data, a narrower "
    "identifier, fewer or less invasive recipients?",
    "declaration_contradicted": "Does the processing observed contradict this declaration: does the app do what the "
    "provider declares it does not do?",
}
#: The practice requirements, grouped as E's concerns state them: one concern per practice, purpose and principle
PRACTICE_STEPS = {"purpose_limitation": "no_specified_purpose", "data_minimisation": "less_invasive_alternative"}


class CalibrationError(inputs.InputError):
    """A sample that cannot be drawn or scored: its inputs are missing, or its fixed files changed."""


def settings() -> dict:
    """config.json's `calibration`: units drawn per stratum and the seed."""
    return {"per_stratum": 10, "seed": 1, **(config.load().get("calibration") or {})}


# -- units ------------------------------------------------------------------------------------------------------------


def units(root: Path, report: dict, registry=None) -> list[dict]:
    """Every unit of an assessment with E's outcome, its stratum and what the expert is shown of it."""
    a = inputs.load_assessment(root)
    frame = a.frame
    out = []
    concerns = defaultdict(list)
    for c in report["concerns"]:
        # the collection has one unit per requirement; a statement one, a practice one per purpose and principle
        grain = c["requirement"] if c["subject"] == "collection" else c.get("purpose")
        concerns[(c["principle"], c["subject"], grain)].append(c)
    coverage = {e["requirement"]: e for e in report["coverage"]}

    def unit(principle, step, subject, purpose, requirements, tier_if_silent, shown, grain):
        mine = concerns.get((principle, subject, requirements[0] if subject == "collection" else purpose), [])
        not_applicable = all(subject in coverage.get(r, {}).get("not_applicable", []) for r in requirements)
        if mine:
            outcome = _strongest(c["status"] for c in mine)
            tier = "+".join(sorted({c["tier"] for c in mine}))
        else:
            outcome = "not_applicable" if not_applicable else "silent"
            tier = tier_if_silent
        r = frame.requirement(mine[0]["requirement"] if mine else requirements[0])
        out.append(
            {
                "stratum": {"principle": principle, "tier": tier, "step": step, "outcome": outcome},
                "concerns": [c["id"] for c in mine],
                "requirement": {
                    "id": r.id,
                    "title": r.title,
                    "principle": principle,
                    "provisions": list(r.provisions),
                },
                "question": QUESTIONS[step],
                # what the unit is in any assessment of the same inputs, whatever its model: the requirement for the
                # collection, the declaration for a statement, the practice and its purpose's vocabulary node (None
                # where the purpose has no node, which then aligns with nothing)
                "grain": grain,
                **shown,
            }
        )

    # the collection: one unit per transparency requirement on it
    for r in frame.requirements.values():
        if r.subject != "collection" or r.id not in coverage:
            continue
        unit(
            r.principle,
            r.steps[0],
            "collection",
            None,
            [r.id],
            "rule",
            {"subject": {"kind": "collection"}},
            ("collection", r.id),
        )

    # declared purpose statements
    specific = coverage.get("purpose_specific")
    if specific and a.declaration is not None:
        subjects = assessment.build(a, registry)
        for s in judge.statements(a, subjects):
            if s.declarations[0] not in specific.get("assessed", []) + specific.get("not_applicable", []):
                continue
            shown = {"subject": {"kind": "statement", "text": s.text, "sentence": s.sentence, "channels": s.channels}}
            unit(
                "transparency",
                "not_specific",
                s.declarations[0],
                None,
                ["purpose_specific"],
                "reasoning",
                shown,
                ("statement", s.declarations[0]),
            )

    # practices and their supported purposes
    practices = {p["id"]: p for p in report["subjects"]["practices"]}
    purposes = [
        c
        for c in report["claims"]
        if c["type"] == "purpose" and c["stage"] == "expectation" and c["status"] == "supported"
    ]
    read = stage_one(root)
    for principle, step in PRACTICE_STEPS.items():
        requirements = [
            r.id for r in frame.requirements.values() if r.principle == principle and r.subject == "practice"
        ]
        assessed = {s for r in requirements for s in coverage.get(r, {}).get("assessed", [])}
        channels = sorted({ch for r in requirements for ch in coverage.get(r, {}).get("channels", [])})
        for h in purposes:
            if h["subject"] not in assessed:
                continue
            p = practices[h["subject"]]
            shown = {
                "subject": {
                    "kind": "practice",
                    "type": p["claim_type"],
                    "data": p["data"],
                    "recipient": p["recipient"],
                    "actor": p["actor"],
                    "episodes": p["episodes"],
                },
                "purpose": {
                    k: _uncited(h["purpose"].get(k)) for k in ("action", "object", "beneficiary", "context", "outcome")
                }
                | {"node": h["purpose"].get("node")},
                "context": read.get(h["subject"], {"screens": [], "passages": []}),
            }
            node = h["purpose"].get("node")
            grain = ("practice", h["subject"], node) if node else None
            unit(principle, step, h["subject"], h["id"], requirements, "+".join(channels), shown, grain)
    return out


def stage_one(root: Path) -> dict[str, dict]:
    """Per practice, what the expectation stage read with it: the screens and corpus passages of every stage-1 context
    that held the practice, each once, in the order first read. A passage labelled with the practices it was retrieved
    for (prompt version 8 or later) is shown only with those, without its label; an unlabelled passage of an earlier
    context, which names no practice, with every practice of its batch, as before."""
    out: dict[str, dict] = {}
    for path in sorted(root.glob("expectation/*/s*/context.json")):
        parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
        shown = [p for p in parts if p["kind"] in ("screen", "passage")]
        for practice in (p["id"] for p in parts if p["kind"] == "practice"):
            entry = out.setdefault(practice, {"screens": [], "passages": []})
            for part in shown:
                text = part["text"]
                if part["kind"] == "passage":
                    named, text = retrieved_for(text)
                    if named is not None and practice not in named:
                        continue
                texts = entry["screens" if part["kind"] == "screen" else "passages"]
                if text not in texts:
                    texts.append(text)
    return out


def _uncited(text):
    """A purpose's part without the stage's citations ([S1], [D2]), which point into a context the expert does not
    see; None where nothing else is left."""
    if not isinstance(text, str):
        return text
    left = re.sub(r"\[[A-Z]+\d+\]", "", text).strip(" ,;")
    return left or None


def _strongest(statuses) -> str:
    order = ("supported", "conflicted", "not_established", "not_assessable", "refuted")
    found = set(statuses)
    return next(s for s in order if s in found) if found & set(order) else sorted(found)[0]


# -- drawing ------------------------------------------------------------------------------------------------------------


def draw(folder: str | Path, workspaces: list[str | Path], registry_path=None, per_stratum=None, seed=None) -> dict:
    """Draws the sample from the assessments of the workspaces and fixes it in `folder`, which must not exist."""
    folder = Path(folder)
    if folder.exists():
        raise CalibrationError(f"{folder} exists: a drawn sample is fixed, draw a new one into another folder")
    s = settings()
    per_stratum = s["per_stratum"] if per_stratum is None else per_stratum
    seed = s["seed"] if seed is None else seed
    registry = load_registry(registry_path)

    assessments, every = [], []
    for n, root in enumerate(map(Path, workspaces), 1):
        path = root / REPORT
        if not path.is_file():
            raise CalibrationError(f"{root}: no {REPORT}; run `skuld assess` first")
        report = json.loads(path.read_text(encoding="utf-8"))
        key = f"a{n}"
        app = report["application"]
        assessments.append(
            {
                "key": key,
                "workspace": str(root.resolve()),
                "sha256": inputs.digest(path),
                "application": f"{app['package']}@{app['version']}",
                "components": identity(report["report"]["components"]),
            }
        )
        assessments[-1]["family"] = _family(report)
        assessments[-1]["inputs"] = _inputs(root)
        for u in units(root, report, registry):
            u["assessment"], u["application"] = key, assessments[-1]["application"]
            every.append(u)

    rng = random.Random(seed)
    # several assessments of one application: the same inputs assessed by different model families, whose units are
    # merged, so that one decision of the reviewers scores every family
    families = _families(assessments)
    if families:
        every = _merge(every, assessments, families, rng)
    strata = defaultdict(list)
    for u in every:
        strata[_stratum_key(u["stratum"])].append(u)
    drawn = []
    for k in sorted(strata):
        members = strata[k]
        drawn += members if len(members) <= per_stratum else rng.sample(members, per_stratum)
    rng.shuffle(drawn)  # the order of review says nothing of the stratum

    folder.mkdir(parents=True)
    # across families, an application's documents are copied once, from its first assessment (D is the same for all)
    sources = {u["assessment"] for u in every}
    documents = {
        a["key"]: copy_documents(Path(a["workspace"]), folder / DOCUMENTS / a["key"])
        for a in assessments
        if a["key"] in sources
    }
    items, key = [], {}
    for n, u in enumerate(drawn, 1):
        iid = f"u{n:03d}"
        key[iid] = {"stratum": u["stratum"], "concerns": u["concerns"]}
        if families:
            key[iid] |= {"outcomes": u["outcomes"], "tiers": u["tiers"], "shown_from": u["shown_from"]}
        items.append(
            {
                "id": iid,
                "application": u["application"],
                "requirement": u["requirement"],
                "question": u["question"],
                "subject": u["subject"],
                **({"purpose": u["purpose"]} if "purpose" in u else {}),
                **({"context": u["context"]} if "context" in u else {}),
                "documents": documents[u["assessment"]],
                "assessment": u["assessment"],
            }
        )
    write_json(folder / SAMPLE, {"items": items})
    write_json(folder / KEY, key)
    manifest = {
        "id": folder.name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": skuld.__version__,
        "method": {"id": "skuld.calibrate", "version": VERSION},
        "seed": seed,
        "per_stratum": per_stratum,
        **({"mode": "families", "families": families} if families else {}),
        "assessments": assessments,
        "strata": [
            {
                **strata[k][0]["stratum"],
                "population": len(strata[k]),
                "drawn": sum(1 for u in drawn if _stratum_key(u["stratum"]) == k),
            }
            for k in sorted(strata)
        ],
        "files": {SAMPLE: file_sha256(folder / SAMPLE), KEY: file_sha256(folder / KEY)},
    }
    write_json(folder / MANIFEST, manifest)
    return manifest


def stratum_name(s: dict) -> str:
    """A stratum for printing: its principle, tier, step and outcome, or across families how many raise a concern."""
    parts = [str(s[k]) for k in ("principle", "tier", "step", "outcome") if k in s]
    return " ".join(parts + ([f"raised by {s['raised']}"] if "raised" in s else []))


def _stratum_key(s: dict) -> tuple:
    """One model: principle, tier, step and E's outcome. Across families: principle, step and how many families
    support a concern on the unit (`raised`)."""
    return tuple(s.get(k) for k in ("principle", "tier", "step", "outcome", "raised"))


# -- across model families --------------------------------------------------------------------------------------------

#: A family's outcome for a unit it has no unit for: a practice's purpose (by vocabulary node) it did not infer
ABSENT = "absent"


def _family(report: dict) -> str | None:
    """The model family an assessment's stages asked, or None where they asked several; a reasoning setting is part
    of it (`qwen3.8:27b (think low)`), as the same model with reasoning off and on are two configurations."""
    models = {model_identity(c) for c in report["report"]["components"] if c["role"] == "model"}
    return next(iter(models)) if len(models) == 1 else None


def model_identity(component: dict) -> str:
    """A model component's name with its reasoning setting, where one was set."""
    think = component.get("think")
    if think is None:
        return component["id"]
    return f"{component['id']} (think {str(think).lower()})"


def _inputs(root: Path) -> dict:
    """What an assessment assessed, by digest: its O reports, D's report, the exploration, the frame and the corpus.
    Assessments of one application by different families must agree on all of it."""
    data = inputs._yaml(Path(root) / inputs.ASSESSMENT)
    return {
        "observation": sorted(e["sha256"] for e in data["observation"]),
        "declaration": (data.get("declaration") or {}).get("sha256"),
        "exploration": (data.get("exploration") or {}).get("sha256"),
        "frame": [data["frame"]["id"], str(data["frame"]["version"]), data["frame"]["sha256"]],
        "corpus": data["corpus"]["sha256"],
    }


def _families(assessments: list[dict]) -> list[str]:
    """The model families of a draw across families, or [] where every application has one assessment. Across
    families, every application is assessed once by each family, on the same inputs."""
    by_app = defaultdict(list)
    for a in assessments:
        by_app[a["application"]].append(a)
    if all(len(g) == 1 for g in by_app.values()):
        return []
    families = None
    for app, group in sorted(by_app.items()):
        named = [a["family"] for a in group]
        if None in named:
            raise CalibrationError(f"{app}: an assessment asked several models; one family per assessment")
        if len(set(named)) != len(named):
            raise CalibrationError(f"{app}: two assessments by the same family ({', '.join(sorted(named))})")
        if families is None:
            families = sorted(named)
        elif sorted(named) != families:
            raise CalibrationError(f"{app}: assessed by {sorted(named)}, the others by {families}")
        first = group[0]["inputs"]
        for a in group[1:]:
            differ = sorted(k for k in first if a["inputs"][k] != first[k])
            if differ:
                raise CalibrationError(f"{app}: the assessments differ in their inputs ({', '.join(differ)})")
    return families


def _outcome(outcomes) -> str:
    """One family's outcome for a merged unit from its units there (two purposes of a practice on one node)."""
    found = set(outcomes)
    if found - set(SILENT):
        return _strongest(found - set(SILENT))
    return "silent" if "silent" in found else "not_applicable"


def _merge(every: list[dict], assessments: list[dict], families: list[str], rng: random.Random) -> list[dict]:
    """The units of all families merged by grain: one unit per application, principle, step and grain, with each
    family's outcome (`absent` where it has no such unit) and its stratum by how many families support a concern.
    A practice's purpose without a vocabulary node aligns with nothing and stays its family's alone. The reviewers
    read the purpose as one family worded it, chosen at random (the seed is recorded); the key keeps which."""
    family = {a["key"]: a["family"] for a in assessments}
    first = {}
    for a in assessments:
        first.setdefault(a["application"], a["key"])
    grouped: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for n, u in enumerate(every):
        grain = u["grain"] if u["grain"] is not None else ("unaligned", u["assessment"], n)
        k = (u["application"], u["stratum"]["principle"], u["stratum"]["step"], grain)
        grouped[k][family[u["assessment"]]].append(u)
    merged = []
    for k in sorted(grouped, key=repr):
        got = grouped[k]
        outcomes = {f: _outcome(u["stratum"]["outcome"] for u in got[f]) if f in got else ABSENT for f in families}
        shown_from = rng.choice(sorted(got))
        base = got[shown_from][0]
        u = {
            "stratum": {
                "principle": base["stratum"]["principle"],
                "step": base["stratum"]["step"],
                "raised": sum(o == "supported" for o in outcomes.values()),
            },
            "outcomes": outcomes,
            "concerns": {f: sorted({c for x in got.get(f, []) for c in x["concerns"]}) for f in families},
            "tiers": {
                f: "+".join(sorted({x["stratum"]["tier"] for x in got[f]})) if f in got else None for f in families
            },
            "shown_from": shown_from,
            "requirement": base["requirement"],
            "question": base["question"],
            "subject": base["subject"],
            "assessment": first[k[0]],
            "application": k[0],
        }
        if "purpose" in base:
            u["purpose"] = base["purpose"]
        if "context" in base:
            context = {"screens": [], "passages": []}
            for x in (x for f in sorted(got) for x in got[f]):
                for part, texts in x["context"].items():
                    context[part] += [t for t in texts if t not in context[part]]
            u["context"] = context
        merged.append(u)
    return merged


def copy_documents(root: Path, target: Path) -> list[dict]:
    """The collection's documents the assessment's D report names, copied from Sága's collection for the expert,
    with D's status of each (a document D could not analyse is shown too: the expert reads what the provider gives)."""
    a = inputs.load_assessment(root)
    if a.declaration is None:
        return []
    report = a.declaration.load()
    source = _collection(a.declaration.path, report["collection"].get("path") or "")
    out = []
    for ch in report["channels"]:
        if not ch.get("document") or source is None:
            continue
        folder = source / "documents" / ch["document"]
        for f in sorted(folder.glob("*.json")) if folder.is_dir() else ():
            if f.name == "meta.json":
                continue
            target.mkdir(parents=True, exist_ok=True)
            name = f"{ch['channel']}-{f.name}"
            shutil.copyfile(f, target / name)
            out.append({"channel": ch["channel"], "status": ch["status"], "file": f"{DOCUMENTS}/{target.name}/{name}"})
    return out


def _collection(report_path: Path, relative: str) -> Path | None:
    """Sága's collection folder, which D's report names relative to where Urda ran."""
    for parent in Path(report_path).resolve().parents:
        if relative and (parent / relative).is_dir():
            return (parent / relative).resolve()
    return None


# -- what a calibration holds for -------------------------------------------------------------------------------------


def identity(components: list[dict]) -> list[list]:
    """The components a calibration holds for: the models by digest, the prompts, methods and D's analysis by version,
    the frame, vocabularies, alignment and registry; not what varies per context (a filled prompt's digest, a seed) or
    per application (D's report)."""
    out = set()
    for c in components:
        role, cid = c["role"], c["id"]
        if role == "model":
            # the reasoning setting where one was set: the same model with reasoning off and on are two configurations
            think = (str(c["think"]),) if "think" in c else ()
            out.add((role, cid, c.get("sha256") or "", c.get("stage") or "", *think))
        elif role in ("prompt", "method"):
            extra = json.dumps(
                {k: v for k, v in c.items() if k not in ("role", "id", "version", "sha256", "stage", "seed")},
                sort_keys=True,
            )
            out.add((role, cid, c.get("version") or "", c.get("stage") or "", extra))
        elif role == "declaration_analysis":
            out.add((role, cid, c.get("version") or ""))
        elif role in ("frame", "vocabulary", "alignment", "registry"):
            out.add((role, cid, c.get("version") or "", c.get("sha256") or ""))
    return sorted(map(list, out))


def check(folder: str | Path, workspaces: list[str | Path]) -> list[str]:
    """Whether the calibration holds for these assessments: every component they name that the calibrated ones do not
    (a changed model or prompt, another D configuration) is a problem."""
    manifest = read_json(Path(folder) / MANIFEST)
    calibrated = {tuple(x) for a in manifest["assessments"] for x in a["components"]}
    problems = []
    for root in map(Path, workspaces):
        report = read_json(root / REPORT)
        for x in identity(report["report"]["components"]):
            if tuple(x) not in calibrated:
                problems.append(f"{root.name}: {x[0]} {x[1]} {' '.join(str(v) for v in x[2:] if v)} is not calibrated")
    return problems


# -- scores -----------------------------------------------------------------------------------------------------------


def score(folder: str | Path) -> dict:
    """Error rates from the expert's decisions: per stratum, and per principle and step weighted by the strata's
    populations. The sample's files must be those drawn."""
    folder = Path(folder)
    manifest = read_json(folder / MANIFEST)
    for name, sha in manifest["files"].items():
        if file_sha256(folder / name) != sha:
            raise CalibrationError(f"{name} is not the file drawn (digest differs)")
    key = read_json(folder / KEY)
    reviews = decisions(folder / REVIEWS) if (folder / REVIEWS).is_file() else {}
    if manifest.get("mode") == "families":
        return _score_families(folder, manifest, key, reviews)
    by_stratum = defaultdict(lambda: {"fails": 0, "holds": 0, "unsure": 0})
    for iid, entry in key.items():
        r = reviews.get(iid)
        if r and r.get("decision") in DECISIONS:
            by_stratum[_stratum_key(entry["stratum"])][r["decision"]] += 1
    strata = []
    for s in manifest["strata"]:
        counts = by_stratum[_stratum_key(s)]
        n = counts["fails"] + counts["holds"]
        measure = (
            "precision" if s["outcome"] == "supported" else "miss_rate" if s["outcome"] in SILENT else "concern_rate"
        )
        strata.append(
            {
                **s,
                **counts,
                "measure": measure,
                "rate": round(counts["fails"] / n, 3) if n else None,
                "interval": [round(x, 3) for x in wilson(counts["fails"], n)] if n else None,
            }
        )
    totals = defaultdict(lambda: {"population": 0, "weighted": 0.0, "reviewed": 0})
    for s in strata:
        if s["rate"] is None:
            continue
        t = totals[(s["principle"], s["step"], s["measure"])]
        t["population"] += s["population"]
        t["weighted"] += s["population"] * s["rate"]
        t["reviewed"] += s["fails"] + s["holds"]
    out = {
        "calibration": manifest["id"],
        "scored": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviewed": sum(1 for iid in key if (reviews.get(iid) or {}).get("decision") in ("fails", "holds")),
        "unsure": sum(1 for iid in key if (reviews.get(iid) or {}).get("decision") == "unsure"),
        "items": len(key),
        "strata": strata,
        "estimates": [
            {
                "principle": p,
                "step": step,
                "measure": m,
                "rate": round(t["weighted"] / t["population"], 3),
                "population": t["population"],
                "reviewed": t["reviewed"],
            }
            for (p, step, m), t in sorted(totals.items())
        ],
    }
    write_json(folder / SCORES, out)
    return out


def _measure(outcome: str) -> str:
    """What a reviewed unit measures of the family with this outcome: the precision of its concerns, its misses among
    its silences, its misses among the purposes it did not infer, or how often what it could not establish is one."""
    if outcome == "supported":
        return "precision"
    if outcome in SILENT:
        return "miss_rate"
    return "miss_rate_absent" if outcome == ABSENT else "concern_rate"


def _score_families(folder: Path, manifest: dict, key: dict, reviews: dict) -> dict:
    """Across families: per stratum (principle, step, families raising) the share the reviewers confirm as concerns;
    per family, principle and step its precision and misses, each unit weighted by its stratum's population over the
    units decided in it. The intervals are Wilson's on the unweighted counts, so a guide only where the weights differ."""
    strata = []
    weight = {}
    by_stratum = defaultdict(lambda: {"fails": 0, "holds": 0, "unsure": 0})
    for iid, entry in key.items():
        r = reviews.get(iid)
        if r and r.get("decision") in DECISIONS:
            by_stratum[_stratum_key(entry["stratum"])][r["decision"]] += 1
    for s in manifest["strata"]:
        k = _stratum_key(s)
        counts = by_stratum[k]
        n = counts["fails"] + counts["holds"]
        # over the units decided (not those drawn): a stratum with unsure units counts for its whole population
        weight[k] = s["population"] / n if n else 0.0
        strata.append(
            {
                **s,
                **counts,
                "measure": "confirmed",
                "rate": round(counts["fails"] / n, 3) if n else None,
                "interval": [round(x, 3) for x in wilson(counts["fails"], n)] if n else None,
            }
        )
    totals = defaultdict(lambda: {"fails": 0, "n": 0, "w_fails": 0.0, "w_n": 0.0})
    for iid, entry in key.items():
        decision = (reviews.get(iid) or {}).get("decision")
        if decision not in ("fails", "holds"):
            continue
        w = weight[_stratum_key(entry["stratum"])]
        s = entry["stratum"]
        for fam, outcome in entry["outcomes"].items():
            t = totals[(fam, s["principle"], s["step"], _measure(outcome))]
            t["n"] += 1
            t["w_n"] += w
            if decision == "fails":
                t["fails"] += 1
                t["w_fails"] += w
    out = {
        "calibration": manifest["id"],
        "scored": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "families",
        "families": manifest["families"],
        "reviewed": sum(1 for iid in key if (reviews.get(iid) or {}).get("decision") in ("fails", "holds")),
        "unsure": sum(1 for iid in key if (reviews.get(iid) or {}).get("decision") == "unsure"),
        "items": len(key),
        "strata": strata,
        "estimates": [
            {
                "family": fam,
                "principle": p,
                "step": step,
                "measure": m,
                "rate": round(t["w_fails"] / t["w_n"], 3) if t["w_n"] else None,
                "interval": [round(x, 3) for x in wilson(t["fails"], t["n"])],
                "reviewed": t["n"],
            }
            for (fam, p, step, m), t in sorted(totals.items())
        ],
    }
    write_json(folder / SCORES, out)
    return out


# -- two reviewers ----------------------------------------------------------------------------------------------------

AGREEMENT = "agreement.json"


def decisions(path: Path, missing_ok: bool = False) -> dict:
    """A reviews file's decisions by item: the review tool's form (by id at the top), or `{"items": {...}}`; with
    `missing_ok`, none where the file is not there yet (a sample's own reviews.json before adjudication)."""
    if missing_ok and not path.is_file():
        return {}
    data = read_json(path)
    return data["items"] if isinstance(data.get("items"), dict) else data


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa of two reviewers' decisions on the same items; None where it is undefined (no items, or both
    reviewers gave one decision throughout, so that chance agreement is 1)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    labels = {x for pair in pairs for x in pair}
    expected = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in labels)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def agree(folder: str | Path, first: str | Path, second: str | Path) -> dict:
    """Two reviewers' independent decisions on one sample: Cohen's kappa overall and per principle (on all three
    decisions, and on fails and holds where both decided one), and the items they disagree on, for adjudication.
    Where the sample has no reviews.json yet, it is seeded with the decisions both reviewers agree on, so that the
    review tool's next undecided item is the next to adjudicate."""
    folder = Path(folder)
    key = read_json(folder / KEY)
    a, b = decisions(Path(first)), decisions(Path(second))

    def decided(r, iid):
        return (r.get(iid) or {}).get("decision") in DECISIONS

    both = [iid for iid in sorted(key) if decided(a, iid) and decided(b, iid)]
    principles = sorted({key[iid]["stratum"]["principle"] for iid in key})

    def kappas(ids):
        pairs = [(a[i]["decision"], b[i]["decision"]) for i in ids]
        binary = [p for p in pairs if "unsure" not in p]
        k3, k2 = kappa(pairs), kappa(binary)
        return {
            "items": len(pairs),
            "agreed": sum(x == y for x, y in pairs),
            "kappa": round(k3, 3) if k3 is not None else None,
            "kappa_fails_holds": round(k2, 3) if k2 is not None else None,
            "items_fails_holds": len(binary),
        }

    disagreements = [
        {"id": iid, "first": a[iid], "second": b[iid]} for iid in both if a[iid]["decision"] != b[iid]["decision"]
    ]
    out = {
        "calibration": folder.name,
        "compared": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviews": [str(Path(first)), str(Path(second))],
        "undecided": {"first": sum(not decided(a, i) for i in key), "second": sum(not decided(b, i) for i in key)},
        "overall": kappas(both),
        "principles": {p: kappas([i for i in both if key[i]["stratum"]["principle"] == p]) for p in principles},
        "disagreements": disagreements,
    }
    write_json(folder / AGREEMENT, out)
    if not (folder / REVIEWS).exists():
        seeded = {}
        for iid in both:
            if a[iid]["decision"] == b[iid]["decision"]:
                notes = " | ".join(n for n in (a[iid].get("note"), b[iid].get("note")) if n)
                seeded[iid] = {"decision": a[iid]["decision"], "note": notes, "reviewed": out["compared"]}
        write_json(folder / REVIEWS, seeded)
        out["seeded"] = len(seeded)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval of k of n."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


# -- files ------------------------------------------------------------------------------------------------------------


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
