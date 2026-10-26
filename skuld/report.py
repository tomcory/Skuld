"""The case report: the experimental channel's measurements, written as JSON, validated against Ratatoskr's schema
(`expectation_report`), and rendered as Markdown."""

import json
from pathlib import Path

from ratatoskr.schemas import validate


def write(report: dict, root: Path) -> tuple[Path, Path]:
    """Validates the report and writes report.json and report.md into the workspace."""
    validate("expectation_report", report)
    json_path, md_path = root / "report.json", root / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
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
        lines.append(
            f"| {r['id'][-6:]} | {r['alternative'] or 'baseline'} | {', '.join(r['cases'])} "
            f"| {r['verification']['status']} | {unv} | {decisions} |"
        )
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
        lines.append(f"| {k['case']} | {k['purpose']} | {k['alternative']} | {runs} | {k['outcome']} | {worse} |")
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
