"""`skuld purposes map`: invented purpose nodes placed at the nearest node of the vocabulary, the map kept and grown."""

import json

import pytest

from skuld import purposemap
from skuld.common import PURPOSES, vocabulary


def _workspace(root, *nodes):
    folder = root / "expectation" / "e1" / "s1"
    folder.mkdir(parents=True)
    answer = {"purposes": [{"node": n} for n in nodes]}
    (folder / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
    return root


def _embedder(nearest: dict[str, str]):
    """Each node's document is its own axis; a label's query lies on the axis of the node `nearest` names, a little
    towards the next one (the runner-up)."""
    ids = [n.id for n in vocabulary(PURPOSES)]
    calls = []

    def embed(texts):
        calls.append(len(texts))
        out = []
        for t in texts:
            v = [0.0] * len(ids)
            if t.startswith(purposemap.INSTRUCT):
                i = ids.index(nearest[t.removeprefix(purposemap.INSTRUCT)])
                v[i], v[(i + 1) % len(ids)] = 1.0, 0.5
            else:
                v[len(out)] = 1.0
            out.append(v)
        return out

    return embed, calls


def test_invented_nodes_are_placed_at_the_nearest_node_and_counted(tmp_path):
    ws = _workspace(tmp_path / "w", "Profiling", "Profiling", "Advertising", "?")
    embed, _ = _embedder({"Profiling": "Personalisation"})
    built, new = purposemap.build([ws], tmp_path / "map.json", embed, digest="sha256:x")
    assert new == ["Profiling"]
    entry = built["entries"]["Profiling"]
    assert entry["node"] == "Personalisation" and entry["occurrences"] == 2 and entry["similarity"] > 0.8
    assert entry["runner_up"]["node"] != "Personalisation"
    assert built["vocabulary_version"] == vocabulary(PURPOSES).version and built["embedding_digest"] == "sha256:x"
    assert json.loads((tmp_path / "map.json").read_text(encoding="utf-8")) == built


def test_built_again_the_map_keeps_its_labels_and_embeds_only_new_ones(tmp_path):
    out = tmp_path / "map.json"
    embed, calls = _embedder({"Profiling": "Personalisation", "Tracking": "Advertising"})
    purposemap.build([_workspace(tmp_path / "a", "Profiling")], out, embed)
    calls.clear()
    built, new = purposemap.build([_workspace(tmp_path / "b", "Tracking")], out, embed)
    assert new == ["Tracking"] and set(built["entries"]) == {"Profiling", "Tracking"}
    assert built["entries"]["Profiling"]["occurrences"] == 1  # not seen again: its count is kept
    calls.clear()
    purposemap.build([tmp_path / "b"], out, embed)
    assert calls == []  # nothing new: no model call


def test_a_map_of_another_vocabulary_version_is_not_extended(tmp_path):
    out = tmp_path / "map.json"
    out.write_text(json.dumps({"entries": {}, "vocabulary_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="another version"):
        purposemap.build([], out, _embedder({})[0])
