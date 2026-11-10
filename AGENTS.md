# Working on this repo

Herdr profiles: per-project layouts, themes and mods for the Herdr app.
`README.md` explains what it is, for people who use it; `CONTRIBUTING.md`
explains how it works inside, how the repo is laid out and the developer
commands. Read both first.

## Before changing anything

- Read `~/.config/herdr-app/AGENTS.md`: Herdr's own manual (layouts, mods,
  keys, commands). The type files `~/.config/herdr-app/gpui-kit.d.ts` and
  `herdr.d.ts` are the truth for the mod API.
- A profile may have a roadmap; ask the person where it is if they mention
  one and it isn't here.

## Rules

- Everything in Herdr is in English: names, UI text, files, commits.
- This repo is the source. Edit here, then `make check && make install`.
  Never edit the installed copies in `~/.config/herdr-app` directly; if the
  person tweaked something live there, `make pull` first.
- The repo is public (GitHub, `origin`). Push only when the person asks,
  and never add another remote. Nothing personal in what's committed: no
  emails, home paths or private project names.
- Personal rules (which project gets which profile) belong in
  `~/.config/herdr-app/profiles.json`, never here.
- Layouts are built from the recipe in each `profile.json` (CONTRIBUTING,
  "Layouts are built"). Don't add whole layout files or copy the switcher into one.
  `tests/golden/` is what install must write: change it only on purpose.
- Mods: `mod.json` before `main.js`; no imports outside the mod's folder;
  `herdr-app check <installed mod folder>` must pass, and look at it with
  `herdr-app shot` and `herdr-app status` before calling it done.
- Each change: update the profile's `RECIPE.md` and `CHANGELOG.md`, run
  `make test` if the installer changed, and commit.
