"""Repair the cases whose family in a study catalogue was replaced by another proposal's (23 Nov 2026).

Proposals running at once before Skuld 0.12.13 each read the study catalogue when they started; two that described
the same new family id both wrote `<id>@1`, the later replacing the earlier. A case of the earlier then names a family
whose file is not the one it was proposed with (its `author.generated.family.sha256` differs from the file's).

For each such case of each `proposals/<model>/summary.json` of the workspaces given, the family is rebuilt from the
model's answer as `propose` built it (`new_family`, the answer kept in the case's sample folder). The rebuilt family
must have exactly the recorded digest at its recorded version, else nothing is repaired for the case. It is then added
to the catalogue (Skuld 0.12.13's `add`: the same family as one on disk is that one, another is the next version) and
the case names it; the summary before is kept beside it (`summary.before-repair.json`). No model is asked.

    python tools/repair_family_collisions.py --exploration <run> --new-families <study catalogue> <workspace> [--dry-run]
"""

import argparse
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import yaml

from skuld import propose
from skuld.select import CATALOGUE as BASE


def _text(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def repair(workspace: Path, exploration: Path, study: Path, dry_run: bool) -> list[str]:
    exp = propose.read(exploration)
    flows = {str(f.episode): f for f in exp.flows}
    application = f"{exp.package}@{exp.version}"
    catalogue = propose.load_catalogue((BASE, study))
    out = []
    for path in sorted(workspace.glob("proposals/*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for case in summary.get("cases", []):
            generated = (case.get("author") or {}).get("generated") or {}
            fam = generated.get("family") or {}
            file = study / "families" / f"{fam.get('id')}@{fam.get('version')}.yaml"
            if not fam or not file.is_file():
                continue
            if hashlib.sha256(file.read_bytes()).hexdigest() == fam["sha256"]:
                continue
            where = f"{path.parent.name} {case['case']}"
            folder = workspace / generated["answer"]
            answer = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
            prompt = json.loads((folder / "record.json").read_text(encoding="utf-8"))["prompt"]
            news = [x for x in answer.get("features", []) if x.get("family") == "new"
                    and (x.get("new_family") or {}).get("id") == fam["id"]]
            if len(news) != 1:
                out.append(f"{where}: {len(news)} new families {fam['id']} in the answer; not repaired")
                continue
            author = {
                "kind": "model",
                "name": summary["model"],
                "prompt": f"skuld.propose {generated['generator']['version']}",
                "sha256": prompt["sha256"],
            }
            data = propose.new_family(news[0]["new_family"], flows[str(case["episode"])], application, exp.run_id, author)
            if "reviewed" in data and not data["reviewed"]:
                del data["reviewed"]
            rebuilt = hashlib.sha256(_text({**data, "version": fam["version"]}).encode("utf-8")).hexdigest()
            if rebuilt != fam["sha256"]:
                out.append(f"{where}: the rebuilt {fam['id']} is {rebuilt[:12]}, not {fam['sha256'][:12]}; not repaired")
                continue
            if dry_run:
                out.append(f"{where}: {fam['id']}@{fam['version']} rebuilds exactly; would be added")
                continue
            added = catalogue.add(copy.deepcopy(data))
            case["family"] = added.key
            generated["family"] = {**fam, "version": added.version, "sha256": added.sha256}
            case.setdefault("repairs", []).append(
                {"what": "family", "was": f"{fam['id']}@{fam['version']}", "now": added.key,
                 "why": "its file was replaced by a concurrent proposal's (Skuld before 0.12.13)",
                 "tool": "tools/repair_family_collisions.py"}
            )
            changed = True
            out.append(f"{where}: {fam['id']}@{fam['version']} -> {added.key}")
        if changed:
            shutil.copy2(path, path.with_name("summary.before-repair.json"))
            path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--exploration", type=Path, required=True)
    ap.add_argument("--new-families", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    lines = repair(a.workspace, a.exploration, a.new_families, a.dry_run)
    for line in lines:
        print(line)
    return 1 if any("not repaired" in x for x in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
