// Checks of the History mod's pure parts (model.js), run by tests/test_history_mod.py under node.
// Git runs only in throwaway repos under argv[2], with the mod's own arguments, its own
// identity and no global or system config. Prints one JSON object; the Python test asserts on it.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import {
  READ, DIFF, gitVersion, lazyArgs, partialClone, repoPaths, watchDirs, branchRefs, logArgs, parseLog, appendPage,
  parseBody, parseFiles, diffLines, graph, dotLane, graphSpan, layoutShows, refs,
} from "./model.js";

const tmp = process.argv[2], out = {};
const env = {
  PATH: process.env.PATH, HOME: tmp, LANG: "C", LC_ALL: "C", GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: path.join(tmp, "gitconfig"),
  GIT_AUTHOR_NAME: "Tester", GIT_AUTHOR_EMAIL: "tester@example.com", GIT_COMMITTER_NAME: "Tester", GIT_COMMITTER_EMAIL: "tester@example.com",
};
fs.writeFileSync(env.GIT_CONFIG_GLOBAL, "");
const run = (cwd, args, more = {}) => {
  try { return { code: 0, stdout: execFileSync("git", args, { cwd, env: { ...env, ...more }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }), stderr: "" }; }
  catch (e) { return { code: e.status ?? 1, stdout: e.stdout ?? "", stderr: e.stderr ?? "" }; }
};
const git = (cwd, args, more) => { const r = run(cwd, args, more); if (r.code) throw new Error(`git ${args.join(" ")}: ${r.stderr}`); return r.stdout; };
// What the mod runs: READ (and the lazy-fetch flag) before the command.
const read = (cwd, args, lazy = []) => run(cwd, [...READ, ...lazy, ...args]);
const repo = (name) => { const dir = path.join(tmp, name); fs.mkdirSync(dir); git(dir, ["init", "-q", "-b", "main"]); return dir; };
const commit = (dir, message, more) => git(dir, ["commit", "-q", "--allow-empty", "-m", message], more);
const tree = (dir) => {
  const files = [];
  const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else files.push([path.relative(dir, p), fs.statSync(p).mtimeMs, fs.statSync(p).size]); } };
  walk(dir);
  return JSON.stringify(files.sort());
};
const version = gitVersion(git(tmp, ["--version"]));

// Records: 0x1F in a subject and an author, a subject on two lines, a body.
{
  const dir = repo("records");
  commit(dir, "first");
  commit(dir, "sub\x1fject", { GIT_AUTHOR_NAME: "Ann\x1fBee" });
  commit(dir, "two line\nsubject\n\nthe body\n\nmore body\n");
  commit(dir, "no body");
  const log = parseLog(read(dir, logArgs(0, 10, ["HEAD"])).stdout, 10);
  out.records = {
    hashes: log.commits.map(c => c.hash), expected: git(dir, ["rev-list", "HEAD"]).trim().split("\n"), more: log.more,
    subjects: log.commits.map(c => c.subject), authors: log.commits.map(c => c.author),
    parents: log.commits.map(c => c.parents.length), refs: log.commits[0].refs,
    bodies: log.commits.map(c => parseBody(read(dir, ["show", "-s", "--format=%b", c.hash]).stdout)),
  };
  const two = parseLog(read(dir, logArgs(0, 2, ["HEAD"])).stdout, 2);
  out.records.limited = { n: two.commits.length, more: two.more };
}

// log.showSignature=true in the repo: signature text before every record.
{
  let keygen = true;
  try { execFileSync("ssh-keygen", ["-q", "-t", "ed25519", "-N", "", "-f", path.join(tmp, "key")], { stdio: "ignore" }); } catch { keygen = false; }
  if (keygen && version && (version[0] > 2 || version[1] >= 34)) {
    const dir = repo("signed");
    for (const [k, v] of [["gpg.format", "ssh"], ["user.signingkey", path.join(tmp, "key.pub")], ["commit.gpgsign", "true"], ["log.showSignature", "true"]]) git(dir, ["config", k, v]);
    commit(dir, "signed one"); commit(dir, "signed two");
    const raw = run(dir, logArgs(0, 10, ["HEAD"])).stdout;
    const log = parseLog(read(dir, logArgs(0, 10, ["HEAD"])).stdout, 10);
    out.signed = {
      plainHasSignature: !/^[0-9a-f]{40}/.test(raw),
      hashes: log.commits.map(c => c.hash), expected: git(dir, ["rev-list", "HEAD"]).trim().split("\n"),
      subjects: log.commits.map(c => c.subject),
      body: parseBody(read(dir, ["show", "-s", "--format=%b", "HEAD"]).stdout),
    };
  } else out.signed = null;
}

// Paging: a page read with --skip after a new commit repeats one already listed.
{
  const dir = repo("paging");
  for (let i = 1; i <= 6; i++) commit(dir, `c${i}`);
  const page = (skip) => parseLog(read(dir, logArgs(skip, 3, ["HEAD"])).stdout, 3).commits;
  const first = page(0), second = page(3);
  const joined = appendPage(first, second);
  commit(dir, "c7");
  const moved = appendPage(first, page(3));
  out.paging = { joined: joined?.map(c => c.subject) ?? null, moved, unique: new Set(joined?.map(c => c.hash)).size };
  // A page graphed on its own continues the lines of the one above it.
  const all = parseLog(read(dir, logArgs(0, 100, ["HEAD"])).stdout, 100).commits;
  const whole = graph(all, { lanes: [], colors: [], next: 0 }), state = { lanes: [], colors: [], next: 0 };
  out.paging.graphJoins = JSON.stringify([...graph(all.slice(0, 3), state), ...graph(all.slice(3), state)]) === JSON.stringify(whole);
}

// Paths that are pathspec magic or patterns: each file's diff is its own.
{
  const dir = repo("paths");
  const names = { "src[id].tsx": "bracket", "srci.tsx": "plain", ":colon": "colon", "a*b": "star", "-dash": "dash", "sp ace": "space", "dir/nested?.md": "question" };
  for (const [name, text] of Object.entries(names)) { fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true }); fs.writeFileSync(path.join(dir, name), `${text}\n`); }
  fs.writeFileSync(path.join(dir, "bin.dat"), Buffer.from([0, 1, 2, 0]));
  git(dir, ["add", "-A"]); commit(dir, "files");
  const [c] = parseLog(read(dir, logArgs(0, 1, ["HEAD"])).stdout, 1).commits;
  const base = ["--root", c.hash];
  const files = parseFiles(read(dir, ["diff-tree", "-r", "-z", "--numstat", ...DIFF, ...base]).stdout, read(dir, ["diff-tree", "-r", "-z", "--name-status", ...DIFF, ...base]).stdout);
  out.paths = {
    files: files.map(f => [f.path, f.dir, f.name, f.status, f.add, f.binary]),
    diffs: Object.fromEntries(files.map(f => [f.path, diffLines(read(dir, ["diff-tree", "-p", ...DIFF, ...base, "--", f.path]).stdout, f.binary)])),
    expected: names,
  };
}

// Worktrees: refs move in the common folder, which holds the worktree's own.
{
  const dir = repo("main-wt");
  commit(dir, "one");
  const wt = path.join(tmp, "wt");
  git(dir, ["worktree", "add", "-q", "-b", "side", wt]);
  const args = ["rev-parse", "--show-toplevel", "--absolute-git-dir", "--path-format=absolute", "--git-common-dir"];
  const main = repoPaths(git(dir, args)), other = repoPaths(git(wt, args));
  out.worktree = { main: main.dirs.length === 1 && main.dirs[0] === main.gitDir, other: other.dirs, otherGitDir: other.gitDir, common: main.gitDir };
}

// A partial clone: History reads what's there and never downloads or writes.
{
  const src = repo("source");
  git(src, ["config", "uploadpack.allowFilter", "true"]);
  fs.writeFileSync(path.join(src, "f.txt"), "one\n"); git(src, ["add", "f.txt"]); commit(src, "one");
  fs.writeFileSync(path.join(src, "f.txt"), "two\n"); git(src, ["commit", "-q", "-am", "two"]);
  const clone = path.join(tmp, "partial");
  git(tmp, ["clone", "-q", "--filter=blob:none", "--no-checkout", `file://${src}`, clone]);
  const config = ["config", "--get-regexp", "^(extensions\\.partialclone|remote\\..*\\.promisor)$"];
  const lazy = lazyArgs(version);
  out.partial = { isPartial: partialClone(read(clone, config).stdout), sourcePartial: partialClone(read(src, config).stdout), lazy };
  if (lazy) {
    const before = tree(path.join(clone, ".git"));
    const log = read(clone, logArgs(0, 10, ["HEAD"]), lazy);
    const diff = read(clone, ["diff-tree", "-p", ...DIFF, "HEAD~1", "HEAD", "--", "f.txt"], lazy);
    out.partial.logOk = log.code === 0 && parseLog(log.stdout, 10).commits.length === 2;
    out.partial.diffFailed = diff.code !== 0;
    out.partial.unchanged = before === tree(path.join(clone, ".git"));
  }
}

// The graph past 10 lanes: the dot stays on the last lane, marked.
{
  const h = (n) => n.toString(16).padStart(40, "0");
  const commits = [{ hash: h(100), parents: Array.from({ length: 13 }, (_, i) => h(i)) }, ...Array.from({ length: 13 }, (_, i) => ({ hash: h(i), parents: [] }))];
  const rows = graph(commits, { lanes: [], colors: [], next: 0 });
  out.lanes = { cols: rows.map(r => r.col), dots: rows.map(r => dotLane(r.col)), span: graphSpan(rows), spanFirst: graphSpan(rows.slice(0, 1)),
    spanJoined: graphSpan(rows.slice(5), graphSpan(rows.slice(0, 5))) };
}

// Small parts.
out.versions = ["git version 2.39.5 (Apple Git-154)", "git version 2.44.0", "git version 3.0.1", "nonsense"].map(v => lazyArgs(gitVersion(v)));
out.watchDirs = [watchDirs("/r/.git", "/r/.git"), watchDirs("/r/.git/worktrees/x", "/r/.git"), watchDirs("/w/.git", "/elsewhere/common"), watchDirs("/r/.git", "--git-common-dir"), watchDirs("/r/.git", undefined)];
out.partialConfig = [partialClone("remote.origin.promisor true\n"), partialClone("extensions.partialclone origin\n"), partialClone("remote.origin.promisor false\n"), partialClone("")];
out.branches = branchRefs("refs/heads/main\tabc\nrefs/remotes/origin/HEAD\tabc\nrefs/remotes/origin/x\tdef\nrefs/tags/v1\t123\n");
out.refs = refs("HEAD -> main, origin/main, origin/HEAD, tag: v1");
out.appendDup = appendPage([{ hash: "a" }, { hash: "b" }], [{ hash: "b" }, { hash: "c" }]);
out.diffCut = diffLines(["diff --git a/x b/x", "@@ -1 +1 @@", ...Array.from({ length: 1600 }, () => "+y"), "+" + "z".repeat(5000)].join("\n") + "\n", false);
out.diffCut = { n: out.diffCut.length, last: out.diffCut.at(-1) };
const block = (id) => ({ id, type: "block", content: { mod: id === "history" ? "standard-history" : "x" } });
const panel = (active, hidden) => ({ type: "row", children: [block("main"), { id: "panel", type: "column", hidden, children: [{ id: "body", type: "stack", active, children: [block("files"), block("history")] }] }] });
out.shows = {
  shown: layoutShows(panel("history", false), "standard-history"),
  otherChild: layoutShows(panel("files", false), "standard-history"),
  hiddenPanel: layoutShows(panel("history", true), "standard-history"),
  none: layoutShows({ type: "row", children: [block("main")] }, "standard-history"),
  floating: layoutShows({ type: "row", children: [block("main")], floating: [{ id: "f", content: { mod: "standard-history" } }] }, "standard-history"),
  nothing: layoutShows(null, "standard-history"),
};
console.log(JSON.stringify(out));
