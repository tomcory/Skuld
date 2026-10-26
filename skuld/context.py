"""
A model's context: the parts a context procedure gives it, each with its kind, its text and where it comes from. The
stages' procedures (expectation.py, judge.py) say which kinds and origins their contexts may hold, and refuse others.
"""

import hashlib
import json
from dataclasses import dataclass


class ContextError(Exception):
    """A context that holds a part the procedure may not give a model."""


@dataclass(frozen=True)
class Context:
    """The parts given to a model, each {id, kind, text, provenance}."""

    parts: tuple[dict, ...]

    @property
    def ids(self) -> set[str]:
        return {p["id"] for p in self.parts}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def of_kind(self, kind: str) -> set[str]:
        return {p["id"] for p in self.parts if p["kind"] == kind}

    def render(self, sections: list[tuple[str, str]]) -> str:
        """The parts under their section titles, (title, kind) in order, each as `[id] text`."""
        out = []
        for title, kind in sections:
            parts = [p for p in self.parts if p["kind"] == kind]
            if parts:
                out.append(f"## {title}\n")
                out += [f"[{p['id']}] {p['text']}\n" for p in parts]
        return "\n".join(out)


def check(context: Context, kinds: dict[str, tuple[str, ...]], stage: str) -> None:
    """Refuses a part of a kind the stage does not give, or whose provenance has another origin."""
    for part in context.parts:
        allowed = kinds.get(part["kind"])
        if allowed is None:
            raise ContextError(f"{part['id']}: a part of kind {part['kind']!r} is not given to {stage}")
        for pointer in part["provenance"]:
            if pointer["origin"] not in allowed:
                only = pointer["origin"] == "d_report" and "declaration" in kinds
                raise ContextError(
                    f"{part['id']}: a {part['kind']} part may not come from {pointer['origin']!r} in {stage}"
                    + (" (a part of D's report is given only as a declaration)" if only else "")
                )


def part(pid: str, kind: str, text: str, origin: tuple[str, str], run: str | None = None) -> dict:
    pointer = {"origin": origin[0], "record": origin[1]}
    if run:
        pointer["run"] = run
    return {"id": pid, "kind": kind, "text": text, "provenance": [pointer]}


def screen_text(screen: dict) -> str:
    """
    A screen's text, for a run recorded before Loki recorded what a screen showed: the texts below its actionable
    elements, in order and once each; else the labels of its condensed form.
    """
    texts = []
    for action in (screen.get("actions") or {}).values():
        locator = action.get("locator") or {}
        for t in [locator.get("text"), locator.get("content_desc"), *(locator.get("subtree_texts") or ())]:
            if t and t not in texts:
                texts.append(t)
    if texts:
        return " | ".join(texts)
    lines = [line[2:] for line in (screen.get("condensed") or "").splitlines() if line.startswith("- ")]
    return " | ".join(line.split("] ", 1)[-1] for line in lines) or (screen.get("title") or "")
