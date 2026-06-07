"""
Shared color-transform engine for ComfyUI-MLUT.

Holds the common in-memory representations every loader normalizes to, plus the
sampling / blend / depth math (ported from the original ReShade `_BaseLUT.fxh`).
Both the MLUT node and the general LUT Apply node build on this module so there
is a single implementation of the grade.

Representations:
  * ``Lut3D``   - a `[D=blue, H=green, W=red, 3]` cube (every 3D format reduces
                  to this: .cube, .3dl, HALD, ReShade strips, MLUT atlas bands).
  * ``Lut1D``   - per-channel curves `[K, 3]` (the `.1dlut` format).
  * ``Palette`` - a `[K, 3]` color list (swatches: .aco/.act/.ase/palette-PNG).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F

# ReShade Dot() luma weights (BaseLUT line 110).
_LUMA = (0.2125, 0.7154, 0.0721)


# ---------------------------------------------------------------------------
# Representations
# ---------------------------------------------------------------------------

@dataclass
class Lut3D:
    cube: np.ndarray            # [D=blue, H=green, W=red, 3] float32, values 0..1
    title: str = ""


@dataclass
class Lut1D:
    curve: np.ndarray           # [K, 3] float32 per-channel output, values 0..1
    title: str = ""


@dataclass
class Palette:
    colors: np.ndarray                       # [K, 3] float32 in 0..1
    names: list[str] | None = None
    groups: dict[str, list[int]] = field(default_factory=dict)  # .ase groups


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _luma(rgb: torch.Tensor) -> torch.Tensor:
    """Per-pixel luma of an [..., 3] tensor, keeping the channel dim (-> [...,1])."""
    w = torch.tensor(_LUMA, dtype=rgb.dtype, device=rgb.device)
    return (rgb * w).sum(dim=-1, keepdim=True)


def _safe_smoothstep(e0: "torch.Tensor | float", e1: "torch.Tensor | float",
                     x: torch.Tensor) -> torch.Tensor:
    """HLSL smoothstep, guarding the degenerate e0 == e1 case as a hard step."""
    denom = (e1 - e0)
    if isinstance(denom, torch.Tensor):
        denom = torch.where(denom.abs() < 1e-6, torch.full_like(denom, 1e-6), denom)
    elif abs(denom) < 1e-6:
        return (x >= e1).to(x.dtype)
    t = torch.clamp((x - e0) / denom, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# 3D cube sampling (trilinear / nearest via grid_sample, tetrahedral by hand)
# ---------------------------------------------------------------------------

def _sample_grid(image: torch.Tensor, cube: np.ndarray, mode: str) -> torch.Tensor:
    """Sample ``cube`` ([D=blue, H=green, W=red, 3]) with the RGB of ``image``
    via grid_sample. ``mode`` is "bilinear" (=trilinear here, 5-D input) or
    "nearest". Returns the looked-up RGB, same shape as the image."""
    b, h, w, _ = image.shape

    # cube -> grid_sample input [1, C=3, D=blue, H=green, W=red]
    lut = torch.from_numpy(np.ascontiguousarray(np.transpose(cube, (3, 0, 1, 2))))
    lut = lut.unsqueeze(0).to(device=image.device, dtype=image.dtype)

    # grid last dim = (x->red/W, y->green/H, z->blue/D), normalized to [-1, 1].
    # align_corners=True so 0 -> first sample, 1 -> last sample.
    grid = image * 2.0 - 1.0  # [B, H, W, 3] already ordered (r, g, b)
    grid = grid.reshape(1, b, h, w, 3)  # batch folded into D_out

    sampled = F.grid_sample(
        lut, grid, mode=mode, padding_mode="border", align_corners=True
    )  # [1, 3, B, H, W]
    return sampled[0].permute(1, 2, 3, 0).contiguous()  # [B, H, W, 3]


def _sample_tetrahedral(image: torch.Tensor, cube: np.ndarray) -> torch.Tensor:
    """Tetrahedral interpolation (the OpenColorIO / .cube-standard 6-tetrahedra
    form). More accurate along the neutral axis than trilinear; matches pro LUT
    tools. ``cube`` is [D=blue, H=green, W=red, 3], image RGB in [0, 1]."""
    cube_t = torch.from_numpy(np.ascontiguousarray(cube)).to(
        device=image.device, dtype=image.dtype)
    nb, ng, nr = cube_t.shape[0], cube_t.shape[1], cube_t.shape[2]
    flat = cube_t.reshape(-1, 3)  # [D*H*W, 3], indexed (z*ng + y)*nr + x

    r, g, bch = image[..., 0], image[..., 1], image[..., 2]
    fx = r.clamp(0, 1) * (nr - 1)   # red   -> x
    fy = g.clamp(0, 1) * (ng - 1)   # green -> y
    fz = bch.clamp(0, 1) * (nb - 1)  # blue  -> z

    x0 = fx.floor().clamp(0, nr - 2).long(); x1 = x0 + 1
    y0 = fy.floor().clamp(0, ng - 2).long(); y1 = y0 + 1
    z0 = fz.floor().clamp(0, nb - 2).long(); z1 = z0 + 1
    dx = (fx - x0).unsqueeze(-1)
    dy = (fy - y0).unsqueeze(-1)
    dz = (fz - z0).unsqueeze(-1)

    def corner(xi, yi, zi):
        lin = (zi * ng + yi) * nr + xi
        return flat[lin.reshape(-1)].reshape(*xi.shape, 3)

    c000 = corner(x0, y0, z0); c100 = corner(x1, y0, z0)
    c010 = corner(x0, y1, z0); c001 = corner(x0, y0, z1)
    c110 = corner(x1, y1, z0); c101 = corner(x1, y0, z1)
    c011 = corner(x0, y1, z1); c111 = corner(x1, y1, z1)

    o1 = (1 - dx) * c000 + (dx - dy) * c100 + (dy - dz) * c110 + dz * c111
    o2 = (1 - dx) * c000 + (dx - dz) * c100 + (dz - dy) * c101 + dy * c111
    o3 = (1 - dz) * c000 + (dz - dx) * c001 + (dx - dy) * c101 + dy * c111
    o4 = (1 - dz) * c000 + (dz - dy) * c001 + (dy - dx) * c011 + dx * c111
    o5 = (1 - dy) * c000 + (dy - dz) * c010 + (dz - dx) * c011 + dx * c111
    o6 = (1 - dy) * c000 + (dy - dx) * c010 + (dx - dz) * c110 + dz * c111

    branch_a = torch.where(dy > dz, o1, torch.where(dx > dz, o2, o3))
    branch_b = torch.where(dz > dy, o4, torch.where(dz > dx, o5, o6))
    return torch.where(dx > dy, branch_a, branch_b)


def sample_cube(image: torch.Tensor, cube: np.ndarray,
                interpolation: str = "trilinear") -> torch.Tensor:
    """Sample a 3D LUT cube with the image's RGB using the chosen interpolation."""
    if interpolation == "tetrahedral":
        return _sample_tetrahedral(image, cube)
    mode = "nearest" if interpolation == "nearest" else "bilinear"
    return _sample_grid(image, cube, mode)


# Back-compat name used by the original MLUT node.
_sample_lut = sample_cube


# ---------------------------------------------------------------------------
# Anti-banding: smooth cube upsample (Catmull-Rom) + output dithering
# ---------------------------------------------------------------------------

def _catmull_resample_axis(t: torch.Tensor, axis: int, new_len: int) -> torch.Tensor:
    """Resample ``t`` along ``axis`` to ``new_len`` using Catmull-Rom (passes
    through the original samples, C1-continuous between them)."""
    n = t.shape[axis]
    if new_len == n:
        return t
    p = torch.linspace(0, n - 1, new_len, device=t.device, dtype=t.dtype)
    i = torch.floor(p)
    frac = p - i
    i = i.long()
    P0 = t.index_select(axis, (i - 1).clamp(0, n - 1))
    P1 = t.index_select(axis, i.clamp(0, n - 1))
    P2 = t.index_select(axis, (i + 1).clamp(0, n - 1))
    P3 = t.index_select(axis, (i + 2).clamp(0, n - 1))

    tt, t2 = frac, frac * frac
    t3 = t2 * frac
    w0 = 0.5 * (-t3 + 2 * t2 - tt)
    w1 = 0.5 * (3 * t3 - 5 * t2 + 2)
    w2 = 0.5 * (-3 * t3 + 4 * t2 + tt)
    w3 = 0.5 * (t3 - t2)

    shape = [1] * t.dim()
    shape[axis] = new_len
    return (P0 * w0.reshape(shape) + P1 * w1.reshape(shape)
            + P2 * w2.reshape(shape) + P3 * w3.reshape(shape))


def upsample_cube(cube: np.ndarray, target: int) -> np.ndarray:
    """Smoothly resample a 3D LUT cube to ``target`` nodes per axis (Catmull-Rom
    along each of blue/green/red). Reduces resolution/contour banding while
    keeping the look at the original nodes. Returns a new ``[T, T, T, 3]`` cube."""
    t = torch.from_numpy(np.ascontiguousarray(cube)).float()
    for axis in (0, 1, 2):
        t = _catmull_resample_axis(t, axis, target)
    return np.ascontiguousarray(t.clamp(0.0, 1.0).numpy(), dtype=np.float32)


def add_dither(img: torch.Tensor, amplitude: float = 1.0 / 255.0) -> torch.Tensor:
    """Add ~1-LSB triangular-PDF (TPDF) dither to break up 8-bit quantization
    banding. Leaves the color transform unchanged in expectation."""
    noise = torch.rand_like(img) - torch.rand_like(img)  # triangular in [-1, 1]
    return (img + noise * amplitude).clamp(0.0, 1.0)


# ---------------------------------------------------------------------------
# 1D curve application
# ---------------------------------------------------------------------------

def apply_curve(image: torch.Tensor, curve: np.ndarray) -> torch.Tensor:
    """Apply a per-channel 1D LUT. ``curve`` is [K, 3]; linear-interpolated with
    align_corners semantics (input 0 -> curve[0], 1 -> curve[K-1])."""
    k = curve.shape[0]
    c = torch.from_numpy(np.ascontiguousarray(curve)).to(image.device, image.dtype)
    pos = image.clamp(0.0, 1.0) * (k - 1)
    i0 = pos.floor().clamp(0, k - 2).long()
    i1 = i0 + 1
    frac = pos - i0
    out = torch.empty_like(image)
    for ch in range(3):
        col = c[:, ch]
        lo = col[i0[..., ch]]
        hi = col[i1[..., ch]]
        out[..., ch] = lo * (1.0 - frac[..., ch]) + hi * frac[..., ch]
    return out


# ---------------------------------------------------------------------------
# Grade (intensity / chroma / luma) and depth fade (ported from _BaseLUT.fxh)
# ---------------------------------------------------------------------------

def grade(orig: torch.Tensor, lut_rgb: torch.Tensor,
          intensity: float, chroma: float, luma: float) -> torch.Tensor:
    """Blend the looked-up color over the original (BaseLUT lines 137-142)."""
    chroma_col = lut_rgb * chroma + orig * (1.0 - chroma)
    chroma_only = chroma_col - _luma(chroma_col)
    added_luma = _luma(lut_rgb) * luma + _luma(orig) * (1.0 - luma)
    out = chroma_only + added_luma
    return out * intensity + orig * (1.0 - intensity)


def prep_depth(depth: torch.Tensor, b: int, h: int, w: int,
               invert: bool) -> torch.Tensor:
    """Reduce a depth IMAGE to a [B, H, W, 1] scalar field matched to the image."""
    d = depth
    if d.dim() == 3:
        d = d.unsqueeze(-1)
    d = d.mean(dim=-1, keepdim=True)

    if d.shape[1] != h or d.shape[2] != w:
        d = F.interpolate(d.permute(0, 3, 1, 2), size=(h, w),
                          mode="bilinear", align_corners=False).permute(0, 2, 3, 1)

    if d.shape[0] != b:
        if d.shape[0] == 1:
            d = d.expand(b, -1, -1, -1)
        else:
            reps = (b + d.shape[0] - 1) // d.shape[0]
            d = d.repeat(reps, 1, 1, 1)[:b]

    d = d.clamp(0.0, 1.0)
    if invert:
        d = 1.0 - d
    return d


def apply_depth(orig: torch.Tensor, out: torch.Tensor, depth: torch.Tensor,
                invert: bool, focus: float, fade_near: float, fade_far: float,
                power_near: float, power_far: float) -> torch.Tensor:
    """Confine the grade to a depth band (BaseLUT lines 144-157)."""
    b, h, w, _ = orig.shape
    d = prep_depth(depth, b, h, w, invert)
    near_start = float(np.clip(focus - fade_near, 0.0, 1.0))
    far_end = float(np.clip(focus + fade_far, 0.0, 1.0))
    blend_near = _safe_smoothstep(near_start, focus, d) ** power_near
    blend_far = (1.0 - _safe_smoothstep(focus, far_end, d)) ** power_far
    blend_depth = (blend_near * blend_far).clamp(0.0, 1.0)
    return orig * (1.0 - blend_depth) + out * blend_depth


# Back-compat name used by the original MLUT node.
_prep_depth = prep_depth


# ---------------------------------------------------------------------------
# Palette mapping (nearest color + optional dithering) for the Palette node
# ---------------------------------------------------------------------------

def map_palette(image: torch.Tensor, colors: np.ndarray, mode: str = "nearest",
                amount: float = 1.0) -> torch.Tensor:
    """Remap each pixel to the nearest palette color. ``colors`` is [K, 3] in
    0..1. ``mode``:
      * "nearest"        - hard posterize to the palette.
      * "blue_noise"     - blue-noise dither before quantizing: pattern-free,
                           reads as fine natural grain (vectorized, fast).
      * "ordered"        - 4x4 Bayer dither (structured crosshatch look).
      * "floyd_steinberg"- serial error diffusion (good tone, slower).
    Dither amplitude auto-scales to the palette's color spacing.
    ``amount`` blends the result over the original."""
    pal = torch.from_numpy(np.ascontiguousarray(colors)).to(image.device, image.dtype)
    orig = image[..., :3].clamp(0.0, 1.0)

    if mode == "floyd_steinberg":
        mapped = _floyd_steinberg(orig, pal)
    elif mode == "blue_noise":
        amp = _palette_step(pal)
        mapped = _nearest((orig + _blue_noise_like(orig) * amp).clamp(0.0, 1.0), pal)
    elif mode == "ordered":
        amp = _palette_step(pal)
        mapped = _nearest((orig + _bayer_offset(orig) * amp).clamp(0.0, 1.0), pal)
    else:
        mapped = _nearest(orig, pal)

    if amount < 1.0:
        mapped = mapped * amount + orig * (1.0 - amount)
    return mapped.clamp(0.0, 1.0)


def _palette_step(pal: torch.Tensor) -> float:
    """Mean nearest-neighbor distance between palette colors — a good dither
    amplitude (noise spans roughly the gap between adjacent palette colors)."""
    if pal.shape[0] < 2:
        return 0.0
    d = torch.cdist(pal, pal)
    d.fill_diagonal_(float("inf"))
    return float(d.min(dim=1).values.mean().clamp(min=1e-4))


def _nearest_index(flat: torch.Tensor, pal: torch.Tensor) -> torch.Tensor:
    """Nearest palette index per row of ``flat`` [P,3]; chunked over P."""
    idx = torch.empty(flat.shape[0], dtype=torch.long, device=flat.device)
    chunk = 65536
    for s in range(0, flat.shape[0], chunk):
        block = flat[s:s + chunk]
        d2 = (block[:, None, :] - pal[None, :, :]).pow(2).sum(-1)
        idx[s:s + chunk] = d2.argmin(dim=1)
    return idx


def _nearest(rgb: torch.Tensor, pal: torch.Tensor) -> torch.Tensor:
    return pal[_nearest_index(rgb.reshape(-1, 3), pal)].reshape(rgb.shape)


def _bayer_offset(rgb: torch.Tensor) -> torch.Tensor:
    bayer = torch.tensor([
        [0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]
    ], dtype=rgb.dtype, device=rgb.device) / 16.0 - 0.5  # zero-mean [-0.5, 0.5]
    b, h, w, _ = rgb.shape
    tile = bayer.repeat((h + 3) // 4, (w + 3) // 4)[:h, :w]
    return tile.reshape(1, h, w, 1)


def _blue_noise_like(img: torch.Tensor) -> torch.Tensor:
    """Per-channel blue-noise field ~[-0.5, 0.5], zero-mean, made by high-pass
    filtering white noise in the frequency domain (no structured pattern)."""
    b, h, w, c = img.shape
    white = torch.rand(b, h, w, c, device=img.device, dtype=img.dtype) - 0.5
    f = torch.fft.fftn(white, dim=(1, 2))
    fy = torch.fft.fftfreq(h, device=img.device).reshape(1, h, 1, 1)
    fx = torch.fft.fftfreq(w, device=img.device).reshape(1, 1, w, 1)
    radius = torch.sqrt(fy * fy + fx * fx)
    hp = (radius / radius.max().clamp(min=1e-8)).to(f.dtype)  # emphasize highs
    bn = torch.fft.ifftn(f * hp, dim=(1, 2)).real
    bn = bn - bn.mean()
    return (bn / (bn.std().clamp(min=1e-6) * 4.0)).clamp(-0.5, 0.5)


def _floyd_steinberg(rgb: torch.Tensor, pal: torch.Tensor) -> torch.Tensor:
    """Serial error diffusion. The per-pixel palette lookup uses a precomputed
    coarse 3D nearest-index grid so the inner loop avoids the per-pixel argmin
    (much faster than before, but still inherently serial)."""
    G = 64
    axis = torch.linspace(0, 1, G, device=pal.device, dtype=pal.dtype)
    grid = torch.stack(torch.meshgrid(axis, axis, axis, indexing="ij"), -1).reshape(-1, 3)
    qlut = _nearest_index(grid, pal).cpu().numpy().astype(np.int32)  # [G^3]
    pal_np = pal.detach().cpu().numpy()

    out = torch.empty_like(rgb)
    for n in range(rgb.shape[0]):
        work = rgb[n].detach().cpu().numpy().astype(np.float32)
        h, w, _ = work.shape
        for y in range(h):
            row, nrow = work[y], (work[y + 1] if y + 1 < h else None)
            for x in range(w):
                old = row[x]
                gi = np.clip((old * (G - 1) + 0.5).astype(np.int32), 0, G - 1)
                new = pal_np[qlut[(gi[0] * G + gi[1]) * G + gi[2]]]
                row[x] = new
                err = old - new
                if x + 1 < w:
                    row[x + 1] += err * (7 / 16)
                if nrow is not None:
                    if x > 0:
                        nrow[x - 1] += err * (3 / 16)
                    nrow[x] += err * (5 / 16)
                    if x + 1 < w:
                        nrow[x + 1] += err * (1 / 16)
        out[n] = torch.from_numpy(work).to(rgb.device, rgb.dtype)
    return out
