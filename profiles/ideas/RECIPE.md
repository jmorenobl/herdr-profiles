# Ideas

A warm, paper-colored window for an idea inbox. The ideas space opens on a
kanban board of every idea by status; the right panel shows the chosen idea
with its notes and actions, and one key captures a new idea from any space.

![Ideas](layouts/ideas.svg)

## What you see

- **Left, 268px**: Herdr's spaces and agents sidebar, unchanged.
- **Center**: the active tab. In the ideas space the first tab is **Board**,
  a tab whose only pane is the `ideas` mod:
  - A header row: "Ideas" (15px semibold), a 240px search box, type chips
    (All, then the idea types: Book, Code, Legal, Other by default), a "Parked & dropped · N" toggle and a
    black **+ New** button.
  - Four columns filling the width (six with the toggle): Seed (`ansi3`),
    Exploring (`ansi4`), Ripe (accent), Active (`ansi2`), Parked (`muted`),
    Dropped (`dim`). Each on a `canvas` card, with a dot, label and count.
  - Cards: title (13px medium, wraps), `#tags` in accent, and a meta line
    (`Code · 3d · 2 files · project`). The selected card has an accent border.
  - A segmented sort control before the toggle: Manual (default), Recent,
    A–Z. Manual puts ideas not placed yet first, newest first, then the saved
    order.
  - **Stale** cards (seed, exploring or ripe, with `updated`, or else
    `created`, more than 30 days ago) at 60% opacity, their age in amber
    (`ansi3`), also in the side list.
  - **Review · N** after the sort control when there are stale ideas: black
    when the weekly review is due (no review finished in 7 days), outlined
    otherwise.
  - **Review mode** replaces the header and columns: "Review", "2 of 5", a
    **Done · Esc** button, and one stale idea at a time on a centered 680px
    `popover` card (status, type, "untouched 3mo" in amber, title 22px, tags,
    origin, the text as markdown up to 460px, its other files). Below it:
    **Keep going** (K; "Keep going → Exploring" for a seed), **Park** (P),
    **Drop…** (D) and **Skip** (S or →). Drop swaps the buttons for a
    one-line "Why drop it?" input with Drop and Cancel. The end shows what
    was kept, parked and dropped.
- **Right, 420px (300–720)**, on a `surface` card, one of:
  - **Overview** (Board tab shown, nothing selected): a weekly review note
    (how many are stale, when the last review was, a **Review N** button),
    counts by status and by type, and the eight most recently touched ideas.
  - **Detail** (an idea selected): "← All ideas", title (16px), origin,
    status chips, type chips, actions (**Develop with Claude** or **Back to
    Claude**, **Open project** or **Start project**, **Show in Finder**
    on macOS or **Show in folder** on Linux),
    the project path, a strip of the idea's text files (idea.md, notes.md, …)
    and the chosen file as markdown.
  - **List** (any other tab, nothing selected): search, type chips and
    collapsible status sections of one-line rows (title, type, age).
- **Theme `ideas`**: background `#fbf6ee`, foreground `#3a3027`, canvas
  `#efe6d8`, chrome `#f3ebdf`, accent `#b5652b`.

## How it behaves

- Going to the ideas space the first time adds the Board tab and moves it
  first. The **Board** button in the list brings it back if closed.
- Drag a card to place it: before or after the card under the pointer (a
  3px accent line shows the spot), or last when dropped in a column's empty
  space. Across columns this also changes its status. The order goes to
  `.board.json` in the ideas folder; dropping while sorted by Recent or A–Z
  switches to Manual from what's shown.
- While dragging: a shadowed copy
  (accent border) follows the pointer from where it was grabbed, the card
  leaves a faint slot, and the target column highlights. Cards show an open
  hand cursor, a closed one while dragging. Dragging starts after 4px, so a
  click still selects; leaving the board cancels the drag, and a drop ends it
  (nothing of the drag is left over). Clicking a card selects it everywhere.
  A drop that can't save the order (`.board.json` changed on disk) changes
  nothing, the status included, and says to try again; one whose status
  can't be written (`idea.md` changed on disk) puts the saved order back.
- The review goes through the stale ideas oldest first. Keep going moves a
  seed to exploring and otherwise only stamps `updated:`; Park sets
  `parked`; Drop sets `dropped` and `why:` (it needs the line: Enter saves,
  Esc cancels); Skip changes nothing. Each choice is written at once, in
  order, on the file as it is on disk then (an agent may have written it
  meanwhile: a write that finds it changed reads it again and tries once
  more, unless its `status:` changed there too: then that newer choice
  stands and the review says it couldn't save). Finishing the queue writes `reviewed:` (today) to `.board.json`;
  leaving early doesn't. A write that fails says so ("Could not save the
  review of an idea", "Could not save the review") and isn't counted in the
  end's summary; a failed `reviewed:` leaves the Review button due. Keys work once the review has focus (it takes it
  when started from the button, or on a click).
- `ideas.review` (`herdr-app do ideas.review`, or a key in `keys.json`)
  starts the review from anywhere in the ideas space: it asks the board
  through `shared("ideas.review")` (the time of the request) and opens the
  Board tab if it's closed; a board that opens within 15 seconds of a
  request takes it, and starts once its ideas are read.
- An idea whose type changes during a review stays in the queue: the side
  panel appends each move to `shared("ideas.moved")` (`[{seq, from, to}]`,
  the last 20), and the review replays, in order, only the moves made after
  it started.
- A dropped idea's detail shows "Dropped: <why>".
- Autocommit: if the ideas folder is a git repo of its own (the top of its
  work tree), the side panel (only it, so copies don't race) runs `git add -A`
  (leaving out `.DS_Store` files even if the folder's `.gitignore` doesn't)
  and commits one minute after the last change it sees, and once when it
  starts. A timer that fires while a commit runs waits for another quiet
  minute after it, so nothing is left behind; when the panel goes (the layout
  switches away, the app quits) a commit still waiting is tried right away
  (in five git/sh processes: close() has a quarter of a second, and a commit
  cut short leaves the changes staged for the next one).
  New files count even with `status.showUntrackedFiles=no`. Subjects: "Add idea: <title>",
  "Update: <title>", "Remove idea: <title>", "Update N ideas", "Board: order
  and review" (non-ASCII names as they are, cut at 72 characters); the body
  lists the files. It doesn't commit, and warns, when the folder is inside a
  bigger repo (a commit there would take whatever else is staged), or while a
  merge, rebase, cherry-pick or revert (of one commit or several) is under way, with unresolved
  conflicts or on a detached HEAD (it would conclude the person's operation,
  conflict markers and all); finishing that in a terminal lets it go on. A failure warns once until a commit
  works again. `"autocommit": false` under `profiles.ideas` turns it off.
- Status chips rewrite `status:` and stamp `updated:`. Type chips move the
  idea's folder to the new type and show its `idea.md` again. A type change
  is refused, with a notice naming the tab, while a terminal (an agent, an
  editor) works inside the idea's folder: what it wrote next would bring the
  old folder back and split the idea. A second click before a change lands
  is ignored.
- The detail's note file (notes.md, …) belongs to the idea it was chosen on:
  selecting another idea, here, on the board or by capturing, shows that
  one's `idea.md`. The shown file is read again on every change in the
  folder, so an agent writing it is followed.
- **Develop with Claude** opens a tab named after the idea, running `claude`
  (the `agent` setting; the button says its name) in the idea's folder, asked to read `idea.md`, start with questions and keep
  notes beside it. If that tab exists, it's selected instead: a tab with a
  terminal working inside the idea's folder, else a tab named after the idea
  (only a named tab, and not one working in another idea's folder). The
  folder is matched as given and with symlinks resolved, as a terminal may
  report either; the same check guards type changes. Showing that tab
  selects its idea in the panel.
- **Start project** (ripe ideas without a project) opens the same kind of
  tab, asked to follow "Starting a project" in the folder's AGENTS.md, in
  `projectsRoot` when it's set, else proposing a location and asking.
- **Open project** goes to the space already working in `project:`, or
  opens a new space there (where the profile switcher picks its layout).
- `ctrl-shift-i` (any space, any layout: the one key in `global`, since
  capture is for when you're elsewhere) and **+ New** open the capture
  dialog (520×410): idea, notes, type. Enter saves, Esc cancels; the new idea
  becomes the selected one. Its folder is the title in lowercase letters and
  digits of any script, accents off Latin letters and `ß`, `æ`, `ø`, `ł`, …
  spelled out ("Straße" → `strasse`, "日本語" stays), the rest dashes, at most
  48 characters (`idea` when nothing is left; `-2`, `-3` when taken).
- Everything follows the folder live (`watchFolder`).

## Built from

- Layout `ideas.json`, built from the recipe in `profile.json`: the
  `standard` layout (without `cloned_from`), an `ideas-side` block
  (`{ "mod": "ideas" }`, 420px) after `main` in `work-body`, theme `ideas`,
  preview `layouts/ideas.svg`, and the switcher the build adds. The
  Files/Changes/History `panel` stays, because the tab bar (core's
  `standard-tabs`, Herdr's `tabs` plus a History button) shows and hides
  the `panel` node per space. Its Files block uses core's `standard-files` (Herdr's
  `files` with markdown files shown rendered) and its History block core's
  `standard-history`, like the standard layout.
- Mod `ideas`, one mod in three roles chosen by props: `{ view: "board" }`
  in a tab pane (kanban), a layout block (side panel), an overlay
  (`mod.open`, capture). Copies share the selection through
  `shared("ideas.selected")`.
  `main.js` is the View: it picks the role and copies each role's methods
  onto its prototype (`board.js`, `review.js`, `side.js`, `capture.js`, and
  `common.js` for what board and side share), so `this` is always the view.
  `config.js` is the only reader of `profiles.json` → `profiles.ideas`;
  `store.js` (files), `actions.js` (tabs, spaces, projects), `ui.js` (chips,
  buttons, search, status and type labels).
- Drag and drop: `on_mouse_down` on a card keeps the grab point
  (`local_position`) and width (`bounds`); `on_mouse_move` on the board
  (`relative()`) moves an `absolute()` copy to its `local_position`;
  `on_hover` and `on_mouse_up` on columns pick the target. The copy has no
  handlers, so it doesn't block the columns under it.
- Review: `track_focus` + `on_key_down` on the review root; the start
  request is a shared token the board compares in render (focus can't be
  taken in render, hence focus on click). Writes go through one promise
  chain so a fast run of choices lands in order.
- `herdr` calls: `nextCommand`, `watchFolder`, `exec`, `readTextFile`, `writeTextFile`
  (with the expected old text), `run` (`tab.new` with `mod`/`argv`/`task`,
  `tab.select`, `tab.move`, `space.select`, `space.new`, `mod.open`),
  `shared`/`setShared`, `notify`, `closeOverlay`, `spaces`, `panes`.
- Settings, all under `profiles.json` → `profiles.ideas`, read by
  `config.js` when a copy starts (capture reads them again when it saves):
  - `folder`: asked at install the first time (`ask` in `profile.json`,
    default `~/ideas`, with the rule `{ "path": "{folder}" }` following the
    answer). Checked like the installer checks it (`checkFolder` mirrors
    `spec.check_folder`, and a test runs both on the same list):
    surrounding whitespace dropped, then `/…` or `~/…`, no `//`, `.`/`..`
    parts or control characters, not `/`, the home folder or above it;
    missing, unreadable, broken or bad, the mod uses `~/ideas`, the side
    panel warns why (the file or key), and capture shows "Saves into …"
    in amber instead of the origin;
  - `autocommit` (default on);
  - `types`: a list of folder names (`^[a-z0-9][a-z0-9_-]{0,31}$`, up to
    12, no repeats), each a string or `{name, label}` (label 1–24
    characters on one line; labels are a prototype-less map and lookups use
    `Object.hasOwn`, so a type called `constructor` is fine). Default `book`, `code`, `legal`, `other`. Labels: the
    given one, else the default label, else the name capitalized with
    spaces. A capture without a known type goes to `other`, else the last
    type;
  - `agent`: a command, a string split on spaces, or an argv list
    (default `claude`);
  - `agentName`: what the buttons call it (1–24 characters). Without it,
    the command's name capitalized, or "the agent" when the command is a
    runner or interpreter (npx, uvx, bunx, pnpx, pnpm, yarn, npm, bun, uv,
    pipx, env, python, python3, node, deno, sh, bash, zsh);
  - `projectsRoot`: where Start project puts projects (checked like
    `folder`, else ignored with a warning). Its task names it; without it the task asks
    the agent to propose a location and ask.

  A bad `types`, `agent` or `projectsRoot` falls back whole to its default, and the side
  panel (one per window) shows a warning. Until the settings are read the
  view uses the defaults (`defaultConfig()`), so with nothing configured
  nothing changes. The types reach `store.js` as arguments (listing,
  moving, creating, autocommit); the defaults stay in the mod
  (`DEFAULT_TYPES`), not in `profile.json`.
  When it starts, the side panel also names top-level folders holding
  ideas that aren't types (`untypedFolders`): their ideas don't show. A
  drop rewrites `.board.json` from the shown ideas and appends the saved
  ids of types not shown (`hiddenOrder`), so their order survives.
- `tests/test_ideas_store.py` runs the whole mod under node on throwaway
  folders and git repos, with a stand-in `herdr` doing real file writes and
  git (`tests/js/herdr_git_stub.js`) and a stand-in UI that takes any builder
  call and logs the text and colors drawn (`tests/js/gpui_view_stub.js`):
  autocommit (a bigger repo, a merge or
  rebase under way, a detached HEAD, `showUntrackedFiles=no`, non-ASCII
  names, emoji subjects, committing on close), creating, listing, moving and
  updating ideas, slugs, `.board.json`, ages across daylight saving, a drop
  whose status write fails, review writes, the review asked for with the
  Board tab closed, the note file following the selection, type changes
  under a working tab and double clicks, and finding agent tabs. Also the
  glue around the two pure helpers: the side panel (not the board) warns
  once about untyped folders and still loads when they can't be listed
  (`main.js`), and the capture overlay shows "From <space>", or "Saves into
  …" in amber (`ansi3`) once profiles.json turns out to give no folder
  (`capture.js`).
- `tests/test_ideas_mod.py` runs `config.js`, `ui.js`, `actions.js` and
  `store.js`, plus `capture.js`, `board.js` and `common.js` on a stand-in
  view, under node with a stand-in `herdr` (`tests/js/`), when node is
  installed: settings, folder checks against the installer's, labels,
  agent names, untyped folders and their warning, a drop keeping hidden
  types' order, and capture's "Saves into". The warning text is
  `untypedNotice` (store.js) and capture's line `captureFootnote`, so they
  can be tested without the UI.
- The folder's format is `project/AGENTS.md`: copy it in, with a `CLAUDE.md`
  containing `@AGENTS.md`.

## Watch out

- Front matter is flat `key: value` lines; nested YAML is not parsed.
- Autocommit runs only while the ideas layout is shown (the side panel is
  what commits): a capture made from another space is committed on the next
  visit.
- Staleness reads `updated:`/`created:` only: notes Claude writes beside
  `idea.md` don't refresh an idea unless `updated:` is stamped too (the
  folder's AGENTS.md asks agents to).
- Only `<type>/<slug>/idea.md` counts as an idea; loose files are ignored.
- Claude tabs are found again by a terminal working in the idea's folder,
  else by name (the idea's title, cut to 28 characters): a renamed tab whose
  agent left the folder isn't found.
- Ages are whole local days (rounded, so a daylight saving change doesn't
  make an idea a day younger).
- `Develop with Claude` assumes `claude` (or the `agent` setting) is on the
  PATH. Reveal runs `open` on macOS ("Show in Finder") and `xdg-open` on
  Linux ("Show in folder"), chosen by `window().platform`; on Windows there's
  no button. A failure shows a warning. The board reads this computer's
  folder only.

## Done when

- Going to a space in the ideas folder switches to this layout and shows a
  Board tab first; leaving the space switches back.
- Every idea shows in its status column; search and type chips filter both
  the board and the list.
- Dragging a card to another column rewrites its `status:`.
- `ctrl-shift-i` in another space creates `<type>/<slug>/idea.md` with
  `status: seed`, and it appears on the board without a reload.
- Develop with Claude twice on the same idea opens one tab, not two.
- An idea with `created:` over 30 days ago and no `updated:` shows faded
  with its age in amber, and Review takes it; Drop with a reason writes
  `status: dropped` and `why:`; finishing the review greys the button
  until a week later.
