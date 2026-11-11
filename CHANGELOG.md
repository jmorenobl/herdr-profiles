# Changelog

## Unreleased

- `standard`: a bottom terminal, as in an editor. A **Terminal** button in
  the tab bar (`standard-tabs.terminal` for a key; README has the line for
  `keys.json`) shows a shell below the focused pane and hides it without
  ending it: hidden is parked (`terminal.park`), so the shell and its
  history come back (`terminal.keep`, down). One per space, started in the
  focused pane's folder with `hc run` and found again by its
  `standard.terminal=<space id>` label; pressed in another tab, it moves
  there. A parked one whose space is closed is ended. A space on another
  machine gets a plain split down. The core now has a key of its own,
  ``ctrl-` `` in `global`, added on a first install like any profile's; a
  home installed before keeps its `keys.json` as it is (README has the line
  to add).
- Installer: a full uninstall removes a `keys.json` section install made
  once it's empty, whichever profile's key made it. It was left behind
  empty when a later profile's key was the last one out, which the core
  having a key now makes the usual case.
- README: a banner on top, the profiles as a deck of cards (`standard`,
  `ideas`, and one face down for the next). It's a page,
  `docs/banner/banner.html`, that `make banner` renders to
  `docs/banner.png` with headless Chrome; adding a profile now includes
  dealing its card (CONTRIBUTING, "Adding a profile"). The ideas board
  screenshot moved to the ideas section.

## 0.9.4 — 2026-11-10

- Keeping up with Herdr: `upstream/` keeps Herdr 0.1.14's originals of what
  `core/` cloned (`main`, `files`, `tabs`), unchanged. `make upstream` reads
  the installed Herdr's originals (checked against Herdr's hashes in
  `installed.json`) and says per file what a new Herdr changed: take, merge,
  new, gone (`--diff` shows it, `--save` records it once merged); it never
  changes a clone. `make install` notes, and goes on, when Herdr is newer
  than the version recorded there. `make check` checks the record.
  CONTRIBUTING, "Keeping up with Herdr".
- CI: actions on Node 24 (GitHub retires Node 20): checkout v7.0.1,
  setup-python v7.1.0, setup-node v7.1.0, still pinned by exact tag.
- Installer: a profile's keys can go in its own layout's section
  (`layout:<name>`), which is where keys for one window belong; `global`
  stays for keys that must work from any space (ideas' `ctrl-shift-i`, so
  nothing in what install writes changed). `profile.json` key sections are
  checked: Herdr's names only, and a profile's own layout and mods only. A
  key the person binds in `global` counts as taken in a narrower section
  (it would hide theirs there), and a section whose keys are all taken is no
  longer left behind empty.
- Tests: the ideas mod's glue around its two pure helpers, rendered on the
  stand-in view: the side panel's warning about untyped folders (only the
  side panel, once, and it still loads when the listing fails) and capture's
  footnote (where the idea comes from, or where it saves, in amber). The
  stand-in UI logs the text and colors drawn; the stand-in `herdr` can make
  one `exec` fail (`failExec`) and gives each theme color its own name.

## 0.9.3 — 2026-11-10

- README: a front page for people who don't know Herdr profiles yet: badges
  (tests, license, Herdr, macOS, Python), what it feels like, and each
  profile with screenshots (a History panel shot of a demo repo in
  `docs/history.png`, no metadata).

## 0.9.2 — 2026-11-10

What exists, working well: fixes from independent audits of every mod and
the installer's open items.

### Mods

- **Ideas, autocommit.** It no longer commits into a bigger repo the ideas
  folder sits in (that took whatever else was staged there), nor while a
  merge, rebase, cherry-pick or revert is under way, with conflicts or on a
  detached HEAD (that concluded the operation with conflict markers): it
  warns instead. New ideas are seen with `status.showUntrackedFiles=no`;
  non-ASCII names stay readable in subjects; subjects and tab names no
  longer cut an emoji in half; a pending commit is made when the side panel
  closes.
- **Ideas.** A type change is refused while a terminal works inside the
  idea's folder (it split the idea in two); a double click on a type or
  status chip no longer reports a failure. Agent tabs are found by a terminal
  in the idea's folder, by name only for named tabs. The side panel's note
  file follows the selected idea and is re-read when it changes on disk.
  `ideas.review` with the Board tab closed now starts the review. A drop
  whose status can't be written puts the order back; review writes retry
  once on a changed file and say what failed. Ages no longer come out a day
  short after a daylight saving change. New ideas' folders keep letters of
  any script (`Straße` → `strasse`, `日本語` stays). Ideas are read in
  parallel on reload.
- **Files panel, markdown images.** Only an image alone on its line is drawn
  (a badge `[![CI](…)](link)` as one picture that opens its link; also a
  list item's own paragraph or a quote's line); an image in a
  table, a sentence or a row of badges shows its alt text (or file name),
  and images in code (spans, fenced, indented) or HTML comments are left
  alone. Before, every image was cut out, tearing tables and badges apart.
- **Files panel.** `![](<a b.png>)` works; a link to a folder (`[docs](docs/)`)
  opens it in the tree instead of "Cannot preview"; at most 4 images load at
  once; a web image (a badge) is downloaded again every 6 hours (offline, the
  last copy shows); an image still loading from another space or file no
  longer lands in the one shown.
- **Switcher.** A `profiles.json` of the wrong shape (`"rules": {}`, a `null`
  rule or profile, not an object) falls back to the default instead of
  failing on every redraw; a remote space's `~` folder is looked up in that
  machine's home and a relative one no longer hangs the lookup; a check
  that ends after you moved on no longer lets another space be checked
  twice at once.
- **Tab bar.** After a layout switch (by hand or by the switcher), a space
  never seen before opens with the side panel closed, as Herdr's own does,
  instead of inheriting the last space's panel.
- README: what rules can't match (letter case, symlinks, `~` on another
  machine).
- **History panel.** The list no longer breaks with `log.showSignature` set,
  or with a 0x1F in a subject or an author; a subject written on two lines
  isn't repeated in the body. A file's diff is that file's only (names like
  `src[id].tsx` or `:colon` were read as patterns). Show more no longer
  repeats commits when history moved meanwhile (it reads the list again),
  nor adds the old branch's page after you pick another one. Moving to
  another folder of the same repo keeps the open commit and what's loaded.
  In a partial clone, opening a commit never downloads (git 2.44 or newer;
  older git shows the message only) and says what isn't there. The "first
  1,000 files" and "Cannot read more history" notes clear when they no longer
  apply. Hidden, the panel stops reading git and catches up when shown; in a
  worktree it also follows the refs shared with the main checkout; past 10
  lanes, a commit's dot stays on the last lane with a mark. Watching another
  repo and back no longer leaves extra watchers running.

### Installer

- **Several checkouts, one Herdr home.** Install records the checkout that
  installed (its folder and branch). Another clone or worktree stops before
  writing and says which one installed; `status` says so too, and `pull`
  stops. `install --take-over` makes this checkout the one. A home
  installed before keeps working as this checkout's.
- **Killed while writing.** A process killed between writing files and
  saving its record (`kill -9`, a crash) no longer loses what install added
  to `profiles.json` and `keys.json`: a journal is written first, and the
  next command finishes what was cut short, records it and says so (also
  for uninstall, and for a mod folder left half staged).
- A full uninstall also takes back what was added for a profile no longer
  installed (lost in a `--take-over`, or gone from the repo). A
  `profiles.json` that is a symlink stays one.
- **Your formatting stays.** `keys.json` and `profiles.json` get the
  smallest edit (one line more, in your indentation, tabs, CRLF or on one
  line), and an uninstall gives them back byte for byte.
- **A full uninstall leaves the home as it was**: the empty `layouts/`,
  `themes/` and `mods/` folders install made go, and a `profiles.json` you
  had loses the `"default": null` / `"profiles": {}` install left (also for
  homes installed before 0.8.0).
- Folder answers: letter case counts as the same folder in the "your home
  or above" check (`/users` on macOS), and `\x1c`-`\x1f`, C1 controls and a
  BOM are refused, by the installer and the ideas mod alike.
- `make check` with `HERDR_APP_BIN` pointing nowhere fails and says why,
  instead of skipping the mods.
- Tests see the write order (`mod.json` first, new mod folders whole).

## 0.9.1 — 2026-11-10

First public release. Versions before it were never published; this one
starts the record. What's in it:

- **Profiles per project.** A profile is a layout, a theme and its panels.
  An invisible switcher in every profile layout picks the profile when you
  go to a space: a `.herdr-profile` file in the project, else the rules in
  `~/.config/herdr-app/profiles.json`, else the default.
- **`standard`** (the default): Herdr's main window, a Files panel that
  shows markdown rendered (links and images), and a History panel with the
  repo's commits and branches as a graph.
- **`ideas`**: an idea inbox folder as a kanban board, idea details with
  actions for your coding agent, quick capture with `ctrl-shift-i` from any
  space, a weekly review of stale ideas, and autocommit of the folder.
  Install asks where your ideas live (default `~/ideas`).
- **Installer** (`make install`, `make uninstall`, `make status`): install
  all profiles or the ones you name; checks Herdr ≥ 0.1.14; never
  overwrites a file you changed or one of your own with the same name;
  only adds to `keys.json` and `profiles.json`, and uninstall takes back
  only what it added and you haven't changed.
- macOS only, for now. Apache 2.0; parts are derived from Herdr (NOTICE).
