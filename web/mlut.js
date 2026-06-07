// ComfyUI web extension for the "MLUT Apply" node.
// Makes the `lut_name` dropdown depend on the selected `pack`: when the pack
// changes we fetch that pack's LUT names from the backend route registered in
// __init__.py (GET /mlut/luts?pack=...) and repopulate the second combo.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

async function fetchLutNames(pack) {
    try {
        const resp = await api.fetchApi(`/mlut/luts?pack=${encodeURIComponent(pack)}`);
        const data = await resp.json();
        return Array.isArray(data.names) ? data.names : [];
    } catch (e) {
        console.error("[MLUT] failed to fetch LUT names:", e);
        return [];
    }
}

function applyNames(lutWidget, names) {
    if (!names || names.length === 0) return;
    lutWidget.options.values = names;
    if (!names.includes(lutWidget.value)) {
        lutWidget.value = names[0];
    }
    // notify any change handler + redraw
    if (lutWidget.callback) lutWidget.callback(lutWidget.value);
    app.graph.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "comfyui.mlut.dependent_dropdown",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MLUT_Apply") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;

            const packWidget = this.widgets?.find((w) => w.name === "pack");
            const lutWidget = this.widgets?.find((w) => w.name === "lut_name");
            if (!packWidget || !lutWidget) return r;

            const refresh = async (pack) => {
                const names = await fetchLutNames(pack);
                applyNames(lutWidget, names);
            };

            // Chain onto the pack widget's callback so we react to user changes.
            const prevCb = packWidget.callback;
            packWidget.callback = function (value) {
                const ret = prevCb ? prevCb.apply(this, arguments) : undefined;
                refresh(value);
                return ret;
            };

            // Populate once for the initial pack (deferred so a loaded graph's
            // saved lut_name value is preserved if it's valid for the pack).
            const savedLut = lutWidget.value;
            setTimeout(async () => {
                const names = await fetchLutNames(packWidget.value);
                if (names.length) {
                    lutWidget.options.values = names;
                    if (names.includes(savedLut)) lutWidget.value = savedLut;
                    else lutWidget.value = names[0];
                    app.graph.setDirtyCanvas(true, true);
                }
            }, 0);

            return r;
        };
    },
});
