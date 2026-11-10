# Changelog

## Unreleased

- **Files panel, markdown images.** Only an image alone on its line is drawn
  (a badge `[![CI](…)](link)` as one picture that opens its link); an image
  in a table, a list or a row of badges shows its alt text, and images in
  code (spans, fenced, indented) or HTML comments are left alone. Before,
  every image was cut out, tearing tables and badges apart.
- **Files panel.** `![](<a b.png>)` works; a link to a folder (`[docs](docs/)`)
  opens it in the tree instead of "Cannot preview"; at most 4 images load at
  once; a web image (a badge) is downloaded again every 6 hours (offline, the
  last copy shows); an image still loading from another space or file no
  longer lands in the one shown.
- **Switcher.** A `profiles.json` of the wrong shape (`"rules": {}`, a `null`
  rule or profile, not an object) falls back to the default instead of
  failing on every redraw; a remote space's `~` folder is looked up in that
  machine's home and a relative one no longer hangs the lookup; two quick
  space changes no longer check the same space twice.
- **Tab bar.** After a layout switch (by hand or by the switcher), a space
  never seen before opens with the side panel closed, as Herdr's own does,
  instead of inheriting the last space's panel.
- README: what rules can't match (letter case, symlinks, `~` on another
  machine).

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
