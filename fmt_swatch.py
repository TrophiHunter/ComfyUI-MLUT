"""Swatch / palette loaders: ``.act``, ``.aco``, ``.ase``, and palette PNGs.

All return a ``Palette`` ([K,3] float RGB in 0..1, optional names/groups). Binary
formats are big-endian. Color-space conversions (HSB / CMYK / Lab / Gray ->
sRGB) are applied so every palette ends up in RGB.
"""

from __future__ import annotations

import struct

import numpy as np

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    from .sampler import Palette
except ImportError:  # standalone (tests)
    from sampler import Palette


# ---------------------------------------------------------------------------
# Color-space conversions (-> sRGB 0..1)
# ---------------------------------------------------------------------------

def _hsb_to_rgb(h, s, v):
    import colorsys
    return colorsys.hsv_to_rgb(h, s, v)


def _cmyk_to_rgb(c, m, y, k):
    return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))


def _lab_to_rgb(L, a, b):
    # Lab (D65) -> XYZ -> linear sRGB -> sRGB
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    def inv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787

    xr, yr, zr = inv(fx), inv(fy), inv(fz)
    x, y, z = xr * 0.95047, yr * 1.0, zr * 1.08883

    r = x * 3.2406 - y * 1.5372 - z * 0.4986
    g = -x * 0.9689 + y * 1.8758 + z * 0.0415
    bl = x * 0.0557 - y * 0.2040 + z * 1.0570

    def gamma(u):
        u = max(0.0, min(1.0, u))
        return 1.055 * (u ** (1 / 2.4)) - 0.055 if u > 0.0031308 else 12.92 * u

    return (gamma(r), gamma(g), gamma(bl))


def _finish(colors, names=None, groups=None) -> Palette:
    arr = np.asarray(colors, dtype=np.float32).reshape(-1, 3)
    return Palette(np.clip(arr, 0.0, 1.0), names=names, groups=groups or {})


# ---------------------------------------------------------------------------
# .act  (Adobe Color Table: 256 RGB triplets, optional trailing count)
# ---------------------------------------------------------------------------

def _load_act(path: str) -> Palette:
    data = open(path, "rb").read()
    count = 256
    if len(data) >= 772:
        count = struct.unpack(">H", data[768:770])[0]
        if not (1 <= count <= 256):
            count = 256
    cols = np.frombuffer(data[:768], dtype=np.uint8).reshape(256, 3)[:count]
    return _finish(cols.astype(np.float32) / 255.0)


# ---------------------------------------------------------------------------
# .aco  (Photoshop swatches; parse v1 block for colors)
# ---------------------------------------------------------------------------

def _load_aco(path: str) -> Palette:
    data = open(path, "rb").read()
    ver, count = struct.unpack(">HH", data[:4])
    if ver != 1:
        # Some writers omit v1; fall back to treating the head as count-only.
        count = struct.unpack(">H", data[2:4])[0]
    off = 4
    colors = []
    for _ in range(count):
        if off + 10 > len(data):
            break
        space, w, x, y, z = struct.unpack(">HHHHH", data[off:off + 10])
        off += 10
        if space == 0:      # RGB
            colors.append((w / 65535.0, x / 65535.0, y / 65535.0))
        elif space == 1:    # HSB
            colors.append(_hsb_to_rgb(w / 65535.0, x / 65535.0, y / 65535.0))
        elif space == 2:    # CMYK (0 = 100% ink)
            colors.append(_cmyk_to_rgb(1 - w / 65535.0, 1 - x / 65535.0,
                                       1 - y / 65535.0, 1 - z / 65535.0))
        elif space == 7:    # Lab
            a_s = w - 65536 if w >= 32768 else w  # not used; L is unsigned below
            L = w / 100.0
            aa = (x - 65536 if x >= 32768 else x) / 100.0
            bb = (y - 65536 if y >= 32768 else y) / 100.0
            colors.append(_lab_to_rgb(L, aa, bb))
        elif space == 8:    # Grayscale
            g = w / 10000.0
            colors.append((g, g, g))
        else:               # unknown -> approximate as RGB-ish
            colors.append((w / 65535.0, x / 65535.0, y / 65535.0))
    return _finish(colors)


# ---------------------------------------------------------------------------
# .ase  (Adobe Swatch Exchange; color entries + groups)
# ---------------------------------------------------------------------------

def _load_ase(path: str) -> Palette:
    data = open(path, "rb").read()
    if data[:4] != b"ASEF":
        raise ValueError(f"{path}: not an ASE file")
    nblocks = struct.unpack(">I", data[8:12])[0]
    off = 12
    colors, names, groups = [], [], {}
    current_group = None

    for _ in range(nblocks):
        if off + 6 > len(data):
            break
        btype, blen = struct.unpack(">HI", data[off:off + 6])
        body = data[off + 6:off + 6 + blen]
        off += 6 + blen

        if btype == 0xC002:  # group end
            current_group = None
            continue

        # name (uint16 char count incl. null) then UTF-16BE
        p = 0
        name = ""
        if len(body) >= 2:
            nlen = struct.unpack(">H", body[:2])[0]
            p = 2 + nlen * 2
            name = body[2:p - 2].decode("utf-16-be", "replace") if nlen else ""

        if btype == 0xC001:  # group start
            current_group = name or f"group_{len(groups)}"
            groups.setdefault(current_group, [])
            continue

        if btype == 0x0001:  # color entry
            model = body[p:p + 4].decode("ascii", "replace").strip()
            p += 4
            if model == "RGB":
                r, g, b = struct.unpack(">fff", body[p:p + 12])
                rgb = (r, g, b)
            elif model == "CMYK":
                c, m, y, k = struct.unpack(">ffff", body[p:p + 16])
                rgb = _cmyk_to_rgb(c, m, y, k)
            elif model == "LAB":
                L, a, b = struct.unpack(">fff", body[p:p + 12])
                if L <= 1.0:
                    L *= 100.0
                rgb = _lab_to_rgb(L, a, b)
            elif model == "GRAY":
                (g,) = struct.unpack(">f", body[p:p + 4])
                rgb = (g, g, g)
            else:
                rgb = (0.0, 0.0, 0.0)
            idx = len(colors)
            colors.append(rgb)
            names.append(name)
            if current_group is not None:
                groups[current_group].append(idx)

    return _finish(colors, names=names, groups=groups)


# ---------------------------------------------------------------------------
# palette PNG (every pixel is a swatch color; dedupe, keep first-seen order)
# ---------------------------------------------------------------------------

def _load_png(path: str) -> Palette:
    if Image is None:
        raise RuntimeError("Pillow is required to load palette PNGs.")
    a = np.asarray(Image.open(path).convert("RGB")).reshape(-1, 3)
    _, first = np.unique(a, axis=0, return_index=True)
    cols = a[np.sort(first)]
    return _finish(cols.astype(np.float32) / 255.0)


# ---------------------------------------------------------------------------

_DISPATCH = {
    ".act": _load_act,
    ".aco": _load_aco,
    ".ase": _load_ase,
    ".png": _load_png,
}


def load(path: str) -> Palette:
    ext = path[path.rfind("."):].lower()
    fn = _DISPATCH.get(ext)
    if fn is None:
        raise ValueError(f"Unsupported swatch format: {ext}")
    return fn(path)
