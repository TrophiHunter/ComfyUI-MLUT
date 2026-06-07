"""ReShade-style strip-LUT PNG loader.

A strip lays the N blue slices of an N³ cube side by side. Two orientations:
  * horizontal: ``W = N²``, ``H = N`` (tile b at columns [b*N, b*N+N), red across
    a tile's width, green down its height) — identical to a single MLUT band.
  * vertical:   ``H = N²``, ``W = N``.
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
        raise RuntimeError("Pillow is required to load strip PNGs.")
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]

    if w == h * h:        # horizontal: pixel (g, b*N + r) -> reshape [g, b, r] -> [b, g, r]
        n = h
        cube = a.reshape(n, n, n, 3).transpose(1, 0, 2, 3)
    elif h == w * w:      # vertical: pixel (b*N + g, r) -> reshape [b, g, r] directly
        n = w
        cube = a.reshape(n, n, n, 3)
    else:
        raise ValueError(f"{path}: {w}x{h} is not a strip (need W=H² or H=W²)")

    return Lut3D(np.ascontiguousarray(cube, dtype=np.float32))
