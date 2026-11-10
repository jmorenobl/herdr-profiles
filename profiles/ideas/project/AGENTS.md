# Ideas

This folder is an idea inbox: books, software, legal work, anything.
Ideas get lost in conversations; here each one has a folder and a status.
The Herdr app shows them as a board (the `ideas` layout), and `ctrl-shift-i`
captures a new one from anywhere.

## Layout

```
book/  code/  legal/  other/      one folder per type
  <slug>/                         one folder per idea
    idea.md                       the idea (required)
    notes.md, research/, ...      anything that helps develop it
```

Those four are the default types. The person may have set others in Herdr's
`~/.config/herdr-app/profiles.json` → `profiles.ideas.types` (a list of
folder names, or `{ "name": ..., "label": ... }`): use the types listed
there, or the four defaults when there's no such list. Ideas in any other
folder don't show on the board, so ask before putting an idea anywhere else.

The type is the folder: to change an idea's type, move its folder. The slug
is the title in lowercase ASCII with dashes (`el-ultimo-farero`). Nothing
else lives at the top level besides this file, `CLAUDE.md`, `README.md` and
`.board.json`.

`.board.json` is the board's own state: the order the person gave the cards
and the day of the last weekly review
(`{"version": 1, "order": {"<status>": ["<type>/<slug>", ...]}, "reviewed": "2026-11-09"}`).
The board writes it; leave it alone, except when you move or rename an idea's folder:
then replace its old id there with the new one.

## idea.md

```markdown
---
title: Novel about the last lighthouse keeper in Galicia
status: seed
created: 2026-11-09
origin: conversation with Claude about lighthouses
---
Free text, in whatever language the idea came in.
```

- `status`, one of:
  - `seed`: just captured, raw.
  - `exploring`: being thought through, researched, discussed.
  - `ripe`: clear enough to start.
  - `active`: it became a project (set `project:`).
  - `parked`: good, but not now.
  - `dropped`: decided against it (keep it and say why in `why:`).
- `created`: when it was captured. `updated`: set it to today whenever you
  change the idea or its status.
- `origin`: where it came from (a conversation, a project, a walk). Optional.
- `project`: the project folder once it exists (`~/...` or an absolute path).
- `tags`: optional, comma separated on one line (`tags: galicia, thriller`).
- `why`: for a dropped idea, one line on why it was dropped.

An open idea (seed, exploring, ripe) whose `updated` (or `created`) is more
than 30 days old is stale: the board fades it and its weekly review asks
whether to keep going, park or drop it. Stamping `updated` when you work on
an idea keeps it fresh.

Keep the front matter exactly this shape (one `key: value` per line, no
nested YAML): the board parses it line by line.

## Working on an idea

- Capturing: create `<type>/<slug>/idea.md` with `status: seed` and the
  person's own words. Don't polish a seed.
- Developing: never rewrite what the person wrote in `idea.md`. Put
  questions, answers and research in `notes.md` (and `research/` for
  sources), and append a short `## Summary` to `idea.md` when the idea
  becomes clearer. Move it to `exploring` once there's real thinking in it.
- When the person mentions an idea that's already here, update that folder
  instead of making a new one. Search titles first.

## Starting a project

When a `ripe` idea becomes a project, first propose the name and location
and wait for the person's OK.

- **Where**: if the person has said where their projects go (Herdr's Start
  project button passes the `projectsRoot` setting, when it's set), propose
  `<that folder>/<slug>`. Otherwise propose a location and ask; don't
  assume one.
- **How**: set it up the way the person starts that kind of project, and
  ask when you don't know. For code, that's usually `git init` and a
  `README.md` that starts from the idea; ask about language and stack
  before adding anything else. Copy this idea's `idea.md` (and useful
  notes) into the project when it helps the work start from the idea.
- The person can add their own recipe per type here (a tool to run, a
  template to copy); follow it when there is one.

Finally set `status: active`, `project: <folder>` and `updated:` in this
idea's `idea.md`.
