"""Adobe/DaVinci ``.cube`` loader (treated as 3D here).

`.cube` data is ordered red-fastest, then green, then blue:
``index = r + g*N + b*N²``. Reshaping the flat `[N³, 3]` data as ``(N, N, N, 3)``
therefore yields a cube indexed ``[blue, green, red]`` directly — exactly the
layout the sampler expects. Input domain is assumed to be 0..1 (the norm for
creative LUTs); a non-default DOMAIN is read but not rescaled.
"""

from __future__ import annotations

import numpy as np

try:
    from .sampler import Lut3D, Lut1D
except ImportError:  # standalone (tests)
    from sampler import Lut3D, Lut1D


def load(path: str):
    size3d = size1d = None
    title = ""
    data: list[list[float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            up = s.upper()
            if up.startswith("TITLE"):
                title = s.split('"')[1] if '"' in s else s[5:].strip()
                continue
            if up.startswith("LUT_3D_SIZE"):
                size3d = int(s.split()[-1]); continue
            if up.startswith("LUT_1D_SIZE"):
                size1d = int(s.split()[-1]); continue
            if up.startswith(("DOMAIN_MIN", "DOMAIN_MAX", "LUT_3D_INPUT_RANGE",
                              "LUT_1D_INPUT_RANGE")):
                continue
            parts = s.split()
            if len(parts) >= 3:
                try:
                    data.append([float(parts[0]), float(parts[1]), float(parts[2])])
                except ValueError:
                    continue

    arr = np.asarray(data, dtype=np.float32)

    if size1d and not size3d:
        return Lut1D(arr.reshape(size1d, 3), title=title)

    n = size3d if size3d else int(round(len(arr) ** (1.0 / 3.0)))
    if n ** 3 != len(arr):
        raise ValueError(f"{path}: expected {n**3} entries, got {len(arr)}")
    cube = arr.reshape(n, n, n, 3)  # [blue, green, red, 3]
    return Lut3D(np.ascontiguousarray(cube, dtype=np.float32), title=title)
