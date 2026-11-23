"""
The calibration sample of one application in the re-run of the Expectation paper's evaluation
(`expectation-paper/rerun-2026-11/rerun-plan.md`, decision D-26, author 21 Nov 2026):

    every testable group (supported and undecided, both families' union), stratified per app, 2 groups per app (all
    where fewer), seed 20261121; drawn per app by a committed script once both families' E of the app exist, written
    to inputs/chosen.yaml before any experiment of the app.

A testable group is a group of `skuld select` (data type x purpose node, the unit of the aggregated concerns) with at
least one eligible candidate: a practice and a supported inferred purpose that the minimisation reasoning does not
decide and that an experiment of the catalogue could observe. The groups of the application's assessments (one per
model family) are pooled by their id, the pool is sorted, and `per_app` groups are drawn from it with
`random.Random(f"{seed}:{package}")`, so that each application's draw depends on the seed and the application only.

For each assessment, every eligible member of a drawn group that the assessment holds is written into its
`inputs/chosen.yaml` with the reason `calibrate` (one marked member chooses its whole group; marking every eligible
one makes the choice independent of the member order). A group only one family holds is chosen in that family's
workspace; `skuld select --assessment <other>` later joins the families' choices (reason `union`). Entries already in
`inputs/chosen.yaml` keep their reason. A workspace whose selection is fixed (`inputs/selection.json`) is refused:
the draw comes before any experiment of the application.

Usage (in Skuld's venv): python tools/rerun_calibration_draw.py <workspace> [<workspace> ...] --record <file.json>
[--seed 20261121] [--per-app 2] [--dry-run]. The record says what was pooled, drawn and written, and when.
"""

import argparse
import json
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from skuld import __version__, yamlio

CHOSEN = Path("inputs/chosen.yaml")
SELECTION = Path("inputs/selection.json")
REASON = "calibrate"


def candidates(workspace: Path) -> list[dict]:
    """The selection's candidates of a workspace, as `skuld select --list` prints them."""
    skuld = Path(sys.executable).parent / "skuld"
    out = subprocess.run([str(skuld), "select", str(workspace), "--list"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise SystemExit(f"{workspace}: skuld select --list failed: {out.stderr.strip()[-500:]}")
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


def package_of(workspace: Path) -> str:
    data = yamlio.load((workspace / "assessment.yaml").read_text(encoding="utf-8")) or {}
    return str((data.get("application") or {}).get("package"))


def draw(workspaces: list[Path], seed: int, per_app: int, dry_run: bool = False) -> dict:
    packages = {package_of(w) for w in workspaces}
    if len(packages) != 1:
        raise SystemExit(f"the workspaces assess different applications: {sorted(packages)}")
    package = packages.pop()
    for w in workspaces:
        if (w / SELECTION).is_file():
            raise SystemExit(f"{w}: the selection is fixed ({SELECTION}); the draw comes before any experiment")
    found = {w: candidates(w) for w in workspaces}
    testable = {w: sorted({c["group"] for c in cs if c["eligible"]}) for w, cs in found.items()}
    pool = sorted(set().union(*testable.values()))
    rng = random.Random(f"{seed}:{package}")
    drawn = sorted(rng.sample(pool, min(per_app, len(pool))))
    record = {
        "package": package,
        "decision": "rerun-plan D-26",
        "seed": seed,
        "per_app": per_app,
        "drawn_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "skuld": __version__,
        "pool": pool,
        "drawn": drawn,
        "workspaces": {},
    }
    for w, cs in found.items():
        path = w / CHOSEN
        data = (yamlio.load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}
        entries = list(data.get("chosen") or [])
        held = {str(e["id"]) for e in entries}
        written = []
        for c in cs:
            # a candidate whose concern (v) is not stated has no concern id: it is named by its practice, which
            # `skuld select` matches as well (23 Nov 2026: the re-run's Peacock Flashlight was written as `id: null`)
            key = c["concern"] or c["practice"]
            if c["eligible"] and c["group"] in drawn and key not in held:
                entries.append({"id": key, "reason": REASON, "group": c["group"]})
                held.add(key)
                written.append(key)
        record["workspaces"][str(w)] = {
            "candidates": len(cs),
            "testable_groups": testable[w],
            "written": written,
        }
        if written and not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = yaml.safe_dump({**data, "chosen": entries}, sort_keys=False, allow_unicode=True, width=120)
            path.write_text(text, encoding="utf-8", newline="\n")
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The re-run's calibration draw of one application (D-26).")
    ap.add_argument("workspaces", nargs="+", type=Path, help="the application's assessment workspaces, one per family")
    ap.add_argument("--record", type=Path, required=True, help="where the draw's record is written (JSON)")
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--per-app", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true", help="draw and record, write no chosen.yaml")
    args = ap.parse_args(argv)
    if args.record.exists():
        raise SystemExit(f"{args.record}: a draw of this application is already recorded")
    record = draw(args.workspaces, args.seed, args.per_app, args.dry_run)
    record["dry_run"] = args.dry_run
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("package", "pool", "drawn")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
