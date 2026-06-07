"""
MLUT data layer: discover LUT packs, parse their ReShade `.fx` configs, and
build 3D LUT cubes from the PNG atlases.

Each `.fx` file in `Shaders/` is a thin config consumed by `_BaseLUT.fxh`. It
declares the atlas geometry and the names of every LUT baked into the matching
`.png` in `Textures/`:

    #define fLUT_TileSizeXY 32   -> N : cube resolution (R/G size, per-tile px)
    #define fLUT_TileAmount 32   -> T : number of blue slices laid out in X
    #define fLUT_LutAmount  40   -> L : number of LUTs stacked in Y
    #define fLUT_TextureName "....png"
    #define fLUT_LutList " name a\0 name b\0 ..."   -> L names

Atlas pixel layout (W = N*T, H = N*L), for LUT band ``sel``:
    rows  [sel*N, sel*N + N)
    blue slice b -> columns [b*N, b*N + N)
    inside a tile: column = red index (0..N-1), row = green index (0..N-1)
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import numpy as np

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow ships with ComfyUI
    Image = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
SHADERS_DIR = os.path.join(_HERE, "Shaders")
TEXTURES_DIR = os.path.join(_HERE, "Textures")
_CACHE_FILE = os.path.join(_HERE, "mlut_index.json")
# Bump whenever the parse format / cache schema changes, so stale caches written
# by an older build are invalidated even if the Shaders folder is unchanged.
_CACHE_VERSION = 2

# ---------------------------------------------------------------------------
# .fx parsing
# ---------------------------------------------------------------------------

_INT_DEFINE = lambda key: re.compile(  # noqa: E731
    r"#define\s+" + re.escape(key) + r"\s+(\d+)"
)
_STR_DEFINE = lambda key: re.compile(  # noqa: E731
    r'#define\s+' + re.escape(key) + r'\s+"([^"]*)"'
)


def parse_fx(path: str) -> dict | None:
    """Parse one `.fx` config into ``{png, N, T, L, names}`` or ``None``."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None

    def _int(key):
        m = _INT_DEFINE(key).search(text)
        return int(m.group(1)) if m else None

    n = _int("fLUT_TileSizeXY")
    t = _int("fLUT_TileAmount")
    l = _int("fLUT_LutAmount")

    png_m = _STR_DEFINE("fLUT_TextureName").search(text)
    # The LUT list is a single-line quoted literal with no embedded quotes, so
    # [^"]* stops cleanly at its own closing quote (it must NOT run on to the
    # next #define's string, which a greedy/DOTALL match would do).
    list_m = _STR_DEFINE("fLUT_LutList").search(text)

    if None in (n, t, l) or png_m is None or list_m is None:
        return None

    # LUT names are a single null-(\0)-separated string literal. The literal
    # backslash-zero sequences survive in the source as the two chars "\0".
    raw = list_m.group(1)
    names = [seg.strip() for seg in raw.split(r"\0")]
    names = [seg for seg in names if seg]  # drop empty leading/trailing splits

    return {"png": png_m.group(1), "N": n, "T": t, "L": l, "names": names}


# ---------------------------------------------------------------------------
# Pack discovery (cached to JSON)
# ---------------------------------------------------------------------------


def _build_index() -> dict:
    index: dict[str, dict] = {}
    if not os.path.isdir(SHADERS_DIR):
        return index
    for fname in sorted(os.listdir(SHADERS_DIR)):
        if not fname.lower().endswith(".fx"):
            continue
        meta = parse_fx(os.path.join(SHADERS_DIR, fname))
        if meta is None:
            continue
        # Verify the atlas actually exists before offering the pack.
        if not os.path.isfile(os.path.join(TEXTURES_DIR, meta["png"])):
            continue
        pack = os.path.splitext(fname)[0]
        index[pack] = meta
    return index


def _dir_signature() -> dict:
    """Cheap fingerprint of the Shaders folder: number of `.fx` files and the
    newest `.fx` mtime. Adding, removing, or editing a pack changes this, which
    is how we detect that the cached index is stale on the next startup."""
    count = 0
    latest = 0.0
    try:
        for fname in os.listdir(SHADERS_DIR):
            if fname.lower().endswith(".fx"):
                count += 1
                m = os.path.getmtime(os.path.join(SHADERS_DIR, fname))
                if m > latest:
                    latest = m
    except OSError:
        pass
    return {"count": count, "mtime": latest}


@lru_cache(maxsize=1)
def scan_packs() -> dict:
    """Return ``{pack_name: meta}`` for every usable pack.

    Parsing all `.fx` files is cached to ``mlut_index.json`` so it happens once
    per install, but the cache is validated against a signature of the Shaders
    folder. If packs have been added / removed / edited since the cache was
    written, it is automatically rebuilt — so dropping new LUTs in and
    restarting ComfyUI is enough to pick them up (no manual cache deletion).
    """
    sig = _dir_signature()
    if os.path.isfile(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            if (isinstance(blob, dict) and blob.get("v") == _CACHE_VERSION
                    and blob.get("sig") == sig
                    and isinstance(blob.get("packs"), dict) and blob["packs"]):
                return blob["packs"]
        except (OSError, ValueError):
            pass

    # Missing, malformed, stale (folder changed), or old schema -> rebuild.
    packs = _build_index()
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"v": _CACHE_VERSION, "sig": sig, "packs": packs}, fh,
                      ensure_ascii=False)
    except OSError:
        pass
    return packs


def refresh_packs() -> dict:
    """Force a re-scan within the running process (clears the in-memory cache).
    Useful for a future 'rescan' action without restarting ComfyUI."""
    scan_packs.cache_clear()
    return scan_packs()


def list_packs() -> list[str]:
    return sorted(scan_packs().keys())


def lut_names(pack: str) -> list[str]:
    meta = scan_packs().get(pack)
    return list(meta["names"]) if meta else []


def resolve_index(pack: str, lut_name: str) -> int:
    """Map a LUT display name to its band index, tolerating stale selections."""
    names = lut_names(pack)
    if not names:
        return 0
    try:
        return names.index(lut_name)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Atlas -> 3D LUT cube
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _load_atlas(pack: str) -> np.ndarray:
    """Load a pack's atlas PNG as float32 RGB in [0, 1]. LRU-cached."""
    if Image is None:
        raise RuntimeError("Pillow is required to load MLUT atlases.")
    meta = scan_packs().get(pack)
    if meta is None:
        raise KeyError(f"Unknown MLUT pack: {pack!r}")
    path = os.path.join(TEXTURES_DIR, meta["png"])
    img = Image.open(path).convert("RGB")
    return np.asarray(img, dtype=np.float32) / 255.0


def cube_from_atlas(atlas: np.ndarray, n: int, t: int, sel: int) -> np.ndarray:
    """Pure reshape: extract LUT band ``sel`` from a full atlas array and return
    a ``[D=T, H=N, W=N, 3]`` cube indexed ``cube[b, g, r]`` (blue, green, red).

    band rows = green index (0..N-1); columns = b*N + red index, so
    columns reshape to (T blue slices, N red) and the blue axis moves to front:
    ``[g=N, (b=T, r=N), 3] -> [b=T, g=N, r=N, 3]``.
    """
    band = atlas[sel * n : sel * n + n, :, :]  # [N, N*T, 3]
    cube = band.reshape(n, t, n, 3).transpose(1, 0, 2, 3)
    return np.ascontiguousarray(cube, dtype=np.float32)


def build_lut3d(pack: str, sel: int) -> np.ndarray:
    """Build the 3D LUT cube for band ``sel`` as ``[D=T, H=N, W=N, 3]`` float32,
    indexed ``cube[b, g, r]`` (blue, green, red)."""
    meta = scan_packs()[pack]
    n, t, l = meta["N"], meta["T"], meta["L"]
    sel = max(0, min(int(sel), l - 1))
    return cube_from_atlas(_load_atlas(pack), n, t, sel)


def pack_geometry(pack: str) -> tuple[int, int, int]:
    meta = scan_packs()[pack]
    return meta["N"], meta["T"], meta["L"]
