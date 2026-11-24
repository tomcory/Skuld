"""
The screens a review shows, as the expectation stage was given them (0.12.19, 24 Nov 2026; the re-run plan's D-37
and D-45): per screen its text, the description by the family's own model where the stage-1 context gave one (a
model's reading, never evidence) and the screenshot where the context attached one. A reviewer judges against what the
stage saw, and since prompt version 10 (expectation.DESCRIBED_SINCE) that holds descriptions and up to
images.MAX_IMAGES screenshots per batch.

A stage-1 context names a screen by its run and screen id only (`events.jsonl#screen/<sid>`); its visit, which a
description joins on, is in the batch the context was made of. The batches are made again as stage 1 made them
(expectation.batches, the assessment's notice definition), and a context's screen S<n> is the batch's n-th shown
screen, which must have the same screen id.

**D-45:** a screen whose description in descriptions.jsonl is empty, by either model, at the visit the screen joins on
(expectation.description_of: its own visit, else the latest earlier visit of the same screen in the episode) is
`empty` here, and is never shown with a description, in either family's items (`view`). A draw that excludes them
(`exclude_empty_descriptions`) passes over an item for the stratum's next eligible item in the seed's order, and its
manifest lists the items passed over: a review of concerns, an item that shows such a screen among its evidence; a
review of stage 1, whose item shows every screen of its practice's batches, an item that cites one (a screen among
its purposes' and dependencies' evidence or cited by a step; D-45 as amended by the author on 24 Nov 2026).

**Visits** (author, 24 Nov 2026): Loki takes one screenshot per visit, when a screen's structure key changes; a change
within the screen (typed text, a toggle, a scroll, a page that finished loading) keeps the visit and takes none, while
stage 1 shows each changed state as a screen of its own. Each screen names its visit (`visit`, the seq of the visit's
first observation: the run of observations with the same structure key it belongs to), so the tool groups a visit's
screens; a screen Loki took no screenshot of is shown with its visit's first screenshot, labelled "before the change"
(`before`), never where gate 1 applies (the screen or the visit's first state a notice).

A screen is keyed by (run, screen id, text): how a concern's evidence item names it (`screen of <run>`, cited at
`events.jsonl#screen/<sid>`) and what a stage-1 context's screen part holds.
"""

import json
import shutil
from pathlib import Path

from skuld import expectation, inputs
from skuld.calibrate import read_json

#: Where a drawn sample keeps its screenshots, each named by its digest
SCREENSHOTS = "screenshots"
DESCRIPTION_PREFIX = "(about S"


class ScreenError(inputs.InputError):
    """A stage-1 context whose screens cannot be matched to the batch they were made of."""


def _key(run: str | None, record: str | None, text: str | None) -> tuple | None:
    if not run or not record or not record.startswith("events.jsonl#screen/"):
        return None
    return (run, record.split("/", 1)[1], text)


def screen_key(part: dict) -> tuple | None:
    """A stage-1 context's screen part's key: (run, screen id, text)."""
    first = (part.get("provenance") or [{}])[0]
    return _key(first.get("run"), first.get("record"), part.get("text"))


def evidence_key(e: dict) -> tuple | None:
    """An evidence item's key, if it is a screen (`screen of <run>`)."""
    if not str(e.get("method") or "").startswith("screen of "):
        return None
    citation = e.get("citation") or {}
    return _key(citation.get("id"), citation.get("at"), e.get("text"))


def _raw_descriptions(directory: Path) -> dict[str, list[dict]]:
    """Per model, every description of a run without an error, empty ones included (D-45 asks after those)."""
    path = Path(directory) / expectation.DESCRIPTIONS
    out: dict[str, list[dict]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if record and record.get("model") and not record.get("error"):
            out.setdefault(record["model"], []).append(record)
    return out


def _description_text(text: str) -> str:
    """A description part's text without its '(about S<n>) ' lead."""
    if text.startswith(DESCRIPTION_PREFIX):
        return text.split(") ", 1)[1] if ") " in text else ""
    return text


def _visits(directory: Path) -> dict[int, dict]:
    """Per screen observation of a run, by seq: the visit's first observation (the earliest of the run of
    observations with the same structure key that ends at it)."""
    events = [json.loads(x) for x in (Path(directory) / "events.jsonl").read_text(encoding="utf-8").splitlines() if x]
    out, start = {}, None
    for e in (e for e in events if e.get("type") == "screen" and e.get("seq") is not None):
        # an observation without a structure key begins a visit of its own
        if start is None or not e.get("exact_key") or e.get("exact_key") != start["_last"]:
            start = {**e, "_last": e.get("exact_key")}
        out[e["seq"]] = start
    return out


def index(root: Path) -> dict[tuple, dict]:
    """Per screen of the workspace's stage-1 contexts, keyed (run, screen id, text): {description, screenshot
    (path in the run, digest), directory, empty (the models whose description at the joined visit is empty), visit
    (the seq of its visit's first observation), before (the visit's first screenshot, for a screen Loki took none
    of)}; {} for a workspace without stage-1 contexts or an assessment.yaml."""
    from skuld import images

    root = Path(root)
    paths = sorted((root / "expectation").rglob("context.json")) if (root / "expectation").is_dir() else []
    if not paths or not (root / "assessment.yaml").is_file():
        return {}
    from skuld import assessment
    from skuld.assess import REPORT
    from skuld.parties import load_registry

    a = inputs.load_assessment(root, check=False)  # the corpus is not read, so a moved one does not matter
    notices = expectation.notices_of(read_json(root / REPORT)) if (root / REPORT).is_file() else None
    made = {b.key: b for b in expectation.batches(a, assessment.build(a, load_registry(None)), notices)}
    raw: dict[Path, dict] = {}
    visits: dict[Path, dict] = {}
    out: dict[tuple, dict] = {}
    for path in paths:
        name = path.relative_to(root / "expectation").parts[0]
        batch = made.get(name)
        parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
        by_id = {p["id"]: p for p in parts}
        for part in (p for p in parts if p["kind"] == "screen"):
            key = screen_key(part)
            if key is None:
                continue
            n = int(part["id"][1:])
            if batch is None or n > len(batch.shown) or batch.shown[n - 1].get("sid") != key[1]:
                raise ScreenError(f"{path.relative_to(root)}: {part['id']} is not its batch's screen {n}")
            shown = batch.shown[n - 1]
            entry = out.setdefault(
                key,
                {
                    "description": None,
                    "screenshot": None,
                    "directory": batch.directory,
                    "empty": set(),
                    "visit": None,
                    "before": None,
                },
            )
            described = by_id.get(f"{part['id']}.d")
            if described and entry["description"] is None:
                entry["description"] = _description_text(described["text"])
            shot = next((x for x in part.get("provenance", []) if x.get("sha256")), None)
            if shot and entry["screenshot"] is None:
                entry["screenshot"] = (shot["record"], shot["sha256"])
            if batch.directory is not None and (batch.directory / "events.jsonl").is_file():
                if batch.directory not in visits:
                    visits[batch.directory] = _visits(batch.directory)
                first = visits[batch.directory].get(shown.get("seq"))
                if first is not None and entry["visit"] is None:
                    entry["visit"] = first["seq"]
                noticed = shown.get("noticed") or frozenset()
                if (
                    first is not None
                    and entry["before"] is None
                    and not shown.get("screenshot")  # Loki took none of this state (not: one stage 1 was not sent)
                    and not shown.get("notice")
                    and shown.get("seq") not in noticed
                    and first["seq"] not in noticed
                    and first.get("screenshot")
                    and (batch.directory / first["screenshot"]).is_file()
                ):
                    entry["before"] = (first["screenshot"], images.digest(batch.directory / first["screenshot"]))
            if batch.directory is not None:
                if batch.directory not in raw:
                    raw[batch.directory] = _raw_descriptions(batch.directory)
                for model, found in raw[batch.directory].items():
                    d = expectation.description_of(shown, found)
                    if d is not None and not (d.get("screen") or "").strip():
                        entry["empty"].add(model)
    return out


def context_keys(root: Path) -> dict[str, dict[str, tuple]]:
    """Per practice, the keys of the screens its stage-1 contexts showed, by text, in the order calibrate.stage_one
    lists the texts (each text once, the first context's)."""
    out: dict[str, dict[str, tuple]] = {}
    for path in sorted(Path(root).glob("expectation/*/s*/context.json")):
        parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
        screens = [p for p in parts if p["kind"] == "screen"]
        for practice in (p["id"] for p in parts if p["kind"] == "practice"):
            mine = out.setdefault(practice, {})
            for s in screens:
                mine.setdefault(s["text"], screen_key(s))
    return out


def view(entry: dict | None) -> dict:
    """What a sample shows of a screen beside its text: {description, screenshot (the sample's file)}, as given; no
    description of a screen whose description is empty by either model (D-45), so that neither family's shows one."""
    if not entry:
        return {}
    out = {}
    if entry.get("description") and not entry.get("empty"):
        out["description"] = entry["description"]
    if entry.get("visit") is not None:
        out["visit"] = f"v{entry['visit']}"  # a seq, never the run's name
    shot = entry.get("screenshot") or entry.get("before")
    if shot:
        record, digest = shot
        out["screenshot"] = f"{SCREENSHOTS}/{digest}{Path(record).suffix or '.png'}"
        if not entry.get("screenshot"):
            out["before_change"] = True  # the visit's first screenshot: the screen before it changed in place
    return out


def empty(entries: list[dict | None]) -> list[str]:
    """The models whose description is empty for any of these screens (D-45), sorted."""
    return sorted({m for e in entries if e for m in e["empty"]})


def copy_screenshots(folder: Path, entries: list[dict | None]) -> int:
    """Copies the screenshots the drawn items show into folder/screenshots/<digest>.<ext>, each once, checking each
    file's digest; returns how many."""
    from skuld import images

    copied = set()
    for e in entries:
        if not e or not (e.get("screenshot") or e.get("before")) or e.get("directory") is None:
            continue
        record, digest = e.get("screenshot") or e["before"]
        target = folder / view(e)["screenshot"]
        if target in copied:
            continue
        source = Path(e["directory"]) / record
        if images.digest(source) != digest:
            raise ScreenError(f"{source}: the screenshot differs from the one its context names")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.add(target)
    return len(copied)
