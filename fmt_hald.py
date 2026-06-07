"""HALD CLUT PNG loader.

A Hald CLUT of level L is a square image of side ``S = L³`` encoding a cube of
size ``N = L²`` (so ``S = N^1.5`` and ``S² = N³``). Pixels are laid out
row-major in red-fastest order (``index = r + g*N + b*N²``), so flattening the
image and reshaping to ``(N, N, N, 3)`` yields the cube indexed ``[blue, green,
red]`` directly.
"""

from __future__ import annotations

import numpy as np

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    from .sampler import Lut3D
except ImportError:  # standalone (tests)
    from sampler import Lut3D


def load(path: str) -> Lut3D:
    if Image is None:
        raise RuntimeError("Pillow is required to load HALD PNGs.")
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    if h != w:
        raise ValueError(f"{path}: HALD CLUT must be square, got {w}x{h}")

    n = int(round(h ** (2.0 / 3.0)))  # cube size = L², side = L³
    if n ** 3 != h * w:
        raise ValueError(f"{path}: side {h} is not a valid HALD size (need N**1.5)")

    cube = a.reshape(-1, 3).reshape(n, n, n, 3)  # row-major -> [blue, green, red, 3]
    return Lut3D(np.ascontiguousarray(cube, dtype=np.float32))
