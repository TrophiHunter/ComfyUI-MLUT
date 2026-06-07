"""
"Palette Apply" node: remap an image to the colors of a swatch/palette
(.aco/.act/.ase/palette-PNG) via nearest-color mapping, with optional dithering
and a blend amount. Shares the tree-browser widget + loaders with LUT Apply.
"""

from __future__ import annotations

import numpy as np

try:
    from . import sampler, loaders, catalog, config
except ImportError:  # standalone (tests)
    import sampler, loaders, catalog, config


def _palette_categories():
    cats = [c for c in catalog.categories() if config.category_kind(c) == "palette"]
    return cats or ["<none>"]


def _default_source(cats):
    if cats and cats[0] != "<none>":
        try:
            return catalog.first_source(cats[0])
        except Exception:
            return ""
    return ""


class PaletteApply:
    """Remap an image to a swatch/palette (nearest color, optional dithering)."""

    @classmethod
    def INPUT_TYPES(cls):
        cats = _palette_categories()
        return {
            "required": {
                "image": ("IMAGE",),
                "category": (cats,),
                "source": ("STRING", {"default": _default_source(cats)}),
                "sub": (["(default)"],),
                "mode": (["nearest", "blue_noise", "ordered", "floyd_steinberg"],),
                "amount": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            },
            "optional": {
                "max_colors": ("INT", {"default": 0, "min": 0, "max": 1024}),
                "depth": ("IMAGE",),
                "invert_depth": ("BOOLEAN", {"default": True}),
                "focus_distance": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "fade_near": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "fade_far": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "blend_power_near": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 5.0, "step": 0.01}),
                "blend_power_far": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 5.0, "step": 0.01}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "name")
    FUNCTION = "apply"
    CATEGORY = "image/color"

    @classmethod
    def VALIDATE_INPUTS(cls, category, source, sub, **_):
        return True

    def apply(self, image, category, source, sub, mode, amount, max_colors=0,
              depth=None, invert_depth=True, focus_distance=0.5,
              fade_near=0.2, fade_far=0.2, blend_power_near=1.0,
              blend_power_far=1.0):
        label = f"{category}/{source}"
        try:
            pal = loaders.load(category, source, sub)
        except Exception as exc:
            print(f"[MLUT] palette load failed for {label} [{sub}]: {exc!r}")
            return (image, label)

        colors = getattr(pal, "colors", None)
        if colors is None or len(colors) == 0:
            print(f"[MLUT] {label} has no colors; returning image unchanged.")
            return (image, label)

        if max_colors and len(colors) > max_colors:
            idx = np.linspace(0, len(colors) - 1, max_colors).round().astype(int)
            colors = colors[idx]

        out = sampler.map_palette(image, colors, mode, amount)

        if depth is not None:
            orig = image[..., :3].clamp(0.0, 1.0)
            out = sampler.apply_depth(orig, out, depth, invert_depth,
                                      focus_distance, fade_near, fade_far,
                                      blend_power_near, blend_power_far)
        return (out, label)
