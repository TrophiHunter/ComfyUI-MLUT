"""
General "LUT Apply" node: select a category (top-level folder) + a source file
(via the tree-browser widget) + an optional sub-selection, then apply the LUT to
an image using the shared sampler/grade/depth pipeline.

Handles every 3D format (.cube, .3dl, HALD, strip, MLUT atlas band) and 1D LUTs
(.1dlut). Swatches have their own Palette Apply node.
"""

from __future__ import annotations

try:
    from . import sampler, loaders, catalog
except ImportError:  # standalone (tests)
    import sampler, loaders, catalog


def _default_source(cats):
    if cats and cats[0] not in ("<none>",):
        try:
            return catalog.first_source(cats[0])
        except Exception:
            return ""
    return ""


class LUTApply:
    """Apply a LUT (any supported 3D/1D format) to an image."""

    @classmethod
    def INPUT_TYPES(cls):
        cats = catalog.categories() or ["<none>"]
        return {
            "required": {
                "image": ("IMAGE",),
                "category": (cats,),
                "source": ("STRING", {"default": _default_source(cats)}),
                "sub": (["(default)"],),
                "intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "chroma": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "luma": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "interpolation": (["trilinear", "tetrahedral", "nearest"],),
            },
            "optional": {
                "upsample": (["off", "33", "65", "129"],),
                "dither": ("BOOLEAN", {"default": False}),
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
        # `source` (tree-driven STRING) and `sub` (JS-populated combo) are managed
        # client-side, so exempt them from ComfyUI's static checks.
        return True

    def apply(self, image, category, source, sub, intensity, chroma, luma,
              interpolation="trilinear", upsample="off", dither=False,
              depth=None, invert_depth=True, focus_distance=0.5,
              fade_near=0.2, fade_far=0.2, blend_power_near=1.0,
              blend_power_far=1.0):
        label = f"{category}/{source}"
        try:
            asset = loaders.load(category, source, sub)
        except Exception as exc:
            print(f"[MLUT] LUT load failed for {label} [{sub}]: {exc!r}")
            return (image, label)

        orig = image[..., :3].clamp(0.0, 1.0)

        if isinstance(asset, sampler.Lut3D):
            cube = asset.cube
            if upsample != "off":
                target = int(upsample)
                if target > min(cube.shape[0], cube.shape[1], cube.shape[2]):
                    cube = sampler.upsample_cube(cube, target)  # smooth anti-band
            lut_rgb = sampler.sample_cube(orig, cube, interpolation)
        elif isinstance(asset, sampler.Lut1D):
            lut_rgb = sampler.apply_curve(orig, asset.curve)
        else:  # a Palette wired into the LUT node -> nearest-color map
            lut_rgb = sampler.map_palette(orig, asset.colors, "nearest", 1.0)

        out = sampler.grade(orig, lut_rgb, intensity, chroma, luma)

        if depth is not None:
            out = sampler.apply_depth(orig, out, depth, invert_depth,
                                      focus_distance, fade_near, fade_far,
                                      blend_power_near, blend_power_far)

        out = sampler.add_dither(out) if dither else out.clamp(0.0, 1.0)
        name = getattr(asset, "title", "") or label
        return (out, name)
