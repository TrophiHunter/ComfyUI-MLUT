"""
Configuration for ComfyUI-MLUT: where the color-asset collection lives and what
top-level category folders exist.

The collection is shipped self-contained inside the package, but the root can be
overridden with the ``MLUT_LUT_ROOT`` environment variable to point at an
external collection instead of copying gigabytes.

Each category is a top-level folder whose contents are parsed by one loader
"kind". ``MLUT`` is special: it is backed by the existing ``Shaders/`` (`.fx`
configs) + ``Textures/`` (atlases) rather than a single folder, and its entries
are packs (each with multiple sub-LUT bands).
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# Base root holding the built-in category folders. Override with MLUT_LUT_ROOT.
ROOT = os.environ.get("MLUT_LUT_ROOT", _HERE)

# Extra search roots (optional, additive): load LUTs/swatches from elsewhere on
# a drive ALONGSIDE the built-in folders — no copying needed. Just add folder
# paths below; each should contain the same category subfolders (CUBE/, 3DL/,
# SWATCH/, ...). Restart ComfyUI after editing.
#   Example:
#       EXTRA_ROOTS = [r"D:\MyLUTs", r"E:\ColorAssets"]
EXTRA_ROOTS: list[str] = [
]

# Optionally also append roots from an env var (os.pathsep-separated).
_env_extra = os.environ.get("MLUT_LUT_EXTRA_ROOTS", "")
if _env_extra:
    EXTRA_ROOTS = EXTRA_ROOTS + [p for p in _env_extra.split(os.pathsep) if p.strip()]


def all_roots() -> list[str]:
    """Base root + extra roots, de-duplicated (ROOT read live so tests can
    monkeypatch it)."""
    seen, out = set(), []
    for r in [ROOT, *EXTRA_ROOTS]:
        rp = os.path.abspath(r)
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out

# category name -> {kind, exts}
#   kind: "mlut" | "lut3d" | "lut1d" | "palette"
CATEGORIES: dict[str, dict] = {
    "MLUT":   {"kind": "mlut",    "exts": (".fx",)},
    "CUBE":   {"kind": "lut3d",   "exts": (".cube",)},
    "3DL":    {"kind": "lut3d",   "exts": (".3dl",)},
    "1DLUT":  {"kind": "lut1d",   "exts": (".1dlut",)},
    "HALD":   {"kind": "lut3d",   "exts": (".png",)},
    "RESHADE": {"kind": "lut3d",  "exts": (".png",)},
    "SWATCH": {"kind": "palette", "exts": (".aco", ".act", ".ase", ".png")},
}

# Categories the Palette Apply node should offer (everything else is LUT Apply).
PALETTE_CATEGORIES = tuple(c for c, m in CATEGORIES.items() if m["kind"] == "palette")
LUT_CATEGORIES = tuple(c for c, m in CATEGORIES.items() if m["kind"] != "palette")


def category_dirs(category: str) -> list[str]:
    """All filesystem folders to search for a category's files (base + extra
    roots). For MLUT this is just the package root (its files are the
    ``Shaders/*.fx`` packs, handled specially by the catalog)."""
    if category == "MLUT":
        return [_HERE]
    return [os.path.join(r, category) for r in all_roots()]


def category_dir(category: str) -> str:
    """First/primary folder for a category (back-compat helper)."""
    dirs = category_dirs(category)
    return dirs[0] if dirs else _HERE


def category_kind(category: str) -> str:
    spec = CATEGORIES.get(category)
    return spec["kind"] if spec else "lut3d"


def category_exts(category: str) -> tuple[str, ...]:
    spec = CATEGORIES.get(category)
    return spec["exts"] if spec else ()
