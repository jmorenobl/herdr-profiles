"""The manifest (`.herdr-profiles.json` in the Herdr home): what install wrote and added.

Version 2 (0.8.0 on):

  {
    "version": 2,
    "installed": ["standard", "ideas"],  the profiles installed now
    "profiles": ["standard", "ideas"],   profiles whose first-time entries were added (see personal);
                                         uninstalling a profile forgets it, so installing it again
                                         is a first time again
    "files": {"<rel>": "<sha256>"},      every file install wrote, as it wrote it
    "owners": {"<rel>": "<profile>"},    the profile each file belongs to
    "added": {                           what install added to the person's own files, exactly as
      "<profile>": {                     it added it: uninstall removes only what is still the same
        "entry": {...} | null,           its profiles.json entry (null: one was there already)
        "rules": [{...}],                rules it appended to profiles.json
        "keys": [{"section": "global", "key": "ctrl-shift-i", "action": "mod.open:ideas",
                  "new_section": false}],
        "default": true                  it set profiles.json's "default" to this profile
      }
    },
    "created": ["profiles.json"],        personal files install created (deleted on a full
                                         uninstall only if nothing is left in them)
    "uninstalled": ["ideas"],            profiles uninstalled on purpose (0.8.1): `install` with no
                                         names leaves them out; naming one brings it back
    "checkout": {"path": "/abs/repo",    the checkout that installed last (0.9.2): another one stops
                 "branch": "main"},      before writing, unless `install --take-over`; branch is
                                         null outside git, "detached at <sha>" off a branch
    "config_keys": ["default"],          top-level keys install added to profiles.json (0.9.2),
                                         taken out again by a full uninstall once empty
    "folders": ["layouts", "mods"]       layouts/ themes/ mods/ folders install made (0.9.2): a full
                                         uninstall removes them if they're empty
  }

"uninstalled", "checkout", "config_keys" and "folders" are optional (older
manifests have none), so the version stays 2. Without "checkout" the home
counts as this checkout's. Without "config_keys" which keys install added is
unknown: a full uninstall then drops any of the three left empty, but only
when it changes profiles.json anyway. Without "folders" none is removed.

The journal (`.herdr-profiles.pending.json`, next to it) is written before
install or uninstall writes anything, marked after each personal file is
written, and deleted once the manifest is saved:

  {"version": 1, "command": "install",
   "after": {...} | null,                the manifest as it will be saved (null: deleted)
   "expect": {"keys.json": "<sha256>" | null},   each personal file it changes, as it will be
   "before": {"keys.json": "<sha256>" | null},   ... as it was (null: no file)
   "content": {"keys.json": "<text>" | null},    ... what it writes (null: deletes it)
   "written": ["profiles.json"]}         those written so far

A process killed in between leaves it behind. The next run (`recover`):
- a personal file written (marked, or as expected): every other file was
  written before it, so "after" is adopted; a personal file still as it was
  is written now (rolled forward); one changed since is left and said;
- none written: the old manifest stays (plus the folders install made); the
  files install wrote are exactly ours, which install recognises on its own;
- a mod staging folder (`mods/.<mod>.staging`) left half written is removed.
Not told apart: a file the person edited after a kill that came between its
write and its mark (counted as not written).
"""

from __future__ import annotations

import os
from typing import Any

VERSION = 2


def installed(data: dict[str, Any]) -> list[str]:
    """The profiles installed in the home, from either manifest version."""
    if "installed" in data:
        return list(data["installed"])
    return list(data.get("profiles", [])) if data.get("files") else []


def owner(data: dict[str, Any], rel: str, repo_owners: dict[str, str]) -> str | None:
    """Which profile a file install wrote belongs to; None when nothing says."""
    return data.get("owners", {}).get(rel) or repo_owners.get(rel)


def added(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    """What install added for `name` to the person's files; None when it wasn't recorded."""
    return data.get("added", {}).get(name)


def uninstalled(data: dict[str, Any]) -> list[str]:
    """The profiles uninstalled on purpose, which `install` with no names leaves out."""
    return list(data.get("uninstalled", []))


def upgrade(data: dict[str, Any], repo_owners: dict[str, str]) -> dict[str, Any]:
    """The same manifest as version 2 (in place): every field there, owners filled in where known."""
    data["installed"] = installed(data)
    data.setdefault("profiles", [])
    data.setdefault("files", {})
    owners = data.setdefault("owners", {})
    for rel in data["files"]:
        if rel not in owners and rel in repo_owners:
            owners[rel] = repo_owners[rel]
    data.setdefault("added", {})
    data.setdefault("created", [])
    data.setdefault("uninstalled", [])
    data.setdefault("folders", [])  # never "config_keys": its absence means "unknown"
    data.pop("version", None)
    ordered = {"version": VERSION, **data}  # version first, for whoever opens the file
    data.clear()
    data.update(ordered)
    return data


JOURNAL_VERSION = 1


def journal(command: str, after: dict[str, Any] | None, expect: dict[str, str | None],
            before: dict[str, str | None], content: dict[str, str | None]) -> dict[str, Any]:
    return {"version": JOURNAL_VERSION, "command": command, "after": after, "expect": expect,
            "before": before, "content": content, "written": []}


def check_journal(data: Any) -> bool:
    names = ("profiles.json", "keys.json")
    return (isinstance(data, dict) and data.get("version") == JOURNAL_VERSION
            and isinstance(data.get("command"), str) and isinstance(data.get("expect"), dict)
            and (data.get("after") is None or isinstance(data["after"], dict))
            and set(data["expect"]) <= set(names)
            and all(isinstance(data.get(k), dict) and set(data[k]) == set(data["expect"])
                    for k in ("before", "content"))
            and isinstance(data.get("written"), list))


def progress(data: dict[str, Any], now: dict[str, str | None]) -> dict[str, str]:
    """Where each personal file the journal expected stands: "done" (marked written, or as
    expected), "before" (still as it was: not written) or "changed" (neither: edited since)."""
    out = {}
    for name, want in data["expect"].items():
        if name in data["written"] or now.get(name) == want:
            out[name] = "done"
        elif now.get(name) == data["before"][name]:
            out[name] = "before"
        else:
            out[name] = "changed"
    return out


def same_checkout(recorded: Any, path: str) -> bool:
    """Whether the checkout recorded in a manifest is the one at `path`. None recorded: yes."""
    if not isinstance(recorded, dict) or not isinstance(recorded.get("path"), str):
        return True
    if recorded["path"] == path:
        return True
    try:
        return os.path.samefile(recorded["path"], path)
    except OSError:
        return False


def describe(recorded: dict[str, Any]) -> str:
    branch = recorded.get("branch")
    gone = "" if os.path.isdir(str(recorded.get("path"))) else ", no longer there"
    return f"{recorded.get('path')}" + (f" (branch {branch}{gone})" if branch else f" ({gone[2:]})" if gone else "")
