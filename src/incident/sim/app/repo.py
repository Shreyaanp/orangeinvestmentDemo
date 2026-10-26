"""The simulated app's git repo: apply commits, produce real diffs, read config from the tree."""

import difflib
import hashlib
import json
from pathlib import Path

from incident.app_models import FileDiff
from incident.sim.app.spec import AppChange, Edit, Value

Tree = dict[str, str]
CONFIG = "config/app.json"


def load_tree(root: Path) -> Tree:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def sha(scope: str, change_id: str) -> str:
    return hashlib.sha256(f"{scope}/{change_id}".encode()).hexdigest()[:7]


def _apply(text: str | None, e: Edit) -> str:
    if not e.find:
        return e.replace
    if text is None or text.count(e.find) != 1:
        raise ValueError(f"edit to {e.path}: {e.find!r} must occur exactly once")
    return text.replace(e.find, e.replace)


def commit(tree: Tree, change: AppChange) -> tuple[Tree, list[FileDiff]]:
    new = dict(tree)
    for e in change.edits:
        new[e.path] = _apply(new.get(e.path), e)
    diffs = []
    for path in dict.fromkeys(e.path for e in change.edits):
        old = tree.get(path, "").splitlines(keepends=True)
        lines = list(difflib.unified_diff(old, new[path].splitlines(keepends=True), n=2))
        patch = "".join(lines[2:])  # drop the ---/+++ header; the path is a field
        adds = sum(1 for ln in lines[2:] if ln.startswith("+"))
        dels = sum(1 for ln in lines[2:] if ln.startswith("-"))
        diffs.append(FileDiff(path=path, additions=adds, deletions=dels, patch=patch))
    return new, diffs


def config_keys(tree: Tree) -> dict[str, Value]:
    """config/app.json flattened to dotted keys, e.g. tools.broker.timeout_s."""
    out: dict[str, Value] = {}

    def walk(prefix: str, node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}{k}.", v)
        elif isinstance(node, bool | int | float | str):
            out[prefix[:-1]] = node

    walk("", json.loads(tree[CONFIG]))
    return out
