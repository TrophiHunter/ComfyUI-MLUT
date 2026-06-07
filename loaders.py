"""
Loader registry: turn a (category, source, sub) selection into one of the
common representations from ``sampler`` (Lut3D / Lut1D / Palette).

Dispatch is by category (the top-level folder), which also disambiguates PNGs
(HALD vs STRIP vs SWATCH vs MLUT atlas). Format parsers live in the ``fmt_*``
modules. MLUT is special-cased (its "files" are the ``Shaders/*.fx`` packs).
"""

from __future__ import annotations

import os

try:
    from . import config
    from . import fmt_mlut, fmt_cube, fmt_3dl, fmt_1dlut, fmt_hald, fmt_strip, fmt_swatch
except ImportError:  # standalone (tests)
    import config
    import fmt_mlut, fmt_cube, fmt_3dl, fmt_1dlut, fmt_hald, fmt_strip, fmt_swatch

# category -> module exposing load(path) (file-based formats)
_FILE_LOADERS = {
    "CUBE": fmt_cube,
    "3DL": fmt_3dl,
    "1DLUT": fmt_1dlut,
    "HALD": fmt_hald,
    "RESHADE": fmt_strip,
    "SWATCH": fmt_swatch,
}


def abspath(category: str, source: str) -> str:
    """Resolve a source against the roots, returning the first that has the file
    (so external roots from lut_paths.txt work transparently)."""
    dirs = config.category_dirs(category)
    for base in dirs:
        p = os.path.join(base, source)
        if os.path.isfile(p):
            return p
    return os.path.join(dirs[0], source) if dirs else source


def sub_entries(category: str, source: str) -> list[str]:
    """Sub-selections within a source: MLUT atlas bands, .ase groups, else default."""
    if category == "MLUT":
        return fmt_mlut.subs(source)
    if category == "SWATCH" and source.lower().endswith(".ase"):
        try:
            groups = fmt_swatch.load(abspath(category, source)).groups
            if groups:
                return ["(all)"] + list(groups.keys())
        except Exception:
            pass
    return ["(default)"]


def load(category: str, source: str, sub: str = "(default)"):
    """Load the selected asset into a Lut3D / Lut1D / Palette."""
    if category == "MLUT":
        return fmt_mlut.load(source, sub)

    mod = _FILE_LOADERS.get(category)
    if mod is None:
        raise ValueError(f"Unknown category: {category!r}")
    result = mod.load(abspath(category, source))

    # .ase group filtering
    if category == "SWATCH" and sub and sub not in ("(default)", "(all)"):
        groups = getattr(result, "groups", None) or {}
        idx = groups.get(sub)
        if idx:
            result.colors = result.colors[idx]
            if result.names:
                result.names = [result.names[i] for i in idx]
    return result
