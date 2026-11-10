# Changelog

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
