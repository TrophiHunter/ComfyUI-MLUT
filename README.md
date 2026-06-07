# ComfyUI-MLUT

Apply color **LUTs** and **swatches/palettes** to images in ComfyUI from one
self-contained collection. Supports:

| Kind | Formats | Node |
|------|---------|------|
| 3D LUT | MLUT atlas (`.fx`+`.png`), `.cube`, `.3dl`, HALD CLUT PNG, ReShade strip PNG | **LUT Apply** |
| 1D LUT | `.1dlut` | **LUT Apply** |
| Swatch/palette | `.aco`, `.act`, `.ase`, palette PNG | **Palette Apply** |

Everything except swatches is normalized to a 3D `[blue, green, red, 3]` cube and
sampled with the shader-accurate engine (trilinear / tetrahedral / nearest) plus
the original MLUT intensity / chroma / luma blend and optional depth fade.

## Install

Copy the `ComfyUI-MLUT` folder into `ComfyUI/custom_nodes/`. No extra
Python packages (numpy / torch / Pillow ship with ComfyUI) Go to https://github.com/TheGordinho/MLUT
and download the shader and texture folders and put them into the ComfyUI/custom_nodes/ComfyUI-MLUT folder
then restart.

## Adding your collection

Drop files into the category folders (subfolders to any depth are fine), then
restart ComfyUI:

```
ComfyUI-MLUT/
  Textures/  Shaders/   <- MLUT atlas packs (category "MLUT")
  CUBE/      Examples/Filmic/Kodak 2383.cube
  3DL/       ...
  1DLUT/     ...
  HALD/      ...
  RESHADE/   ...   (ReShade strip-LUT PNGs)
  SWATCH/    palettes/sunset.ase
```

The catalog is cached (`catalog_index.json`) and auto-rebuilds at startup when a
category folder's contents change (file count / mtime).

**Load from another drive (no copying):** edit `EXTRA_ROOTS` in
[config.py](config.py) to add folders that are searched *alongside* the built-in
ones, e.g. `EXTRA_ROOTS = [r"D:\MyLUTs"]`. Each extra root should contain the
same category subfolders (`CUBE/`, `3DL/`, `SWATCH/`, …). Restart ComfyUI after
editing. (You can also set `MLUT_LUT_ROOT` to relocate the base root, or
`MLUT_LUT_EXTRA_ROOTS` as an env-var equivalent.)

## Nodes

### LUT Apply (`image/color`)
- `image`, `category` (dropdown), **Browse…** (tree picker → sets `source`),
  `sub` (atlas band; `(default)` for single-LUT files), `intensity`, `chroma`,
  `luma`, `interpolation` (`trilinear` / `tetrahedral` / `nearest`).
- Anti-banding (optional): `upsample` (`off`/`33`/`65`/`129`) smoothly resamples a
  low-res cube to more nodes (Catmull-Rom, passes through the original nodes) to
  kill resolution/contour banding; `dither` adds ~1-LSB TPDF noise at output to
  break up 8-bit gradient banding (no change to the color transform). Both
  default off (exact parity); pair `upsample` with `trilinear`/`tetrahedral`.
- Optional depth fade: wire a depth map (DepthAnything/MiDaS) into `depth`, plus
  `invert_depth`, `focus_distance`, `fade_near/far`, `blend_power_near/far`.
- Outputs: graded `image`, resolved `name`.

### Palette Apply (`image/color`)
- `image`, `category`, **Browse…**, `sub` (`.ase` group), `mode`
  (`nearest` / `blue_noise` / `ordered` / `floyd_steinberg`), `amount` (blend),
  optional `max_colors` (subsample the palette).
- Remaps each pixel to the nearest swatch color. Dither amplitude auto-scales to
  the palette's color spacing. Mode guide:
  - `blue_noise` — pattern-free dither, reads as fine natural grain; vectorized
    and fast. **Best for a natural look.**
  - `nearest` — hard posterize (most "styled"/banded).
  - `ordered` — 4×4 Bayer (structured crosshatch).
  - `floyd_steinberg` — error diffusion; good tone but serial/CPU, so slowest
    (now uses a precomputed nearest-color grid, but still best on smaller images).
- Optional depth fade (same as LUT Apply): wire a depth map into `depth` to
  confine the palette remap to a depth band (`invert_depth`, `focus_distance`,
  `fade_near/far`, `blend_power_near/far`).

### MLUT Apply (legacy)
The original MLUT-atlas node (`pack` → `lut_name` dropdowns), kept so existing
graphs keep working. New work should use **LUT Apply** with category `MLUT`.

## The tree browser

`category` is a normal dropdown; **Browse…** opens a modal folder tree for that
category (fetched from `/mlut/tree`) with expand/collapse and a filter box, and
writes the chosen relative path into `source`. The `sub` dropdown repopulates
from `/mlut/sub` whenever category/source changes.

## Code map

- `config.py` — collection root + category definitions.
- `catalog.py` — scans categories into a cached nested tree.
- `loaders.py` + `fmt_*.py` — per-format parsers → `Lut3D` / `Lut1D` / `Palette`.
- `sampler.py` — cube sampling, 1D curve apply, grade, depth, palette mapping.
- `lut_apply_node.py`, `palette_apply_node.py`, `mlut_node.py` — the nodes.
- `web/mlut_tree.js` (tree browser) + `web/mlut.js` (legacy MLUT dropdown).

## Assumptions (handled defensively — report a sample file if a load fails)

- `.cube` = 3D, input domain 0..1. `.3dl` = blue-fastest ordering, output
  normalized by inferred bit depth, validated against `N³` line count.
- `.1dlut` = whitespace/line-delimited floats (1- or 3-column), comments ignored.
- HALD = square, side `N^1.5`. Strip = `W=N²,H=N` or `H=N²,W=N`.
- Palette PNG = every pixel is a swatch color, row-major, identical colors deduped.

## Credit

LUTs / original ReShade shader: [TheGordinho/MLUT](https://github.com/TheGordinho/MLUT)
and contributors (Otis, Marty McFly, luluco250, BlueSkyDefender, etra0).
