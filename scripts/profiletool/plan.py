"""Every file a set of packages installs, and how each one stands in a Herdr home."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import build
from .files import dump_json, sha, sha_bytes
from .home import HERDR_WRITTEN, KINDS, Home
from .spec import Package, SpecError

SKIP = frozenset({".DS_Store"})


@dataclass(frozen=True)
class Entry:
    """One file to install: its path in the home, its bytes, and where they come from."""
    rel: str                  # e.g. "mods/ideas/main.js", "layouts/ideas.json"
    data: bytes
    pkg: Package
    src: Path | None = None   # the repo file it's copied from; None when built

    @property
    def built(self) -> bool:
        return self.src is None

    @property
    def sha(self) -> str:
        return sha_bytes(self.data)

    @property
    def mod(self) -> str | None:
        """The mod folder it belongs to ("mods/ideas/main.js" -> "ideas")."""
        parts = self.rel.split("/")
        return parts[1] if parts[0] == "mods" and len(parts) > 2 else None


def entries(packages: list[Package], only: list[Package] | None = None) -> list[Entry]:
    """Every file `only` installs (default: every package). Layouts build against all `packages`,
    and every package is checked, so a clash between two packages shows whichever is chosen."""
    out: list[Entry] = []
    for pkg in packages:
        out.append(Entry(f"layouts/{pkg.layout.name}.json", dump_json(build.build(pkg, packages)), pkg))
        for kind in KINDS:
            base = pkg.path / kind
            if not base.is_dir():
                continue
            for src in sorted(base.rglob("*")):
                if not src.is_file() or src.name in SKIP | HERDR_WRITTEN:
                    continue
                if kind == "layouts" and src.suffix == ".json":
                    if src != pkg.path / (pkg.layout.source or ""):
                        raise SpecError(f"{src}: a layout file no recipe uses; make it a profile's "
                                        "'layout.source', or remove it")
                    continue  # the recipe's source: installed only as built
                out.append(Entry(f"{kind}/{src.relative_to(base).as_posix()}", src.read_bytes(), pkg, src))
    seen: dict[str, Entry] = {}
    for e in out:
        if e.rel in seen:
            raise SpecError(f"{e.rel} comes from both {seen[e.rel].pkg.path} and {e.pkg.path}")
        seen[e.rel] = e
    if only is None:
        return out
    names = {p.name for p in only}
    return [e for e in out if e.pkg.name in names]


def needs(pkg: Package, packages: list[Package], core: Package) -> list[Package]:
    """What `pkg` can't be installed without: the core (the switcher, the default profile)
    and every layout it's built on (their mods are in its layout too). `pkg` itself first."""
    out = [pkg]
    while out[-1].layout.base is not None:
        base = next((p for p in packages if p.layout.name == out[-1].layout.base), None)
        if base is None or base in out:
            break  # build() says why
        out.append(base)
    return out if core in out else [*out, core]


def top(rel: str) -> str:
    """The name a file takes in the home: "mods/ideas/ui.js" -> "mods/ideas/", else the file."""
    parts = rel.split("/")
    return f"mods/{parts[1]}/" if parts[0] == "mods" and len(parts) > 2 else rel


def clashes(items: list[Entry], home: Home, manifest: dict[str, str]) -> dict[str, Entry]:
    """Names the person already uses for their own things: a symlink (to anything, even our own
    files), or a layout, theme or mod folder that install never wrote (nothing recorded under it), that isn't what install would write.
    {"themes/ideas.json" | "mods/ideas/": the first entry that needs it}.

    A name holding exactly our files is ours (a manifest lost to a crash): no clash. A name
    install wrote before keeps today's per-file states (edited, conflict) instead."""
    owned = {top(rel) for rel in manifest}
    ours: dict[str, list[Entry]] = {}
    for e in items:
        ours.setdefault(top(e.rel), []).append(e)
    found: dict[str, Entry] = {}
    for name, group in ours.items():
        if linked(name, group, home):
            found[name] = group[0]  # a link: what's behind it isn't the home's (even if install wrote there)
            continue
        if name in owned or not os.path.lexists(home.file(name)):
            continue
        if name.startswith("mods/"):
            folder = home.file(name)
            wanted = {e.rel for e in group}
            extra = [p for p in folder.rglob("*") if p.is_file() and p.name not in HERDR_WRITTEN | SKIP
                     and f"{name}{p.relative_to(folder).as_posix()}" not in wanted]
            differ = [e for e in group if home.file(e.rel).exists() and sha(home.file(e.rel)) != e.sha]
            if extra or differ or not folder.is_dir():
                found[name] = group[0]
        elif sha(home.file(name)) != group[0].sha:
            found[name] = group[0]
    return found


def guard_shipped(items: list[Entry], home: Home) -> None:
    """Herdr replaces its own layouts and mods on every start: never install over them."""
    taken = home.shipped()
    for e in items:
        top = "/".join(e.rel.split("/")[:2])
        stem = top.rsplit(".", 1)[0] if top.startswith("layouts/") else top
        if stem in taken:
            raise SpecError(f"{e.rel} would replace something Herdr ships ({stem}); rename it")


def state(e: Entry, home: Home, manifest: dict[str, str]) -> str:
    """same | new | outdated | edited | conflict | missing"""
    dest, recorded = sha(home.file(e.rel)), manifest.get(e.rel)
    if dest is None:
        return "missing" if recorded else "new"
    if dest == e.sha:
        return "same"
    if recorded is None:
        return "conflict"  # something we never wrote is there
    if dest == recorded:
        return "outdated"  # the repo moved on; Herdr's copy is what we installed
    return "edited" if e.sha == recorded else "conflict"  # edited in Herdr (and maybe in the repo too)


def linked(name: str, group: list[Entry], home: Home) -> bool:
    """A symlink at the name, on the way to one of its files, or anywhere in its mod folder."""
    if any(home.linked(e.rel) for e in group):
        return True
    folder = home.file(name)
    return name.startswith("mods/") and folder.is_dir() and any(p.is_symlink() for p in folder.rglob("*"))
