"""MLUT atlas loader — thin wrapper over the existing ``mlut_data`` module.

The MLUT category's "sources" are the ``Shaders/*.fx`` packs, and each pack's
sub-selections are its LUT band names.
"""

from __future__ import annotations

try:
    from . import mlut_data
    from .sampler import Lut3D
except ImportError:  # standalone (tests)
    import mlut_data
    from sampler import Lut3D


def sources() -> list[str]:
    return mlut_data.list_packs()


def subs(source: str) -> list[str]:
    return mlut_data.lut_names(source) or ["(default)"]


def load(source: str, sub: str = "(default)") -> Lut3D:
    names = mlut_data.lut_names(source)
    sel = mlut_data.resolve_index(source, sub) if (sub and names) else 0
    return Lut3D(mlut_data.build_lut3d(source, sel),
                 title=f"{source}: {sub}")
