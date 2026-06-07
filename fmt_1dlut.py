"""``.1dlut`` per-channel 1D LUT loader.

Many tools save 1D LUTs in the same text shape as a `.cube` 1D LUT — a header
(``LUT_1D_SIZE N``, optional ``TITLE`` / ``DOMAIN_*``) followed by ``N`` data
lines of one value (applies to all channels) or three values (R G B per
channel). This loader handles both that header-style format and bare value
lists, and is tolerant of comments. Values are normalized if they look like
8/10/12/16-bit integers.

Crucially, parsing is **all-or-nothing per line**: any non-numeric token on a
line discards the whole line, so a stray ``LUT_1D_SIZE 4096`` header never
contributes ``4096`` as a phantom sample (which would otherwise dominate the
auto-normalization and collapse the whole curve to ~0).
"""

from __future__ import annotations

import numpy as np

try:
    from .sampler import Lut1D
except ImportError:  # standalone (tests)
    from sampler import Lut1D

_COMMENT_PREFIXES = ("#", ";", "//")
_HEADER_PREFIXES = (
    "LUT_1D_SIZE", "LUT_3D_SIZE", "TITLE",
    "DOMAIN_MIN", "DOMAIN_MAX",
    "LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE",
)


def load(path: str) -> Lut1D:
    size_decl: int | None = None
    rows: list[list[float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith(_COMMENT_PREFIXES):
                continue
            up = s.upper()
            if up.startswith("LUT_1D_SIZE"):
                try:
                    size_decl = int(s.split()[-1])
                except ValueError:
                    pass
                continue
            if up.startswith(_HEADER_PREFIXES):
                continue
            # all-or-nothing: any non-numeric token -> skip the whole line.
            parts = s.replace(",", " ").split()
            try:
                vals = [float(t) for t in parts]
            except ValueError:
                continue
            if vals:
                rows.append(vals)

    if not rows:
        raise ValueError(f"{path}: no numeric data found")

    if all(len(r) >= 3 for r in rows):
        arr = np.asarray([r[:3] for r in rows], dtype=np.float32)
    else:
        arr = np.asarray([[r[0]] * 3 for r in rows], dtype=np.float32)

    if size_decl and len(arr) != size_decl:
        print(f"[MLUT] {path}: LUT_1D_SIZE declared {size_decl} but got {len(arr)} entries.")

    m = float(arr.max()) if arr.size else 1.0
    if m > 1.001:
        denom = next((d for d in (255.0, 1023.0, 4095.0, 65535.0) if m <= d), m)
        arr = arr / denom

    return Lut1D(np.ascontiguousarray(arr, dtype=np.float32))
