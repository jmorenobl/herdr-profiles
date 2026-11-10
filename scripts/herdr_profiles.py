#!/usr/bin/env python3
"""Install, inspect and sync Herdr profiles between this repo and the Herdr home.

The repo is the source of truth. Herdr only reads ~/.config/herdr-app, so
`install` builds each package's layout and copies its themes and mods there,
and records what it wrote (with hashes) in a manifest. That manifest is what
makes the other commands safe:

  install [profile...]
             build + copy repo -> Herdr home: the core and the profiles named
             (none: all), plus those installed already. Checks Herdr's version
             first; refuses to overwrite a file edited in Herdr since the last
             install (use `pull`, or --force) or one of the person's own.
  status     show what differs between the repo and the Herdr home.
  pull       developers: copy files edited in Herdr back into the repo.
  uninstall [profile]
             remove what `install` wrote (everything, or one profile), if it
             wasn't edited since, and what it added to profiles.json and
             keys.json, if that's still as it left it.
  check      validate JSON and profiles, build every layout, and run
             `herdr-app check` on each mod.

Personal settings never live in the repo: profiles.json (which project gets
which profile) and keys.json stay in the Herdr home. `install` only adds a
profile's entry, suggested rules and keys the first time it sees that profile,
and records them so `uninstall` can take them back.

The code is in scripts/profiletool/. Stdlib only; Python 3.9+.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profiletool.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
