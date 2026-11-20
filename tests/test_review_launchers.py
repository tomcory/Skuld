"""
The Windows launchers of a reviewer's package (skuld.review_export: start-<sample>.bat, pack-reviews.bat), checked on
the computer the package is made on, which has no Windows: their line endings, their quoting, that what they name is in
the package, and that they use no syntax of a Unix shell. They have not been run on Windows here.
"""

import json
import re
import zipfile

import pytest

from skuld import review_expectation as rx
from skuld import review_export as rex
from tests.test_review_expectation import workspace

NAMES = ["expect-1", "concerns_2"]
#: The commands the .bat files may start a line with: cmd's own, and node and powershell, which the guide asks for
#: (Node.js) or which Windows has
WINDOWS = {"@echo", "rem", "cd", "where", "start", "set", "node", "pause", "powershell", "echo"}
#: What would be a Unix shell's, not cmd's
UNIX = ("#!", "$(", "`", "/dev/null", "export ", "./", "~/", "rm -", "sleep ", "xdg-open", "command -v", "chmod", ";;")


def bats(names=NAMES, reviewer="a"):
    return {arc: data for arc, data in rex.scripts(reviewer, names).items() if arc.endswith(".bat")}


def test_the_bat_files_have_windows_line_endings_and_are_plain_ascii():
    found = bats()
    assert set(found) == {f"start-{n}.bat" for n in NAMES} | {"pack-reviews.bat"}
    for arc, data in found.items():
        assert data.count(b"\n") == data.count(b"\r\n") > 3, arc  # every line ends CRLF, none LF alone
        assert data.endswith(b"\r\n") and b"\r\r" not in data
        assert data.isascii(), arc  # cmd reads a .bat in the console's code page
        assert data.startswith(b"@echo off\r\n")
    # the other launchers keep LF
    for arc, data in rex.scripts("a", NAMES).items():
        if not arc.endswith(".bat"):
            assert b"\r" not in data, arc


def test_the_bat_files_use_no_unix_shell_syntax():
    for arc, data in bats().items():
        text = data.decode()
        for token in UNIX:
            assert token not in text, f"{arc}: {token!r}"
        # cmd expands %…%: the only one is the batch file's own folder
        assert "%" not in text.replace("%~dp0", ""), arc
        for line in text.splitlines():
            assert line.split()[0] in WINDOWS, f"{arc}: {line}"
            assert line.count('"') % 2 == 0, f"{arc}: unbalanced quotes in {line}"
            assert not line.rstrip().endswith("\\"), f"{arc}: a Unix line continuation"


def quoted_spans(line: str) -> list[tuple[int, int]]:
    return [m.span() for m in re.finditer(r'"[^"]*"', line)]


def test_the_bat_files_quote_their_paths():
    for arc, data in bats().items():
        text = data.decode()
        assert 'cd /d "%~dp0"' in text, arc  # the package's folder, wherever it was unpacked (spaces included)
        for line in text.splitlines():
            spans = quoted_spans(line)
            for m in re.finditer(r"samples[\\/]", line):
                assert any(a < m.start() < b for a, b in spans), f"{arc}: unquoted path in {line}"
    for n, port in zip(NAMES, range(rex.PORT, rex.PORT + len(NAMES)), strict=True):
        start = bats()[f"start-{n}.bat"].decode()
        assert f'node tool\\server.js "samples\\{n}"' in start
        assert f"set PORT={port}\r\n" in start and f"start http://localhost:{port}" in start
    pack = bats()["pack-reviews.bat"].decode()
    # each path the packer lists is quoted for PowerShell too, inside the double-quoted -Command
    for n in NAMES:
        for f in rex.RETURNED:
            assert f"'samples/{n}/{f}'" in pack
    assert "'reviews-a.zip'" in pack and "tar.exe -a -c -f 'reviews-a.zip'" in pack


@pytest.fixture
def drawn(tmp_path):
    runs = [workspace(tmp_path, "model-x"), workspace(tmp_path, "model-y")]
    folders = []
    for name in NAMES:
        folder = tmp_path / "reviews" / name
        rx.draw(folder, runs, per_stratum=5, seed=2)
        folders.append(folder)
    return folders


@pytest.mark.skipif(not (rex.TOOL / "node_modules").is_dir(), reason="the review tool's modules are not installed")
def test_what_the_bat_files_name_is_in_the_exported_package(tmp_path, drawn):
    out = rex.export(tmp_path / "pkg.zip", drawn, "a")
    root = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as z:
        z.extractall(root)
    package = root / "asgard-review-a"
    for n in NAMES:
        start = (package / f"start-{n}.bat").read_bytes()
        assert start == rex.scripts("a", NAMES)[f"start-{n}.bat"]  # as tested above, CRLF kept by the zip
        [(script, sample)] = re.findall(r'^node (\S+) "([^"]+)"\r$', start.decode(), re.M)
        assert (package / script.replace("\\", "/")).is_file()
        assert (package / sample.replace("\\", "/") / "sample.json").is_file()
    pack = (package / "pack-reviews.bat").read_text(encoding="ascii")
    listed = re.findall(r"'([^']+)'", pack.split("Where-Object")[0])
    assert listed[0] == "reviewer.json" and (package / "reviewer.json").is_file()
    for path in listed[1:]:
        # the returned files are written by the tool later: their sample folder is there
        assert path.rsplit("/", 1)[1] in rex.RETURNED and (package / path).parent.is_dir()
    assert {s["name"] for s in json.loads((package / "reviewer.json").read_text())["samples"]} == set(NAMES)
    # the server takes the port and the sample as the launcher gives them
    server = (package / "tool" / "server.js").read_text(encoding="utf-8")
    assert "process.env.PORT" in server and "process.argv[2]" in server


@pytest.mark.skipif(not (rex.TOOL / "node_modules").is_dir(), reason="the review tool's modules are not installed")
def test_a_sample_whose_name_the_launchers_and_the_import_cannot_take_is_not_exported(tmp_path, drawn):
    spaced = drawn[0].rename(drawn[0].with_name("expect 1"))
    with pytest.raises(rex.ReviewError, match="folder name"):
        rex.export(tmp_path / "pkg.zip", [spaced], "a")
