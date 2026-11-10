// The ideas mod's folder, git and view logic on real throwaway folders and git repos, run by
// tests/test_ideas_store.py under node (TZ=Europe/Madrid, for the daylight saving case).
// The mod's files are loaded as they are, with herdr_git_stub.js as `herdr` and
// gpui_view_stub.js as gpui-kit/gpui-base. Prints { case: null | "what failed" } as JSON.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { state, GIT_ENV } from "./herdr.js";
import {
  autocommit, createIdea, slugify, moveIdea, updateIdea, listIdeas, readBoard, writeBoard,
  daysSince, ago, today, parse,
} from "./store.js";
import { tabFor, tabName, workingIn, select, selected } from "./actions.js";
import { REVIEW, freshRequest } from "./common.js";
import Ideas from "./main.js";
import { drawn } from "./gpui.js";

const ROOT = process.argv[2];
const T = ["book", "code", "legal", "other"];
const cases = {};
const test = (name, fn) => { cases[name] = fn; };

const g = (dir, ...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8", env: GIT_ENV, stdio: ["ignore", "pipe", "pipe"] });
const gTry = (dir, ...args) => { try { return g(dir, ...args); } catch (e) { return null; } };
let n = 0;
const fresh = (name) => { const d = path.join(ROOT, `${++n}-${name}`); fs.mkdirSync(d, { recursive: true }); return d; };
const repo = (name) => { const d = fresh(name); g(d, "init", "-q", "-b", "main"); g(d, "commit", "-q", "--allow-empty", "-m", "init"); return d; };
const write = (p, text) => { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); };
const read = (p) => fs.readFileSync(p, "utf8");
const subject = (d) => g(d, "log", "-1", "--format=%s").replace(/\n$/, "");
const commits = (d) => Number(g(d, "rev-list", "--count", "HEAD").trim());
const idea = (title, extra = "") => `---\ntitle: ${title}\nstatus: seed\ncreated: 2020-01-01\n${extra}---\nBody of ${title}\n`;

// A view's context: spawned tasks run at once, timers wait until `fire`.
function makeCx() {
  const cx = {
    timers: [], errors: [],
    notify() {}, stop_propagation() {},
    focus_handle() { return { focus() {} }; },
    spawn(fn) { Promise.resolve().then(() => fn(cx)).catch((e) => cx.errors.push(e)); },
    timer: { after(_ms, fn) { cx.timers.push(fn); } },
  };
  return cx;
}
// Every exec is synchronous underneath, so a few turns of the event loop finish all the work.
const settle = async () => { for (let i = 0; i < 40; i++) await new Promise((r) => setImmediate(r)); };
const fire = async (cx) => { for (const f of cx.timers.splice(0)) f(cx); await settle(); };

// A copy of the mod in a role: "side" (no props), "board" ({ view: "board" }).
async function view(folder, role, settings = {}) {
  state.profiles = { profiles: { ideas: { folder, ...settings } } };
  state.props = role === "board" ? { view: "board" } : {};
  const v = new Ideas();
  const cx = makeCx();
  v.init(state.props, cx);
  await settle();
  assert.equal(v.loaded, true, "the view loaded");
  assert.deepEqual(cx.errors, []);
  return { v, cx };
}
const noteTitles = () => state.notes.map((x) => x.title);
// The ideas space showing, with a shell in the ideas folder.
const ideasSpaceFor = (folder, tabs = []) => {
  state.spaces = [{ id: "s1", index: 1, name: "ideas", named: false, folder, machine: null, active: true,
    tabs: [{ id: "t1", index: 1, name: "1", named: false, active: true }, ...tabs] }];
  state.panes = [{ pane: "p1", terminal: "a1", tab: "t1", cwd: folder }];
};

// ---------- autocommit ----------

test("autocommit leaves a bigger repo alone", async () => {
  const P = repo("parent");
  write(`${P}/journal.md`, "a\n"); g(P, "add", "."); g(P, "commit", "-qm", "journal");
  write(`${P}/journal.md`, "half done\n"); g(P, "add", "journal.md");
  const I = `${P}/ideas`;
  await createIdea(I, { title: "Nested", body: "x", type: "code" }, T);
  await assert.rejects(autocommit(I, [], T), /inside a bigger git repo \(as ideas\)/);
  assert.equal(commits(P), 2);
  assert.equal(g(P, "diff", "--cached", "--name-only"), "journal.md\n", "only what the person staged stays staged");
});

test("autocommit won't conclude a merge", async () => {
  const M = repo("merge");
  write(`${M}/code/c/idea.md`, idea("C")); g(M, "add", "-A"); g(M, "commit", "-qm", "base");
  g(M, "checkout", "-qb", "other"); write(`${M}/code/c/idea.md`, idea("C", "why: other\n")); g(M, "commit", "-qam", "o");
  g(M, "checkout", "-q", "main"); write(`${M}/code/c/idea.md`, idea("C", "why: main\n")); g(M, "commit", "-qam", "m");
  assert.equal(gTry(M, "merge", "-q", "other"), null, "the merge conflicts");
  await assert.rejects(autocommit(M, [], T), /a merge is in progress/);
  assert.equal(subject(M), "m");
  assert.ok(g(M, "ls-files", "--unmerged").trim(), "the conflict isn't marked resolved");
});

test("autocommit won't commit during a rebase", async () => {
  const R = repo("rebase");
  write(`${R}/code/c/idea.md`, idea("C")); g(R, "add", "-A"); g(R, "commit", "-qm", "base");
  g(R, "checkout", "-qb", "topic"); write(`${R}/code/c/idea.md`, idea("C", "why: topic\n")); g(R, "commit", "-qam", "t");
  g(R, "checkout", "-q", "main"); write(`${R}/code/c/idea.md`, idea("C", "why: main\n")); g(R, "commit", "-qam", "m");
  g(R, "checkout", "-q", "topic");
  assert.equal(gTry(R, "rebase", "-q", "main"), null, "the rebase conflicts");
  const head = g(R, "rev-parse", "HEAD");
  await assert.rejects(autocommit(R, [], T), /rebase/);
  assert.equal(g(R, "rev-parse", "HEAD"), head);
  gTry(R, "rebase", "--abort");
});

test("autocommit waits for a cherry-pick of several commits", async () => {
  const C = repo("sequencer");
  write(`${C}/code/c/idea.md`, idea("C")); g(C, "add", "-A"); g(C, "commit", "-qm", "base");
  g(C, "checkout", "-qb", "other");
  write(`${C}/code/c/idea.md`, idea("C", "why: o1\n")); g(C, "commit", "-qam", "o1");
  write(`${C}/code/d/idea.md`, idea("D")); g(C, "add", "-A"); g(C, "commit", "-qm", "o2");
  g(C, "checkout", "-q", "main"); write(`${C}/code/c/idea.md`, idea("C", "why: main\n")); g(C, "commit", "-qam", "m");
  assert.equal(gTry(C, "cherry-pick", "main..other"), null, "the first pick conflicts");
  write(`${C}/code/c/idea.md`, idea("C", "why: both\n")); g(C, "add", "-A"); g(C, "commit", "-qm", "o1 resolved");
  write(`${C}/code/e/idea.md`, idea("E"));
  await assert.rejects(autocommit(C, [], T), /several commits is in progress/);
  assert.equal(subject(C), "o1 resolved");
  gTry(C, "cherry-pick", "--abort");
});

test("autocommit runs few processes", async () => {
  const R = repo("count");
  write(`${R}/code/x/idea.md`, idea("X"));
  state.execs = 0;
  assert.equal(await autocommit(R, [], T), "Add idea: x");
  assert.ok(state.execs <= 5, `${state.execs} processes`);
  state.execs = 0;
  assert.equal(await autocommit(R, [], T), null);
  assert.ok(state.execs <= 2, `${state.execs} processes with nothing to do`);
});

test("autocommit won't commit on a detached HEAD", async () => {
  const D = repo("detached");
  g(D, "checkout", "-q", "--detach");
  write(`${D}/code/x/idea.md`, idea("X"));
  await assert.rejects(autocommit(D, [], T), /detached HEAD/);
  assert.equal(commits(D), 1);
});

test("autocommit sees new ideas with showUntrackedFiles=no", async () => {
  const U = repo("untracked");
  g(U, "config", "status.showUntrackedFiles", "no");
  await createIdea(U, { title: "Hidden", body: "", type: "code" }, T);
  assert.equal(await autocommit(U, [], T), "Add idea: hidden", "a title it doesn't know: the slug");
  assert.equal(g(U, "ls-files"), "code/hidden/idea.md\n");
});

test("autocommit names non-ASCII ideas as they are", async () => {
  const Q = repo("quote");
  write(`${Q}/code/café/idea.md`, idea("Café"));
  assert.equal(await autocommit(Q, [], T), "Add idea: café");
  assert.match(g(Q, "log", "-1", "--format=%b"), /^A code\/café\/idea\.md$/m);
  write(`${Q}/code/café/notes "quoted".md`, "n\n");
  assert.equal(await autocommit(Q, [{ id: "code/café", title: "Café au lait" }], T), "Update: Café au lait");
  assert.match(g(Q, "log", "-1", "--format=%b"), /^A code\/café\/notes "quoted"\.md$/m);
});

test("autocommit cuts subjects by characters", async () => {
  const E = repo("emoji");
  const title = "a".repeat(61) + "🚀" + "b";
  const id = await createIdea(E, { title, body: "", type: "code" }, T);
  await autocommit(E, [{ id, title }], T);
  assert.equal(subject(E), "Add idea: " + "a".repeat(61) + "🚀");
});

test("autocommit subjects, .DS_Store and nothing to do", async () => {
  const S = repo("subjects");
  const id = await createIdea(S, { title: "One", body: "", type: "code" }, T);
  write(`${S}/code/one/.DS_Store`, "junk");
  assert.equal(await autocommit(S, [{ id, title: "One" }], T), "Add idea: One");
  assert.doesNotMatch(g(S, "ls-files"), /DS_Store/);
  assert.equal(await autocommit(S, [], T), null, "nothing changed");
  write(`${S}/code/one/notes.md`, "n\n");
  assert.equal(await autocommit(S, [{ id, title: "One" }], T), "Update: One");
  await writeBoard(S, { order: { seed: [id] } }, null);
  assert.equal(await autocommit(S, [], T), "Board: order and review");
  fs.rmSync(`${S}/code/one`, { recursive: true });
  assert.equal(await autocommit(S, [], T), "Remove idea: one");
  assert.equal(await autocommit(fresh("not-a-repo"), [], T), null);
});

// ---------- the store ----------

test("slugify keeps every script", async () => {
  const cases = [["日本語のアイデア", "日本語のアイデア"], ["Идея номер 2", "идея-номер-2"], ["🚀 launch", "launch"],
    ["Ça va ñandú", "ca-va-nandu"], ["Straße", "strasse"], ["Ærø Łódź", "aero-lodz"], ["がぎ", "がぎ"],
    ["हिन्दी", "हिन्दी"], ["!!!", "idea"], ["", "idea"], ["  -Hello, World!- ", "hello-world"]];
  for (const [text, slug] of cases) assert.equal(slugify(text), slug, text);
  const long = slugify("字".repeat(60));
  assert.equal(Array.from(long).length, 48);
  assert.equal(slugify("a".repeat(47) + " b"), "a".repeat(47), "no dash left at the end");
  assert.equal(slugify("a".repeat(47) + "🚀🚀"), "a".repeat(47));
});

test("createIdea writes a seed in a free folder", async () => {
  const F = fresh("create");
  const a = await createIdea(F, { title: "My idea", body: "  text \n", type: "code", origin: "Herdr space\nx" }, T);
  const b = await createIdea(F, { title: "My idea", body: "", type: "code" }, T);
  const c = await createIdea(F, { title: "Ünïcode\nline", body: "", type: "nope" }, T);
  assert.deepEqual([a, b, c], ["code/my-idea", "code/my-idea-2", "other/unicode-line"]);
  const text = read(`${F}/${a}/idea.md`);
  assert.equal(text, `---\ntitle: My idea\nstatus: seed\ncreated: ${today()}\norigin: Herdr space x\n---\ntext\n`);
  assert.match(read(`${F}/${c}/idea.md`), /^title: Ünïcode line$/m);
  assert.equal(await createIdea(F, { title: "x", body: "", type: "book" }, ["book"]), "book/x");
  assert.equal(await createIdea(F, { title: "y", body: "", type: "zz" }, ["book", "misc"]), "misc/y", "no other: the last type");
});

test("listIdeas reads every idea", async () => {
  const F = fresh("list");
  write(`${F}/code/a/idea.md`, "---\ntitle: Alpha\nstatus: ripe\ncreated: 2020-01-01\nupdated: 2021-01-01\ntags: x, y\n---\nBody\n");
  write(`${F}/code/a/notes.md`, "n");
  write(`${F}/code/a/research/z.md`, "z");
  write(`${F}/book/no-front/idea.md`, "just text\n");
  write(`${F}/book/no-idea/notes.md`, "x");
  write(`${F}/work/hidden/idea.md`, idea("Hidden"));
  write(`${F}/code/loose.md`, "x");
  const list = await listIdeas(F, T);
  assert.deepEqual(list.map((i) => i.id), ["code/a", "book/no-front"]);
  assert.deepEqual(list[0].files, ["notes.md", "research/z.md"]);
  assert.deepEqual([list[0].title, list[0].status, list[0].updated, list[0].tags], ["Alpha", "ripe", "2021-01-01", ["x", "y"]]);
  assert.deepEqual([list[1].title, list[1].status, list[1].body], ["no front", "seed", "just text"]);
});

test("moveIdea moves the folder to a free place", async () => {
  const F = fresh("move");
  const id = await createIdea(F, { title: "Mover", body: "", type: "code" }, T);
  await createIdea(F, { title: "Mover", body: "", type: "book" }, T);
  const [i] = (await listIdeas(F, T)).filter((x) => x.id === id);
  assert.equal(await moveIdea(F, i, "code", T), id, "same type");
  assert.equal(await moveIdea(F, i, "nope", T), id, "unknown type");
  assert.equal(await moveIdea(F, i, "book", T), "book/mover-2");
  assert.ok(!fs.existsSync(`${F}/code/mover`));
  assert.match(read(`${F}/book/mover-2/idea.md`), /title: Mover/);
  const [l] = (await listIdeas(F, T)).filter((x) => x.id === "book/mover-2");
  assert.equal(await moveIdea(F, l, "legal", T), "legal/mover-2", "a type folder that doesn't exist yet: the slug goes along");
});

test("updateIdea sets front matter and refuses a stale text", async () => {
  const F = fresh("update");
  write(`${F}/code/u/idea.md`, "---\ntitle: U\nstatus: seed\n---\nBody\n");
  let [u] = await listIdeas(F, T);
  await updateIdea(u, { status: "ripe", why: "a\nb" });
  assert.equal(read(u.path), `---\ntitle: U\nstatus: ripe\nwhy: a b\nupdated: ${today()}\n---\nBody\n`);
  await assert.rejects(updateIdea(u, { status: "parked" }), /stale/);
  assert.match(read(u.path), /status: ripe/);
  write(`${F}/code/v/idea.md`, "no front matter\n");
  [u] = (await listIdeas(F, T)).filter((x) => x.id === "code/v");
  await updateIdea(u, { status: "exploring" });
  assert.equal(parse(read(u.path)).meta.status, "exploring");
  assert.equal(parse(read(u.path)).meta.title, "v");
  assert.match(read(u.path), /no front matter/);
});

test("readBoard and writeBoard", async () => {
  const F = fresh("board");
  assert.deepEqual(await readBoard(F), { text: null, order: {}, reviewed: null });
  const text = await writeBoard(F, { order: { seed: ["code/a"] }, reviewed: "2026-01-01" }, null);
  assert.deepEqual(await readBoard(F), { text, order: { seed: ["code/a"] }, reviewed: "2026-01-01" });
  await assert.rejects(writeBoard(F, { order: {} }, null), /stale/);
  write(`${F}/.board.json`, "{broken");
  assert.deepEqual((await readBoard(F)).order, {});
});

test("ages count whole days across daylight saving", async () => {
  const Real = Date;
  const spring = new Real(2026, 2, 30).getTime() - new Real(2026, 2, 29).getTime();
  assert.equal(spring, 23 * 3600000, "TZ=Europe/Madrid has a 23-hour day on 29 March 2026");
  const at = (y, m, d) => {
    const now = new Real(y, m, d, 9).getTime();
    globalThis.Date = class extends Real { constructor(...a) { super(...(a.length ? a : [now])); } static now() { return now; } };
  };
  try {
    at(2026, 3, 1);
    assert.equal(today(), "2026-04-01");
    assert.equal(daysSince("2026-03-20"), 12);
    assert.equal(daysSince("2026-03-29"), 3);
    assert.equal(ago("2026-03-25"), "7d");
    at(2026, 10, 1);
    assert.equal(daysSince("2026-10-20"), 12);
    assert.equal(daysSince("2026-11-01"), 0);
    assert.equal(daysSince(""), null);
  } finally { globalThis.Date = Real; }
});

// ---------- the views ----------

test("a failed status write on a drop changes nothing", async () => {
  const F = fresh("drop");
  write(`${F}/code/a/idea.md`, idea("A")); write(`${F}/code/b/idea.md`, idea("B"));
  const before = { seed: ["code/a", "code/b"] };
  await writeBoard(F, { order: before }, null);
  const { v, cx } = await view(F, "board");
  state.failWrite = (p) => p.endsWith("/code/a/idea.md");
  Object.assign(v, { drag: "code/a", moved: true, overCard: "end:ripe", after: false });
  v.drop("ripe", cx);
  await settle();
  assert.deepEqual((await readBoard(F)).order, before, "the order on disk is back");
  assert.equal(parse(read(`${F}/code/a/idea.md`)).meta.status, "seed");
  assert.deepEqual(v.sorted(v.ideas.filter((i) => i.status === "seed"), "seed").map((i) => i.id), ["code/a", "code/b"]);
  assert.ok(noteTitles().includes("The idea changed on disk"));
  state.failWrite = null;
  Object.assign(v, { drag: "code/a", moved: true, overCard: "end:ripe", after: false });
  v.drop("ripe", cx);
  await settle();
  assert.deepEqual((await readBoard(F)).order.ripe, ["code/a"]);
  assert.equal(parse(read(`${F}/code/a/idea.md`)).meta.status, "ripe");
});

test("the review starts on a board opened for it", async () => {
  const F = fresh("review-start");
  write(`${F}/code/old/idea.md`, idea("Old"));
  ideasSpaceFor(F);
  const { v: side } = await view(F, "side");
  side.requestReview();
  assert.deepEqual(state.runs.at(-1)[0], "tab.new");
  assert.equal(state.runs.at(-1)[1].mod, "ideas", "the Board tab opens");
  assert.ok(freshRequest(state.shared.get(REVIEW)));
  // The board that tab makes: it starts once its ideas are loaded.
  state.props = { view: "board" };
  const board = new Ideas();
  const cx = makeCx();
  board.init(state.props, cx);
  board.render();
  assert.equal(board.review, null, "not before the ideas are read");
  await settle();
  board.render();
  assert.deepEqual(board.review?.queue, ["code/old"]);
  // A board opening long after a request doesn't start one.
  state.shared.set(REVIEW, Date.now() - 60000);
  const { v: late } = await view(F, "board");
  late.render();
  assert.equal(late.review, null);
  // A board already open starts when the request comes.
  side.requestReview();
  late.render();
  assert.deepEqual(late.review?.queue, ["code/old"]);
});

test("review writes are retried and failures said as they are", async () => {
  const F = fresh("review-writes");
  write(`${F}/code/s1/idea.md`, idea("S1"));
  write(`${F}/code/s2/idea.md`, idea("S2").replace("2020-01-01", "2020-02-01"));
  const { v, cx } = await view(F, "board");
  v.startReview(cx);
  assert.deepEqual(v.review.queue, ["code/s1", "code/s2"]);
  let edited = false;
  state.beforeWrite = (p) => {   // an agent writes S1 just before the review does
    if (p.endsWith("/code/s1/idea.md") && !edited) { edited = true; fs.appendFileSync(p, "Agent note\n"); }
  };
  state.failWrite = (p) => p.endsWith("/code/s2/idea.md") || p.endsWith("/.board.json");
  const r = v.review;
  v.reviewAct("keep", cx);
  v.reviewAct("park", cx);
  await settle();
  const s1 = read(`${F}/code/s1/idea.md`);
  assert.match(s1, /status: exploring/);
  assert.match(s1, /Agent note/, "the agent's text is kept");
  assert.equal(parse(read(`${F}/code/s2/idea.md`)).meta.status, "seed");
  assert.deepEqual([r.kept, r.parked], [1, 0], "only what was written is counted");
  assert.deepEqual(noteTitles(), ["Could not save the review of an idea", "Could not save the review"]);
  assert.equal(v.reviewed, null, "the review's day isn't kept when it wasn't saved");
  assert.equal(fs.existsSync(`${F}/.board.json`), false);
  state.failWrite = null; state.beforeWrite = null;
  v.startReview(cx);
  v.reviewAct("skip", cx);
  await settle();
  assert.equal((await readBoard(F)).reviewed, today());
  assert.equal(v.reviewed, today());
});

test("the side panel's note file follows the selection and the disk", async () => {
  const F = fresh("side-file");
  write(`${F}/code/a/idea.md`, idea("A")); write(`${F}/code/a/notes.md`, "first\n");
  write(`${F}/code/b/idea.md`, idea("B"));
  const { v, cx } = await view(F, "side");
  const a = v.ideas.find((i) => i.id === "code/a");
  select("code/a");
  v.showFile(a, "notes.md", cx);
  await settle();
  assert.equal(v.fileText, "first\n");
  write(`${F}/code/a/notes.md`, "second\n");
  await v.reload(cx);
  assert.equal(v.fileText, "second\n", "re-read on reload");
  select("code/b");               // as the board or capture would
  v.render();
  assert.equal(v.file, null);
  assert.equal(v.shownFile(v.ideas.find((i) => i.id === "code/b")), null);
});

test("a type change waits for the tab working in the idea", async () => {
  const F = fresh("type-busy");
  write(`${F}/code/a/idea.md`, idea("A"));
  ideasSpaceFor(F, [{ id: "t2", index: 2, name: "A", named: true, active: false }]);
  state.panes.push({ pane: "p2", terminal: "a2", tab: "t2", cwd: `${F}/code/a/research` });
  const { v, cx } = await view(F, "side");
  const a = v.ideas[0];
  assert.equal(workingIn(a)?.name, "A");
  v.setType(a, "book", cx);
  await settle();
  assert.ok(fs.existsSync(`${F}/code/a/idea.md`), "not moved");
  assert.equal(state.notes.at(-1).title, "Not moving the idea");
  assert.match(state.notes.at(-1).body, /"A" is working in its folder/);
  state.panes.at(-1).tab = "t1";    // a shell in the space's unnamed first tab
  v.setType(a, "book", cx);
  await settle();
  assert.match(state.notes.at(-1).body, /^Tab 1 is working in its folder/);
  state.panes.pop();
  state.panes.push({ pane: "p3", mod: "ideas", terminal: null, tab: "t2", cwd: null });
  v.setType(a, "book", cx);
  v.setType(a, "book", cx);        // a double click
  await settle();
  assert.ok(fs.existsSync(`${F}/book/a/idea.md`));
  assert.ok(!fs.existsSync(`${F}/book/a-2`));
  assert.ok(!noteTitles().includes("Could not move the idea"));
  assert.equal(selected(), "book/a");
});

test("a review retry leaves a status changed meanwhile", async () => {
  const F = fresh("review-status");
  write(`${F}/code/s/idea.md`, idea("S"));
  const { v, cx } = await view(F, "board");
  v.startReview(cx);
  state.beforeWrite = (p) => {
    if (p.endsWith("/code/s/idea.md") && !state.edited) { state.edited = true; write(p, read(p).replace("status: seed", "status: active")); }
  };
  v.reviewAct("park", cx);
  await settle();
  assert.equal(parse(read(`${F}/code/s/idea.md`)).meta.status, "active");
  assert.deepEqual(noteTitles(), ["Could not save the review of an idea"]);
});

test("a symlinked ideas folder is matched by its real path", async () => {
  const real = fresh("real-ideas");
  const link = path.join(ROOT, `${++n}-link`);
  fs.symlinkSync(real, link);
  write(`${real}/code/a/idea.md`, idea("A"));
  const [a] = await listIdeas(link, T);
  assert.equal(a.dir, `${link}/code/a`);
  assert.equal(a.realDir, `${fs.realpathSync(real)}/code/a`);
  const [b] = await listIdeas(fs.realpathSync(real), T);
  assert.equal(b.realDir, null, "no second path when there's no link");
});

test("a double click on a status writes once", async () => {
  const F = fresh("status-twice");
  write(`${F}/code/a/idea.md`, idea("A"));
  const { v, cx } = await view(F, "side");
  v.setStatus(v.ideas[0], "ripe", cx);
  v.setStatus(v.ideas[0], "ripe", cx);
  await settle();
  assert.equal(parse(read(`${F}/code/a/idea.md`)).meta.status, "ripe");
  assert.deepEqual(state.notes, []);
});

test("agent tabs are found by their folder, names only when named", async () => {
  const F = "/x/ideas";
  const long = "Same title that is quite long, part ";
  const a = { dir: `${F}/code/a`, title: `${long}one` }, b = { dir: `${F}/code/b`, title: `${long}two` };
  assert.equal(tabName(a), tabName(b));
  const space = { tabs: [{ id: "tA", name: tabName(a), named: true }, { id: "tU", name: "2", named: false }, { id: "tB", name: "renamed", named: true }] };
  state.panes = [{ pane: "p", terminal: "x", tab: "tA", cwd: `${F}/code/a` }, { pane: "q", terminal: "y", tab: "tB", cwd: `${F}/code/b/notes` }];
  assert.equal(tabFor(a, space)?.id, "tA");
  assert.equal(tabFor(b, space)?.id, "tB", "by its folder, whatever its name");
  state.panes = [{ pane: "p", terminal: "x", tab: "tA", cwd: `${F}/code/a` }];
  assert.equal(tabFor(b, space), null, "not the tab of an idea with the same start of title");
  state.panes = [{ pane: "p", terminal: "x", tab: "tA", cwd: "/somewhere/else" }];
  assert.equal(tabFor(a, space)?.id, "tA", "a named tab whose agent moved elsewhere");
  assert.equal(tabFor({ dir: `${F}/code/two`, title: "2" }, space), null, "an unnamed tab's position isn't a name");
  assert.equal(tabFor({ dir: `${F}/code/ab`, title: "zz" }, { tabs: [{ id: "tA", name: "x", named: true }] }), null, "code/a isn't inside code/ab");
  state.panes = [{ pane: "p", terminal: "x", tab: "tA", cwd: F }, { pane: "r", terminal: "z", tab: "tA", cwd: `${F}/code` }];
  assert.equal(tabFor(a, space)?.id, "tA", "an agent at the ideas folder's top or in a type folder still has its tab");
  state.panes = [{ pane: "p", terminal: "x", tab: "tB", cwd: "/real/ideas/code/b/x" }];
  assert.equal(tabFor({ ...b, realDir: "/real/ideas/code/b" }, space)?.id, "tB", "a terminal reporting the resolved path");
  state.spaces = [space];
  assert.equal(workingIn({ ...b, realDir: "/real/ideas/code/b" })?.id, "tB");
  assert.equal(tabName({ title: "a".repeat(26) + "🚀🚀" }), "a".repeat(26) + "🚀🚀", "28 characters fit");
  assert.equal(tabName({ title: "a".repeat(26) + "🚀🚀🚀" }), "a".repeat(26) + "🚀…");
});

test("closing the side panel commits what's pending", async () => {
  const F = repo("close");
  const { v, cx } = await view(F, "side");
  await fire(cx);                 // the commit when it starts: nothing to do
  assert.equal(commits(F), 1);
  await createIdea(F, { title: "Late", body: "", type: "code" }, T);
  await v.reload(cx);             // as the folder watch does
  v.scheduleCommit(cx);
  await v.close(cx);
  assert.equal(subject(F), "Add idea: Late");
  await v.close(cx);              // nothing pending any more
  assert.equal(commits(F), 2);
  await cx.timers.splice(0)[0](cx);   // the minute after: nothing left
  await settle();
  assert.equal(commits(F), 2);
  assert.deepEqual(state.notes, []);
  const { v: off, cx: cx2 } = await view(F, "side", { autocommit: false });
  await createIdea(F, { title: "Off", body: "", type: "code" }, T);
  off.scheduleCommit(cx2);
  await off.close(cx2);
  assert.equal(commits(F), 2, "autocommit off: nothing");
});

test("the side panel warns once about a nested folder", async () => {
  const P = repo("nested-side");
  const F = `${P}/ideas`;
  write(`${F}/code/a/idea.md`, idea("A"));
  const { v, cx } = await view(F, "side");
  await fire(cx);
  v.scheduleCommit(cx);
  await fire(cx);
  assert.deepEqual(noteTitles(), ["Could not commit the ideas folder"]);
  assert.equal(commits(P), 1);
});

test("every role renders", async () => {
  const F = fresh("render");
  write(`${F}/code/a/idea.md`, idea("A")); write(`${F}/code/a/notes.md`, "n");
  ideasSpaceFor(F);
  for (const role of ["side", "board"]) {
    const { v, cx } = await view(F, role);
    v.render();
    select("code/a");
    v.render();
    v.startReview(cx);
    v.render();
    select(null);
  }
});

// ---------- main.js and capture.js glue ----------

test("the side panel warns about folders that aren't types, once", async () => {
  const F = fresh("untyped");
  write(`${F}/code/a/idea.md`, idea("A")); write(`${F}/work/b/idea.md`, idea("B"));
  ideasSpaceFor(F);
  await view(F, "board");
  assert.deepEqual(state.notes, [], "the board doesn't warn (the side panel does)");
  await view(F, "side");
  const warned = state.notes.filter((x) => x.title === "Ideas: some folders aren't types");
  assert.equal(warned.length, 1);
  assert.equal(warned[0].level, "warning");
  assert.match(warned[0].body, /Ideas in work don't show: add it to "types"/);
  // With work as a type, nothing to say.
  state.notes = [];
  await view(F, "side", { types: ["code", "work"] });
  assert.deepEqual(noteTitles(), []);
});

test("the side panel still loads when the untyped folders can't be listed", async () => {
  const F = fresh("unlisted");
  write(`${F}/code/a/idea.md`, idea("A")); write(`${F}/work/b/idea.md`, idea("B"));
  ideasSpaceFor(F);
  // Only the listing of untyped folders (store.js OTHERS) fails; everything else runs.
  state.failExec = (cmd, args) => cmd === "sh" && String(args[1]).includes('for f in "$d"/*/idea.md');
  const { v } = await view(F, "side");
  assert.deepEqual(v.ideas.map((x) => x.id), ["code/a"]);
  assert.ok(!noteTitles().includes("Ideas: some folders aren't types"));
});

// The capture overlay, rendered: the footnote's text and the color drawn just before it.
async function captureFoot(settings) {
  state.profiles = settings === null ? null : { profiles: { ideas: settings } };
  state.props = { overlay: "o1" };
  const v = new Ideas();
  const cx = makeCx();
  v.init(state.props, cx);
  const foot = () => {
    drawn.length = 0;
    v.render();
    const i = drawn.findIndex(([k, s]) => k === "text" && /^(From |Saves into )/.test(s));
    return i < 0 ? null : { text: drawn[i][1], color: drawn[i - 1]?.[0] === "color" ? drawn[i - 1][1] : null };
  };
  const before = foot();
  await settle();
  assert.deepEqual(cx.errors, []);
  return { before, after: foot() };
}

test("capture says where the idea comes from", async () => {
  state.spaces = [{ id: "s1", index: 1, name: "api", folder: "/srv/api", active: true, tabs: [] }];
  const { after } = await captureFoot({ folder: "~/notes/ideas" });
  assert.deepEqual(after, { text: "From api", color: "dim" });
});

test("capture says where it saves, in amber, when profiles.json gives no folder", async () => {
  state.spaces = [{ id: "s1", index: 1, name: "api", folder: "/srv/api", active: true, tabs: [] }];
  const { before, after } = await captureFoot({});
  assert.deepEqual(before, { text: "From api", color: "dim" }, "the defaults until profiles.json is read");
  assert.deepEqual(after, { text: "Saves into ~/ideas", color: "ansi3" });
  // No space active: no origin, nothing beside the buttons (but the warning still shows).
  state.spaces = [];
  assert.equal((await captureFoot({ folder: "~/notes/ideas" })).after, null);
  assert.deepEqual((await captureFoot(null)).after, { text: "Saves into ~/ideas", color: "ansi3" });
});

const out = {};
for (const [name, fn] of Object.entries(cases)) {
  Object.assign(state, { notes: [], runs: [], shared: new Map(), spaces: [], panes: [], failWrite: null, beforeWrite: null, failExec: null, props: {}, edited: false });
  try { await fn(); out[name] = null; }
  catch (e) { out[name] = String(e?.stack ?? e); }
}
console.log(JSON.stringify(out));
process.exit(0);
