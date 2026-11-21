"""The case report: the experimental channel's measurements, written as JSON, validated against Ratatoskr's schema
(`expectation_report`), and rendered as Markdown."""

import json
from pathlib import Path

from ratatoskr.schemas import validate


def write(report: dict, root: Path) -> tuple[Path, Path]:
    """Validates the report and writes report.json and report.md into the workspace."""
    validate("expectation_report", report)
    json_path, md_path = root / "report.json", root / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    md_path.write_text(markdown(report), encoding="utf-8", newline="\n")
    return json_path, md_path


def markdown(report: dict) -> str:
    app = report["application"]
    lines = [
        f"# Case report: {app['package']} {app['version']}",
        "",
        f"Skuld {report['report']['skuld']}, {report['report']['created']}. Features covered: "
        + ", ".join(f"{f['id']} ({f['name']})" for f in report["features"])
        + ".",
        "",
        "## Runs",
        "",
        "| run | condition | cases | verification | unverifiable | decisions |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["runs"]:
        decisions = ", ".join(f"{d['case']}/{d['purpose']} {d['decision']}" for d in r["decisions"])
        parts = r["verification"].get("unverifiable") or ()
        unv = f"{len(parts)} part(s)" if parts else "–"
        status = r["verification"]["status"]
        if r["verification"].get("substitutes"):
            status += f" (substitute: {', '.join(r['verification']['substitutes'])})"
        condition = r["alternative"] or ("control" if r.get("control") else "baseline")
        if r.get("goal"):
            g = r["goal"]
            condition += f" (goal {'reached' if g['reached'] else 'not reached'}" + (
                f", window {g['window'][0]}–{g['window'][1]})" if g.get("window") else ")"
            )
        lines.append(f"| {r['id'][-6:]} | {condition} | {', '.join(r['cases'])} | {status} | {unv} | {decisions} |")
    lines += [
        "",
        "## Comparisons",
        "",
        "| case | purpose | alternative | runs | outcome | worse |",
        "|---|---|---|---|---|---|",
    ]
    for k in report["comparisons"]:
        worse = ", ".join(f"{n}: {m['worse']}" for n, m in k["tradeoff"]["measurements"].items()) or "–"
        runs = f"{len(k['baseline_runs'])} + {len(k['alternative_runs'])}"
        outcome = k["outcome"] + (f" (substitute: {', '.join(k['substitutes'])})" if k.get("substitutes") else "")
        lines.append(f"| {k['case']} | {k['purpose']} | {k['alternative']} | {runs} | {outcome} | {worse} |")
    lines += controls_markdown(report)
    proposed = [c for c in report["cases"] if len(c.get("proposers") or ()) > 1]
    if proposed:
        lines += ["", "## Cases of several proposers", ""]
        lines += [f"- {c['id']}: {', '.join(p['name'] for p in c['proposers'])}" for c in proposed]
    lines += ["", "## Not compared", ""]
    untested = [
        f"- {c['id']}: {u['alternative']} for {u['purpose']}: {u['reason']}"
        for c in report["cases"]
        for u in c.get("untested", [])
    ]
    problems = [
        f"- {c['id']}: {a['id']} is no member of the search space: {'; '.join(a['problems'])}"
        for c in report["cases"]
        for a in c["scope"]["search_space"]
        if a.get("problems")
    ]
    lines += untested + problems or ["None."]
    return "\n".join(lines) + "\n"


def controls_markdown(report: dict, heading: str = "## Controls") -> list[str]:
    """The case report's controls by family: each control's outcome against what was expected; a control expected to
    break that preserves is a sensitivity failure of the family's oracle, where the control runs tried the blocked
    hosts ("control not exercised" otherwise); a break by control runs that did not reach their goal is "broken: goal
    not reached". Nothing where no case has a control."""
    controls = [(c["id"], k) for c in report["cases"] for k in c.get("controls") or ()]
    if not controls:
        return []
    lines = [
        "",
        heading,
        "",
        "Controls test the oracles, not the application: none is a comparison, and no claim is made from one.",
        "",
        "| family | case | purpose | intervention | expected | outcome | runs | sensitivity |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case, k in sorted(controls, key=lambda x: (x[1].get("family") or "?", x[0])):
        runs = f"{len(k.get('baseline_runs') or ())} + {len(k.get('control_runs') or ())}"
        why = k.get("reason") or (f"broken: {k['broken']}" if k.get("broken") else None) or k.get("note")
        outcome = k["outcome"] + (f" ({why})" if why else "")
        flag = "**failure**" if k["sensitivity_failure"] else "–"
        lines.append(
            f"| {k.get('family') or '?'} | {case} | {k['purpose']} | {k['intervention']} | {k['expected']} "
            f"| {outcome} | {runs} | {flag} |"
        )
    failed = sorted({k.get("family") or "?" for _, k in controls if k["sensitivity_failure"]})
    if failed:
        lines += ["", f"Sensitivity failures of the oracles of: {', '.join(failed)}."]
    return lines
