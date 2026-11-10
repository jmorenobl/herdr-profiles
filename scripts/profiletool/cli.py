"""The command line: `python3 scripts/herdr_profiles.py <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import commands, herdr
from .home import Home, default_home
from .spec import SpecError

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install, inspect and sync Herdr profiles between this repo and the Herdr home.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="what differs between the repo and the Herdr home")
    p = sub.add_parser("install", help="build and copy the repo into the Herdr home",
                       description="Installs the core (the standard profile and the switcher) and the profiles you"
                                   " name; with no names, every profile but those uninstalled on purpose. Profiles"
                                   " installed before stay installed and are updated too (`uninstall <profile>`"
                                   " removes one).")
    p.add_argument("profiles", nargs="*", metavar="PROFILE", help="profiles to install (default: all but those uninstalled on purpose)")
    p.add_argument("--force", action="store_true", help="overwrite files edited in Herdr since the last install")
    p.add_argument("--set", action="append", default=[], metavar="PROFILE.SETTING=VALUE",
                   help="answer a new profile's question in advance (repeatable), e.g. ideas.folder=~/notes/ideas")
    p.add_argument("--skip-version-check", action="store_true",
                   help=f"install even if herdr-app is missing or older than {herdr.show(herdr.MIN_VERSION)}")
    sub.add_parser("pull", help="developers: copy files edited in Herdr back into this repo")
    p = sub.add_parser("uninstall", help="remove what install wrote (everything, or one profile)",
                       description="Removes what install wrote and takes back what it added to profiles.json and"
                                   " keys.json, where still exactly as it left it. With a profile, only that one.")
    p.add_argument("profile", nargs="?", metavar="PROFILE", help="the profile to remove (default: everything)")
    sub.add_parser("check", help="validate JSON and profiles, build every layout, run herdr-app check on every mod")
    args = parser.parse_args(argv)

    ctx = commands.Context(REPO, Home(default_home()))
    run = {
        "status": lambda: commands.status(ctx),
        "install": lambda: commands.install(ctx, names=args.profiles, force=args.force, sets=args.set,
                                            prompt=input if sys.stdin.isatty() and sys.stdout.isatty() else None,
                                            version_check=not args.skip_version_check),
        "pull": lambda: commands.pull(ctx),
        "uninstall": lambda: commands.uninstall(ctx, args.profile),
        "check": lambda: commands.check(ctx),
    }[args.command]
    try:
        return run()
    except SpecError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
