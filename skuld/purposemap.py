"""
`skuld purposes map`: the purpose map, which places the purpose nodes the models invented in stage-1 answers (outside
the purpose vocabulary, e.g. "Profiling") at the nearest node of the vocabulary by semantic similarity (author,
11 Nov 2026). Built until 20 Nov 2026 by `expectation-paper/study-2026-11/build_purpose_map.py`, whose method this is.

    labels        every node of the workspaces' stage-1 answers that is no node of the vocabulary, with how often
    embeddings    an embedding model (default qwen3-embedding:8b-fp16, Ollama's /api/embed): the query is the invented
                  label after an instruction, the documents are each node's title and description
    the map       per label the node of greatest cosine similarity, its similarity and the runner-up; with the model,
                  its digest, the instruction, the vocabulary's version and digest, and when it was built

Built again over more workspaces, the map keeps every label it has (so that what was read with it reads the same) and
adds the new ones; the occurrences are counted again. config.json's `purpose_map` names the map that stage 1's
answers are read with (a path, or {path, sha256}), and every mapped purpose names its digest.
"""

import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from skuld.common import PURPOSES, vocabulary

MODEL = "qwen3-embedding:8b-fp16"
INSTRUCT = (
    "Instruct: Given the name of a purpose for processing personal data, retrieve the matching purpose category\n"
    "Query: "
)
METHOD = "nearest dpv-purposes node by cosine similarity of embeddings (author, 11 Nov 2026)"
#: Texts per embedding request
BATCH = 32

Embed = Callable[[list[str]], list[list[float]]]


def labels(workspaces: list[Path]) -> Counter:
    """How often each invented node occurs in the stage-1 answers of the workspaces (every attempt and top-up)."""
    vocab = vocabulary(PURPOSES)
    found: Counter = Counter()
    for root in workspaces:
        for path in sorted(Path(root).glob("expectation/**/answer.json")):
            try:
                answer = json.loads(path.read_text(encoding="utf-8") or "{}")
            except ValueError:
                continue
            for p in (answer.get("purposes") or []) if isinstance(answer, dict) else []:
                node = p.get("node") if isinstance(p, dict) else None
                if isinstance(node, str) and node and node != "?" and node not in vocab:
                    found[node] += 1
    return found


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def vocabulary_sha256() -> str:
    """The purpose vocabulary's digest, as the map records it."""
    return hashlib.sha256(
        json.dumps(vocabulary(PURPOSES).reference(), sort_keys=True, default=str).encode()
    ).hexdigest()


def build(
    workspaces: list[Path], out: Path, embed: Embed, model: str = MODEL, digest: str | None = None
) -> tuple[dict, list[str]]:
    """The map in `out` with the workspaces' new labels added, written there, and the labels added."""
    vocab = vocabulary(PURPOSES)
    found = labels(workspaces)
    kept = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {"entries": {}}
    if kept.get("vocabulary_sha256") not in (None, vocabulary_sha256()):
        raise ValueError(f"{out} was built on another version of {PURPOSES}; build a new map for {vocab.version}")
    new = sorted(label for label in found if label not in kept["entries"])
    if new:
        nodes = list(vocab)
        documents = embed([f"{n.title}: {n.description or ''}".strip() for n in nodes])
        queries = embed([INSTRUCT + label for label in new])
        for label, q in zip(new, queries, strict=True):
            ranked = sorted(((cosine(q, d), n.id) for n, d in zip(nodes, documents, strict=True)), reverse=True)
            kept["entries"][label] = {
                "node": ranked[0][1],
                "similarity": round(ranked[0][0], 4),
                "runner_up": {"node": ranked[1][1], "similarity": round(ranked[1][0], 4)},
            }
    for label, entry in kept["entries"].items():
        entry["occurrences"] = found.get(label, entry.get("occurrences", 0))
    kept.update(
        {
            "method": METHOD,
            "embedding_model": model,
            "embedding_digest": digest if digest is not None else kept.get("embedding_digest"),
            "instruction": INSTRUCT,
            "vocabulary": PURPOSES,
            "vocabulary_version": vocab.version,
            "vocabulary_sha256": vocabulary_sha256(),
            "built": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kept, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return kept, new


def ollama_embedder(model: str = MODEL) -> tuple[Embed, str | None]:
    """An embedding function on the Ollama server Ratatoskr's environment names (OLLAMA_BASE_URL, OLLAMA_API_KEY),
    and the model's digest there."""
    import ollama
    from ratatoskr import env

    key = env.api_key("ollama")
    client = ollama.Client(
        host=env.base_url("ollama") or "http://localhost:11434",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        timeout=600,
    )

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out += [list(e) for e in client.embed(model=model, input=texts[i : i + BATCH]).embeddings]
        return out

    digest = next((m.digest for m in client.list().models if m.model == model), None)
    return embed, digest
