// What the buttons do: tabs with the agent (Claude by default), the board tab, projects as spaces.
import { spaces, panes, run, exec, notify, shared, setShared, window } from "herdr";
import { expand, tilde } from "./store.js";

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

// The space the ideas live in: the one showing now if it works in the ideas folder.
export function ideasSpace(folder) {
  const s = spaces().find((s) => s.active);
  if (!s) return null;
  const tabIds = new Set(s.tabs.map((t) => t.id));
  const here = panes().some((p) => tabIds.has(p.tab) && inside(p.cwd, folder)) || inside(s.folder, folder);
  return here ? s : null;
}

// A tab's name for an idea; also how we find that tab again.
export const tabName = (idea) => idea.title.length > 28 ? `${idea.title.slice(0, 27)}…` : idea.title;

export function tabFor(idea, space) {
  return space?.tabs.find((t) => t.name === tabName(idea)) ?? null;
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

// `agent` is the argv from profiles.json (["claude"] by default).
function agentTab(idea, space, agent, task) {
  const existing = tabFor(idea, space);
  if (existing) return run("tab.select", { id: existing.id });
  run("tab.new", { name: tabName(idea), folder: idea.dir, argv: agent, task, ...(space ? { space: space.id } : {}) });
}

export function develop(idea, space, agent) {
  agentTab(idea, space, agent,
    "Read idea.md in this folder: it's one of my ideas (the format and rules are in the ideas folder's AGENTS.md). " +
    "Help me develop it: start with the questions that matter most. Keep notes in this folder (notes.md, research/). " +
    "Reply in the language the idea is written in.");
}

// `projectsRoot` (profiles.json, or null): where projects go. Without it the agent proposes a place and asks.
export function startProject(idea, space, agent, projectsRoot) {
  const where = projectsRoot
    ? `My projects folder is ${tilde(projectsRoot)}: the project goes in a new folder there. `
    : "I haven't said where my projects go: propose a location and ask me. ";
  agentTab(idea, space, agent,
    "Read idea.md in this folder: this idea is ripe and I want to turn it into a project. " + where +
    "Follow \"Starting a project\" in the ideas folder's AGENTS.md: propose the name and location first and wait for my OK. " +
    "Reply in the language the idea is written in.");
}

// Goes to the space working in the idea's project, or opens one there.
export async function openProject(idea) {
  const path = expand(idea.project);
  if ((await exec("test", ["-d", path])).code !== 0) {
    notify({ title: "Project folder not found", body: tilde(path), level: "warning", timeout: 5000 });
    return;
  }
  const local = spaces().filter((s) => !s.machine);
  const byPane = (s) => {
    const ids = new Set(s.tabs.map((t) => t.id));
    return panes().some((p) => ids.has(p.tab) && inside(p.cwd, path));
  };
  const found = local.find(byPane) ?? local.find((s) => inside(s.folder, path));
  if (found) run("space.select", { id: found.id });
  else run("space.new", { folder: path });
}

// Showing an idea's folder in the system's file manager, where we know how.
const REVEAL = { macos: ["open", "Show in Finder"], linux: ["xdg-open", "Show in folder"] };
const revealer = () => REVEAL[window()?.platform] ?? null;
// The button's label, or null where there's no button (Windows).
export const revealLabel = () => revealer()?.[1] ?? null;

export async function reveal(idea) {
  const [cmd] = revealer() ?? [];
  if (!cmd) return;
  const r = await exec(cmd, [idea.dir]).catch((e) => ({ code: -1, stderr: String(e.message ?? e) }));
  if (r.code !== 0) notify({ title: `Could not run ${cmd}`, body: r.stderr?.trim() || tilde(idea.dir), level: "warning", timeout: 5000 });
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

