"""
Catalog: discover what's available per category and expose it as a nested tree
for the tree-browser widget.

A category's tree is ``{"dirs": {name: subtree}, "files": [basename, ...]}``;
relative paths (used as the ``source`` value) are reconstructed by joining the
folder names walked to reach a file. MLUT is special — its "files" are the
``Shaders/*.fx`` pack names (flat, no folders).

The whole catalog is cached to ``catalog_index.json`` and validated on each
startup against a per-category signature (file count + newest mtime), reusing
the auto-refresh pattern from ``mlut_data``. Adding files + restarting picks
them up; bump ``_CACHE_VERSION`` if the cache schema changes.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

try:
    from . import config, fmt_mlut
except ImportError:  # standalone (tests)
    import config, fmt_mlut

_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_index.json")
_CACHE_VERSION = 1


def _category_signature(category: str) -> dict:
    if category == "MLUT":
        return {"count": len(fmt_mlut.sources()), "mtime": 0.0}
    exts = config.category_exts(category)
    count, latest = 0, 0.0
    for base in config.category_dirs(category):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith(exts):
                    count += 1
                    try:
                        m = os.path.getmtime(os.path.join(dirpath, fn))
                        latest = max(latest, m)
                    except OSError:
                        pass
    return {"count": count, "mtime": latest}


def _prune(node: dict) -> None:
    for name in list(node["dirs"].keys()):
        child = node["dirs"][name]
        _prune(child)
        if not child["files"] and not child["dirs"]:
            del node["dirs"][name]


def _sort_files(node: dict) -> None:
    node["files"].sort()
    for child in node["dirs"].values():
        _sort_files(child)


def _build_tree(category: str) -> dict:
    if category == "MLUT":
        return {"dirs": {}, "files": sorted(fmt_mlut.sources())}

    exts = config.category_exts(category)
    root = {"dirs": {}, "files": []}
    # Merge the tree across all roots (base + extra). Same relative path in two
    # roots: the file appears once; loaders resolve which root actually has it.
    for base in config.category_dirs(category):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, base)
            node = root
            if rel != ".":
                for part in rel.split(os.sep):
                    node = node["dirs"].setdefault(part, {"dirs": {}, "files": []})
            for fn in filenames:
                if fn.lower().endswith(exts) and fn not in node["files"]:
                    node["files"].append(fn)
    _sort_files(root)
    _prune(root)
    return root


@lru_cache(maxsize=1)
def _catalog() -> dict:
    sig = {c: _category_signature(c) for c in config.CATEGORIES}
    if os.path.isfile(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            if (blob.get("v") == _CACHE_VERSION and blob.get("sig") == sig
                    and isinstance(blob.get("trees"), dict)):
                return blob["trees"]
        except (OSError, ValueError):
            pass

    trees = {}
    for c in config.CATEGORIES:
        t = _build_tree(c)
        if t["files"] or t["dirs"]:
            trees[c] = t
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"v": _CACHE_VERSION, "sig": sig, "trees": trees}, fh,
                      ensure_ascii=False)
    except OSError:
        pass
    return trees


def categories() -> list[str]:
    """Categories that actually have content (MLUT first if present)."""
    found = _catalog()
    ordered = [c for c in config.CATEGORIES if c in found]
    return ordered


def tree(category: str) -> dict:
    return _catalog().get(category, {"dirs": {}, "files": []})


def first_source(category: str) -> str:
    """A reasonable default selection (first file, descending folders)."""
    node = tree(category)
    parts: list[str] = []
    while node["dirs"] and not node["files"]:
        name = sorted(node["dirs"].keys())[0]
        parts.append(name)
        node = node["dirs"][name]
    if node["files"]:
        parts.append(node["files"][0])
    return "/".join(parts)


def siblings(category: str, source: str) -> list[str]:
    """Sorted relative paths of the files in the same folder as ``source`` (for
    the node's prev/next file stepping). For MLUT this is the flat pack list."""
    node = tree(category)
    parts = [p for p in source.split("/") if p]
    folders = parts[:-1]
    for fo in folders:
        node = (node.get("dirs") or {}).get(fo)
        if node is None:
            return []
    prefix = "/".join(folders)
    files = sorted(node.get("files") or [])
    return [f"{prefix}/{f}" if prefix else f for f in files]


def refresh() -> dict:
    """Force a re-scan within the running process (clears the in-memory cache)."""
    _catalog.cache_clear()
    return _catalog()
