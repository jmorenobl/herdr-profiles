// The History panel's pure parts: git's arguments and what its output means,
// the lane graph, and where the panel sits in the layout. No Herdr calls here,
// so the tests run it under node (tests/js/history_test.js).

// Reads write nothing under .git (no index refresh or lock, no fsmonitor cookie):
// the folder watch would see it, and every refresh would start the next one.
// Paths are literal (`src[id].tsx` is not a pattern), and a signature setting
// can't put text before the records.
export const READ = ["--no-optional-locks", "--literal-pathspecs", "-c", "core.fsmonitor=false",
  "-c", "diff.autoRefreshIndex=false", "-c", "log.showSignature=false"];
export const DIFF = ["--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"];
export const PAGE = 300, MAX_LANES = 10, MAX_LINES = 1500, MAX_FILES = 1000;
const HASH = /^[0-9a-f]{40}([0-9a-f]{24})?$/;

// A partial clone downloads what's missing when git reads it; `--no-lazy-fetch`
// (git 2.44) stops that, so History never writes or goes online. Older git can't.
export function gitVersion(text) {
  const m = /(\d+)\.(\d+)/.exec(text ?? "");
  return m ? [Number(m[1]), Number(m[2])] : null;
}
export const lazyArgs = (version) => version && (version[0] > 2 || (version[0] === 2 && version[1] >= 44)) ? ["--no-lazy-fetch"] : null;
// `git config --get-regexp '^(extensions\.partialclone|remote\..*\.promisor)$'`: a partial clone?
export const partialClone = (text) => (text ?? "").split("\n").some((l) => /^extensions\.partialclone \S/.test(l) || /^remote\..*\.promisor true$/.test(l));

// `rev-parse --show-toplevel --absolute-git-dir --path-format=absolute --git-common-dir`.
// A worktree's refs live in the common folder; its own folder is usually inside it.
export function repoPaths(stdout) {
  const [root, gitDir, common] = stdout.trim().split("\n");
  return { root, gitDir, dirs: watchDirs(gitDir, common) };
}
export function watchDirs(gitDir, common) {
  const dirs = [gitDir];
  if (common && common.startsWith("/") && common !== gitDir) {
    if (gitDir.startsWith(common + "/")) dirs[0] = common;
    else dirs.push(common);
  }
  return dirs;
}

// "HEAD -> main, origin/main, tag: v1" as short chips: the branch HEAD is on first.
export function refs(text) {
  return text.split(", ").filter(Boolean).filter(r => r !== "HEAD" && !r.endsWith("/HEAD"))
    .map(r => r.startsWith("HEAD -> ") ? { name: r.slice(8), head: true } : r.startsWith("tag: ") ? { name: r.slice(5), tag: true } : { name: r });
}

// `for-each-ref --format=%(refname)%09%(objectname)`: the branches the picker offers.
export function branchRefs(stdout) {
  return stdout.split("\n").filter(Boolean).map(l => l.split("\t")[0])
    .filter(ref => (ref.startsWith("refs/heads/") || ref.startsWith("refs/remotes/")) && !ref.endsWith("/HEAD"))
    .map(ref => ({ ref, name: ref.replace(/^refs\/(heads|remotes)\//, ""), remote: ref.startsWith("refs/remotes/") }));
}

// One record per commit, its fields on lines: no field can hold a newline
// (%s joins the subject's lines), while 0x1F can be in any of them.
const FORMAT = "%H%n%h%n%P%n%at%n%D%n%an%n%s";
export const logArgs = (skip, count, revs) =>
  ["log", "-z", "--no-color", `--skip=${skip}`, "-n", String(count + 1), "--date-order", `--format=${FORMAT}`, ...revs, "--"];
export function parseLog(stdout, count) {
  const commits = [];
  for (const entry of stdout.split("\0")) {
    const lines = entry.split("\n"), at = lines.findIndex((l) => HASH.test(l));
    if (at < 0 || lines.length - at < 7) continue;
    const [hash, short, parents, time, decoration, author, ...subject] = lines.slice(at);
    commits.push({ hash, short, parents: parents ? parents.split(" ") : [], author, time: Number(time), refs: refs(decoration), subject: subject.join(" ") });
  }
  return { commits: commits.slice(0, count), more: commits.length > count };
}

// A page read with --skip joins the list only if history didn't move under it:
// a commit already listed means it did (and the list can't hold one twice).
export function appendPage(commits, page) {
  const seen = new Set(commits.map(c => c.hash));
  return page.some(c => seen.has(c.hash)) ? null : [...commits, ...page];
}

// `show -s --format=%b`: the message after the subject's paragraph.
export function parseBody(stdout) {
  const text = stdout.replace(/\s+$/, "").replace(/^\n+/, "");
  return text ? text.split("\n") : [];
}

// `diff-tree -r -z --numstat` and `--name-status` of one commit: its files.
// With -z, --root and a lone commit print its hash first.
export function parseFiles(numstat, status) {
  const stats = {};
  for (const entry of numstat.split("\0")) {
    const [a, d, ...parts] = entry.split("\t");
    if (parts.length) stats[parts.join("\t")] = { add: Number(a) || 0, del: Number(d) || 0, binary: a === "-" };
  }
  const s = status.split("\0").filter(Boolean), files = [], seen = new Set();
  for (let i = 0; i < s.length; i++) {
    if (!/^[ACDMRTUX]\d*$/.test(s[i])) continue;
    const path = s[++i];
    if (path === undefined || seen.has(path)) continue;
    seen.add(path);
    const parts = path.split("/"), name = parts.pop();
    files.push({ path, dir: parts.length ? parts.join("/") + "/" : "", name, status: s[i - 1][0], ...(stats[path] ?? { add: 0, del: 0, binary: false }) });
  }
  return files;
}

// One file's `diff-tree -p`: its hunks, cut to what a panel can show.
export function diffLines(stdout, binary) {
  const all = stdout.replace(/\n$/, "").split("\n"), first = all.findIndex((l) => l.startsWith("@@"));
  const lines = first < 0 ? [binary ? "Binary file changed" : "No text diff"] : all.slice(first);
  if (lines.length > MAX_LINES) lines.splice(MAX_LINES, lines.length, `… ${lines.length - MAX_LINES} more lines`);
  return lines.map(line => line.length > 4000 ? line.slice(0, 4000) + "… (line truncated)" : line);
}

// Numbers each diff line once, so a frame only draws the rows on screen.
export function diffRows(lines) {
  let old = 0, next = 0;
  return lines.map((line) => {
    const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
    if (match) { old = +match[1]; next = +match[2]; return { kind: "@", text: line }; }
    const kind = line[0];
    if (kind === "-") return { kind, number: old++, text: line.slice(1) || " " };
    if (kind === "+") return { kind, number: next++, text: line.slice(1) || " " };
    if (kind === " ") { old++; return { kind, number: next++, text: line.slice(1) || " " }; }
    return { kind: "", text: line };
  });
}

// The graph, one row per commit, continuing from `state` so a page loaded later
// joins the lines above it. `lanes[j]` is the commit lane j waits for; a lane's
// color is a number fixed when it starts. Lines are in lane units, y 0 (top),
// 1 (the dot) and 2 (bottom).
export function graph(commits, state) {
  const { lanes, colors } = state, rows = [];
  for (const c of commits) {
    const lines = [];
    let col = lanes.indexOf(c.hash);
    const tip = col < 0;
    if (tip) { col = lanes.indexOf(null); if (col < 0) col = lanes.length; lanes[col] = c.hash; colors[col] = state.next++; }
    // Above the dot: lanes waiting for this commit meet at it, the rest pass by.
    for (let j = 0; j < lanes.length; j++) {
      if (lanes[j] === null) continue;
      if (lanes[j] === c.hash) {
        if (!(tip && j === col)) lines.push({ from: [j, 0], to: [col, 1], color: colors[j] });
        if (j !== col) lanes[j] = null;
      } else lines.push({ from: [j, 0], to: [j, 2], color: colors[j] });
    }
    const color = colors[col], [first, ...rest] = c.parents;
    // Below it: the first parent goes on in this lane, or joins the lane that already waits for it.
    if (first === undefined) lanes[col] = null;
    else {
      const k = lanes.indexOf(first);
      if (k >= 0 && k !== col) { lanes[col] = null; lines.push({ from: [col, 1], to: [k, 2], color: colors[k] }); }
      else { lanes[col] = first; lines.push({ from: [col, 1], to: [col, 2], color }); }
    }
    // A merge's other parents: a lane each, new unless one already waits for it.
    for (const p of rest) {
      let k = lanes.indexOf(p);
      if (k < 0) { k = lanes.indexOf(null); if (k < 0) k = lanes.length; lanes[k] = p; colors[k] = state.next++; }
      lines.push({ from: [col, 1], to: [k, 2], color: colors[k] });
    }
    while (lanes.length && lanes[lanes.length - 1] === null) { lanes.pop(); colors.pop(); }
    let width = col;
    for (const l of lines) width = Math.max(width, l.from[0], l.to[0]);
    rows.push({ col, color, lines, width: width + 1 });
  }
  return rows;
}

// Where a row's dot goes: past MAX_LANES it stays on the last lane, marked.
export const dotLane = (col) => col < MAX_LANES ? { lane: col, over: false } : { lane: MAX_LANES - 1, over: true };

// How many lanes the graph shows, and whether a dot sits past them, over all
// rows so far (`seen` is the answer for the rows before these).
export function graphSpan(rows, seen = { lanes: 1, over: false }) {
  let lanes = seen.lanes, over = seen.over;
  for (const r of rows) { lanes = Math.max(lanes, Math.min(MAX_LANES, r.width)); over = over || r.col >= MAX_LANES; }
  return { lanes, over };
}

// Whether the shown layout shows a block of `mod`: false when every such block
// is hidden (a hidden node above it, or another child of a stack); null when the
// layout has none (a pane or an overlay), which only the app can tell.
export function layoutShows(node, mod) {
  let found = false;
  const walk = (n, visible) => {
    if (!n || typeof n !== "object") return false;
    visible = visible && !n.hidden;
    if (n.content?.mod === mod) { found = true; if (visible) return true; }
    const kids = Array.isArray(n.children) ? n.children : [];
    const active = n.type === "stack" ? (n.active ?? kids[0]?.id) : undefined;
    for (const k of kids) if (walk(k, visible && (active === undefined || k?.id === active))) return true;
    for (const k of Array.isArray(n.floating) ? n.floating : []) if (walk(k, visible)) return true;
    return false;
  };
  return walk(node, true) ? true : found ? false : null;
}
