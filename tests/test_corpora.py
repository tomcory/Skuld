"""Earlier corpora kept and workspaces repointed to them (the step of 18 Nov 2026 as `skuld corpus keep | repoint`)."""

import shutil
from pathlib import Path

import pytest

from skuld import corpora, corpus
from skuld.cli import main

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


@pytest.fixture
def suite(tmp_path):
    """A corpus, an empty corpora/ and a workspace naming the corpus by its digest."""
    source, kept = tmp_path / "corpus", tmp_path / "corpora"
    shutil.copytree(CORPUS, source)
    kept.mkdir()
    ws = tmp_path / "cases" / "app@1"
    ws.mkdir(parents=True)
    digest = corpus.load(source).sha256
    (ws / "assessment.yaml").write_text(
        f"# a comment that stays\napplication: app\ncorpus:\n  path: ../../corpus\n  sha256: {digest}\nmodels: {{}}\n",
        encoding="utf-8",
    )
    return source, kept, ws, digest


def test_a_corpus_is_kept_under_its_digest_with_its_norms(suite):
    source, kept, _, digest = suite
    target, copied = corpora.keep(source, kept)
    assert copied and target == kept / digest[:8] and corpus.load(target).sha256 == digest
    assert (target / corpus.NORMS).is_dir()
    assert corpora.keep(source, kept) == (target, False)  # kept before: nothing copied


def test_after_a_change_the_workspaces_that_named_it_are_repointed_and_logged(suite):
    source, kept, ws, digest = suite
    corpora.keep(source, kept)
    next(source.glob("*.yaml")).unlink()  # the corpus changes
    (moved,) = corpora.repoint([ws.parent], source, kept)
    assert (moved.before, moved.after) == ("../../corpus", f"../../corpora/{digest[:8]}")
    text = (ws / "assessment.yaml").read_text(encoding="utf-8")
    assert text.startswith("# a comment that stays\n") and f"  path: ../../corpora/{digest[:8]}\n" in text
    assert f"  sha256: {digest}\n" in text
    log = (kept / f"{digest[:8]}-repointed.tsv").read_text(encoding="utf-8").splitlines()
    assert log[0] == "workspace\tcorpus.path before" and log[1].endswith("app@1/assessment.yaml\t../../corpus")
    assert corpora.repoint([ws.parent], source, kept) == []  # it no longer names corpus/


def test_a_workspace_whose_corpus_was_not_kept_is_reported_not_changed(suite):
    source, kept, ws, digest = suite
    before = (ws / "assessment.yaml").read_text(encoding="utf-8")
    next(source.glob("*.yaml")).unlink()
    (orphan,) = corpora.repoint([ws], source, kept)
    assert orphan.after is None and orphan.digest == digest
    assert (ws / "assessment.yaml").read_text(encoding="utf-8") == before


def test_a_workspace_of_the_current_corpus_is_left_alone(suite):
    source, kept, ws, _ = suite
    assert corpora.repoint([ws], source, kept) == []


def test_the_command_lists_and_fails_on_an_orphan(suite, capsys):
    source, _, ws, _ = suite
    next(source.glob("*.yaml")).unlink()
    assert main(["corpus", "repoint", str(ws), "--corpus", str(source), "--dry-run"]) == 1
    assert "name a corpus not kept" in capsys.readouterr().out
