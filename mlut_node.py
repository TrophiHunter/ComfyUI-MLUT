"""
Legacy MLUT-atlas node, kept for back-compat with existing graphs.

Selects a pack + LUT band via the original two dependent dropdowns
(`pack` -> `lut_name`, driven by web/mlut.js + the /mlut/luts route). The grade
math now lives in the shared ``sampler`` module; the general "LUT Apply" node
supersedes this one (MLUT is just one of its categories).
"""

from __future__ import annotations

try:
    from . import mlut_data, sampler
except ImportError:  # standalone (tests)
    import mlut_data
    import sampler


class MLUT_Apply:
    """Apply an MLUT (ReShade Multi-LUT) color grade to an image."""

    @classmethod
    def INPUT_TYPES(cls):
        packs = mlut_data.list_packs() or ["<no packs found>"]
        first_names = mlut_data.lut_names(packs[0]) or ["<none>"]
        return {
            "required": {
                "image": ("IMAGE",),
                "pack": (packs,),
                "lut_name": (first_names,),
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
    RETURN_NAMES = ("image", "lut_name")
    FUNCTION = "apply"
    CATEGORY = "image/color"

    @classmethod
    def VALIDATE_INPUTS(cls, pack, lut_name, **_):
        return True

    def apply(self, image, pack, lut_name, intensity, chroma, luma,
              interpolation="trilinear", upsample="off", dither=False,
              depth=None, invert_depth=True, focus_distance=0.5,
              fade_near=0.2, fade_far=0.2, blend_power_near=1.0,
              blend_power_far=1.0):
        if pack not in mlut_data.scan_packs():
            print(f"[MLUT] Unknown pack {pack!r}; returning image unchanged.")
            return (image, str(lut_name))

        sel = mlut_data.resolve_index(pack, lut_name)
        cube = mlut_data.build_lut3d(pack, sel)
        if upsample != "off":
            target = int(upsample)
            if target > min(cube.shape[0], cube.shape[1], cube.shape[2]):
                cube = sampler.upsample_cube(cube, target)

        orig = image[..., :3].clamp(0.0, 1.0)
        lut_rgb = sampler.sample_cube(orig, cube, interpolation)
        out = sampler.grade(orig, lut_rgb, intensity, chroma, luma)

        if depth is not None:
            out = sampler.apply_depth(orig, out, depth, invert_depth,
                                      focus_distance, fade_near, fade_far,
                                      blend_power_near, blend_power_far)

        out = sampler.add_dither(out) if dither else out.clamp(0.0, 1.0)
        names = mlut_data.lut_names(pack)
        return (out, names[sel] if names else str(lut_name))
