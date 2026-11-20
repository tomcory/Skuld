"""
skuld review exclude: a drawn sample without the units of applications withdrawn from the study after the draw.

The reviewers keep the sample they were given; the units of a withdrawn application are taken out afterwards. Within a
stratum, the units the draw picked that do not belong to the withdrawn application are a simple random sample of the
stratum's other units, so the derived sample keeps the draw's design; for a stage-1 draw capped per application
(`--per-app`), the withdrawal also frees the share the cap gave the application, which the derived sample does not
redraw, so its strata hold no more than they did and the cap's lean towards the average over applications stays. Each stratum's population loses the withdrawn
application's units, which are counted again from its workspaces. Those workspaces are given explicitly, since they have
usually been moved out of the run, and are matched to the draw's records by their assessment's digest. The derived folder holds
sample.json, key.json and manifest.json without those units, and, where present, reviews.json and recall.json without
them. Unit ids are kept, so a reviewer's reviews.json of the original sample can be read against the derived key
(`skuld review agree`, `expect-agree`) unchanged. The manifest records what it was derived from and why (`derived`).
Applies to both kinds of sample: aggregated concerns (`skuld.review`) and stage-1 practices (`skuld.review_expectation`).

    skuld review exclude reviews/concerns-2026-11-13 reviews/concerns-2026-11-13-19apps \\
        <withdrawn workspaces, one per run> --application ru.yandex.yandexmaps --reason "…"
"""

import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from skuld import inputs, review
from skuld import review_expectation as rx
from skuld.aggregate import REPORT as AGGREGATE
from skuld.assess import REPORT
from skuld.calibrate import file_sha256, read_json, write_json

VERSION = "1"
AUTHOR = {"id": "skuld.review_exclude", "version": VERSION}


class ExcludeError(inputs.InputError):
    """A sample that cannot be derived: changed files, a missing or changed workspace, or nothing to exclude."""


def _package(app: str) -> str:
    return app.rsplit("@", 1)[0]


def _matches(app: str, wanted: list[str]) -> bool:
    return any(app == w or _package(app) == w for w in wanted)


def _populations(kind: str, workspace: dict, root: Path, steps: list[str] | None = None) -> Counter:
    """Units per stratum key of one withdrawn workspace, counted as the draw counted them (only its steps, for a draw
    limited to some)."""
    run = workspace["run"]
    if kind == review.KIND:
        found, _ = review.units(root)
        strata = [review._stratum(run, u) for u in found]
        return Counter(review._skey(s) for s in strata if not steps or s["step"] in steps)
    return Counter(rx._skey({"run": run, "role": u["_role"], "status": u["_status"]}) for u in rx.units(root))


def exclude(folder, out, workspaces, applications: list[str], reason: str) -> dict:
    folder, out = Path(folder), Path(out)
    if out.exists():
        raise ExcludeError(f"{out} exists: a derived sample is written once, into a new folder")
    if not applications:
        raise ExcludeError("name the withdrawn applications (--application)")
    manifest = read_json(folder / review.MANIFEST)
    for name, sha in manifest["files"].items():
        if file_sha256(folder / name) != sha:
            raise ExcludeError(f"{folder / name} is not the file drawn (digest differs)")
    kind = manifest["kind"]
    if kind not in (review.KIND, rx.KIND):
        raise ExcludeError(f"{folder}: unknown kind of sample {kind!r}")
    skey = review._skey if kind == review.KIND else rx._skey

    gone = [w for w in manifest["workspaces"] if _matches(w["application"], applications)]
    if not gone:
        raise ExcludeError(f"{folder}: no workspace of {', '.join(applications)} in the draw")
    # the withdrawn workspaces, as given (usually moved out of their run), matched to the draw's records by digest
    given = {inputs.digest(Path(root) / REPORT): Path(root) for root in workspaces}
    removed_population = Counter()
    for w in gone:
        root = given.get(w["assessment"])
        if root is None:
            raise ExcludeError(
                f"give the workspace of {w['application']} in run {w['run']}, as drawn from (it counts the population)"
            )
        if "aggregate" in w and inputs.digest(root / AGGREGATE) != w["aggregate"]:
            raise ExcludeError(f"{root}: its aggregate is not the one drawn from (digest differs)")
        removed_population += _populations(kind, w, root, manifest.get("steps"))

    gone_keys = {w["key"] for w in gone}
    gone_apps = {w["application"] for w in gone}
    key = read_json(folder / review.KEY)
    sample = read_json(folder / review.SAMPLE)
    dropped = sorted(i for i, e in key.items() if e["workspace"] in gone_keys)
    removed_drawn = Counter(skey(key[i]["stratum"]) for i in dropped)

    strata = []
    for s in manifest["strata"]:
        k = skey(s)
        population = s["population"] - removed_population.get(k, 0)
        drawn = s["drawn"] - removed_drawn.get(k, 0)
        if population < 0 or drawn < 0 or drawn > population:
            raise ExcludeError(f"stratum {k}: the withdrawn workspaces do not count as the draw did")
        if population:
            strata.append({**s, "population": population, "drawn": drawn})
    unknown = set(removed_population) - {skey(s) for s in manifest["strata"]}
    if unknown:
        raise ExcludeError(f"the withdrawn workspaces have units in strata the draw did not have: {sorted(unknown)}")

    out.mkdir(parents=True)
    keep = set(key) - set(dropped)
    new_sample = {**sample, "items": [i for i in sample["items"] if i["id"] in keep]}
    if "applications" in new_sample:  # concern samples: per application its documents and recall view
        new_sample["applications"] = {a: v for a, v in sample["applications"].items() if a not in gone_apps}
        if (folder / review.DOCUMENTS).is_dir():
            used = {
                Path(d).parts[1]
                for v in new_sample["applications"].values()
                for d in _document_paths(v)
                if len(Path(d).parts) > 1
            }
            for sub in (folder / review.DOCUMENTS).iterdir():
                if sub.name in used:
                    shutil.copytree(sub, out / review.DOCUMENTS / sub.name)
    write_json(out / review.SAMPLE, new_sample)
    write_json(out / review.KEY, {i: e for i, e in key.items() if i in keep})
    for name in (review.REVIEWS, review.RECALL):
        if (folder / name).is_file():
            data = read_json(folder / name)
            if name == review.REVIEWS:
                data = {i: v for i, v in data.items() if i not in dropped}
            else:
                data = {a: v for a, v in data.items() if a not in gone_apps}
            write_json(out / name, data)

    derived = {
        **{k: v for k, v in manifest.items() if k not in ("files", "strata", "workspaces")},
        **({"anchor": sum(1 for i in new_sample["items"] if i.get("blind_first"))} if "anchor" in manifest else {}),
        "id": out.name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "workspaces": [w for w in manifest["workspaces"] if w["key"] not in gone_keys],
        **(
            {"applications": [x for x in manifest["applications"] if x.get("application") not in gone_apps]}
            if "applications" in manifest
            else {}
        ),
        "strata": strata,
        "derived": {
            "by": AUTHOR,
            "from": manifest["id"],
            "manifest": file_sha256(folder / review.MANIFEST),
            "excluded": sorted(gone_apps),
            "workspaces": [w["key"] for w in gone],
            "units": dropped,
            "reason": reason,
        },
        "files": {review.SAMPLE: file_sha256(out / review.SAMPLE), review.KEY: file_sha256(out / review.KEY)},
    }
    write_json(out / review.MANIFEST, derived)
    return derived


def _document_paths(entry: dict) -> list[str]:
    """The document paths an application's entry names, wherever they sit in it."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith(review.DOCUMENTS + "/"):
            found.append(o)

    walk(entry.get("documents"))
    return found
