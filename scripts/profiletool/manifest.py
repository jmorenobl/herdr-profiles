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
    "uninstalled": ["ideas"]             profiles uninstalled on purpose (0.8.1): `install` with no
                                         names leaves them out; naming one brings it back
  }

"uninstalled" is optional (a 0.8.0 manifest has none: nothing was uninstalled
on purpose), so the version stays 2.

A profile installed before 0.8.0 is known (in "profiles") but has nothing in
"added". Install then records, once, what is still exactly as that install
would have added it (personal.recognise); what isn't stays unrecorded, and
uninstall keeps it.

Version 1 (before 0.8.0) has only "profiles" and "files", and always meant
every profile was installed. It's read as: installed = its "profiles", owners
= the repo's (a file the repo no longer has belongs to no profile), and
nothing known about what was added: uninstall keeps those and says so.
"""

from __future__ import annotations

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
    data.pop("version", None)
    ordered = {"version": VERSION, **data}  # version first, for whoever opens the file
    data.clear()
    data.update(ordered)
    return data
