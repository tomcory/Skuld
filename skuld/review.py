"""
The review of E's output (author, 12 Nov 2026): a non-blind verification of aggregated concerns (skuld aggregate) by
two reviewers working independently, blind to the model run that produced them. It replaces the blind calibration
(skuld calibrate, EV-E9) as the paper's evaluation; that calibration is kept and unchanged.

A unit is one aggregated concern, shown in full: its label, status, tier and uncertainty, its members with their
reasons, the alternatives and purposes E stated, the evidence items its members rest on, and the application's
documents. Units of several runs of one application (one workspace each, the run named by the workspace's parent
folder; a run's workspaces must name the same models, reasoning setting included) are drawn together, stratified by run, principle, tier, step and status, and
interleaved (`interleave`: every prefix of the review order covers the strata in proportion to their drawn sizes, so
that a partial return is a smaller stratified sample; until 20 Nov 2026 they were shuffled); the sample never names the
run, which only key.json holds. By default each run's units are allocated to its strata in
proportion to their size, `per_run` in all with at least `floor` per stratum (or all of a smaller one), so that the
weighted estimate per run keeps nearly the precision of its sample (author, 12 Nov 2026: 70 per run); with
`per_stratum`, every stratum gets that many instead (equal allocation, which roughly halves the effective sample of a
run whose strata differ in size as much as the study's). Seeing E's conclusion anchors a reviewer, so what
the review measures is agreement with E's output, not precision.

The reviewer records, before the overall judgment:

    evidence    the evidence exists and is cited correctly: yes, partly, no, or none cited
    follows     the conclusion follows from it: yes, partly, no
    phrases     for a unit of declared purposes: per phrase, specific, not specific or unsure (specificity is a property
                of each phrase, and a unit can be mixed)
    overall     the verdict on the concern as stated: agree, disagree or unsure (unsure is left out of the rates), with a
                note. For a unit of declared purposes E holds not specific, the verdict is derived from the phrases
                (author, 12 Nov 2026): agree if every phrase judged is not specific, disagree if none is, partly if some
                are (partly counts as not agreeing), unsure if every phrase is unsure

Some units (`--anchor`, drawn among supported units other than declared purposes) are shown blind first: subject and
question only, with a blind decision (fails, holds, unsure) recorded before E's output is revealed; the difference
between the blind and the non-blind judgments on them estimates the anchoring. Every unit of declared purposes (concern
(ii), purpose not specific) carries its phrases (`blind_phrases`, since 20 Nov 2026): the reviewer first judges each
phrase specific, not specific or unsure with E's output hidden (reviews.json: `blind_phrases`, kept apart from the
non-blind `phrases` and never changed once saved), and then judges the unit with E's output as any other; the score
gives the blind phrases' agreement with E beside the non-blind one on the same phrases. A sample drawn before carries
no `blind_phrases`; it loads and scores as before. After an application's units, the reviewer scans its practices
and declarations for what E should have raised and did not (the recall pass, recall.json): a lower bound on misses.

The sample folder:

    manifest.json   the workspaces by run and digest (assessment and aggregate), the seed, the strata (population and
                    drawn), the digests of sample.json and key.json
    sample.json     the units as the reviewer sees them, and per application its practices, declarations and documents
    key.json        per unit: its run, workspace, aggregated concern, concerns and stratum
    documents/      each application's collection, copied from Sága's collection
    reviews.json    the reviewer's judgments per unit (the review tool writes it)
    recall.json     the reviewer's recall pass per application
    scores.json     agreement per unit and per member, per stratum, run, principle and step; which strata a partial
                    return reached (`skuld review score`)
    agreement.json  two reviewers' κ per criterion and principle, and their disagreements (`skuld review agree`)
"""

import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import skuld
from skuld import inputs, review_reasons
from skuld.aggregate import REPORT as AGGREGATE
from skuld.assess import REPORT
from skuld.calibrate import (
    QUESTIONS,
    copy_documents,
    decisions,
    file_sha256,
    kappa,
    model_identity,
    read_json,
    wilson,
    write_json,
)

#: 2 since the drawn units are interleaved by stratum instead of shuffled (every prefix of the sample covers the strata
#: in proportion), a unit of declared purposes carries its phrases to be judged blind first (`blind_phrases`) and is no
#: longer drawn as an anchoring unit (20 Nov 2026)
#: 3 since the criteria have `mostly` and an answer short of yes names its reasons (skuld.review_reasons.CONCERNS), the
#: sample carries the criteria's values and the reasons (`questions`), and two reviewers' agreement on a criterion is also
#: given as linearly weighted κ (author, 24 Nov 2026)
#: 4 since an experiment among a unit's evidence is shown as what it did (skuld.review_experiments: the feature and
#: purpose, the change, the success check, the runs per side, the screens the check was met at), and a unit's
#: experiments are each shown, no longer merged into its first (author, 24 Nov 2026)
VERSION = "4"
KIND = "aggregate-review"
MANIFEST, SAMPLE, KEY, REVIEWS, RECALL, SCORES, AGREEMENT = (
    "manifest.json",
    "sample.json",
    "key.json",
    "reviews.json",
    "recall.json",
    "scores.json",
    "agreement.json",
)
DOCUMENTS = "documents"
OVERALL = ("agree", "disagree", "partly", "unsure")  # partly: only derived from a unit's phrases
DECIDED = ("agree", "disagree", "partly")  # the verdicts the rates count
EVIDENCE = ("yes", "mostly", "partly", "no", "none_cited")
FOLLOWS = ("yes", "mostly", "partly", "no")
#: The phrases' answers that judge (the review tool also offers unsure, and fails, holds or unsure for a unit shown
#: blind; tools/calibration-review/server.js checks them)
JUDGED_PHRASE = ("specific", "not_specific")
#: What the reviewer is asked of a unit
ASK = "Do you agree with this aggregated concern as E states it, on the evidence it gives and the documents?"


class ReviewError(inputs.InputError):
    """A review that cannot be drawn or scored: a workspace without its aggregate, or changed files."""


def source(e: dict) -> str:
    """Where an evidence item comes from, in words a reviewer reads (the item's id and method are E's internals)."""
    method = e.get("method") or ""
    cid = str((e.get("citation") or {}).get("id") or "")
    dimension = (e.get("claim") or {}).get("dimension")
    if dimension == "O":
        return "the practice as observed"
    if dimension == "D":
        return "the provider's documents"
    if dimension == "E":
        return "a claim of E"
    if method.startswith("traffic of"):
        return "traffic as captured"
    if method.startswith("screen of"):
        return "a screen of the app"
    if method.startswith("hypothesis of the expectation stage"):
        return "E's expectation stage (its predicted purpose)"
    if method.startswith("application of"):
        return "the application's name and version"
    if cid.startswith("norms/"):
        return "a legal norm or guidance (corpus)"
    if cid.endswith((".yaml", ".yml", ".md")):
        return "documentation (corpus)"
    return e.get("kind") or "item"


def settings() -> dict:
    """config.json's `review`: units drawn per stratum, anchoring units, the seed, and whether a unit showing a screen
    with an empty description is passed over (D-45; the re-run's profiles)."""
    from skuld import config

    return {
        "per_run": 70,
        "floor": 3,
        "anchor": 0,
        "seed": 1,
        "exclude_empty_descriptions": False,
        **(config.load().get("review") or {}),
    }


# -- units ------------------------------------------------------------------------------------------------------------


def _uncited(text):
    """Text without the stage's citations, single or listed ([S1], [S1, S2, D3]); None where nothing is left."""
    if not isinstance(text, str):
        return text
    left = re.sub(r"\s*\[[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*\]", "", text).strip(" ,;")
    return left or None


def _purpose_text(purpose: dict) -> dict:
    """E's purpose as the reviewer reads it: without the stage's citations ([S1], [D2]), which point into a context
    the review does not show."""
    out = {k: _uncited(purpose.get(k)) for k in ("action", "object", "beneficiary", "context", "outcome")}
    return {k: v for k, v in {**out, "node": purpose.get("node")}.items() if v}


def _frame(root: Path):
    # only the frame is read: a corpus or exploration changed since does not keep a unit from being shown or counted
    return inputs.load_assessment(root, check=False).frame


def units(root: Path) -> tuple[list[dict], dict]:
    """The units of one workspace (its aggregated concerns, as the reviewer sees them) and what the recall pass shows
    of its application (its practices and declared purposes). A screen among a unit's evidence comes with its
    description and screenshot as stage 1 was given them (review_screens), and `_screens` holds them, for D-45 and the
    copy."""
    from skuld import review_experiments
    from skuld.review_screens import evidence_key, index, view

    screens = index(root)
    experiments = review_experiments.index(root)
    report = read_json(root / REPORT)
    agg = read_json(root / AGGREGATE)
    frame = _frame(root)
    concerns = {c["id"]: c for c in report["concerns"]}
    claims = {c["id"]: c for c in report.get("claims", [])}
    evidence = {e["id"]: e for e in report.get("evidence", [])}
    declarations = {d["id"]: d for d in report["subjects"].get("declarations", [])}
    practices_by_id = {p["id"]: p for p in report["subjects"].get("practices", [])}
    relations_by_id = {r["id"]: r for r in report.get("relations", [])}

    out = []
    for a in agg["aggregated_concerns"]:
        r = frame.requirement(a["requirement"])
        cited: dict[str, set] = defaultdict(set)
        members = []
        for m in a["members"]:
            c = concerns[m["concern"]]
            shown = {k: m[k] for k in ("subject", "data", "recipient", "purpose", "declared", "statement") if k in m}
            shown["concern"] = m["concern"]
            shown["reason"] = m["reason"]
            purpose = claims.get(c.get("purpose") or "", {}).get("purpose")
            if purpose:
                shown["purpose_stated"] = _purpose_text(purpose)
            alternatives = []
            for b in c.get("basis", []):
                cl = claims.get(b, {})
                if cl.get("type") == "alternative":
                    alternatives.append(
                        {
                            "alternative": cl.get("alternative"),
                            "status": cl.get("status"),
                            "level": cl.get("level"),
                            "component": (cl.get("component") or "").rsplit(".", 1)[-1] or None,
                            "reason": cl.get("reason"),
                        }
                    )
                for x in cl.get("supporting", []):
                    cited[x].add(m["concern"])
            if alternatives:
                shown["alternatives"] = alternatives
            if c.get("specified"):
                shown["specified"] = sorted({declarations[d].get("value") for d in c["specified"] if d in declarations})
            if c.get("silence"):
                shown["silence"] = c["silence"]
            if c["step"] == "declaration_contradicted":
                # (iii): the declaration as D read it, and each observed practice that contradicts it
                d = declarations.get(c["subject"], {})
                shown["declaration"] = {
                    k: d[k]
                    for k in ("channel", "type", "polarity", "data", "recipient", "value")
                    if d.get(k) is not None
                }
                shown["contradicted_by"] = [
                    {
                        "practice": rel["subject"],
                        "type": practices_by_id.get(rel["subject"], {}).get("claim_type"),
                        "data": practices_by_id.get(rel["subject"], {}).get("data"),
                        "recipient": (practices_by_id.get(rel["subject"], {}).get("party") or {}).get("owner")
                        or practices_by_id.get(rel["subject"], {}).get("recipient"),
                        "aspect": rel.get("aspect"),
                        **({"condition": rel["condition"]} if rel.get("condition") else {}),
                    }
                    for rel in (relations_by_id.get(i) for i in c.get("relations", []))
                    if rel
                ]
            for x in c.get("supporting", []):
                cited[x].add(m["concern"])
            members.append(shown)
        items, by_text = [], {}
        for x in sorted(cited, key=lambda i: int(i.split(":")[1]) if i.split(":")[1].isdigit() else 0):
            e = evidence.get(x)
            if not e or e.get("kind") == "claim" and not e.get("text"):
                continue
            # the same text under several items (cited in several samples) is shown once, citing all of them; an
            # experiment has no text: it is the same where it names the same comparison (before 0.12.33, every
            # experiment of a unit was shown as its first)
            compared = review_experiments.comparison_of(e)
            key = (source(e), e.get("text"), compared or e.get("method") if e.get("kind") == "run" else None)
            if key in by_text:
                by_text[key]["members"] = sorted(set(by_text[key]["members"]) | cited[x])
                by_text[key]["items"].append(x)
                continue
            by_text[key] = {
                "id": x,
                "items": [x],
                "kind": e.get("kind"),
                "source": source(e),
                "text": e.get("text"),
                "method": e.get("method"),
                "citation": e.get("citation"),
                "members": sorted(cited[x]),
                **view(screens.get(evidence_key(e))),
            }
            card = experiments.get(compared) if compared else None
            if card is not None:
                by_text[key]["experiment"] = review_experiments.view(card)
                by_text[key]["_shots"] = review_experiments.shots(card)
            items.append(by_text[key])
        out.append(
            {
                "aggregated": a["id"],
                "requirement": {
                    "id": r.id,
                    "title": r.title,
                    "principle": a["principle"],
                    "provisions": list(r.provisions),
                },
                "question": QUESTIONS.get(a["step"]),
                "step": a["step"],
                "label": a["label"],
                "status": a["status"],
                "tier": a["tier"],
                "uncertainty": a["uncertainty"],
                "disagreeing": a["disagreeing"],
                "condition": a.get("condition", []),
                "kind": "declared"
                if a["requirement"] == "purpose_specific"
                else "contradicted"
                if a["step"] == "declaration_contradicted"
                else "practice"
                if "data" in a["key"]
                else "other",
                "members": members,
                "evidence": items,
                "_concerns": [m["concern"] for m in a["members"]],
                # a member rests on an experiment: an item of an `ex:` channel supports it or a claim it rests on
                "_experiment": any(
                    str(evidence.get(x, {}).get("channel") or "").startswith("ex:")
                    for m in a["members"]
                    for x in [
                        *concerns[m["concern"]].get("supporting", []),
                        *(
                            y
                            for b in concerns[m["concern"]].get("basis", [])
                            for y in claims.get(b, {}).get("supporting", [])
                        ),
                    ]
                ),
                "_screens": [
                    screens[k] for k in {evidence_key(evidence[i]) for e in items for i in e["items"]} if k in screens
                ],
                # the screenshots of the experiments shown (copied, never counted for D-45: they are no stage-1 screens)
                "_shots": [x for e in items for x in e.pop("_shots", [])],
            }
        )
    practices = [
        {"id": p["id"], "type": p.get("claim_type"), "data": p.get("data"), "recipient": p.get("recipient")}
        for p in report["subjects"].get("practices", [])
    ]
    declared = sorted({(d.get("value") or "?") for d in declarations.values()})
    return out, {"practices": practices, "declared_nodes": declared}


# -- drawing ----------------------------------------------------------------------------------------------------------


def interleave(strata: list[list], rng: random.Random) -> list:
    """
    The drawn units of several strata in one review order such that every prefix of it covers the strata in proportion
    to their drawn sizes: each stratum's units are shuffled, and each next position goes to the stratum furthest behind
    its share (L·n/N less the units it has in the first L, for a stratum of n units in a sample of N), ties broken at
    random. A prefix of length L then holds L·n/N units of a stratum of n to within one (in every case the tests try;
    a stride schedule with random offsets, tried first, drifts by more where there are many strata). The order says
    nothing usable of a unit's run or stratum: which stratum takes a position depends only on the strata's drawn
    sizes, which the reviewer is not shown, and on random ties, and which of a stratum's units fills it is random.
    """
    queues = [rng.sample(list(members), len(members)) for members in strata if members]
    total = sum(map(len, queues))
    taken = [0] * len(queues)
    out = []
    for length in range(1, total + 1):
        open_ = [k for k, q in enumerate(queues) if taken[k] < len(q)]
        k = max(open_, key=lambda k: (length * len(queues[k]) / total - taken[k], rng.random()))
        out.append(queues[k][taken[k]])
        taken[k] += 1
    return out


def _stratum(run: str, u: dict) -> dict:
    out = {
        "run": run,
        "principle": u["requirement"]["principle"],
        "tier": u["tier"],
        "step": u["step"],
        "status": u["status"],
    }
    if "_by_experiment" in u:  # a draw with census_experiments: units resting on an experiment are a stratum apart
        out["experiment"] = u["_experiment"]
    return out


#: What a unit's stratum is made of
STRATUM = ("run", "principle", "tier", "step", "status")
#: What a stratum may also be made of, in a draw that asked for it (None in one that did not)
OPTIONAL = ("experiment",)


def _skey(s: dict) -> tuple:
    return tuple(s[k] for k in STRATUM) + tuple(s.get(k) for k in OPTIONAL)


def shares(populations: dict, n: int, floor: int = 1, census: frozenset = frozenset()) -> dict:
    """`n` units shared out over strata of these populations: a census stratum whole, every other at least `floor`
    (or all of a smaller one), the rest in proportion to the populations by largest remainder (ties to the larger
    population, then the key), never more than a stratum has. Fewer than n only if the strata hold fewer."""
    out = {k: (v if k in census else min(v, floor)) for k, v in populations.items()}
    rest = [k for k in populations if k not in census]
    left = n - sum(out.values())
    while left > 0:
        open_ = [k for k in rest if out[k] < populations[k]]
        if not open_:
            break
        total = sum(populations[k] for k in open_)
        quota = {k: left * populations[k] / total for k in open_}
        whole = {k: min(int(quota[k]), populations[k] - out[k]) for k in open_}
        if sum(whole.values()) == 0:
            k = max(open_, key=lambda k: (quota[k] - int(quota[k]), populations[k], k))
            whole[k] = 1
        for k, v in whole.items():
            out[k] += v
        left -= sum(whole.values())
    return out


def draw(
    folder: str | Path,
    workspaces: list[str | Path],
    per_stratum: int | None = None,
    seed: int | None = None,
    anchor: int | None = None,
    per_run: int | None = None,
    steps: list[str] | None = None,
    exclude_empty_descriptions: bool | None = None,
    tiers: list[str] | None = None,
    total_per_run: int | None = None,
    census_experiments: bool = False,
    floor: int | None = None,
) -> dict:
    """Draws the review's units from the workspaces' aggregates and fixes them in `folder`, which must not exist:
    per run in proportion to the strata (`per_run`, the default), or `per_stratum` in each. With `steps`, only units
    of those steps are drawn (e.g. a supplementary sample of a concern type added after the first draw); the
    manifest records them, and the strata's populations are of those steps alone. With `exclude_empty_descriptions`
    (D-45), a unit showing a screen whose description is empty by either model is passed over for the stratum's next
    eligible one in the seed's order (review_expectation.eligible_first), and the manifest lists those passed over.
    The screenshots the drawn units show are copied into the folder (review_screens).

    With `tiers`, only units of those tiers are drawn. With `census_experiments`, the units with a member resting on an
    experiment (an evidence item of an `ex:` channel) are a stratum apart, drawn whole. With `total_per_run`, each
    run's units number that many in all: its census strata whole, the rest shared out over its other strata in
    proportion, at least `floor` each (`shares`)."""
    from skuld.review_expectation import eligible_first
    from skuld.review_screens import copy_screenshots, empty

    folder = Path(folder)
    if folder.exists():
        raise ReviewError(f"{folder} exists: a drawn sample is fixed, draw a new one into another folder")
    s = settings()
    per_run = None if per_stratum else (per_run or s["per_run"])
    floor = s["floor"] if floor is None else floor
    seed = s["seed"] if seed is None else seed
    anchor = s["anchor"] if anchor is None else anchor
    exclude = s["exclude_empty_descriptions"] if exclude_empty_descriptions is None else exclude_empty_descriptions

    every, workspaces_out, apps = [], [], {}
    for n, root in enumerate(map(Path, workspaces), 1):
        for name in (REPORT, AGGREGATE):
            if not (root / name).is_file():
                raise ReviewError(f"{root}: no {name}; run `skuld assess` and `skuld aggregate` first")
        report = read_json(root / REPORT)
        app = f"{report['application']['package']}@{report['application']['version']}"
        run = root.resolve().parent.name
        wkey = f"w{n}"
        models = sorted({model_identity(c) for c in report["report"].get("components", []) if c["role"] == "model"})
        workspaces_out.append(
            {
                "key": wkey,
                "run": run,
                "models": models,
                "application": app,
                "workspace": str(root.resolve()),
                "assessment": inputs.digest(root / REPORT),
                "aggregate": inputs.digest(root / AGGREGATE),
            }
        )
        found, recall = units(root)
        if steps:
            found = [u for u in found if u["step"] in steps]
        if tiers:
            found = [u for u in found if u["tier"] in tiers]
        if census_experiments:
            for u in found:
                u["_by_experiment"] = True
        apps.setdefault(app, {"root": root, "recall": recall})
        for u in found:
            u["_run"], u["_workspace"], u["application"] = run, wkey, app
            every.append(u)
    runs = sorted({w["run"] for w in workspaces_out})
    # a run is one model configuration: its workspaces must name the same models, reasoning setting included (a
    # workspace that asked no model, as one where no practice was observed, names none and contradicts nothing)
    for run in runs:
        named = {tuple(w["models"]) for w in workspaces_out if w["run"] == run and w["models"]}
        if len(named) > 1:
            raise ReviewError(
                f"run {run}: its workspaces name different models ({'; '.join(map(', '.join, sorted(named)))})"
            )
    for app in apps:
        have = sorted(w["run"] for w in workspaces_out if w["application"] == app)
        if len(set(have)) != len(have):
            raise ReviewError(f"{app}: two workspaces of the same run ({', '.join(have)})")

    rng = random.Random(seed)
    strata = defaultdict(list)
    for u in every:
        strata[_skey(_stratum(u["_run"], u))].append(u)
    if total_per_run:
        # shared out over what may be drawn: with exclude_empty_descriptions, a stratum's eligible units (D-45), so
        # that a run still gets its total and a census stratum is every eligible unit of it
        sizes = {}
        for run in runs:
            mine = {
                k: sum(1 for u in v if not exclude or not empty(u["_screens"]))
                for k, v in strata.items()
                if k[0] == run
            }
            census = frozenset(k for k in mine if census_experiments and k[len(STRATUM)] is True)
            sizes |= shares(mine, total_per_run, floor, census)
    else:
        sizes = {k: allocation(strata, k, per_stratum, per_run, floor) for k in strata}
    chosen = []
    passed_over: list = []

    def ok(u):
        return not empty(u["_screens"])

    for k in sorted(strata):
        members = strata[k]
        if exclude:
            chosen.append(eligible_first(members, sizes[k], rng, ok, passed_over))
        else:
            chosen.append(members if len(members) <= sizes[k] else rng.sample(members, sizes[k]))
    # every prefix covers the strata in proportion, so that a partial return is a smaller stratified sample
    drawn = interleave(chosen, rng)
    # a unit of declared purposes is judged blind phrase by phrase (blind_phrases), not by an anchoring decision
    supported = [u for u in drawn if u["status"] == "supported" and u["kind"] != "declared"]
    anchored = {id(u) for u in rng.sample(supported, min(anchor, len(supported)))}

    folder.mkdir(parents=True)
    screenshots = copy_screenshots(folder, [e for u in drawn for e in [*u["_screens"], *u.get("_shots", [])]])
    if steps:  # a supplementary sample shows only the applications it has units of
        apps = {app: x for app, x in apps.items() if any(u["application"] == app for u in drawn)}
    applications = {}
    for i, (app, x) in enumerate(sorted(apps.items()), 1):
        applications[app] = {
            "documents": copy_documents(Path(x["root"]), folder / DOCUMENTS / f"app{i}"),
            **x["recall"],
        }
    items, key = [], {}
    for n, u in enumerate(drawn, 1):
        iid = f"r{n:03d}"
        key[iid] = {
            "run": u["_run"],
            "workspace": u["_workspace"],
            "aggregated": u["aggregated"],
            "concerns": u["_concerns"],
            "members": len(u["members"]),
            "stratum": _stratum(u["_run"], u),
        }
        item = {k: v for k, v in u.items() if not k.startswith("_") and k != "aggregated"}
        item["id"] = iid
        item["ask"] = ASK
        if id(u) in anchored:
            item["blind_first"] = True
        if u["kind"] == "declared":
            item["blind_phrases"] = [{"concern": m["concern"], "statement": m.get("statement")} for m in u["members"]]
        items.append(item)
    from skuld.review_expectation import vocabularies  # the tool shows a unit's data types and purposes in them

    write_json(
        folder / SAMPLE,
        {
            "kind": KIND,
            "items": items,
            "applications": applications,
            "vocabularies": vocabularies(),
            # the criteria's values and the reasons an answer short of yes names, as the tool shows and checks them
            "questions": {
                "criteria": {"evidence": list(EVIDENCE), "follows": list(FOLLOWS)},
                "reasons": review_reasons.questions(review_reasons.CONCERNS),
            },
        },
    )
    write_json(folder / KEY, key)
    manifest = {
        "id": folder.name,
        "kind": KIND,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": skuld.__version__,
        "method": {"id": "skuld.review", "version": VERSION},
        "seed": seed,
        "allocation": {"total_per_run": total_per_run, "floor": floor, "census_experiments": census_experiments}
        if total_per_run
        else {"per_stratum": per_stratum}
        if per_stratum
        else {"proportional": True, "per_run": per_run, "floor": floor},
        **({"tiers": sorted(tiers)} if tiers else {}),
        "anchor": len(anchored),
        **({"steps": sorted(steps)} if steps else {}),
        # D-45: the units passed over because a screen they show has an empty description, by model
        **(
            {
                "empty_descriptions": {
                    "excluded": True,
                    "passed_over": [
                        {
                            "run": u["_run"],
                            "application": u["application"],
                            "aggregated": u["aggregated"],
                            "stratum": _stratum(u["_run"], u),
                            "empty_by": empty(u["_screens"]),
                        }
                        for u in passed_over
                    ],
                    "ineligible": sum(1 for u in every if not ok(u)),
                    "rule": "a unit showing a screen whose description is empty by either model among its evidence is "
                    "passed over",
                }
            }
            if exclude
            else {}
        ),
        "screenshots": screenshots,
        "runs": runs,
        "run_models": {
            run: next((w["models"] for w in workspaces_out if w["run"] == run and w["models"]), []) for run in runs
        },
        "workspaces": workspaces_out,
        "strata": [
            {
                **_stratum(strata[k][0]["_run"], strata[k][0]),
                "population": len(strata[k]),
                "drawn": sum(1 for u in drawn if _skey(_stratum(u["_run"], u)) == k),
            }
            for k in sorted(strata)
        ],
        "files": {SAMPLE: file_sha256(folder / SAMPLE), KEY: file_sha256(folder / KEY)},
    }
    write_json(folder / MANIFEST, manifest)
    return manifest


def allocation(strata: dict, k: tuple, per_stratum: int | None, per_run: int | None, floor: int) -> int:
    """How many units stratum k gets: per_stratum, or its share of its run's per_run (at least floor)."""
    size = len(strata[k])
    if per_stratum:
        return min(size, per_stratum)
    run_total = sum(len(v) for kk, v in strata.items() if kk[0] == k[0])
    return min(size, max(floor, round(per_run * size / run_total)))


# -- scores -----------------------------------------------------------------------------------------------------------


def _given(*paths: str | Path) -> list[dict]:
    """The reviews in the files a reviewer returned, which must exist: a mistyped path would otherwise agree on
    nothing and seed an empty reviews.json."""
    for path in paths:
        if not Path(path).is_file():
            raise ReviewError(f"{path}: no such reviews file")
    return [decisions(Path(path)) for path in paths]


def _member_agreement(item: dict, review: dict) -> tuple[float, float] | None:
    """A unit's agreement weighted by its members: (agreeing members, judged members). For a unit of declared
    purposes with phrases judged, a phrase agrees where its judgment matches E's (supported: not specific); otherwise
    the overall judgment counts for every member."""
    phrases = review.get("phrases") or {}
    if item["kind"] == "declared" and phrases and item["status"] == "supported":
        judged = [v for v in phrases.values() if v in JUDGED_PHRASE]
        return (sum(v == "not_specific" for v in judged), len(judged)) if judged else None
    if review.get("overall") in ("agree", "disagree"):  # a partly unit has its phrases, above
        n = len(item["members"])
        return (n if review["overall"] == "agree" else 0, n)
    return None


def _rate(k, n):
    return {"rate": round(k / n, 3) if n else None, "interval": [round(x, 3) for x in wilson(k, n)] if n else None}


#: What a partial return's scores stand for, said in scores.json beside the strata it reached
COVERAGE_NOTE = (
    "Each stratum is weighted by its population over the units judged in it. A stratum with no unit judged has no rate "
    "and drops out of the weighted rates, which then stand only for the strata reached (population_covered: their "
    "share of the estimate's population); the strata listed under not_reviewed and without_rate are not represented."
)


def coverage(strata: list[dict], fields: tuple[str, ...], units: int, reviewed: int) -> dict:
    """Which strata a return reached: those with a unit reviewed, those with a unit judged (counted in the rates), and
    the strata without either, each named by its `fields`; `strata` are the scores' strata, each with its
    `population`, `drawn`, `reviewed` and `judged`."""
    keep = ("population", "drawn")
    return {
        "partial": reviewed < units,
        "units": units,
        "reviewed": reviewed,
        "strata": len(strata),
        "strata_reviewed": sum(1 for s in strata if s["reviewed"]),
        "strata_judged": sum(1 for s in strata if s["judged"]),
        "not_reviewed": [{k: s[k] for k in (*fields, *keep)} for s in strata if not s["reviewed"]],
        "without_rate": [{k: s[k] for k in (*fields, *keep)} for s in strata if s["reviewed"] and not s["judged"]],
        "note": COVERAGE_NOTE,
    }


def coverage_lines(c: dict) -> list[str]:
    """A score's coverage (`coverage`) as the command prints it: what was reviewed and, for each stratum not reached
    or without a rate, its name, units drawn and population, with what the rates then stand for."""
    out = [
        f"{c['reviewed']} of {c['units']} units reviewed{' (a partial return)' if c['partial'] else ''}; "
        f"{c['strata_reviewed']} of {c['strata']} strata reached, {c['strata_judged']} with a unit judged"
    ]
    for label, strata in (("not reviewed", c["not_reviewed"]), ("reviewed, none judged", c["without_rate"])):
        for st in strata:
            name = " ".join(str(v) for k, v in st.items() if k not in ("population", "drawn"))
            out.append(f"  {label}: {name} ({st['drawn']} drawn of {st['population']})")
    if c["not_reviewed"] or c["without_rate"]:
        out.append(f"  {c['note']}")
    return out


def _blind_phrases(items: dict, key: dict, reviews: dict) -> dict:
    """
    The phrases of declared purposes judged blind (before E's output was shown) against E, beside the same phrases
    judged after: per run and in all, over the units E holds not specific (supported), where a phrase agrees with E if
    judged not specific; unsure is left out. Unweighted, with Wilson intervals. `changed` counts the phrases judged
    differently after E's output was shown, `towards_e` those changed to not specific.
    """
    out = {"units": 0, "units_judged_blind": 0, "units_not_supported": 0, "runs": {}}
    totals = defaultdict(lambda: {"bk": 0, "bn": 0, "k": 0, "n": 0, "paired": 0, "changed": 0, "towards_e": 0})
    for iid, item in items.items():
        if not item.get("blind_phrases") or iid not in key:
            continue
        out["units"] += 1
        r = reviews.get(iid) or {}
        blind = (r.get("blind_phrases") or {}).get("phrases") or {}
        if not blind:
            continue
        out["units_judged_blind"] += 1
        if item["status"] != "supported":
            out["units_not_supported"] += 1  # E does not hold its phrases not specific: no agreement to count
            continue
        after = r.get("phrases") or {}
        for p in item["blind_phrases"]:
            b, a = blind.get(p["concern"]), after.get(p["concern"])
            for scope in (key[iid]["stratum"]["run"], "all"):
                t = totals[scope]
                if b in JUDGED_PHRASE:
                    t["bk"] += b == "not_specific"
                    t["bn"] += 1
                if a in JUDGED_PHRASE:
                    t["k"] += a == "not_specific"
                    t["n"] += 1
                if b in JUDGED_PHRASE and a in JUDGED_PHRASE:
                    t["paired"] += 1
                    t["changed"] += a != b
                    t["towards_e"] += a != b and a == "not_specific"
    for scope, t in sorted(totals.items()):
        blind_rate, after_rate = _rate(t["bk"], t["bn"]), _rate(t["k"], t["n"])
        out["runs"][scope] = {
            "blind": {"phrases": t["bn"], **blind_rate},
            "non_blind": {"phrases": t["n"], **after_rate},
            "paired": t["paired"],
            "changed": t["changed"],
            "towards_e": t["towards_e"],
            "difference": round(after_rate["rate"] - blind_rate["rate"], 3) if t["bn"] and t["n"] else None,
        }
    return out


def score(folder: str | Path) -> dict:
    """Agreement with E's output from one reviewer's judgments: per stratum, and per run, principle and step weighted
    by the strata's populations; per unit and per member; the criteria; the anchoring units; the phrases of declared
    purposes judged blind beside the same judged after; the recall pass; and which strata a partial return reached
    (per stratum drawn, reviewed and judged)."""
    folder = Path(folder)
    manifest = read_json(folder / MANIFEST)
    for name, sha in manifest["files"].items():
        if file_sha256(folder / name) != sha:
            raise ReviewError(f"{name} is not the file drawn (digest differs)")
    key = read_json(folder / KEY)
    items = {i["id"]: i for i in read_json(folder / SAMPLE)["items"]}
    reviews = decisions(folder / REVIEWS, missing_ok=True)
    # a judged unit stands for its stratum's population over the units judged in it (not over those drawn), so that a
    # stratum with unsure or not yet reviewed units counts for its whole population
    judged, reviewed = defaultdict(int), defaultdict(int)
    for iid, entry in key.items():
        if (reviews.get(iid) or {}).get("overall") in DECIDED:
            judged[_skey(entry["stratum"])] += 1
        if (reviews.get(iid) or {}).get("overall") in OVERALL:
            reviewed[_skey(entry["stratum"])] += 1
    weight = {_skey(s): (s["population"] / judged[_skey(s)] if judged[_skey(s)] else 0.0) for s in manifest["strata"]}

    by_stratum = defaultdict(
        lambda: {"agree": 0, "disagree": 0, "partly": 0, "unsure": 0, "members_agree": 0.0, "members": 0.0}
    )
    criteria = defaultdict(
        lambda: {"evidence": defaultdict(int), "follows": defaultdict(int), "reasons": defaultdict(int), "other": []}
    )
    totals = defaultdict(lambda: {"k": 0, "n": 0, "wk": 0.0, "wn": 0.0, "mk": 0.0, "mn": 0.0})
    for iid, entry in key.items():
        r = reviews.get(iid) or {}
        s = entry["stratum"]
        sk = _skey(s)
        if r.get("overall") in OVERALL:
            by_stratum[sk][r["overall"]] += 1
        for c in ("evidence", "follows"):
            if r.get(c):
                t = criteria[(s["run"], s["principle"], s["step"])]
                t[c][r[c]] += 1
                # its reasons as <criterion>:<answer>:<reason>, the written ones listed
                counts = defaultdict(int)
                review_reasons.tally(c, r, review_reasons.CONCERNS, counts, t["other"], {"id": iid, "criterion": c})
                for k, n in counts.items():
                    t["reasons"][f"{c}:{k}"] += n
        m = _member_agreement(items[iid], r)
        if r.get("overall") in DECIDED:
            if m:
                by_stratum[sk]["members_agree"] += m[0]
                by_stratum[sk]["members"] += m[1]
            t = totals[(s["run"], s["principle"], s["step"], s["status"])]
            agreed = r["overall"] == "agree"
            t["k"] += agreed
            t["n"] += 1
            t["wk"] += weight[sk] * agreed
            t["wn"] += weight[sk]
            if m:
                t["mk"] += weight[sk] * m[0]
                t["mn"] += weight[sk] * m[1]

    strata = []
    for s in manifest["strata"]:
        c = by_stratum[_skey(s)]
        n = c["agree"] + c["disagree"] + c["partly"]
        strata.append(
            {
                **s,
                "reviewed": reviewed[_skey(s)],
                "judged": judged[_skey(s)],
                "agree": c["agree"],
                "disagree": c["disagree"],
                "partly": c["partly"],
                "unsure": c["unsure"],
                **_rate(c["agree"], n),
                "members_rate": round(c["members_agree"] / c["members"], 3) if c["members"] else None,
            }
        )

    anchoring = {"units": 0, "blind_fails": 0, "blind_decided": 0, "agree": 0, "decided": 0}
    for iid, item in items.items():
        if not item.get("blind_first"):
            continue
        r = reviews.get(iid) or {}
        anchoring["units"] += 1
        blind = (r.get("blind") or {}).get("decision")
        if blind in ("fails", "holds"):
            anchoring["blind_decided"] += 1
            anchoring["blind_fails"] += blind == "fails"
        if r.get("overall") in DECIDED:
            anchoring["decided"] += 1
            anchoring["agree"] += r["overall"] == "agree"
    if anchoring["blind_decided"] and anchoring["decided"]:
        anchoring["blind_rate"] = round(anchoring["blind_fails"] / anchoring["blind_decided"], 3)
        anchoring["non_blind_rate"] = round(anchoring["agree"] / anchoring["decided"], 3)
        anchoring["difference"] = round(anchoring["non_blind_rate"] - anchoring["blind_rate"], 3)

    # per estimate (run, principle, step, status), the share of its strata's population in strata with a unit judged
    population, covered = defaultdict(int), defaultdict(int)
    for s in manifest["strata"]:
        e = (s["run"], s["principle"], s["step"], s["status"])
        population[e] += s["population"]
        covered[e] += s["population"] if judged[_skey(s)] else 0

    recall = decisions(folder / RECALL, missing_ok=True)
    misses = [
        {"application": app, **m} for app, entry in sorted(recall.items()) for m in (entry or {}).get("missed", [])
    ]
    out = {
        "review": manifest["id"],
        "scored": datetime.now(UTC).isoformat(timespec="seconds"),
        "measure": "agreement with E's output (non-blind; not precision)",
        "items": len(key),
        "judged": sum(1 for iid in key if (reviews.get(iid) or {}).get("overall") in DECIDED),
        "unsure": sum(1 for iid in key if (reviews.get(iid) or {}).get("overall") == "unsure"),
        "strata": strata,
        "estimates": [
            {
                "run": run,
                "principle": p,
                "step": step,
                "status": status,
                "units": t["n"],
                "rate": round(t["wk"] / t["wn"], 3) if t["wn"] else None,
                # Wilson's interval is of the unweighted rate, given beside it; the weighted rate can lie outside it
                "unweighted_rate": _rate(t["k"], t["n"])["rate"],
                "interval": _rate(t["k"], t["n"])["interval"],
                "members_rate": round(t["mk"] / t["mn"], 3) if t["mn"] else None,
                "population_covered": round(covered[(run, p, step, status)] / population[(run, p, step, status)], 3)
                if population[(run, p, step, status)]
                else None,
            }
            for (run, p, step, status), t in sorted(totals.items())
        ],
        "criteria": [
            {
                "run": run,
                "principle": p,
                "step": step,
                **{c: dict(v[c]) for c in ("evidence", "follows")},
                **({"reasons": dict(sorted(v["reasons"].items()))} if v["reasons"] else {}),
                **({"other_reasons": v["other"]} if v["other"] else {}),
            }
            for (run, p, step), v in sorted(criteria.items())
        ],
        "anchoring": anchoring,
        "blind_phrases": _blind_phrases(items, key, reviews),
        "coverage": coverage(strata, STRATUM, len(key), sum(reviewed.values())),
        "recall": {
            "applications_done": sum(1 for e in recall.values() if (e or {}).get("done")),
            "applications": len(read_json(folder / SAMPLE)["applications"]),
            "missed": misses,
        },
    }
    write_json(folder / SCORES, out)
    return out


# -- two reviewers ----------------------------------------------------------------------------------------------------


def agree(folder: str | Path, first: str | Path, second: str | Path) -> dict:
    """Two reviewers' independent judgments on one sample: Cohen's κ for the overall judgment, each criterion and the
    phrases, overall and per principle and run; the units they disagree on overall, for adjudication. κ measures
    reliability, not validity: both reviewers see the same output and share its anchor. Where the sample has no
    reviews.json yet, it is seeded with the units both judged alike, so that the review tool's next open unit is the
    next to adjudicate."""
    folder = Path(folder)
    key = read_json(folder / KEY)
    a, b = _given(first, second)

    def pairs(field, ids, values):
        return [
            (a[i][field], b[i][field])
            for i in ids
            if a.get(i, {}).get(field) in values and b.get(i, {}).get(field) in values
        ]

    def kappas(ids):
        out = {}
        for field, values in (("overall", OVERALL), ("evidence", EVIDENCE), ("follows", FOLLOWS)):
            p = pairs(field, ids, values)
            k = kappa(p)
            out[field] = {
                "items": len(p),
                "agreed": sum(x == y for x, y in p),
                "kappa": round(k, 3) if k is not None else None,
            }
            if field in review_reasons.ORDERED:  # a criterion: also weighted over yes, mostly, partly, no
                from skuld.review_expectation import weighted_kappa

                w = weighted_kappa(p, review_reasons.ORDERED[field])
                out[field]["weighted_kappa"] = round(w, 3) if w is not None else None
        binary = [x for x in pairs("overall", ids, OVERALL) if "unsure" not in x]
        k = kappa(binary)
        # agree, partly and disagree: the units neither reviewer was unsure of
        out["overall_without_unsure"] = {"items": len(binary), "kappa": round(k, 3) if k is not None else None}
        phrases = [
            (a[i]["phrases"][c], b[i]["phrases"][c])
            for i in ids
            for c in (a.get(i, {}).get("phrases") or {})
            if (b.get(i, {}).get("phrases") or {}).get(c) in JUDGED_PHRASE and a[i]["phrases"][c] in JUDGED_PHRASE
        ]
        k = kappa(phrases)
        out["phrases"] = {"items": len(phrases), "kappa": round(k, 3) if k is not None else None}

        def blind(r):
            return (r.get("blind_phrases") or {}).get("phrases") or {}

        judged_blind = [
            (blind(a[i])[c], blind(b[i])[c])
            for i in ids
            for c in blind(a.get(i, {}))
            if blind(b.get(i, {})).get(c) in JUDGED_PHRASE and blind(a[i])[c] in JUDGED_PHRASE
        ]
        k = kappa(judged_blind)
        out["blind_phrases"] = {"items": len(judged_blind), "kappa": round(k, 3) if k is not None else None}
        return out

    ids = sorted(key)
    principles = sorted({key[i]["stratum"]["principle"] for i in ids})
    runs = sorted({key[i]["stratum"]["run"] for i in ids})
    both = [i for i in ids if a.get(i, {}).get("overall") in OVERALL and b.get(i, {}).get("overall") in OVERALL]
    out = {
        "review": folder.name,
        "compared": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviews": [str(Path(first)), str(Path(second))],
        "note": "kappa measures reliability, not validity: both reviewers see E's output and share its anchor",
        "undecided": {
            "first": sum(a.get(i, {}).get("overall") not in OVERALL for i in ids),
            "second": sum(b.get(i, {}).get("overall") not in OVERALL for i in ids),
        },
        "overall": kappas(ids),
        "principles": {p: kappas([i for i in ids if key[i]["stratum"]["principle"] == p]) for p in principles},
        "runs": {r: kappas([i for i in ids if key[i]["stratum"]["run"] == r]) for r in runs},
        "disagreements": [{"id": i, "first": a[i], "second": b[i]} for i in both if a[i]["overall"] != b[i]["overall"]],
    }
    write_json(folder / AGREEMENT, out)
    if not (folder / REVIEWS).exists():
        seeded = {}
        for i in both:
            if a[i]["overall"] == b[i]["overall"]:
                merged = {
                    k: a[i][k]
                    for k in ("evidence", "follows", "phrases", "blind")
                    if k in a[i] and a[i][k] == b[i].get(k)
                }
                # phrases judged alike blind are kept (with the first reviewer's time), so that the adjudicator is not
                # asked them blind again
                blind = (a[i].get("blind_phrases") or {}).get("phrases")
                if blind and blind == (b[i].get("blind_phrases") or {}).get("phrases"):
                    merged["blind_phrases"] = a[i]["blind_phrases"]
                notes = " | ".join(n for n in (a[i].get("note"), b[i].get("note")) if n)
                seeded[i] = {"overall": a[i]["overall"], **merged, "note": notes, "reviewed": out["compared"]}
        write_json(folder / REVIEWS, seeded)
        out["seeded"] = len(seeded)
    return out
