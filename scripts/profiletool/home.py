"""The Herdr home (~/.config/herdr-app): the only folder Herdr reads."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .files import load_json, notify, write_json
from .spec import SpecError

# Herdr writes these into mod folders; they're not ours.
HERDR_WRITTEN = frozenset({"gpui-kit.d.ts", "jsconfig.json", "tsconfig.json"})
# The kinds of things a package installs, each in its own folder of the home.
KINDS = ("layouts", "themes", "mods")
# The manifest's fields that are lists (manifest.py documents them all).
LISTS = ("installed", "profiles", "created", "uninstalled", "config_keys", "folders")


def default_home() -> Path:
    return Path(os.environ.get("HERDR_APP_HOME", Path.home() / ".config" / "herdr-app"))


@dataclass(frozen=True)
class Home:
    path: Path

    @property
    def manifest_path(self) -> Path:
        """What install wrote, with hashes: what makes the other commands safe."""
        return self.path / ".herdr-profiles.json"

    @property
    def pending_path(self) -> Path:
        """The journal: what a write phase is about to do, until its manifest is saved (manifest.py)."""
        return self.path / ".herdr-profiles.pending.json"

    @property
    def profiles_path(self) -> Path:
        return self.path / "profiles.json"

    @property
    def keys_path(self) -> Path:
        return self.path / "keys.json"

    def file(self, rel: str) -> Path:
        return self.path / rel

    def load_manifest(self) -> dict[str, Any]:
        data = self.load_checked(self.manifest_path, {}, "move it away to start over (install then adopts"
                                 " files that are exactly ours, and stops on any other)")
        if not isinstance(data, dict) or not all(isinstance(data.get(k, []), list) for k in LISTS) \
                or not all(isinstance(data.get(k, {}), dict) for k in ("files", "owners", "added", "checkout")):
            raise SpecError(f"{self.manifest_path}: not a manifest this tool wrote; fix it, or move it away")
        return data

    @staticmethod
    def load_checked(path: Path, default: Any, fix: str) -> Any:
        try:
            return load_json(path, default)
        except (ValueError, OSError) as err:
            raise SpecError(f"{path}: can't read it ({err}); {fix}") from None

    def linked(self, rel: str) -> Path | None:
        """The first symlink on the way from the home to `rel` (itself included), or None.
        Nothing is ever deleted through one: what's behind it isn't the home's."""
        kind, _, rest = rel.rstrip("/").partition("/")
        p = self.path / kind  # a linked layouts/, mods/ or themes/ folder is fine: it's the home's
        for part in rest.split("/") if rest else []:
            p = p / part
            if p.is_symlink():
                return p
        return None

    def save_manifest(self, data: dict[str, Any]) -> None:
        write_json(self.manifest_path, data)

    def shipped(self) -> set[str]:
        """Names Herdr ships and replaces on every start ("layouts/main", "mods/files")."""
        where = self.path / "installed.json"
        data = self.load_checked(where, {}, "Herdr writes it on start: restart Herdr, or move it away")
        if not isinstance(data, dict):
            raise SpecError(f"{where}: must be a JSON object (Herdr writes it on start: restart Herdr)")
        names = data.keys()
        return {f"layouts/{n.split(':', 1)[1]}" if n.startswith("layout:") else f"mods/{n}" for n in names}

    def remove(self, rel: str) -> None:
        """Deletes a file we wrote, then any folder it leaves empty (Herdr's own files don't count).
        Callers check `linked` first; this never follows a link either."""
        dest = self.file(rel)
        if self.linked(rel):
            return
        dest.unlink(missing_ok=True)
        notify("delete", dest)
        stop = {self.path, *(self.path / kind for kind in KINDS)}
        for parent in dest.parents:
            if parent in stop or parent.is_symlink():
                return
            try:
                if any(p for p in parent.iterdir() if p.name not in HERDR_WRITTEN):
                    return
                shutil.rmtree(parent)
                notify("delete", parent)
            except FileNotFoundError:
                pass
