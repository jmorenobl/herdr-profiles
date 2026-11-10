"""Layouts built from a recipe, so no layout is hand-kept.

  built layout = base tree           (a file in the package, or another layout's tree)
               - cloned_from         (when derived: it describes the base file, not this one)
               + inserted nodes
               + the switcher        (a floating block running mods/profiles, in every layout)
               + root keys from set  (theme, preview, ...)

A derived layout gets its base's tree and inserts, not its base's `set`: keys
like theme and preview belong to each layout.

Herdr has no layout-independent place for a mod, so the profile switcher must
be inside every layout a profile shows; injecting it here keeps that a build
step instead of a copy-paste rule.
"""

from __future__ import annotations

import copy
from typing import Any, Iterator

from .files import load_json
from .spec import Insert, Package, SpecError

SWITCHER_MOD = "profiles"
SWITCHER = {"id": "profiles", "content": {"mod": SWITCHER_MOD}, "edge": "bottom", "align": "end"}

Tree = dict[str, Any]


def build(pkg: Package, packages: list[Package]) -> Tree:
    """The layout `pkg` installs, as Herdr reads it."""
    tree = base_tree(pkg, packages)
    if SWITCHER_MOD not in mods_in(tree):
        tree.setdefault("floating", []).append(copy.deepcopy(SWITCHER))
    tree.update(copy.deepcopy(pkg.layout.set))
    return tree


def base_tree(pkg: Package, packages: list[Package], seen: tuple[str, ...] = ()) -> Tree:
    """The recipe's tree before the switcher and `set`: what another layout can build on."""
    recipe = pkg.layout
    if recipe.name in seen:
        raise SpecError(f"{pkg.path}: layout bases loop: {' -> '.join((*seen, recipe.name))}")
    if recipe.source is not None:
        try:
            tree = load_json(pkg.path / recipe.source, None)
        except ValueError as err:
            raise SpecError(f"{pkg.path / recipe.source}: invalid JSON: {err}") from None
        if not isinstance(tree, dict):
            raise SpecError(f"{pkg.path / recipe.source}: a layout must be a JSON object")
    else:
        base = next((p for p in packages if p.layout.name == recipe.base), None)
        if base is None:
            raise SpecError(f"{pkg.path}: base layout {recipe.base!r} is not in any package")
        tree = base_tree(base, packages, (*seen, recipe.name))
        tree.pop("cloned_from", None)
    for item in recipe.inserts:
        insert(tree, item, pkg)
    return tree


def insert(tree: Tree, item: Insert, pkg: Package) -> None:
    ids = [n.get("id") for n in walk(tree)]
    if item.node["id"] in ids:
        raise SpecError(f"{pkg.path}: node id {item.node['id']!r} already exists in the base layout")
    parent = next((n for n in walk(tree) if n.get("id") == item.into), None)
    if parent is None or not isinstance(parent.get("children"), list):
        raise SpecError(f"{pkg.path}: no node {item.into!r} with children to insert into")
    children = parent["children"]
    sibling = item.after or item.before
    if sibling is None:
        children.append(copy.deepcopy(item.node))
        return
    at = next((i for i, c in enumerate(children) if c.get("id") == sibling), None)
    if at is None:
        raise SpecError(f"{pkg.path}: {item.into!r} has no child {sibling!r}")
    children.insert(at + 1 if item.after else at, copy.deepcopy(item.node))


def unbuild(pkg: Package, tree: Tree) -> Tree | None:
    """For a plain recipe (source + switcher only): the source file that builds `tree`.
    None when that can't be done faithfully (the switcher block itself was changed)."""
    if not pkg.layout.plain:
        return None
    tree = copy.deepcopy(tree)
    switchers = [f for f in tree.get("floating", []) if (f.get("content") or {}).get("mod") == SWITCHER_MOD]
    if switchers != [SWITCHER]:
        return None
    floating = [f for f in tree["floating"] if f != SWITCHER]
    if floating:
        tree["floating"] = floating
    else:
        tree.pop("floating", None)
    return tree


def walk(node: Tree) -> Iterator[Tree]:
    """Every node of a layout tree: the root, its children, and floating blocks."""
    yield node
    for child in node.get("children", []) or []:
        if isinstance(child, dict):
            yield from walk(child)
    for block in node.get("floating", []) or []:
        if isinstance(block, dict):
            yield from walk(block)


def mods_in(tree: Tree) -> set[str]:
    return {m for n in walk(tree) if isinstance(m := (n.get("content") or {}).get("mod"), str)}
