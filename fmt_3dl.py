"""Autodesk/Lustre/Flame ``.3dl`` 3D LUT loader.

Layout: an optional first numeric line lists the input mesh node values (its
length = cube size N); then N³ integer ``R G B`` triplets. The Autodesk
convention orders triplets with **blue varying fastest** (then green, then red):
``index = b + g*N + r*N²``. Output integers are normalized by the inferred
bit-depth max (255 / 1023 / 4095 / 65535, whichever first covers the data max).
"""

from __future__ import annotations

import numpy as np

try:
    from .sampler import Lut3D
except ImportError:  # standalone (tests)
    from sampler import Lut3D

_BITDEPTH_MAXES = (255, 1023, 4095, 65535)


def _ints(parts):
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


def load(path: str) -> Lut3D:
    mesh = None
    data: list[list[int]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            ints = _ints(parts)
            if ints is None:
                continue
            if mesh is None and len(ints) > 3:
                mesh = ints  # the input grid line
                continue
            if len(ints) >= 3:
                data.append(ints[:3])

    arr = np.asarray(data, dtype=np.float32)
    n = len(mesh) if mesh else int(round(len(arr) ** (1.0 / 3.0)))
    if n ** 3 != len(arr):
        raise ValueError(f"{path}: expected {n**3} entries, got {len(arr)}")

    data_max = float(arr.max()) if arr.size else 1.0
    maxval = next((m for m in _BITDEPTH_MAXES if data_max <= m), data_max or 1.0)
    arr = arr / maxval

    # blue fastest -> reshape gives [red, green, blue]; reorder to [blue, green, red]
    cube = arr.reshape(n, n, n, 3).transpose(2, 1, 0, 3)
    return Lut3D(np.ascontiguousarray(cube, dtype=np.float32))
