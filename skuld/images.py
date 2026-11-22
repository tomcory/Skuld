"""
Screenshots for a model (0.12.4): the screens' PNGs of a Loki run, shrunk so that a request carries them cheaply.

As Loki sends its agent's screenshots (`loki/llm.py` `fit_images`): JPEG at quality 75, the longest side at most
`MAX_SIDE` pixels, and together under `BUDGET_BYTES`, shrunk further step by step (down to `MIN_SIDE`) where they are
not. A stage-1 request carries at most `MAX_IMAGES` (the SNET gateway's limit per request, docs/INFERENCE_GUIDE.md).
The context names each image by the digest of the screenshot file as Loki wrote it (`digest`), so the sample's
identity does not depend on the encoding.
"""

import hashlib
import io
from pathlib import Path

#: The images a request carries at most (the gateway takes 8 per request)
MAX_IMAGES = 8
MAX_SIDE, MIN_SIDE = 896, 320
#: The images of one request together, encoded (the gateway takes request bodies up to 100 MB)
BUDGET_BYTES = 3_000_000
QUALITY = 75
MIME = "image/jpeg"


def digest(path: Path) -> str:
    """The sha256 of a screenshot file as Loki wrote it."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _encode(data: bytes, side: int) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        image.thumbnail((side, side))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=QUALITY, optimize=True)
        return out.getvalue()


def prepare(paths: list[Path]) -> list[bytes]:
    """The screenshots at `paths`, in order, as JPEG bytes that fit the budget together."""
    raw = [Path(p).read_bytes() for p in paths[:MAX_IMAGES]]
    side = MAX_SIDE
    while True:
        encoded = [_encode(data, side) for data in raw]
        if sum(map(len, encoded)) <= BUDGET_BYTES or side <= MIN_SIDE:
            return encoded
        side = max(MIN_SIDE, int(side * 0.8))


def spread(n: int, k: int = MAX_IMAGES) -> list[int]:
    """`k` indices of `n` items spread evenly over them, first and last included (all where n <= k)."""
    if n <= k:
        return list(range(n))
    if k == 1:
        return [0]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
