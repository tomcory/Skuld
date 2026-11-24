"""
A reviewer's package (author, 12 Nov 2026): the review tool and one reviewer's copies of the review samples as one
zip, to send to a reviewer who runs it on their own computer with Node.js, offline; and the import of what they send
back.

    skuld review export <package.zip> <sample folders…> --reviewer <id>
    skuld review import <returned.zip> <reviews folder>

The package holds, below one folder `asgard-review-<id>/`:

    README.md               the reviewer's guide: what to judge, in which order, how to start and how to send back
    reviewer.json           the reviewer's id, the samples and when the package was made
    tool/                   the review tool (server.js, public/, package.json) with the modules the server needs
    samples/<name>/         per sample its sample.json, for a review of concerns the documents, and the screenshots
                            stage 1 was given of the units' screens; never key.json or manifest.json, which name the
                            runs
    start-<name>.command    macOS: start the tool on that sample and open it in the browser (also -.sh, -.bat)
    pack-reviews.command    macOS: pack the reviews into reviews-<id>.zip to send back (also .sh, .bat)

The export refuses a sample whose sample.json names one of its manifest's runs or models. The import files each
sample's reviews.json (and recall.json) into <reviews folder>/<sample>-<id>/; a file already there (a part-way return)
is kept beside it as <name>.<time>.bak.
"""

import json
import re
import shutil
import stat
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from skuld.review import ReviewError

TOOL = Path(__file__).resolve().parents[1] / "tools" / "calibration-review"
#: What of the browser modules the server serves (server.js: /vendor/…): only these files are packed
VENDOR = {
    "vue": ["dist/vue.esm-browser.prod.js", "package.json"],
    "bootstrap": ["dist/css/bootstrap.min.css", "package.json"],
    "bootstrap-icons": ["font", "package.json"],
}
#: Modules only Vue's build needs, not the server or the page
SKIPPED = {
    "@vue",
    "@babel",
    "@jridgewell",
    "postcss",
    "source-map-js",
    "nanoid",
    "picocolors",
    "magic-string",
    "estree-walker",
    "entities",
    "csstype",
    ".package-lock.json",
    ".bin",
}
RETURNED = ("reviews.json", "recall.json")
PORT = 3001


def _plain(name) -> bool:
    """Whether a name is letters, digits, - or _ only, and so names one folder and no path."""
    return isinstance(name, str) and bool(name) and name.replace("-", "").replace("_", "").isalnum()


def export(out: str | Path, samples: list[str | Path], reviewer: str, note: str | None = None) -> Path:
    """The reviewer's package; `note`, if given, opens its guide (e.g. that the package is a demonstration)."""
    out = Path(out)
    if out.exists():
        raise ReviewError(f"{out} exists")
    if not _plain(reviewer):
        raise ReviewError("the reviewer's id must be letters, digits, - or _")
    if not (TOOL / "node_modules").is_dir():
        raise ReviewError(f"{TOOL}: run `npm install` there first")
    root = f"asgard-review-{reviewer}"
    files: dict[str, bytes | Path] = {}
    names = []
    for folder in map(Path, samples):
        sample = folder / "sample.json"
        if not sample.is_file():
            raise ReviewError(f"{folder}: no sample.json")
        _check_blind(folder)
        kind = json.loads(sample.read_text(encoding="utf-8"))["kind"]
        name = folder.name
        if not _plain(name):  # the launchers and the import take it as one plain name (import_ refuses any other)
            raise ReviewError(f"{folder}: a sample's folder name must be letters, digits, - or _")
        if name in {n for n, _ in names}:
            raise ReviewError(f"two samples named {name}")
        names.append((name, kind))
        files[f"samples/{name}/sample.json"] = sample
        for sub in ("documents", "screenshots"):  # screenshots: what stage 1 was given of the units' screens
            for f in sorted((folder / sub).rglob("*")) if (folder / sub).is_dir() else []:
                if f.is_file():
                    files[f"samples/{name}/{sub}/{f.relative_to(folder / sub).as_posix()}"] = f
    for f in ("server.js", "package.json", "package-lock.json"):
        if (TOOL / f).is_file():
            files[f"tool/{f}"] = TOOL / f
    for f in sorted((TOOL / "public").rglob("*")):
        if f.is_file():
            files[f"tool/public/{f.relative_to(TOOL / 'public').as_posix()}"] = f
    modules = TOOL / "node_modules"
    for top in sorted(modules.iterdir()):
        if top.name in SKIPPED:
            continue
        keep = VENDOR.get(top.name)
        paths = [top / k for k in keep] if keep else [top]
        for p in paths:
            for f in [p] if p.is_file() else sorted(p.rglob("*")):
                if f.is_file():
                    files[f"tool/node_modules/{f.relative_to(modules).as_posix()}"] = f
    made = datetime.now(UTC).isoformat(timespec="seconds")
    files["reviewer.json"] = json.dumps(
        {"reviewer": reviewer, "samples": [{"name": n, "kind": k} for n, k in names], "made": made}, indent=1
    ).encode()
    files["README.md"] = ((f"> **{note}**\n\n" if note else "") + guide(reviewer, names)).encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in sorted(files.items()):
            z.writestr(_info(f"{root}/{arc}", 0o644), src if isinstance(src, bytes) else src.read_bytes())
        for arc, text in sorted(scripts(reviewer, [n for n, _ in names]).items()):
            z.writestr(_info(f"{root}/{arc}", 0o755), text)
    return out


def scripts(reviewer: str, names: list[str]) -> dict[str, bytes]:
    """The package's launchers and packers as written: a start-<name> per sample, each on its own port (two samples
    open at once never collide), and pack-reviews; a .bat with Windows' line endings (CRLF), the others with LF."""
    out = {}
    for i, name in enumerate(names):
        out |= launchers(name, PORT + i)
    out |= packers(reviewer, names)
    return {arc: text.replace("\n", "\r\n" if arc.endswith(".bat") else "\n").encode() for arc, text in out.items()}


def _info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _check_blind(folder: Path) -> None:
    """A sample is sent only if neither its sample.json nor its folder's name (which the package shows) names one of
    the runs or models its manifest names."""
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        raise ReviewError(f"{folder}: no manifest.json; export the drawn sample's own folder, not a reviewer's copy")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    shown = (folder / "sample.json").read_text(encoding="utf-8")
    named = set(m.get("runs") or []) | {x for v in (m.get("run_models") or {}).values() for x in v}
    named |= {model.split(" (")[0] for model in named}
    found = sorted(n for n in named if n and (n in shown or n in folder.name))
    if found:
        raise ReviewError(f"{folder}/sample.json names {', '.join(found)}: not blind to the run")


def launchers(name: str, port: int = PORT) -> dict[str, str]:
    url = f"http://localhost:{port}"
    sh = f"""#!/bin/sh
# Starts the review tool on the sample {name} and opens it in the browser; close this window to stop it.
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
    echo "Node.js is not installed: get it from https://nodejs.org (version 18 or later), then start this again."
    read -r _
    exit 1
fi
( sleep 2; (open "{url}" || xdg-open "{url}") >/dev/null 2>&1 ) &
PORT={port} node tool/server.js "samples/{name}"
"""
    bat = f"""@echo off
rem Starts the review tool on the sample {name} and opens it in the browser; close this window to stop it.
cd /d "%~dp0"
where node >nul 2>nul || (echo Node.js is not installed: get it from https://nodejs.org ^(version 18 or later^). & pause & exit /b 1)
start "" cmd /c "timeout /t 2 >nul & start {url}"
set PORT={port}
node tool\\server.js "samples\\{name}"
pause
"""
    return {f"start-{name}.command": sh, f"start-{name}.sh": sh, f"start-{name}.bat": bat}


def packers(reviewer: str, names: list[str]) -> dict[str, str]:
    target = f"reviews-{reviewer}.zip"
    listed = " ".join(f"samples/{n}/{f}" for n in names for f in RETURNED)
    sh = f"""#!/bin/sh
# Packs your reviews into {target}, next to this file: send that file back.
cd "$(dirname "$0")" || exit 1
rm -f "{target}"
files=""
for f in reviewer.json {listed}; do [ -f "$f" ] && files="$files $f"; done
zip -q "{target}" $files && echo "Packed: $(pwd)/{target}"
"""
    ps = ", ".join(f"'samples/{n}/{f}'" for n in names for f in RETURNED)  # tar keeps the folders
    bat = f"""@echo off
rem Packs your reviews into {target}, next to this file: send that file back.
cd /d "%~dp0"
powershell -NoProfile -Command "$f = @('reviewer.json', {ps}) | Where-Object {{ Test-Path $_ }}; if (Test-Path '{target}') {{ Remove-Item '{target}' }}; & tar.exe -a -c -f '{target}' $f"
echo Packed: %~dp0{target}
pause
"""
    return {"pack-reviews.command": sh, "pack-reviews.sh": sh, "pack-reviews.bat": bat}


def guide(reviewer: str, names: list[tuple[str, str]]) -> str:
    order = sorted(names, key=lambda x: x[1] != "expectation-review")
    rows = "\n".join(
        f"{i}. `{n}`: "
        + {
            "expectation-review": "the expectation stage's predictions (do this one first)",
            "aggregate-review": "E's aggregated concerns",
        }.get(k, k)
        + f" — start with `start-{n}`, opens http://localhost:{PORT + [x for x, _ in names].index(n)}"
        for i, (n, k) in enumerate(order, 1)
    )
    return f"""# Review of an expectation analysis of Android apps (reviewer {reviewer})

Thank you for reviewing. This package holds a small web tool and the samples you review. Everything runs on your own
computer; nothing is sent anywhere. Your judgments are saved as you go, so you can stop and continue at any time.

## Before you start

You need **Node.js** (version 18 or later; https://nodejs.org). Nothing else is installed.

## The samples, in this order

{rows}

Start a sample with the launcher of your system: `start-<sample>.command` on macOS (double-click; the first time,
right-click → Open, as it is not from the App Store), `start-<sample>.sh` on Linux, `start-<sample>.bat` on Windows.
Each sample opens in the browser at its own address (above); close the launcher's window to stop it.
The page's title says which review it is: **Review of the expectation stage** shows what the analysis's first stage saw
(traffic, screens, documentation); **Review of aggregated concerns** shows the provider's documents (privacy policy,
Data safety section, store listing), which those concerns are about.
**Help** at the top of each page is the codebook: what each question means, where each answer ends and the next begins
(yes, mostly, partly, no), the reasons to pick for an answer short of yes, and the keyboard shortcuts. Please read it
once before you start, and again when a unit leaves you between two answers.

Please work **independently**: other reviewers review the same samples, and the agreement between you is part of the
result. You are not told which model produced a unit; please do not try to find out.

### The expectation stage's predictions

Each unit is one practice of an app (data sent to a recipient, or read on the device) and what the first stage of the
analysis predicted for it: the purposes the processing serves and whether the data is needed for them. **Judge the
predictions against what the stage saw**, which the right-hand side shows: the practice, its traffic as captured (where
there is some), the screens of the app where it occurred, and documentation passages. The stage did not see the
provider's privacy policy, so do not judge against
it; if you know that the provider says otherwise, say so in the note. The purposes are shown one at a time. **Done** is
accepted once every question is answered; **Save** keeps a unit half-done.

### E's aggregated concerns

Each unit is one aggregated concern: concerns the analysis raised that share a requirement and a subject. You see its
statement, its members, the evidence and the app's documents. First judge whether the evidence exists and is cited
correctly and whether the conclusion follows; then whether **the concern holds for the app**, as stated: holds, does
not hold, or unsure. You judge the app, not whether you agree with the analysis. When
every unit of an app is judged, the **recall pass** asks what the analysis should have raised for the app and did not.

## Sending your reviews back

Run `pack-reviews` (`.command`, `.sh` or `.bat`). It writes `reviews-{reviewer}.zip` next to it; send that file back.
You can send it part-way through and again at the end.
"""


#: The review tool's timestamps (JavaScript's toISOString)
TOOL_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def check_returned(file: str, data, sample: dict, made: str | None, now: datetime) -> list[str]:
    """
    What looks wrong in a returned file, flagged rather than refused (the reviews are the reviewer's): an entry for no
    unit (application) of the sample, a `reviewed` time not in the tool's format, or outside the review period (from
    when the package was made to now). Reviewer B's file had every `reviewed` 1970-01-01T00:00:00.0000.
    """
    if not isinstance(data, dict):
        return [f"{file}: not a mapping of {'units' if file == 'reviews.json' else 'applications'}"]
    known = (
        {i["id"] for i in sample.get("items", [])} if file == "reviews.json" else set(sample.get("applications") or {})
    )
    start = datetime.fromisoformat(made) - timedelta(days=1) if made else None
    flags, odd, outside = [], [], []
    for key, entry in data.items():
        if key not in known:
            flags.append(f"{file}: {key} is no {'unit' if file == 'reviews.json' else 'application'} of the sample")
        if not isinstance(entry, dict):
            flags.append(f"{file}: {key} is not an entry of the tool")
            continue
        stamp = entry.get("reviewed")
        if not isinstance(stamp, str) or not TOOL_TIME.match(stamp):
            odd.append(key)
            continue
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when > now + timedelta(minutes=5) or (start and when < start):
            outside.append(key)
    if odd:
        flags.append(
            f"{file}: {len(odd)} of {len(data)} entries have a reviewed time not in the tool's format ({odd[0]}: "
            f"{data[odd[0]].get('reviewed') if isinstance(data[odd[0]], dict) else None!r})"
        )
    if outside:
        flags.append(
            f"{file}: {len(outside)} of {len(data)} entries were reviewed outside the review period "
            f"({outside[0]}: {data[outside[0]]['reviewed']})"
        )
    return flags


def import_(returned: str | Path, folder: str | Path, flags: list[str] | None = None) -> list[Path]:
    """
    Files a reviewer's returned reviews: per sample, <folder>/<sample>-<reviewer>/reviews.json (and recall.json). A zip
    packed flat (the files next to reviewer.json, as Windows' Compress-Archive packs them) is read as the package's
    one sample; one that names several samples is refused, as is a zip from which nothing would be filed. What looks
    wrong in a file is appended to `flags` (check_returned) and filed nonetheless.
    """
    folder = Path(folder)
    flags = [] if flags is None else flags
    written = []
    now = datetime.now(UTC)
    with zipfile.ZipFile(returned) as z:
        names = z.namelist()
        # the package's reviewer.json, not a Finder-made AppleDouble copy of it (__MACOSX/…/._reviewer.json)
        meta = next(
            (
                n
                for n in names
                if not n.startswith("__MACOSX/") and n.replace("\\", "/").rsplit("/", 1)[-1] == "reviewer.json"
            ),
            None,
        )
        if meta is None:
            raise ReviewError(f"{returned}: no reviewer.json")
        about = json.loads(z.read(meta))
        reviewer = about["reviewer"]
        samples = [s["name"] for s in about.get("samples") or []]
        # both name folders below the reviews folder: a returned package cannot name a path outside it
        if not _plain(reviewer) or not all(_plain(s) for s in samples):
            raise ReviewError(f"{returned}: its reviewer.json names a reviewer or sample that is no plain name")
        prefix = meta[: -len("reviewer.json")]
        found = []
        for n in names:
            rest = n[len(prefix) :] if n.startswith(prefix) else n
            parts = rest.replace("\\", "/").split("/")  # a Windows packer may write backslashes
            if len(parts) == 3 and parts[0] == "samples" and parts[2] in RETURNED:
                found.append((n, parts[1], parts[2]))
            elif len(parts) == 1 and parts[0] in RETURNED:  # packed flat
                if len(samples) != 1:
                    raise ReviewError(
                        f"{returned}: {parts[0]} is packed without its sample's folder, and the package names "
                        f"{len(samples)} samples; ask for the zip that pack-reviews writes"
                    )
                found.append((n, samples[0], parts[0]))
        if not found:
            raise ReviewError(
                f"{returned}: no reviews.json or recall.json below samples/<sample>/ or next to reviewer.json "
                f"(the zip holds {', '.join(names[:6])}{' …' if len(names) > 6 else ''})"
            )
        for n, sample, file in found:
            if not (folder / sample / "sample.json").is_file():
                raise ReviewError(f"{folder / sample}: no such drawn sample")
            target = folder / f"{sample}-{reviewer}" / file
            try:
                data = json.loads(z.read(n))  # a returned file must be JSON
            except json.JSONDecodeError as e:
                raise ReviewError(f"{returned}: {n} is not JSON ({e})") from None
            drawn = json.loads((folder / sample / "sample.json").read_text(encoding="utf-8"))
            flags += [f"{sample}: {f}" for f in check_returned(file, data, drawn, about.get("made"), now)]
            if target.exists():
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                backup, n_same = target.with_name(f"{target.name}.{stamp}.bak"), 1
                while backup.exists():  # two imports within one second keep both earlier returns
                    n_same += 1
                    backup = target.with_name(f"{target.name}.{stamp}-{n_same}.bak")
                target.rename(backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not (target.parent / "sample.json").exists():
                shutil.copyfile(folder / sample / "sample.json", target.parent / "sample.json")
            target.write_bytes(z.read(n))
            written.append(target)
    return written
