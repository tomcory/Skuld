"""
The review tool (tools/calibration-review/server.js) on a review of aggregated concerns: a unit of declared purposes is
served with its phrases only until each is judged blind, and the blind judgments are kept apart and never changed. Runs
the tool with Node.js; skipped where Node.js or the tool's modules are not installed.
"""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from skuld import review
from skuld import review_export as rex
from skuld.calibrate import file_sha256
from tests.test_review import FRAME, assessment, workspace

pytestmark = pytest.mark.skipif(
    not shutil.which("node") or not (rex.TOOL / "node_modules").is_dir(),
    reason="Node.js or the review tool's modules are not installed",
)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "_frame", lambda root: FRAME)
    monkeypatch.setattr(review, "copy_documents", lambda root, target: [])
    runs = [workspace(tmp_path, "model-x", assessment()), workspace(tmp_path, "model-y", assessment(("criteo",)))]
    folder = tmp_path / "review"
    review.draw(folder, runs, per_stratum=5, seed=3)
    return folder


def serve(folder):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        ["node", str(rex.TOOL / "server.js"), str(folder)],
        env={"PATH": os.environ["PATH"], "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/api"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/progress", timeout=1)
            return proc, base
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("the review tool did not start")


def call(base, path, method="GET", body=None):
    request = urllib.request.Request(
        f"{base}{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def tool(sample):
    proc, base = serve(sample)
    yield sample, base
    proc.kill()
    proc.wait()


def declared(folder):
    items = json.loads((folder / review.SAMPLE).read_text())["items"]
    index = next(n for n, i in enumerate(items) if i["kind"] == "declared")
    return index, items[index]


def test_the_phrases_are_judged_blind_before_es_output_is_shown(tool):
    folder, base = tool
    index, item = declared(folder)
    first, second = (m["concern"] for m in item["members"])
    status, shown = call(base, f"/items/{index}")
    assert status == 200 and shown["blind_phrases_now"]
    assert [m["statement"] for m in shown["members"]] == [p["statement"] for p in item["blind_phrases"]]
    # none of E's output: its status, label, reasons, evidence
    assert not {"status", "label", "evidence", "tier", "uncertainty"} & set(shown)
    assert all(set(m) == {"concern", "statement"} for m in shown["members"])

    status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"evidence": "yes"})
    assert status == 409
    status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"blind_phrases": {"phrases": {first: "specific"}}})
    assert status == 400  # every phrase is judged at once
    blind = {first: "not_specific", second: "specific"}
    status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"blind_phrases": {"phrases": blind, "note": "n"}})
    assert status == 200

    status, shown = call(base, f"/items/{index}")
    assert "blind_phrases_now" not in shown and shown["status"] == "supported" and shown["label"]
    # the blind judgments are never changed; the non-blind phrases are kept apart and give the verdict
    call(base, f"/reviews/{item['id']}", "PUT", {"blind_phrases": {"phrases": {first: "specific", second: "specific"}}})
    after = {first: "not_specific", second: "not_specific"}
    status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"phrases": after, "evidence": "yes", "follows": "yes"})
    assert status == 200
    saved = json.loads((folder / review.REVIEWS).read_text())[item["id"]]
    assert saved["blind_phrases"]["phrases"] == blind and saved["blind_phrases"]["note"] == "n"
    assert saved["phrases"] == after and saved["overall"] == "agree"
    # removing the judgment keeps the blind phrases: the unit has been seen with E's output since
    call(base, f"/reviews/{item['id']}", "DELETE")
    assert json.loads((folder / review.REVIEWS).read_text())[item["id"]] == {"blind_phrases": saved["blind_phrases"]}


def test_a_sample_drawn_before_shows_declared_purposes_as_it_did(sample):
    data = json.loads((sample / review.SAMPLE).read_text())
    for i in data["items"]:
        i.pop("blind_phrases", None)
    (sample / review.SAMPLE).write_text(json.dumps(data))
    manifest = json.loads((sample / review.MANIFEST).read_text())
    manifest["files"][review.SAMPLE] = file_sha256(sample / review.SAMPLE)
    (sample / review.MANIFEST).write_text(json.dumps(manifest))
    proc, base = serve(sample)
    try:
        index, item = declared(sample)
        _, shown = call(base, f"/items/{index}")
        assert "blind_phrases_now" not in shown and shown["status"] == "supported"
        phrases = {m["concern"]: "not_specific" for m in item["members"]}
        status, _ = call(
            base, f"/reviews/{item['id']}", "PUT", {"phrases": phrases, "evidence": "yes", "follows": "yes"}
        )
        assert status == 200
        status, _ = call(base, f"/reviews/{item['id']}", "PUT", {"blind_phrases": {"phrases": phrases}})
        assert status == 400  # no phrases to judge blind in such a sample
    finally:
        proc.kill()
        proc.wait()
    assert review.score(sample)["blind_phrases"]["units"] == 0
