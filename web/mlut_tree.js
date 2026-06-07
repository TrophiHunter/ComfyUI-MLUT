// Custom tree-browser widget for the "LUT Apply" and "Palette Apply" nodes.
//
// Each node has a `category` combo, a `source` STRING widget (the relative path,
// the value of record), and a `sub` combo. This extension:
//   * adds a "Browse…" button that opens a modal folder tree for the current
//     category (fetched from /mlut/tree), with expand/collapse + a filter box;
//   * writes the chosen relative path into `source`;
//   * repopulates `sub` from /mlut/sub whenever category/source changes.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAMES = ["LUTApply", "PaletteApply"];

async function fetchJSON(url) {
    try {
        const r = await api.fetchApi(url);
        return await r.json();
    } catch (e) {
        console.error("[MLUT]", url, e);
        return null;
    }
}

function widget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

// Move an existing widget to sit just after the named widget.
function placeAfter(node, w, afterName) {
    const arr = node.widgets;
    const cur = arr.indexOf(w);
    if (cur >= 0) arr.splice(cur, 1);
    let j = arr.findIndex((x) => x.name === afterName);
    if (j < 0) j = arr.length - 1;
    arr.splice(j + 1, 0, w);
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}

// A single one-row widget drawing two clickable halves: ◀ prev | next ▶
function makePrevNextWidget() {
    return {
        type: "mlut_nav",            // unknown type -> LiteGraph calls our draw/mouse
        name: "prevnext",
        options: { serialize: false },
        draw(ctx, node, width, y, H) {
            const L = window.LiteGraph || {};
            const m = 15, gap = 6;
            const bw = (width - m * 2 - gap) / 2;
            ctx.save();
            ctx.lineWidth = 1;
            ctx.strokeStyle = L.WIDGET_OUTLINE_COLOR || "#666";
            ctx.fillStyle = L.WIDGET_BGCOLOR || "#222";
            roundRect(ctx, m, y, bw, H, 4); ctx.fill(); ctx.stroke();
            roundRect(ctx, m + bw + gap, y, bw, H, 4); ctx.fill(); ctx.stroke();
            ctx.fillStyle = L.WIDGET_TEXT_COLOR || "#ddd";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.font = "12px Arial";
            ctx.fillText("◀ prev", m + bw / 2, y + H / 2);
            ctx.fillText("next ▶", m + bw + gap + bw / 2, y + H / 2);
            ctx.restore();
            this.last_y = y;
        },
        mouse(event, pos, node) {
            const t = event.type;
            if (t === "pointerdown" || t === "mousedown") {
                stepSource(node, pos[0] < node.size[0] / 2 ? -1 : 1);
                return true;
            }
            return false;
        },
        computeSize(width) {
            return [width, (window.LiteGraph && LiteGraph.NODE_WIDGET_HEIGHT) || 20];
        },
    };
}

// Step the `source` widget to the prev/next file in the same folder (wraps).
async function stepSource(node, delta) {
    const cat = widget(node, "category");
    const src = widget(node, "source");
    if (!cat || !src) return;
    const data = await fetchJSON(
        `/mlut/siblings?category=${encodeURIComponent(cat.value)}&source=${encodeURIComponent(src.value || "")}`
    );
    const sibs = (data && data.siblings) || [];
    if (!sibs.length) return;
    let i = sibs.indexOf(src.value);
    i = i < 0 ? 0 : (i + delta + sibs.length) % sibs.length;
    src.value = sibs[i];
    if (src.callback) src.callback(src.value);
    refreshSub(node);
    app.graph.setDirtyCanvas(true, true);
}

async function refreshSub(node) {
    const cat = widget(node, "category");
    const src = widget(node, "source");
    const sub = widget(node, "sub");
    if (!cat || !src || !sub) return;
    const data = await fetchJSON(
        `/mlut/sub?category=${encodeURIComponent(cat.value)}&source=${encodeURIComponent(src.value || "")}`
    );
    const names = data && Array.isArray(data.subs) && data.subs.length ? data.subs : ["(default)"];
    const keep = sub.value;
    sub.options.values = names;
    sub.value = names.includes(keep) ? keep : names[0];
    app.graph.setDirtyCanvas(true, true);
}

// ---- modal tree panel -------------------------------------------------------

function closePanel() {
    document.getElementById("mlut-tree-backdrop")?.remove();
}

// Remember which folders are expanded, per category, across opens + page reloads.
function loadExpanded(cat) {
    try {
        return new Set(JSON.parse(localStorage.getItem("mlut.expanded." + cat) || "[]"));
    } catch (e) {
        return new Set();
    }
}

function saveExpanded(cat, set) {
    try {
        localStorage.setItem("mlut.expanded." + cat, JSON.stringify([...set]));
    } catch (e) { /* storage unavailable */ }
}

function makeRow(label, depth, isDir) {
    const row = document.createElement("div");
    row.style.cssText =
        `padding:2px 6px;padding-left:${6 + depth * 14}px;cursor:pointer;` +
        `white-space:nowrap;font-family:monospace;font-size:12px;border-radius:3px;`;
    row.textContent = (isDir ? "▸ " : "   ") + label;
    row.onmouseenter = () => (row.style.background = "#3a3a3a");
    row.onmouseleave = () => (row.style.background = "transparent");
    return row;
}

function collectFiles(node, prefix, out) {
    for (const f of node.files || []) out.push([...prefix, f]);
    for (const name of Object.keys(node.dirs || {}).sort())
        collectFiles(node.dirs[name], [...prefix, name], out);
}

function collectDirs(node, prefix, out) {
    for (const name of Object.keys(node.dirs || {})) {
        const path = [...prefix, name];
        out.push(path.join("/"));
        collectDirs(node.dirs[name], path, out);
    }
}

function openTree(node) {
    closePanel();
    const cat = widget(node, "category");
    const src = widget(node, "source");
    if (!cat) return;
    const expanded = loadExpanded(cat.value);  // remembered open folders

    const backdrop = document.createElement("div");
    backdrop.id = "mlut-tree-backdrop";
    backdrop.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:10000;" +
        "display:flex;align-items:center;justify-content:center;";
    backdrop.onclick = (e) => { if (e.target === backdrop) closePanel(); };

    const panel = document.createElement("div");
    panel.style.cssText =
        "background:#262626;color:#ddd;width:520px;max-height:70vh;display:flex;" +
        "flex-direction:column;border:1px solid #555;border-radius:6px;overflow:hidden;";
    backdrop.appendChild(panel);

    const header = document.createElement("div");
    header.style.cssText = "padding:8px 10px;border-bottom:1px solid #444;font-weight:bold;";
    header.textContent = `Browse: ${cat.value}`;
    panel.appendChild(header);

    const filter = document.createElement("input");
    filter.placeholder = "filter…";
    filter.style.cssText =
        "margin:8px 10px;padding:5px 8px;background:#1c1c1c;color:#eee;" +
        "border:1px solid #555;border-radius:4px;outline:none;";
    panel.appendChild(filter);

    const toolbar = document.createElement("div");
    toolbar.style.cssText = "display:flex;gap:6px;margin:0 10px 6px;";
    const mkBtn = (label) => {
        const b = document.createElement("button");
        b.textContent = label;
        b.style.cssText =
            "padding:3px 8px;background:#333;color:#ddd;border:1px solid #555;" +
            "border-radius:4px;cursor:pointer;font-size:11px;";
        return b;
    };
    const expandBtn = mkBtn("Expand all");
    const collapseBtn = mkBtn("Collapse all");
    toolbar.appendChild(expandBtn);
    toolbar.appendChild(collapseBtn);
    panel.appendChild(toolbar);

    const list = document.createElement("div");
    list.style.cssText = "overflow:auto;padding:4px 6px 10px;flex:1;";
    panel.appendChild(list);

    document.body.appendChild(backdrop);
    filter.focus();
    document.addEventListener("keydown", function esc(e) {
        if (e.key === "Escape") { closePanel(); document.removeEventListener("keydown", esc); }
    });

    const select = (parts) => {
        src.value = parts.join("/");
        if (src.callback) src.callback(src.value);
        closePanel();
        refreshSub(node);
        app.graph.setDirtyCanvas(true, true);
    };

    fetchJSON(`/mlut/tree?category=${encodeURIComponent(cat.value)}`).then((tree) => {
        if (!tree) { list.textContent = "(failed to load)"; return; }

        const renderTree = (treeNode, prefix, depth, container) => {
            for (const name of Object.keys(treeNode.dirs || {}).sort()) {
                const child = treeNode.dirs[name];
                const path = [...prefix, name].join("/");
                const row = makeRow(name, depth, true);
                const childBox = document.createElement("div");
                let open = expanded.has(path);

                const apply = () => {
                    row.textContent = (open ? "▾ " : "▸ ") + name;
                    childBox.style.display = open ? "block" : "none";
                    if (open && !childBox.dataset.built) {
                        renderTree(child, [...prefix, name], depth + 1, childBox);
                        childBox.dataset.built = "1";
                    }
                };
                row.onclick = () => {
                    open = !open;
                    if (open) expanded.add(path); else expanded.delete(path);
                    saveExpanded(cat.value, expanded);
                    apply();
                };
                container.appendChild(row);
                container.appendChild(childBox);
                apply();  // reflect remembered (possibly open) state
            }
            for (const f of treeNode.files || []) {
                const row = makeRow(f, depth, false);
                row.onclick = () => select([...prefix, f]);
                container.appendChild(row);
            }
        };

        const renderFiltered = (q) => {
            list.innerHTML = "";
            const all = [];
            collectFiles(tree, [], all);
            const hits = all.filter((p) => p.join("/").toLowerCase().includes(q)).slice(0, 500);
            for (const parts of hits) {
                const row = makeRow(parts.join("/"), 0, false);
                row.onclick = () => select(parts);
                list.appendChild(row);
            }
            if (!hits.length) list.textContent = "(no matches)";
        };

        const rebuild = () => {
            list.innerHTML = "";
            const q = filter.value.trim().toLowerCase();
            if (q) renderFiltered(q);
            else renderTree(tree, [], 0, list);
        };

        expandBtn.onclick = () => {
            const all = [];
            collectDirs(tree, [], all);
            expanded.clear();
            all.forEach((p) => expanded.add(p));
            saveExpanded(cat.value, expanded);
            filter.value = "";  // expanding only makes sense in the tree view
            rebuild();
        };
        collapseBtn.onclick = () => {
            expanded.clear();
            saveExpanded(cat.value, expanded);
            rebuild();
        };

        renderTree(tree, [], 0, list);
        filter.oninput = rebuild;
    });
}

// ---- registration -----------------------------------------------------------

app.registerExtension({
    name: "comfyui.mlut.tree_browser",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.includes(nodeData.name)) return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated ? onCreated.apply(this, arguments) : undefined;
            const self = this;

            // Add Browse + a single one-row prev/next widget, then arrange:
            // category, Browse…, source, [◀ prev | next ▶], (sub, sliders…).
            const browse = this.addWidget("button", "Browse…", null, () => openTree(self));
            const nav = this.addCustomWidget(makePrevNextWidget());
            placeAfter(this, browse, "category");
            placeAfter(this, nav, "source");

            const cat = widget(this, "category");
            if (cat) {
                const prev = cat.callback;
                cat.callback = function (v) {
                    const ret = prev ? prev.apply(this, arguments) : undefined;
                    refreshSub(self);
                    return ret;
                };
            }

            const src = widget(this, "source");
            if (src) {
                const prev = src.callback;
                src.callback = (v) => { if (prev) prev(v); refreshSub(self); };
            }

            // populate sub for the (possibly saved) source on load
            setTimeout(() => refreshSub(self), 0);
            return r;
        };
    },
});
