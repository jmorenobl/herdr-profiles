// Checks of the core mods' pure parts, run by tests/test_core_mods.py under node:
// the Files panel's markdown image splitter and its copy of images on another
// machine, the profile switcher's config and the tab bar's bottom terminal.
// Prints one JSON object of results; the Python test asserts on it.
// argv[2]: a throwaway folder with proj/sub/ and proj/.herdr-profile in it, and
// img/ with a.png (several pieces of base64), big.png (too big) and gone.png absent.
import { state, exec } from "./stubs.js";
import { splitImages, linkTarget } from "./markdown.js";
import { fetchRemote, PIECE, MAX_BYTES } from "./pictures.js";
import { loadConfig, profileFor, FIND_UP } from "./profiles.js";
import { LABEL, plan, orphans, startArgs } from "./terminal.js";

const out = { logs: [] };
console.log = (...a) => out.logs.push(a.join(" ")); // the mods log; stdout is for the results
const md = {
  badge: "[![CI](https://x.test/badge.svg)](https://x.test/actions)\n",
  badgeAngle: "[![CI](<a b.svg>)](<docs/a b.md>)\n",
  badgeRow: "[![CI](a.svg)](https://x.test/ci) [![Cov](b.svg)](https://x.test/cov)\n",
  table: "| a | b |\n|---|---|\n| ![x](a.png) | y |\n",
  list: "- item ![i](a.png) more\n- next\n",
  listBlock: "- item\n\n  ![i](a.png)\n- next\n",
  inline: "See ![logo](logo.png) here.\n",
  codeSpan: "Use `![alt](path)` syntax, or ``![b](c) `x` `` too\n",
  fenced: "```md\n![f](f.png)\n```\n![after](a.png)\n",
  longFence: "````\n```\n![f](f.png)\n````\n",
  tilde: "~~~\n![f](f.png)\n~~~\n",
  indented: "Text\n\n    ![code](code.png)\n",
  continuation: "Text\n    ![cont](c.png)\n",
  comment: "<!-- ![c](c.png) -->\n![real](r.png)\n",
  multiComment: "<!--\n![c](c.png)\n-->\n![real](r.png)\n",
  angle: "![sp](<a b.png>)\n",
  title: "![t](a.png \"A title\")\n",
  block: "Intro\n\n![shot](docs/shot.png)\n\nAfter\n",
  html: '<p align="center"><img src="logo.png" alt="Logo" width="100"></p>\n',
  htmlLinked: '<a href="https://x.test"><img src="b.svg"></a>\n',
  escaped: "\\![no](x.png)\n",
  listItem: "1. step\n\n   ![shot](shot.png)\n\n2. next\n",
  lazy: "- item\n  ![lazy](l.png)\n",
  quote: "> ![q](q.png)\n",
  emptyAlt: "[![](a.svg)](https://x.test/ci) ![](img/b.png)\n",
  afterList: "- a\n# Heading\n![x](x.png)\n",
  afterBreak: "* * *\n![x](x.png)\n",
  indentedFence: "para\n\n    ```\n\nText\n\n![x](x.png)\n",
  listFence: "- a\n\n  ```\n  ![f](f.png)\n  ```\n",
  parens: "![a](foo_(bar).png)\n",
  selfClosing: "<img src=x alt=x/>\n",
};
out.slow = {};
for (const l of ["<img ", "<img src=x ", "![a](", "[![a](b)"]) {
  const t = Date.now();
  splitImages(l.repeat(Math.ceil(400000 / l.length)));
  out.slow[l] = Date.now() - t;
}
out.split = Object.fromEntries(Object.entries(md).map(([k, v]) => [k, splitImages(v)]));
out.links = {
  folder: linkTarget("docs/", "/r", "README.md"),
  space: linkTarget("a b.png", "/r", "docs/x.md"),
  encoded: linkTarget("a%20b.png", "/r", "x.md"),
  up: linkTarget("../x.md", "/r", "README.md"),
};

const cfg = async (profiles) => { state.profiles = profiles; return loadConfig(); };
out.config = {
  missing: await cfg(null),
  badJson: await cfg("{nope"),
  nullJson: await cfg("null"),
  array: await cfg([1, 2]),
  string: await cfg('"x"'),
  rulesObject: await cfg({ default: "standard", profiles: { standard: { layout: "standard" } }, rules: {} }),
  badShapes: await cfg({ default: 3, profiles: { a: { layout: "a" }, b: null, c: "x", d: [] }, rules: [null, 1, "x", { path: "~/a", profile: "a" }] }),
  profilesArray: await cfg({ default: "a", profiles: [{ layout: "a" }], rules: [] }),
};

// profileFor on a space in argv[2]/proj/sub, whose proj/.herdr-profile names a profile.
const root = process.argv[2];
state.home = root;
const space = { tabs: [], folder: `${root}/proj/sub`, machine: null };
const pick = async (config) => {
  try { return { profile: await profileFor(space, config) }; } catch (e) { return { error: String(e) }; }
};
const base = (rules, more = {}) => ({ default: "standard", profiles: { standard: { layout: "standard" }, ideas: { layout: "ideas" }, ...more }, rules });
state.files[`${root}/proj/.herdr-profile`] = "ideas\n";
out.pick = { marker: await pick(base([])) };
state.files[`${root}/proj/.herdr-profile`] = "constructor\n";
out.pick.markerProto = await pick(base([]));
state.files[`${root}/proj/.herdr-profile`] = "nope\n";
out.pick.markerUnknown = await pick(base([]));
out.pick.badRules = await pick(base([{ path: 3, profile: "ideas" }, { has: ["x"], profile: "ideas" }, { path: "~/proj", has: 7, profile: "ideas" },
  { profile: "ideas" }, { path: "~/proj", profile: "constructor" }, { path: "~/proj", profile: "toString" }]));
out.pick.path = await pick(base([{ path: "~/proj", profile: "ideas" }]));
out.pick.has = await pick(base([{ has: "sub", profile: "ideas" }]));
out.pick.hasMissing = await pick(base([{ has: "nothing-here", profile: "ideas" }]));
out.pick.loaded = await pick(await cfg({ default: "standard", profiles: { standard: { layout: "standard" }, ideas: null }, rules: [null, { path: "~/proj", profile: "ideas" }] }));
out.findUp = FIND_UP;

// The bottom terminal: what the toggle does, and which parked shells nobody can show any more.
const sp = { id: "sp1", tabs: [{ id: "tb1", active: false }, { id: "tb2", active: true }] };
const shell = (address, space, more = {}) => ({ address, state: "live", labels: { [LABEL]: space }, ...more });
const pane = (terminal, tab) => ({ pane: `p-${terminal}`, terminal, tab });
out.terminal = {
  none: plan(sp, [], []),
  othersOnly: plan(sp, [shell("t1", "sp2"), { address: "t2", state: "live", labels: {} }, { address: "t3", state: "live" }], []),
  finished: plan(sp, [shell("t1", "sp1", { state: "finished" })], []),
  remote: plan(sp, [shell("box/t1", "sp1")], []),
  parked: plan(sp, [shell("t1", "sp1")], [pane("t9", "tb2")]),
  here: plan(sp, [shell("t1", "sp1")], [pane("t1", "tb2")]),
  elsewhere: plan(sp, [shell("t1", "sp1")], [pane("t1", "tb1")]),
  orphans: orphans([sp], [shell("t1", "sp1"), shell("t2", "gone"), shell("t3", "gone"), shell("t4", "gone", { state: "finished" }),
    shell("box/t5", "gone"), { address: "t6", state: "live", labels: {} }], [pane("t3", "tb9")]),
  startLocal: startArgs(sp, "/work/repo"),
  startNoFolder: startArgs(sp, ""),
};

// A space on another machine ("box"): the app names its ids box/…; its shell is box/t…,
// labelled with the space's id as box knows it (or, should the app qualify it, box/…).
const rsp = { id: "box/sp1", machine: "box", tabs: [{ id: "box/tb1", active: false }, { id: "box/tb2", active: true }] };
out.remote = {
  none: plan(rsp, [shell("t1", "sp1"), shell("t2", "box/sp1"), shell("other/t3", "sp1")], []),
  parked: plan(rsp, [shell("box/t1", "sp1")], []),
  qualified: plan(rsp, [shell("box/t1", "box/sp1")], []),
  here: plan(rsp, [shell("box/t1", "sp1")], [pane("box/t1", "box/tb2")]),
  elsewhere: plan(rsp, [shell("box/t1", "sp1")], [pane("box/t1", "box/tb1")]),
  // A local space whose id happens to be "sp1" doesn't take box's shell, nor box's space a local one.
  localTwin: plan(sp, [shell("box/t1", "sp1")], []),
  start: startArgs(rsp, "/home/me/repo"),
  orphansReady: orphans([sp, rsp], [shell("box/t1", "sp1"), shell("box/t2", "gone"), shell("box/t3", "box/gone"), shell("t4", "gone"),
    shell("box/t5", "gone", { state: "finished" }), shell("box/t6", "gone"), shell("far/t7", "gone")], [pane("box/t6", "box/tb1")], [null, "box"]),
  orphansLoading: orphans([sp], [shell("box/t2", "gone"), shell("t4", "gone")], [], [null]),
};

// An image on "box" (here: the stand-in exec runs everything in this computer's sh,
// and records which calls asked for the other machine).
const calls = [];
const counted = (cmd, args, options = {}) => { calls.push({ on: options.on ?? null, step: args[5] ?? "read" }); return exec(cmd, args, options); };
const fetch = async (name) => { calls.length = 0; const r = await fetchRemote(counted, { on: "box", path: `${root}/img/${name}`, dir: `${root}/cache`, ext: "png" }); return { ...r, calls: [...calls] }; };
out.pictures = { piece: PIECE, max: MAX_BYTES, first: await fetch("a.png"), again: await fetch("a.png"), big: await fetch("big.png"), gone: await fetch("gone.png") };

process.stdout.write(JSON.stringify(out));
