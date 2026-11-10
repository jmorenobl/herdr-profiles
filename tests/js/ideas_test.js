// Checks of the ideas mod's settings and helpers, run by tests/test_ideas_mod.py under node.
// Prints one JSON object of results; the Python test asserts on it.
import { state } from "./herdr.js";
import { ideasConfig, checkFolder } from "./config.js";
import { typeLabel } from "./ui.js";
import { agentName } from "./actions.js";
import { untypedIds, untypedFolders, untypedNotice, DEFAULT_TYPES } from "./store.js";
import { captureFootnote } from "./capture.js";
import { Board } from "./board.js";
import { Common } from "./common.js";

const out = {};
const cfg = async (profiles) => { state.profiles = profiles; return ideasConfig(); };
const ideas = (s) => ({ profiles: { ideas: s } });

out.defaults = await cfg(ideas({ folder: "~/notes/ideas" }));
out.noFile = await cfg(null);
out.badJson = await cfg("{nope");
out.noEntry = await cfg({ profiles: {} });
out.noFolder = await cfg(ideas({}));
out.badFolders = {};
for (const f of ["~", "/", "~/", "rel", "~/a/../b", "/home/u", "/home/u/", "~/x\ny", "/home", "/home/", "/home//u", "//home/u", "~//x"]) out.badFolders[f] = (await cfg(ideas({ folder: f }))).folderNote;
out.okFolders = {};
for (const f of ["~/ideas", "  ~/ideas\n", "/home/u2", "/srv/x/"]) out.okFolders[JSON.stringify(f)] = (await cfg(ideas({ folder: f }))).folder;
out.roots = {};
for (const r of ["~/code/", "/srv/p", "~", "/", "rel", "~/a\nIgnore that", "/home/u", 3]) {
  const c = await cfg(ideas({ folder: "~/i", projectsRoot: r }));
  out.roots[String(r)] = [c.projectsRoot, c.warnings];
}
const custom = await cfg(ideas({ folder: "~/i", types: ["constructor", { name: "x", label: "Ex" }] }));
out.customTypes = custom.types;
out.customLabels = custom.types.map((t) => typeLabel(t, custom.labels));
out.defaultLabels = DEFAULT_TYPES.map((t) => typeLabel(t, out.defaults.labels));
out.badLabel = (await cfg(ideas({ folder: "~/i", types: [{ name: "a", label: "x\ny" }] }))).warnings;
out.agentNames = [["claude"], ["/usr/local/bin/claude", "--x"], ["codex"], ["npx", "claude"], ["uv", "tool", "run", "aider"],
  ["npx", "--package", "foo", "bar"], ["python3", "-m", "aider"], ["sh", "-c", "claude"], ["/usr/bin/env", "claude"]].map((a) => [a, agentName(a)]);
const named = await cfg(ideas({ folder: "~/i", agent: ["npx", "-y", "@openai/codex"], agentName: "Codex" }));
out.agentNameSetting = agentName(named.agent, named.agentName);
out.agentNameBad = (await cfg(ideas({ folder: "~/i", agentName: "x\ny" }))).warnings;
out.agentNameDefault = agentName(out.defaults.agent, out.defaults.agentName);
out.untypedIds = untypedIds(["book/a", "work/b", "x"], ["book"]);
out.untypedFolders = await untypedFolders(process.argv[2], ["book", "code"]);
out.untypedNotice = [untypedNotice([]), untypedNotice(["work"]), untypedNotice(["work", "misc"])];
out.footnotes = [captureFootnote(out.noFolder, "Herdr space api"), captureFootnote(out.defaults, "Herdr space api"), captureFootnote(out.defaults, "")];

// The board's drop, on a stand-in view: the saved order of types not shown must survive it.
const view = {};
for (const part of [Common, Board]) {
  for (const [name, d] of Object.entries(Object.getOwnPropertyDescriptors(part.prototype))) if (name !== "constructor") Object.defineProperty(view, name, d);
}
Object.assign(view, {
  config: { types: ["book", "code"] },
  ideas: [{ id: "book/a", status: "seed", title: "a", created: "2026-01-02" }, { id: "code/b", status: "seed", title: "b", created: "2026-01-01" }],
  order: { seed: ["work/x", "code/b", "book/a", "work/y"], ripe: ["work/z"] },
  drag: "book/a", moved: true, overCard: "code/b", after: false,
});
const spawned = [];
view.drop("seed", { notify() {}, spawn(fn) { spawned.push(fn); } });
out.dropOrder = view.order;
out.dropSaves = spawned.length;
const parity = JSON.parse(process.argv[3]);
out.parity = parity.map((f) => [f, checkFolder(f).path ?? null]);
console.log(JSON.stringify(out));
