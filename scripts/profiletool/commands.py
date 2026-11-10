"""status, install, pull, uninstall, check."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import build, herdr, personal, spec
from . import manifest as manifest_mod
from .files import atomic_write, dump_json, finish_first, load_json, sha
from .home import Home
from .plan import Entry, clashes, entries, guard_shipped, needs, state, top


@dataclass(frozen=True)
class Context:
    repo: Path
    home: Home

    def packages(self) -> list[spec.Package]:
        for folder in spec.strays(self.repo):
            print(f"  note      {self.rel(folder)}/ has no profile.json: skipped")
        return spec.discover(self.repo)

    def left_out(self, pkg: spec.Package, packages: list[spec.Package], data: dict) -> str | None:
        """Why `install` with no names leaves `pkg` out (it, or a layout it needs, was uninstalled on
        purpose), or None. Installed profiles are never left out."""
        if pkg.name in manifest_mod.installed(data):
            return None
        gone = manifest_mod.uninstalled(data)
        if pkg.name in gone:
            return "uninstalled on purpose"
        for base in needs(pkg, packages, self.core(packages))[1:]:
            if base.name in gone:
                return f"it needs {base.name}, uninstalled on purpose"
        return None

    def rel(self, path: Path) -> str:
        return path.relative_to(self.repo).as_posix()

    def core(self, packages: list[spec.Package]) -> spec.Package:
        """The package in core/: the default profile and the switcher, installed with every profile."""
        core = next((p for p in packages if p.path == self.repo / "core"), None)
        if core is None:
            raise spec.SpecError(f"{self.repo / 'core'}: missing profile.json (the core is always installed)")
        return core

    def selection(self, packages: list[spec.Package], names: list[str], data: dict,
                  everything: bool = True) -> list[spec.Package]:
        """The packages an install of `names` touches: those (none named: all of them but those
        left out on purpose, unless not `everything`), what they need, the core, and every
        profile installed already."""
        by_name = {p.name: p for p in packages}
        core = self.core(packages)
        unknown = [n for n in names if n not in by_name]
        if unknown:
            raise spec.SpecError(f"no profile named {', '.join(map(repr, unknown))}. Available: "
                                 + ", ".join(f"{p.name} (the core, always installed)" if p == core else p.name
                                             for p in packages))
        if names or not everything:
            start = [by_name[n] for n in names]
        else:
            start = [p for p in packages if not self.left_out(p, packages, data)]
        start += [by_name[n] for n in manifest_mod.installed(data) if n in by_name]
        chosen = {n.name for p in [*start, core] for n in needs(p, packages, core)}
        return [p for p in packages if p.name in chosen]


def status(ctx: Context) -> int:
    data = ctx.home.load_manifest()
    manifest = data.get("files", {})
    packages = ctx.packages()
    have = [p for p in packages if p.name in manifest_mod.installed(data)]
    shown = ctx.selection(packages, [], data, everything=False) if have else []
    items = entries(packages, shown)
    found = clashes(items, ctx.home, manifest)
    dirty = 0
    for e in items:
        s = "clash" if top(e.rel) in found else state(e, ctx.home, manifest)
        if s != "same":
            dirty += 1
            print(f"  {s:<9} {e.rel}")
    for rel in sorted(set(manifest) - {e.rel for e in items}):
        dirty += 1
        print(f"  removed   {rel}  (no longer in the repo; `install` deletes it)")
    for pkg in packages:
        if pkg not in shown:
            why = ctx.left_out(pkg, packages, data)
            if why:
                print(f"  left out  {pkg.name}  ({why}: plain `install` leaves it out;"
                      f" `install {pkg.name}` brings it back)")
            else:
                print(f"  available {pkg.name}  (not installed: `install {pkg.name}`)")
    if not have:
        print("Nothing installed in this Herdr home yet.")
    elif not dirty:
        print("Herdr home matches the repo.")
    print("\n  new/outdated/missing: run install · edited: run pull · conflict: decide, then pull or install --force"
          "\n  clash: a file of your own has that name; move it away first")
    return 0


def install(ctx: Context, names: list[str] | None = None, force: bool = False, sets: list[str] | None = None,
            prompt: personal.Prompt = None, version_check: bool = True) -> int:
    """`names`: the profiles to install (none: all), plus the core and what's installed already;
    `sets`: --set answers; `prompt`: how to ask a new profile's questions (None: use defaults)."""
    packages = ctx.packages()
    owners = repo_owners(packages)
    data = manifest_mod.upgrade(ctx.home.load_manifest(), owners)
    targets = ctx.selection(packages, names or [], data)
    preset = personal.parse_sets(sets or [], packages)
    if version_check:
        print(f"  checked   Herdr app {herdr.require()}")
    core = ctx.core(packages)
    if not names:
        for pkg in packages:
            why = pkg not in targets and ctx.left_out(pkg, packages, data)
            if why:
                print(f"  left out  {pkg.name} ({why}; `install {pkg.name}` brings it back)")
    if names:
        for pkg in targets:
            if pkg.name not in names:
                why = ("the core" if pkg == core else "installed already" if pkg.name in data["installed"]
                       else "needed by what you named")
                print(f"  also      {pkg.name} ({why})")
    for name in sorted(set(preset) - {p.name for p in targets}):
        print(f"  note      --set {name}.… ignored: {name} isn't being installed")
        del preset[name]
    items = entries(packages, targets)
    guard_shipped(items, ctx.home)
    manifest: dict[str, str] = data["files"]

    found = clashes(items, ctx.home, manifest)
    if found:
        report_clashes(ctx, found, targets, packages, data)
        return 1
    states = {e.rel: state(e, ctx.home, manifest) for e in items}
    blocked = [rel for rel, s in states.items() if s in ("edited", "conflict")]
    if blocked and not force:
        print("Not installing: these were changed in the Herdr home since the last install:")
        for rel in blocked:
            print(f"  {states[rel]:<9} {rel}")
        print("Bring them into the repo with `pull`, or overwrite them with `install --force`.")
        return 1

    # The person's files are read and checked, the questions asked and the merge worked out
    # before anything is written: a broken file or a stop at a question leaves the home as it was.
    config, keys = personal.load_config(ctx.home), personal.load_keys(ctx.home)
    recorded = personal.recognise_old(targets, data, config, keys)
    answers = personal.ask_first_time(targets, ctx.home, data, preset, prompt, config)
    merge = personal.plan_first_time(targets, ctx.home, data, answers, config, keys)
    in_repo = {p.name for p in packages}
    chosen = {p.name for p in targets}
    with finish_first():
        new_mods = stage_new_mods(items, ctx.home)
        # mod.json first: Herdr docks a mod folder it finds without one into the shown layout.
        changed = 0
        for e in sorted(items, key=lambda e: (not e.rel.endswith("/mod.json"), e.rel)):
            if states[e.rel] != "same":
                if e.mod not in new_mods:
                    atomic_write(ctx.home.file(e.rel), e.data)
                changed += 1
                print(f"  installed {e.rel}")
            manifest[e.rel] = e.sha
            data["owners"][e.rel] = e.pkg.name

        gone = [rel for rel in sorted(set(manifest) - {e.rel for e in items})
                if not (manifest_mod.owner(data, rel, owners) in in_repo
                        and manifest_mod.owner(data, rel, owners) not in chosen)]
        keeping = mods_kept(gone, ctx.home, manifest)  # another profile's files: install never removes one
        for rel in gone:
            if ctx.home.linked(rel):
                print(f"  kept      {rel} (behind a symlink, {ctx.home.linked(rel)}: not deleted through it)")
            elif rel in keeping:
                print(f"  kept      {rel} (another file of this mod is kept, and a mod without one gets docked by Herdr)")
            elif sha(ctx.home.file(rel)) in (manifest[rel], None):
                ctx.home.remove(rel)
                print(f"  removed   {rel}")
            else:
                print(f"  kept      {rel} (edited in Herdr; it's yours now, delete it yourself)")
            del manifest[rel]
            data["owners"].pop(rel, None)

        for line in recorded:
            print(line)
        changed += merge.apply()
        data["installed"] = [p.name for p in packages if p.name in chosen]
        data["uninstalled"] = [n for n in data["uninstalled"] if n not in chosen]
        ctx.home.save_manifest(data)
    print("Installed." if changed else "Nothing to install: Herdr home matches the repo.")
    return 0


def mods_kept(rels: list[str], home: Home, files: dict[str, str]) -> set[str]:
    """The mod.json files to keep while removing `rels`: those of a mod where another file is
    kept (edited, or behind a symlink). Herdr docks a mod folder without mod.json into the shown layout."""
    kept = {rel.split("/")[1] for rel in rels if rel.startswith("mods/") and rel.count("/") >= 2
            and not rel.endswith("/mod.json")
            and (home.linked(rel) or sha(home.file(rel)) not in (files[rel], None))}
    return {f"mods/{m}/mod.json" for m in kept} & set(rels)


def repo_owners(packages: list[spec.Package]) -> dict[str, str]:
    """Which profile each file the repo installs belongs to."""
    return {e.rel: e.pkg.name for e in entries(packages)} if packages else {}


def report_clashes(ctx: Context, found: dict[str, Entry], targets: list[spec.Package],
                   packages: list[spec.Package], data: dict) -> None:
    core = ctx.core(packages)
    print("Not installing: the Herdr home already has things of its own with these names"
          " (install didn't write them, and won't replace them, not even with --force):")
    for name, e in sorted(found.items()):
        link = " — a symlink" if build_linked(name, ctx.home) else ""
        print(f"  clash     {name}  (profile {e.pkg.name}{link})")
    print("Herdr knows layouts, themes and mods by name, so ours can't go in beside yours. Nothing was written.")
    print(f"Move or rename yours first (they're in {ctx.home.path}), then install again.")
    clashing = {e.pkg.name for e in found.values()}
    fixed = {core.name, *data["installed"]}  # the core and installed profiles are always installed
    movable = clashing - fixed
    if movable and not clashing & fixed:
        keep = [p for p in targets if not any(n.name in movable for n in needs(p, packages, core))]
        print(f"Or leave out {', '.join(sorted(movable))}: `install {' '.join(p.name for p in keep)}`")
    elif core.name in clashing:
        print(f"{core.name} is the core, installed with every profile: yours has to move.")


def stage_new_mods(items: list[Entry], home: Home) -> set[str]:
    """A mod folder that doesn't exist yet appears whole, in one rename."""
    new_mods = {e.mod for e in items if e.mod and not home.file(f"mods/{e.mod}").exists()}
    for mod in sorted(new_mods):
        stage = home.file(f"mods/.{mod}.staging")
        shutil.rmtree(stage, ignore_errors=True)
        for e in items:
            if e.mod == mod:
                target = stage / e.rel.split("/", 2)[2]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(e.data)
        os.replace(stage, home.file(f"mods/{mod}"))
    return new_mods


def pull(ctx: Context) -> int:
    """Brings files edited in Herdr back into the repo. A developer command."""
    data = ctx.home.load_manifest()
    manifest = data.setdefault("files", {})
    pulled = left = 0
    packages = ctx.packages()
    have = [p for p in packages if p.name in manifest_mod.installed(data)]
    items = entries(packages, ctx.selection(packages, [], data, everything=False) if have else [])
    found = clashes(items, ctx.home, manifest)
    for name, e in sorted(found.items()):
        print(f"  skipped   {name}: not install's (a file of your own, or a symlink); not pulled")
    for e in items:
        if top(e.rel) in found:
            continue
        s = state(e, ctx.home, manifest)
        dest = ctx.home.file(e.rel)
        if s not in ("edited", "conflict") or not dest.is_file():
            continue
        if s == "conflict":
            print(f"  conflict  {e.rel}: changed in both places; taking Herdr's copy (the repo's is in git)")
        if e.built:
            if not pull_built(ctx, e, dest):
                left += 1
                continue
        else:
            atomic_write(e.src, dest.read_bytes())
        # What Herdr has is now what the repo has. A built layout's bytes may still differ
        # in format: `status` shows it as outdated, and the next install rewrites it.
        manifest[e.rel] = sha(dest)
        pulled += 1
        print(f"  pulled    {e.rel}")
    data["files"] = manifest
    ctx.home.save_manifest(data)
    if left:
        print(f"Pulled {pulled} file(s); {left} layout edit(s) above need applying by hand.")
        return 1
    print(f"Pulled {pulled} file(s). Review with `git diff`." if pulled else "Nothing edited in Herdr.")
    return 0


def pull_built(ctx: Context, e: Entry, dest: Path) -> bool:
    """A built layout goes back into its source file when the recipe is only source + switcher
    and the switcher is untouched. Otherwise there's no file to write it into faithfully:
    show what changed and leave it."""
    recipe = e.pkg.layout
    try:
        live = load_json(dest, None)
    except ValueError:
        print(f"  not pulled {e.rel}: Herdr's copy is not valid JSON")
        return False
    source = build.unbuild(e.pkg, live) if isinstance(live, dict) else None
    if source is not None:
        atomic_write(e.pkg.path / recipe.source, dump_json(source))
        return True
    why = ("the switcher block is added by the build (scripts/profiletool/build.py)" if recipe.plain
           else f"it's built from the recipe in {ctx.rel(e.pkg.path)}/profile.json")
    print(f"  not pulled {e.rel}: {why}; apply this by hand:")
    ours = e.data.decode().splitlines()
    theirs = dest.read_text(encoding="utf-8").splitlines()
    for line in difflib.unified_diff(ours, theirs, "built", "in Herdr", lineterm="", n=2):
        print(f"    {line}")
    return False


def uninstall(ctx: Context, name: str | None = None) -> int:
    """Removes what install wrote (all of it, or one profile's), and takes back what it added to
    profiles.json and keys.json where that's still exactly as it left it."""
    data = ctx.home.load_manifest()
    have = manifest_mod.installed(data)
    try:
        packages = ctx.packages()
    except spec.SpecError:
        if name:
            raise
        packages = []  # a full uninstall needs only the manifest
    by_name = {p.name: p for p in packages}
    if name is not None:
        if name not in have:
            known = f"no profile named {name!r}" if name not in by_name else f"{name} isn't installed"
            print(f"Nothing to uninstall: {known}. Installed: {', '.join(have) or 'nothing'}.")
            return 1
        core = ctx.core(packages)
        users = [p for p in have if p != name and p in by_name
                 and name in [n.name for n in needs(by_name[p], packages, core)]]
        if users:
            why = ("it's the core (the switcher and the default profile), which every profile needs"
                   if name == core.name else
                   f"{', '.join(users)} {'is' if len(users) == 1 else 'are'} built on its layout")
            print(f"Not uninstalling {name}: {why}.")
            print(f"Uninstall {' and '.join(users)} first, or run `uninstall` with no name to remove everything.")
            return 1
        if name == core.name:
            name = None  # the core alone: that's everything
    if not have and not data:
        print("Nothing to uninstall: nothing from this repo is installed in this Herdr home.")
        return 0
    names = have if name is None else [name]
    owners = repo_owners(packages)
    files = data.get("files", {})
    rels = sorted(rel for rel in files if name is None or manifest_mod.owner(data, rel, owners) == name)
    merge = personal.plan_removal(names, ctx.home, data, packages, everything=name is None)
    with finish_first():
        keeping = mods_kept(rels, ctx.home, files)
        for rel in rels:
            if ctx.home.linked(rel):
                print(f"  kept      {rel} (behind a symlink, {ctx.home.linked(rel)}: not deleted through it)")
            elif rel in keeping:
                print(f"  kept      {rel} (another file of this mod is kept, and a mod without one gets docked by Herdr)")
            elif sha(ctx.home.file(rel)) in (files[rel], None):
                ctx.home.remove(rel)
                print(f"  removed   {rel}")
            else:
                print(f"  kept      {rel} (edited in Herdr; it's yours now)")
            del files[rel]
            data.get("owners", {}).pop(rel, None)
        merge.apply()
        if name is None:
            ctx.home.manifest_path.unlink(missing_ok=True)
        else:
            manifest_mod.upgrade(data, owners)
            data["installed"].remove(name)
            if name in data["profiles"]:
                data["profiles"].remove(name)  # installing it again is a first time again
            data["added"].pop(name, None)
            if name not in data["uninstalled"]:
                data["uninstalled"].append(name)  # `install` with no names leaves it out from now on
            ctx.home.save_manifest(data)
    print(f"Uninstalled {name or 'everything'}." + (f" `install` leaves it out from now on; `install {name}`"
                                                     " brings it back." if name else ""))
    return 0


def check(ctx: Context) -> int:
    """Valid JSON everywhere, valid profiles, layouts that build, and `herdr-app check` on each mod."""
    failed = 0
    invalid: set[Path] = set()
    for path in sorted(ctx.repo.rglob("*.json")):
        if ".git" in path.parts:
            continue
        try:
            load_json(path, None)
        except json.JSONDecodeError as err:
            failed += 1
            invalid.add(path)
            print(f"  invalid   {ctx.rel(path)}: {err}")
    for folder in spec.strays(ctx.repo):
        failed += 1
        print(f"  missing   {ctx.rel(folder)}/profile.json")
    try:
        packages = spec.discover(ctx.repo)
        entries(packages)
        for pkg in packages:
            print(f"  ok        layouts/{pkg.layout.name}.json builds")
    except spec.SpecError as err:
        if not any(str(err).startswith(str(p)) for p in invalid):  # already reported above
            failed += 1
            print(f"  invalid   {err}")
    program = herdr.binary()
    if program is None:
        print("  skipped   herdr-app not found: mods not checked (a local check: run it where Herdr is)")
        print("Checks passed, but mods not checked." if not failed else f"{failed} check(s) failed.")
        return 1 if failed else 0
    for folder in spec.folders(ctx.repo):
        for mod in sorted((folder / "mods").glob("*")) if (folder / "mods").is_dir() else []:
            r = subprocess.run([program, "check", str(mod)], capture_output=True, text=True)
            ok = r.returncode == 0
            failed += not ok
            print(f"  {'ok' if ok else 'FAILED':<9} mods/{mod.name}" + ("" if ok else f"\n{r.stdout}{r.stderr}"))
    print("All checks passed." if not failed else f"{failed} check(s) failed.")
    return 1 if failed else 0


def build_linked(name: str, home: Home) -> bool:
    folder = home.file(name)
    return bool(home.linked(name)) or (folder.is_dir() and any(p.is_symlink() for p in folder.rglob("*")))
