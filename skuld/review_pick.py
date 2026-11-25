"""
skuld review pick: a sample of chosen units of a drawn sample (0.12.38, 25 Nov 2026), for the reviewers' calibration
round (author, 25 Nov 2026): a few units per stage that every reviewer judges alone before the review samples, whose
answers are then compared and discussed, so that the reviewers start the review with one reading of the codebook.

The units are chosen, not drawn: each to cover a case the codebook rules on and reviewers are likely to read
differently (`--why`, recorded per unit). They are chosen from a sample drawn as the review samples are (`skuld review
draw`, `expect-draw`) with another seed, and none may be a unit of a sample named with `--avoid` (the review samples):
a unit judged in calibration and discussed would be judged again, anchored, in the review. A unit is the same where its
workspace's assessment is the same (its digest) and it names the same practice (stage 1) or aggregated concern.

The derived folder holds sample.json, key.json and manifest.json with the chosen units only, renumbered (`<prefix>01`
…, so that they are never mistaken for a review sample's units), the screenshots they show and, for a sample of
aggregated concerns, the documents of their applications. The manifest records what it was derived from, each unit's
former id and why it was chosen, and the samples avoided. Applies to both kinds of sample.

    skuld review pick reviews/candidates-stage1 reviews/calibration-stage1 --items x004 x017 … \\
        --why "x004=beneficiary of ad delivery" … --avoid reviews/stage1-2026-11-24 --prefix c
"""

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import skuld
from skuld import inputs, review
from skuld import review_expectation as rx
from skuld.calibrate import file_sha256, read_json, write_json

VERSION = "1"
AUTHOR = {"id": "skuld.review_pick", "version": VERSION}
SHOT = re.compile(r"screenshots/[0-9a-f]{64}\.[a-z]+")


class PickError(inputs.InputError):
    """Units that cannot be picked: a changed sample, an unknown unit, or a unit of a sample to avoid."""


def _checked(folder: Path) -> dict:
    manifest = read_json(folder / review.MANIFEST)
    for name, sha in manifest["files"].items():
        if file_sha256(folder / name) != sha:
            raise PickError(f"{folder / name} is not the file drawn (digest differs)")
    return manifest


def identities(folder: Path) -> dict[tuple, str]:
    """Per unit of a sample, its identity (the workspace's assessment digest, and the practice or aggregated concern)
    and its id."""
    folder = Path(folder)
    manifest = _checked(folder)
    digest = {w["key"]: w["assessment"] for w in manifest["workspaces"]}
    out = {}
    for iid, k in read_json(folder / review.KEY).items():
        out[(digest[k["workspace"]], k.get("practice") or k.get("aggregated"))] = iid
    return out


def pick(
    source: str | Path,
    dest: str | Path,
    items: list[str],
    why: dict[str, str],
    avoid: list[str | Path] = (),
    prefix: str = "c",
    reason: str = "calibration round",
) -> dict:
    """Writes the sample of the chosen units of `source` to `dest` (see the module's docstring); returns its manifest."""
    source, dest = Path(source), Path(dest)
    if dest.exists():
        raise PickError(f"{dest} exists")
    if len(set(items)) != len(items) or not items:
        raise PickError("name each unit once, at least one")
    manifest = _checked(source)
    sample = read_json(source / review.SAMPLE)
    key = read_json(source / review.KEY)
    by_id = {i["id"]: i for i in sample["items"]}
    unknown = [i for i in items if i not in by_id]
    if unknown:
        raise PickError(f"no such units in {source}: {', '.join(unknown)}")
    missing = [i for i in items if not str(why.get(i) or "").strip()]
    if missing:
        raise PickError(f"say why each unit is chosen (--why): {', '.join(missing)}")
    mine = {v: k for k, v in identities(source).items()}
    avoided = []
    for other in avoid:
        theirs = identities(Path(other))
        clash = [f"{i} (= {theirs[mine[i]]} of {other})" for i in items if mine[i] in theirs]
        if clash:
            raise PickError(f"units of a sample to avoid: {', '.join(clash)}")
        avoided.append({"sample": str(other), "sha256": read_json(Path(other) / review.MANIFEST)["files"]})

    renamed = {old: f"{prefix}{n:02d}" for n, old in enumerate(items, 1)}
    chosen = []
    for old in items:
        item = json.loads(json.dumps(by_id[old]))
        item["id"] = renamed[old]
        item.pop("blind_first", None)  # a calibration unit is judged with E's output; the anchoring is the review's
        chosen.append(item)
    out_sample = {**sample, "items": chosen}
    apps = sorted({i["application"] for i in chosen})
    if "applications" in sample:  # aggregated concerns: their applications' practices, declarations and documents
        out_sample["applications"] = {a: sample["applications"][a] for a in apps}
    out_key = {renamed[old]: key[old] for old in items}

    dest.mkdir(parents=True)
    text = json.dumps(out_sample, ensure_ascii=False)
    shots = sorted(set(SHOT.findall(text)))
    for s in shots:
        (dest / s).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / s, dest / s)
    for a in apps if "applications" in sample else ():
        for d in out_sample["applications"][a].get("documents", []):
            target = dest / d["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / d["file"], target)
    write_json(dest / review.SAMPLE, out_sample)
    write_json(dest / review.KEY, out_key)
    workspaces = {k["workspace"] for k in out_key.values()}
    out = {
        "id": dest.name,
        "kind": manifest["kind"],
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": skuld.__version__,
        "method": manifest["method"],
        "derived": {
            "by": AUTHOR,
            "from": {"sample": manifest["id"], "files": manifest["files"], "seed": manifest.get("seed")},
            "reason": reason,
            "units": [{"id": renamed[old], "from": old, "why": why[old].strip()} for old in items],
            "avoided": avoided,
        },
        "screenshots": len(shots),
        "runs": manifest.get("runs"),
        "run_models": manifest.get("run_models"),
        "workspaces": [w for w in manifest["workspaces"] if w["key"] in workspaces],
        "files": {n: file_sha256(dest / n) for n in (review.SAMPLE, review.KEY)},
    }
    write_json(dest / review.MANIFEST, out)
    return out


KINDS = (review.KIND, rx.KIND)
