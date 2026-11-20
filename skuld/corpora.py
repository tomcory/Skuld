"""
Earlier corpora (`corpora/`): the step of 18 Nov 2026 as a tool. A workspace names its corpus by path and digest
(`assessment.yaml`, `corpus: {path, sha256}`) and refuses to load if the corpus at that path has another digest, so a
change of `corpus/` would orphan every workspace that names it. Before changing it:

    skuld corpus keep                       copies corpus/ (its passages and norms/) to corpora/<first 8 of its
                                            digest>/, checked to have the same digest
    skuld corpus repoint <workspaces…>      after the change: every workspace whose corpus.path is corpus/ but whose
                                            digest is no longer corpus/'s, and whose digest is kept in corpora/, gets
                                            its corpus.path rewritten to the kept copy and nothing else; each is
                                            listed in corpora/<8>-repointed.tsv with the path it had before

A workspace that names a digest no folder of corpora/ holds is reported, not changed: its corpus must be recovered
first (from Git, as on 18 Nov), then kept and repointed.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from skuld import corpus, yamlio

ROOT = Path(__file__).resolve().parents[1]
CORPUS, CORPORA = ROOT / "corpus", ROOT / "corpora"


class CorporaError(Exception):
    """A corpus could not be kept."""


def folder(digest: str, corpora: Path = CORPORA) -> Path:
    """Where the corpus of a digest is kept."""
    return corpora / digest[:8]


def keep(source: Path = CORPUS, corpora: Path = CORPORA) -> tuple[Path, bool]:
    """Keeps the corpus at `source` in corpora/, with its norms; the folder, and whether it was copied now (False: kept
    before, with the same digest)."""
    digest = corpus.load(source).sha256
    target = folder(digest, corpora)
    if target.exists():
        if corpus.load(target).sha256 != digest:
            raise CorporaError(f"{target} holds another corpus than {source} ({digest[:8]}…)")
        return target, False
    target.mkdir(parents=True)
    for path in sorted(source.glob("*.yaml")):
        shutil.copy2(path, target / path.name)
    if (source / corpus.NORMS).is_dir():
        shutil.copytree(source / corpus.NORMS, target / corpus.NORMS)
    if corpus.load(target).sha256 != digest:
        raise CorporaError(f"{target}: the copy's digest differs from {source}'s")
    return target, True


@dataclass
class Repointed:
    workspace: Path  # its assessment.yaml
    before: str
    after: str | None  # None: no kept corpus has its digest; not changed
    digest: str


def _workspaces(given: list[Path]) -> list[Path]:
    out = []
    for g in given:
        g = Path(g)
        if g.is_file() and g.name == "assessment.yaml":
            out.append(g)
        elif (g / "assessment.yaml").is_file():
            out.append(g / "assessment.yaml")
        elif g.is_dir():
            out += sorted(g.glob("**/assessment.yaml"))
    return out


def _rewrite(text: str, path: str) -> str:
    """The assessment.yaml with its corpus.path set, every other byte as it was."""
    lines, inside, done = text.splitlines(keepends=True), False, False
    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")):
            inside = line.rstrip() == "corpus:"
            continue
        if inside and line.lstrip().startswith("path:") and not done:
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f"{indent}path: {path}\n"
            done = True
    if not done:
        raise CorporaError("no corpus.path to rewrite")
    return "".join(lines)


def _listed(path: Path) -> str:
    """A workspace as the log lists it: relative to the suite's root where it lies below it, as on 18 Nov."""
    path = path.resolve()
    return path.relative_to(ROOT.parent).as_posix() if path.is_relative_to(ROOT.parent) else path.as_posix()


def repoint(given: list[Path], source: Path = CORPUS, corpora: Path = CORPORA, write: bool = True) -> list[Repointed]:
    """The workspaces under `given` that name `source` with a digest it no longer has, each repointed to the kept
    corpus of its digest where there is one (unless `write` is False), and logged in corpora/<8>-repointed.tsv."""
    current = corpus.load(source).sha256
    out = []
    for yaml_path in _workspaces(given):
        data = yamlio.load(yaml_path.read_text(encoding="utf-8")) or {}
        named = data.get("corpus") if isinstance(data, dict) else None
        if not isinstance(named, dict) or not named.get("path") or not named.get("sha256"):
            continue
        root = yaml_path.parent
        if (root / named["path"]).resolve() != source.resolve() or named["sha256"] == current:
            continue
        kept = folder(named["sha256"], corpora)
        if not kept.is_dir() or corpus.load(kept).sha256 != named["sha256"]:
            out.append(Repointed(yaml_path, named["path"], None, named["sha256"]))
            continue
        after = Path(os.path.relpath(kept, root)).as_posix()
        out.append(Repointed(yaml_path, named["path"], after, named["sha256"]))
        if write:
            text = yaml_path.read_text(encoding="utf-8")
            yaml_path.write_text(_rewrite(text, after), encoding="utf-8", newline="")
            log = corpora / f"{named['sha256'][:8]}-repointed.tsv"
            new = not log.exists()
            with log.open("a", encoding="utf-8", newline="\n") as f:
                if new:
                    f.write("workspace\tcorpus.path before\n")
                f.write(f"{_listed(yaml_path)}\t{named['path']}\n")
    return out
