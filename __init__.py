"""ComfyUI-MLUT: apply LUTs (MLUT atlas, .cube, .3dl, .1dlut, HALD, strips) and
swatches/palettes (.aco/.act/.ase/PNG) to images.

Registers three nodes and the HTTP routes used by the web extensions:
  * LUT Apply     - general multi-format LUT node (tree-browser widget)
  * Palette Apply - swatch/palette remapping node (tree-browser widget)
  * MLUT Apply    - the original MLUT-atlas node, kept for back-compat
"""

from .lut_apply_node import LUTApply
from .palette_apply_node import PaletteApply
from .mlut_node import MLUT_Apply

NODE_CLASS_MAPPINGS = {
    "LUTApply": LUTApply,
    "PaletteApply": PaletteApply,
    "MLUT_Apply": MLUT_Apply,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LUTApply": "LUT Apply",
    "PaletteApply": "Palette Apply",
    "MLUT_Apply": "MLUT Apply (legacy)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


# ---------------------------------------------------------------------------
# Server routes for the web extensions.
# ---------------------------------------------------------------------------
try:
    from aiohttp import web
    from server import PromptServer

    from . import mlut_data, catalog, loaders

    routes = PromptServer.instance.routes

    @routes.get("/mlut/luts")          # legacy MLUT_Apply dependent dropdown
    async def _mlut_luts(request):
        pack = request.query.get("pack", "")
        return web.json_response({"names": mlut_data.lut_names(pack)})

    @routes.get("/mlut/categories")
    async def _mlut_categories(request):
        return web.json_response({"categories": catalog.categories()})

    @routes.get("/mlut/tree")
    async def _mlut_tree(request):
        cat = request.query.get("category", "")
        return web.json_response(catalog.tree(cat))

    @routes.get("/mlut/sub")
    async def _mlut_sub(request):
        cat = request.query.get("category", "")
        src = request.query.get("source", "")
        try:
            subs = loaders.sub_entries(cat, src)
        except Exception:
            subs = ["(default)"]
        return web.json_response({"subs": subs})

    @routes.get("/mlut/siblings")
    async def _mlut_siblings(request):
        cat = request.query.get("category", "")
        src = request.query.get("source", "")
        try:
            sibs = catalog.siblings(cat, src)
        except Exception:
            sibs = []
        return web.json_response({"siblings": sibs})

except Exception as exc:  # pragma: no cover - import-safe outside ComfyUI
    print(f"[MLUT] server routes not registered ({exc!r}); "
          "the tree browser will not be able to fetch listings.")
