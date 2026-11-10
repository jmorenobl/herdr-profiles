# Contributing

How the profiles work inside, how the repo is laid out, and how to change
it. [README.md](README.md) is for people who only use the profiles; read it
first. Agents working on this repo also follow [AGENTS.md](AGENTS.md).

Herdr's own manual is `~/.config/herdr-app/AGENTS.md` once Herdr is
installed (layouts, mods, keys, commands); the type files next to it
(`gpui-kit.d.ts`, `herdr.d.ts`) are the truth for the mod API.

## Working on it

Herdr reads only `~/.config/herdr-app` (`HERDR_APP_HOME` points the tool at
another folder). This repo is the source; install copies it there and
remembers what it wrote (`.herdr-profiles.json` in the Herdr home).

```sh
make install   # build and copy into Herdr; Herdr reloads it live (ARGS="ideas", ARGS="--set p.s=v")
make status    # what differs between the repo and the Herdr home
make pull      # tweaked something live in Herdr? bring it back here
make check     # JSON, profiles, layouts build, `herdr-app check` on every mod
make test      # the tool's tests, on throwaway Herdr homes
make upstream  # what a new Herdr changed in what core/ cloned (ARGS=--diff, ARGS=--save)
make help      # all of them
```

`make` runs `python3`; `make test PY=/usr/bin/python3` runs the tests with
another Python (keep 3.9 working: macOS's own `/usr/bin/python3` is 3.9).
`scripts/herdr_profiles.py <command> --help` explains each command.

Try changes against a throwaway home, not your own window:

```sh
mkdir -p /tmp/herdr-try
HERDR_APP_HOME=/tmp/herdr-try python3 scripts/herdr_profiles.py install --skip-version-check
HERDR_APP_HOME=/tmp/herdr-try python3 scripts/herdr_profiles.py status
```

`pull` is for working on this repo: it copies what you changed in Herdr (a
theme, a mod) back into the repo's files, to commit. Someone who only uses
the profiles never needs it. It pulls only installed profiles, and never a
file of the person's own.

### Checks: local and CI

- `make test` runs everywhere: the tool's tests inject a fake `herdr-app`
  (`HERDR_APP_BIN`), and the ideas mod's tests run under `node` (skipped
  when node isn't installed).
- `make check` validates every JSON file, every `profile.json`, and builds
  every layout; then it runs `herdr-app check` on every mod. Without
  `herdr-app` it says "skipped" for the mods and still passes, so
  `herdr-app check` is a **local** check: run `make check` on a machine with
  Herdr before you commit a mod change. `HERDR_APP_BIN` set to something
  that isn't a program fails the check, and says why.
- CI (`.github/workflows/test.yml`) runs `make test` on Python 3.9 and 3.12,
  Ubuntu and macOS, and `make check` without Herdr. Only macOS is
  supported; Ubuntu is there to keep the tool portable for when Linux is.
- A mod change also needs a look in Herdr: `herdr-app shot` and
  `herdr-app status` (no errors) after `make install`.

## How the switcher works

```
you select a space
      │
      ▼
mods/profiles (invisible, in every profile layout)
  1. finds the space's folder (its first terminal's live folder)
  2. a `.herdr-profile` file there or in a parent names a profile? use it
  3. else the first rule in profiles.json that matches
  4. else the default profile
      │
      ▼
layout.switch to that profile's layout (only if it isn't shown already)
```

The switcher acts only when the active space changes, so switching layouts
by hand is respected until you go to another space. It reads
`profiles.json` each time, so edits there apply on the next space change.
Rules naming a profile that isn't in `profiles.json` are skipped; a
profile whose layout isn't installed is chosen, but nothing switches.

Herdr has no place for a mod outside layouts, so the switcher has to be in
each layout it should work from. That's why profile layouts are built (next
section) and why a layout of the person's own never switches.

## Layout of the repo

```
core/                      the mechanism; always installed
  profile.json             the standard profile (the default)
  layouts/standard.json    Herdr's main layout (cloned), without the switcher
  mods/profiles/           the switcher
  mods/standard-files/     Herdr's Files panel, with a markdown preview
  mods/standard-history/   the History panel: commits and branches as a graph, read-only
  mods/standard-tabs/      Herdr's tab bar, with a History button
profiles/<name>/           one folder per profile
  profile.json             name, layout recipe, settings, questions, suggested rules and keys
  README.md, docs/         how to use it, with screenshots (not installed)
  RECIPE.md                what it is and how it's built (herdr.dev format)
  layouts/ themes/ mods/   installed into ~/.config/herdr-app; layout JSON is built
  project/                 templates for the project folder itself, if any
upstream/                  Herdr's originals of what core/ cloned, unchanged, and the version
  herdr.json               they're from, with which clone comes from which original
scripts/herdr_profiles.py  install / status / pull / uninstall / check / upstream (`--help`)
scripts/profiletool/       the code behind it (stdlib only; module map in __init__.py)
scripts/export_public.py   `make export`: a clean one-commit copy to publish
tests/                     the tool's tests; tests/golden/ is what install must write
.github/workflows/         CI
LICENSE, NOTICE, LICENSES/ Apache 2.0; what comes from Herdr and Lucide
```

### Layouts are built

No profile keeps a whole layout file by hand. Its `profile.json` has a
recipe, and `install` builds `layouts/<name>.json` from it:

```json
"layout": {
  "name": "ideas",
  "base": "standard",
  "insert": [{ "into": "work-body", "after": "main", "node": { "id": "ideas-side", "…": "…" } }],
  "set": { "theme": "ideas", "preview": "layouts/ideas.svg" }
}
```

- `source` (a layout file in the package) or `base` (another profile's
  layout) is where it starts. A derived layout drops the base's `cloned_from`.
  A profile built on another needs it: installing it installs the base too,
  and the base can't be uninstalled while it's installed.
- `insert` adds nodes into a node's `children`, `after` or `before` a child
  (or last); `set` sets keys on the root (`theme`, `preview`, …).
- The switcher (a floating block running `mods/profiles`) is added to every
  built layout, so no profile can forget it. Don't copy it into a recipe.

`pull` on a layout built only from a `source` file puts Herdr's edits back in
that file. For a recipe with `base`, `insert` or `set` it shows the diff and
leaves the recipe for you to change.

### What install guarantees

- It never overwrites a file changed in the Herdr home since the last
  install: it stops and says to `pull` (or `install --force`).
- It never writes over a layout, theme or mod of the person's own (a clash,
  even with `--force`), nor through a symlink, and refuses names Herdr ships
  (`main`, `files`, …), which Herdr would replace on its next start anyway.
- It writes `mod.json` before anything else in a mod, because Herdr docks a
  mod it finds without one into the shown layout; a new mod folder appears
  whole, in one rename. Tests watch the writes through
  `files.watching` (tests/test_home_safety.py).
- It reads and checks `profiles.json` and `keys.json`, asks its questions
  and works out the whole merge before writing any file; Ctrl-C while
  writing waits until the writes and the manifest are done.
- A process killed while writing (not Ctrl-C: `kill -9`, a crash, power)
  loses nothing: a journal (`.herdr-profiles.pending.json`) holds the
  manifest as it will be and the personal files' new text, marked after
  each of them; the next command finishes and records what was done (or
  drops it if nothing personal was written yet) and says so.
- It edits `profiles.json` and `keys.json` with the smallest textual change
  (`scripts/profiletool/jsonedit.py`), so their formatting stays and an
  uninstall gives them back as they were. Not kept: a value that changes
  is rewritten whole in the file's style, new members go last, and an
  empty object with space inside (`{ }`, or on several lines) comes back as `{}`; a file with
  duplicate keys is rewritten whole in its own indentation.
- It records which checkout installed (folder and branch, in the manifest).
  Another checkout (a worktree, a second clone) sharing the home stops
  before writing (`install`, `pull`), and `status` says so; `install
  --take-over` makes it the one. Install from one checkout at a time: the
  home holds one checkout's files.
- The manifest (`scripts/profiletool/manifest.py` documents it) records
  every file written, which profile owns it, what was added to the person's
  own files (so uninstall takes back only that), and the profiles
  uninstalled on purpose.

## Adding a profile

1. `profiles/<name>/profile.json` (`"schema": 2`), plus its theme and mods.
   The format is documented at the top of `scripts/profiletool/spec.py`.
2. Its layout is a recipe: usually `"base": "standard"` plus `insert` and
   `set`. The switcher is added by the build; don't copy it in.
   Anything personal it needs (a folder) is an `ask` with a default, not a
   fixed setting; its rules can use the answer as `{setting}`.
3. Give its theme the layout's name (`themes/<name>.json`) and `set` it:
   Herdr then offers it only on that layout.
4. Its keys go in `keys`, in `layout:<its layout>` so they act only in its
   window; `global` only for a key that must work from any space (ideas'
   `ctrl-shift-i`). `mod:<one of its mods>` and `terminal` also work; another
   profile's layout or mod doesn't (`make check` says so). Install adds each
   key only where it's free, and a key the person binds in `global` counts as
   taken in the narrower sections too (there it would hide theirs).
5. Write its `README.md` and `RECIPE.md`, then `make check && make install`,
   and look at it in Herdr.
6. If install's output changes on purpose, update `tests/golden/` (it's what
   install must write; never change it by accident).

## Keeping up with Herdr

`core/` holds clones of Herdr's: `layouts/standard.json` (from `main`),
`mods/standard-files/` (from `files`) and `mods/standard-tabs/` (from
`tabs`). Clones are never updated by Herdr, so a new Herdr's fixes don't
reach them on their own. `upstream/` keeps the originals they came from,
unchanged, and `upstream/herdr.json` the version (0.1.14 today).

Herdr updates itself; when it's newer than that version, `make install`
says so (a note; it goes on). Then:

1. `make upstream`: reads the originals the installed Herdr ships from the
   Herdr home (checked against Herdr's own hashes in `installed.json`, so an
   edited copy is never taken for Herdr's) and says, per file of each clone:
   `take` (only Herdr changed it: copy Herdr's over ours), `merge` (we
   changed it too), `new`, `gone`. `ARGS=--diff` prints Herdr's changes.
   It never changes a clone.
2. Carry Herdr's changes into the clones by hand, where they don't fight
   ours. Look at the type files (`gpui-kit.d.ts`, `herdr.d.ts`) too: the
   mod API our mods use (switcher, ideas, history) may have changed.
3. `make check`, `herdr-app check` on the installed mods, a look with
   `herdr-app shot`.
4. `make upstream ARGS=--save` records the new originals and version. Then
   `cloned_from.version` in `core/layouts/standard.json`, NOTICE ("cloned
   from Herdr x.y.z"), `MIN_VERSION` in `scripts/profiletool/herdr.py` if a
   new API is used, and CHANGELOG.

## Each change

Update the profile's `RECIPE.md` (when a profile changed) and
`CHANGELOG.md`, run `make test` (and `make check` with Herdr), and commit.

## Publishing a clean copy

`make export` builds, in a new folder, a fresh git repo holding this repo's
HEAD as one commit, and checks it has nothing personal. The repo and its
history are left alone; only committed files are exported (it says so when
the working tree has changes).

```sh
make export DEST=../herdr-profiles-public AUTHOR="Name <id+name@users.noreply.github.com>"
make export-check DEST=../herdr-profiles-public   # check it again later
```

`AUTHOR` is required and becomes the commit's author and committer and the
new repo's `user.name`/`user.email`; the commit is dated in UTC and the new
repo has no remote. The check fails, naming file and line, on a personal
string in any file (binaries, gzip and zip members, PNG text too), path,
symlink, commit message or author field; on `ROADMAP.md` or anything in
`.git/info/exclude`; and on more than one commit, a parent or a remote.
The denied strings are worked out each time, never stored in the repo:
your `user.email` and every email in this repo's history, your home
folder's path and `/Users/<you>`, `/home/<you>`, plus one string per line of
`.git/info/export-deny` (inside `.git`, so never committed; `#` starts a
comment). Letter case and accents' encoding (NFC/NFD) are ignored; strings
hidden in other encodings (base64, `\/` escapes) are not found.
