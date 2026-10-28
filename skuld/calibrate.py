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

    def unit(principle, step, subject, purpose, requirements, tier_if_silent, shown):
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
                **shown,
            }
        )

    # the collection: one unit per transparency requirement on it
    for r in frame.requirements.values():
        if r.subject != "collection" or r.id not in coverage:
            continue
        unit(r.principle, r.steps[0], "collection", None, [r.id], "rule", {"subject": {"kind": "collection"}})

    # declared purpose statements
    specific = coverage.get("purpose_specific")
    if specific and a.declaration is not None:
        subjects = assessment.build(a, registry)
        for s in judge.statements(a, subjects):
            if s.declarations[0] not in specific.get("assessed", []) + specific.get("not_applicable", []):
                continue
            shown = {"subject": {"kind": "statement", "text": s.text, "sentence": s.sentence, "channels": s.channels}}
            unit("transparency", "not_specific", s.declarations[0], None, ["purpose_specific"], "reasoning", shown)

    # practices and their supported purposes
    practices = {p["id"]: p for p in report["subjects"]["practices"]}
    purposes = [
        c
        for c in report["claims"]
        if c["type"] == "purpose" and c["stage"] == "expectation" and c["status"] == "supported"
    ]
    read = _stage_one(root)
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
            unit(principle, step, h["subject"], h["id"], requirements, "+".join(channels), shown)
    return out


def _stage_one(root: Path) -> dict[str, dict]:
    """Per practice, what the expectation stage read with it: the screens and corpus passages of every stage-1 context
    that held the practice, each once, in the order first read."""
    out: dict[str, dict] = {}
    for path in sorted(root.glob("expectation/*/s*/context.json")):
        parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
        shown = [p for p in parts if p["kind"] in ("screen", "passage")]
        for practice in (p["id"] for p in parts if p["kind"] == "practice"):
            entry = out.setdefault(practice, {"screens": [], "passages": []})
            for part in shown:
                texts = entry["screens" if part["kind"] == "screen" else "passages"]
                if part["text"] not in texts:
                    texts.append(part["text"])
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
    per_stratum = per_stratum or s["per_stratum"]
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
        for u in units(root, report, registry):
            u["assessment"], u["application"] = key, assessments[-1]["application"]
            every.append(u)

    rng = random.Random(seed)
    strata = defaultdict(list)
    for u in every:
        strata[_stratum_key(u["stratum"])].append(u)
    drawn = []
    for k in sorted(strata):
        members = strata[k]
        drawn += members if len(members) <= per_stratum else rng.sample(members, per_stratum)
    rng.shuffle(drawn)  # the order of review says nothing of the stratum

    folder.mkdir(parents=True)
    documents = {a["key"]: _copy_documents(Path(a["workspace"]), folder / DOCUMENTS / a["key"]) for a in assessments}
    items, key = [], {}
    for n, u in enumerate(drawn, 1):
        iid = f"u{n:03d}"
        key[iid] = {"stratum": u["stratum"], "concerns": u["concerns"]}
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
    _write(folder / SAMPLE, {"items": items})
    _write(folder / KEY, key)
    manifest = {
        "id": folder.name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": skuld.__version__,
        "method": {"id": "skuld.calibrate", "version": VERSION},
        "seed": seed,
        "per_stratum": per_stratum,
        "assessments": assessments,
        "strata": [
            {
                **strata[k][0]["stratum"],
                "population": len(strata[k]),
                "drawn": sum(1 for u in drawn if _stratum_key(u["stratum"]) == k),
            }
            for k in sorted(strata)
        ],
        "files": {SAMPLE: _sha(folder / SAMPLE), KEY: _sha(folder / KEY)},
    }
    _write(folder / MANIFEST, manifest)
    return manifest


def _stratum_key(s: dict) -> tuple:
    return (s["principle"], s["tier"], s["step"], s["outcome"])


def _copy_documents(root: Path, target: Path) -> list[dict]:
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
            out.add((role, cid, c.get("sha256") or "", c.get("stage") or ""))
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
    manifest = _read(Path(folder) / MANIFEST)
    calibrated = {tuple(x) for a in manifest["assessments"] for x in a["components"]}
    problems = []
    for root in map(Path, workspaces):
        report = _read(root / REPORT)
        for x in identity(report["report"]["components"]):
            if tuple(x) not in calibrated:
                problems.append(f"{root.name}: {x[0]} {x[1]} {' '.join(str(v) for v in x[2:] if v)} is not calibrated")
    return problems


# -- scores -----------------------------------------------------------------------------------------------------------


def score(folder: str | Path) -> dict:
    """Error rates from the expert's decisions: per stratum, and per principle and step weighted by the strata's
    populations. The sample's files must be those drawn."""
    folder = Path(folder)
    manifest = _read(folder / MANIFEST)
    for name, sha in manifest["files"].items():
        if _sha(folder / name) != sha:
            raise CalibrationError(f"{name} is not the file drawn (digest differs)")
    key = _read(folder / KEY)
    reviews = _read(folder / REVIEWS) if (folder / REVIEWS).is_file() else {}
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
    _write(folder / SCORES, out)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval of k of n."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


# -- files ------------------------------------------------------------------------------------------------------------


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
