// What the buttons do: tabs with the agent (Claude by default), the board tab, projects as spaces.
// With the ideas folder on another machine (place.js), the agent, the projects and the spaces
// for them are on that machine too.
import { spaces, panes, run, exec, notify, shared, setShared, window, knownAgents } from "herdr";
import { expand, tilde, cut } from "./store.js";
import { machine, onPlace, run as runThere } from "./place.js";

export const SELECTED = "ideas.selected";
export const select = (id) => setShared(SELECTED, id ?? null);
export const selected = () => shared(SELECTED) ?? null;

// Ideas whose type changed (so their id did), in order: [{ seq, from, to }], the last 20.
// Shared so another copy of the mod holding ids (the board's review queue) can follow them:
// it remembers the last seq it saw and replays only the moves after it, in order.
const MOVED = "ideas.moved";
const moves = () => { const m = shared(MOVED); return Array.isArray(m) ? m : []; };
export const lastMove = () => moves().at(-1)?.seq ?? 0;
export function noteMove(from, to) {
  setShared(MOVED, [...moves(), { seq: lastMove() + 1, from, to }].slice(-20));
}
// `ids` with every move after `since` applied in order; returns { ids, seq }.
export function followMoves(ids, since) {
  let seq = since;
  for (const m of moves()) {
    if (m.seq <= since) continue;
    ids = ids.map((id) => (id === m.from ? m.to : id));
    seq = m.seq;
  }
  return { ids, seq };
}

const inside = (path, root) => !!path && !!root && (path === root || path.startsWith(root.replace(/\/$/, "") + "/"));

// Spaces on the ideas folder's machine (ids from another machine have its name before a /).
const placeSpaces = () => spaces().filter((s) => onPlace(s.id));

// The space the ideas live in: the one showing now if it's on the ideas folder's machine and
// works in the ideas folder.
export function ideasSpace(folder) {
  const s = spaces().find((s) => s.active);
  if (!s || !onPlace(s.id)) return null;
  const tabIds = new Set(s.tabs.map((t) => t.id));
  const here = panes().some((p) => tabIds.has(p.tab) && inside(p.cwd, folder)) || inside(s.folder, folder);
  return here ? s : null;
}

// A tab's name for an idea (cut by characters, so an emoji isn't split in half).
export const tabName = (idea) => (Array.from(idea.title).length > 28 ? `${cut(idea.title, 27)}…` : idea.title);

// The idea's folder as given and with symlinks resolved (`realDir`, store.js): a terminal's
// live folder may be either.
const dirsOf = (idea) => [idea.dir, idea.realDir].filter(Boolean);
const inIdea = (cwd, idea) => dirsOf(idea).some((d) => inside(cwd, d));
// Inside some idea's folder (<root>/<type>/<slug>) of the ideas folder `idea` is in, but not `idea`'s.
const inOtherIdea = (cwd, idea) => !inIdea(cwd, idea) && dirsOf(idea).some((d) => {
  const root = d.split("/").slice(0, -2).join("/");
  return inside(cwd, root) && cwd.slice(root.length + 1).split("/").filter(Boolean).length >= 2;
});

// Terminal panes on the ideas folder's machine whose live folder is inside the idea's folder.
const panesIn = (idea) => panes().filter((p) => p.terminal && onPlace(p.pane) && inIdea(p.cwd, idea));

// The idea's tab in `space`: one with a terminal working in the idea's folder (the agent tab
// Develop opened, wherever its title went), else a tab named after the idea (its agent moved
// elsewhere): only a named one (an unnamed tab is called by its position, "2"), and not one
// working in another idea (two titles can share their first 27 characters).
export function tabFor(idea, space) {
  if (!space) return null;
  const tabs = new Map(space.tabs.map((t) => [t.id, t]));
  const byPane = panesIn(idea).map((p) => tabs.get(p.tab)).find(Boolean);
  if (byPane) return byPane;
  const elsewhere = new Set(panes().filter((p) => p.terminal && onPlace(p.pane) && inOtherIdea(p.cwd, idea)).map((p) => p.tab));
  return space.tabs.find((t) => t.named && t.name === tabName(idea) && !elsewhere.has(t.id)) ?? null;
}

// A tab, in any space, with a terminal working in the idea's folder (its name for the notice), or null.
export function workingIn(idea) {
  const ids = new Set(panesIn(idea).map((p) => p.tab));
  if (!ids.size) return null;
  for (const s of spaces()) for (const t of s.tabs) if (ids.has(t.id)) return t;
  return { name: "A terminal" };            // a pane in no listed tab
}

// The agent's name for buttons: "agentName" from profiles.json when set, else the command's
// name, capitalized ("claude" -> "Claude"). A runner or interpreter (npx, python3, sh, …) says
// nothing about the agent, so then it's "the agent".
const RUNNERS = new Set(["npx", "uvx", "bunx", "pnpx", "pnpm", "yarn", "npm", "bun", "uv", "pipx", "env",
  "python", "python3", "node", "deno", "sh", "bash", "zsh"]);
export function agentName(agent, name = null) {
  if (name) return name;
  const cmd = agent[0].split("/").pop() || agent[0];
  if (RUNNERS.has(cmd)) return "the agent";
  return cmd.charAt(0).toUpperCase() + cmd.slice(1);
}

// Whether the agent can start on the ideas folder's machine: false only when Herdr's list of
// agents knows the command and says it isn't installed there (then a notice says so).
async function agentThere(agent) {
  if (!machine()) return true;
  const known = await knownAgents({ on: machine() }).catch(() => []);
  const entry = known.find((a) => a.run?.[0] === agent[0]);
  if (!entry || entry.installed) return true;
  notify({ title: `${agentName(agent)} isn't installed on ${machine()}`, body: "Install it there, or set \"agent\" in profiles.json.", level: "warning", timeout: 6000 });
  return false;
}

// `agent` is the argv from profiles.json (["claude"] by default). The tab goes in `space` (the
// ideas space), else in the shown space when it's on the ideas folder's machine. With the folder
// on another machine and no space of it shown, in one of that machine's spaces, else a new one.
async function agentTab(idea, space, agent, task) {
  const existing = tabFor(idea, space);
  if (existing) return run("tab.select", { id: existing.id });
  if (!(await agentThere(agent))) return;
  const tab = { name: tabName(idea), folder: idea.dir, argv: agent, task };
  if (space || !machine()) return run("tab.new", { ...tab, ...(space ? { space: space.id } : {}) });
  const shown = spaces().find((s) => s.active);
  const there = shown && onPlace(shown.id) ? shown : placeSpaces()[0];
  if (there) {
    run("space.select", { id: there.id });
    run("tab.new", { ...tab, space: there.id });
  } else run("space.new", { machine: machine(), folder: idea.dir, argv: agent, task });
}

export function develop(idea, space, agent) {
  return agentTab(idea, space, agent,
    "Read idea.md in this folder: it's one of my ideas (the format and rules are in the ideas folder's AGENTS.md). " +
    "Help me develop it: start with the questions that matter most. Keep notes in this folder (notes.md, research/). " +
    "Reply in the language the idea is written in.");
}

// `projectsRoot` (profiles.json, or null): where projects go. Without it the agent proposes a place and asks.
export function startProject(idea, space, agent, projectsRoot) {
  const where = projectsRoot
    ? `My projects folder is ${tilde(projectsRoot)}: the project goes in a new folder there. `
    : "I haven't said where my projects go: propose a location and ask me. ";
  return agentTab(idea, space, agent,
    "Read idea.md in this folder: this idea is ripe and I want to turn it into a project. " + where +
    "Follow \"Starting a project\" in the ideas folder's AGENTS.md: propose the name and location first and wait for my OK. " +
    "Reply in the language the idea is written in.");
}

// Goes to the space working in the idea's project, or opens one there: on the ideas folder's
// machine, where its `project` folder is.
export async function openProject(idea) {
  const path = expand(idea.project);
  const r = await runThere("test", ["-d", path]).catch(() => ({ code: -1 }));
  if (r.code !== 0) {
    notify({ title: "Project folder not found", body: machine() ? `${tilde(path)} on ${machine()}` : tilde(path), level: "warning", timeout: 5000 });
    return;
  }
  const local = placeSpaces();
  const byPane = (s) => {
    const ids = new Set(s.tabs.map((t) => t.id));
    return panes().some((p) => ids.has(p.tab) && inside(p.cwd, path));
  };
  const found = local.find(byPane) ?? local.find((s) => inside(s.folder, path));
  if (found) run("space.select", { id: found.id });
  else run("space.new", { folder: path, ...(machine() ? { machine: machine() } : {}) });
}

// Showing an idea's folder in the system's file manager, where we know how.
const REVEAL = { macos: ["open", "Show in Finder"], linux: ["xdg-open", "Show in folder"] };
const revealer = () => REVEAL[window()?.platform] ?? null;

// Where `dir` on the ideas folder's machine is on this computer: itself when the folder is here,
// else through the longest "reveal" pair (config.js) it's inside; null when none is.
export function localDir(dir, pairs = []) {
  if (!machine()) return dir;
  for (const [there, here] of pairs) {
    if (dir === there) return here;
    if (dir.startsWith(there.replace(/\/$/, "") + "/")) return here.replace(/\/$/, "") + dir.slice(there.replace(/\/$/, "").length);
  }
  return null;
}

// The button's label, or null where there's no button (Windows, or an idea on another machine
// that "reveal" doesn't reach).
export const revealLabel = (idea, pairs) => (idea && localDir(idea.dir, pairs) === null ? null : revealer()?.[1] ?? null);

export async function reveal(idea, pairs) {
  const [cmd] = revealer() ?? [];
  const dir = localDir(idea.dir, pairs);
  if (!cmd || !dir) return;
  const r = await exec(cmd, [dir]).catch((e) => ({ code: -1, stderr: String(e.message ?? e) }));
  if (r.code !== 0) notify({ title: `Could not run ${cmd}`, body: r.stderr?.trim() || dir, level: "warning", timeout: 5000 });
}

// The Board tab: a tab whose only pane is this mod with { view: "board" }.
export function boardTab(space) {
  if (!space) return null;
  const ids = new Set(space.tabs.map((t) => t.id));
  const pane = panes().find((p) => p.mod === "ideas" && ids.has(p.tab));
  return pane ? space.tabs.find((t) => t.id === pane.tab) : null;
}

export function openBoard(space) {
  const tab = boardTab(space);
  if (tab) run("tab.select", { id: tab.id });
  else run("tab.new", { name: "Board", mod: "ideas", props: { view: "board" }, ...(space ? { space: space.id } : {}) });
}

