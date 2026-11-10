// The commit history of the focused pane's repo, read-only: a graph of commits
// (the current branch, all branches, or one), and a commit's message, files and
// diffs. A panel of the standard profile, opened with History in the tab bar
// (`standard-tabs`). Its look follows Herdr's Changes.
import { View, div, svg, PathBuilder } from "gpui-kit";
import { v_flex, h_flex, Scrollbar, v_virtual_list } from "gpui-base";
import { spaces, panes, focused, exec, watchFolder, theme, settings } from "herdr";

function location() {
  const space = spaces().find((s) => s.active), f = focused();
  const pane = f?.pane ? panes().find(p => p.pane === f.pane) : null;
  const on = f?.pane === null ? (f.terminal?.includes("/") ? f.terminal.split("/")[0] : null) : space?.machine ?? null;
  return { cwd: pane?.cwd || f?.cwd || space?.folder, on };
}
const key = () => JSON.stringify(location());
// Reads write nothing under .git (no index refresh or lock, no fsmonitor cookie):
// the folder watch would see it, and every refresh would start the next one.
const READ = ["--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "diff.autoRefreshIndex=false"];
const DIFF = ["--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"];
const PAGE = 300, ROW = 44, MAX_LINES = 1500;
const LANE = 12, MAX_LANES = 10;
const US = "\x1f";

function ago(seconds) {
  const s = Date.now() / 1000 - seconds;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`;
  if (s < 35 * 86400) return `${Math.floor(s / (7 * 86400))}w`;
  const d = new Date(seconds * 1000), months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[d.getMonth()]} ${d.getDate()}${d.getFullYear() === new Date().getFullYear() ? "" : `, ${d.getFullYear()}`}`;
}
const dateTime = (seconds) => new Date(seconds * 1000).toLocaleString();

// "HEAD -> main, origin/main, tag: v1" as short chips: the branch HEAD is on first.
function refs(text) {
  return text.split(", ").filter(Boolean).filter(r => r !== "HEAD" && !r.endsWith("/HEAD"))
    .map(r => r.startsWith("HEAD -> ") ? { name: r.slice(8), head: true } : r.startsWith("tag: ") ? { name: r.slice(5), tag: true } : { name: r });
}

// The graph, one row per commit, continuing from `state` so a page loaded later
// joins the lines above it. `lanes[j]` is the commit lane j waits for; a lane's
// color is a number fixed when it starts. Lines are in lane units, y 0 (top),
// 1 (the dot) and 2 (bottom).
function graph(commits, state) {
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
    const width = Math.max(col, ...lines.flatMap(l => [l.from[0], l.to[0]])) + 1;
    rows.push({ col, color, lines, width });
  }
  return rows;
}

// Numbers each diff line once, so a frame only draws the rows on screen.
function diffRows(lines) {
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

// Which commits the list shows, remembered per repo: "current" (HEAD), "all"
// (every branch, remote branch and tag), or one branch's full ref name.
const loadModes = () => { try { return JSON.parse(localStorage.getItem("modes") ?? "{}"); } catch { return {}; } };

export default class History extends View {
  init(_props, cx) {
    this.commits = []; this.graph = []; this.rows = []; this.diffWidth = 0; this.files = []; this.refs = [];
    this.modes = loadModes();
    this.refresh(cx);
    cx.timer.every(10000, (cx) => this.refresh(cx));
  }

  git(args) { return exec("git", [...READ, ...args], { cwd: this.root, on: this.on }); }

  // A commit moves HEAD and a ref in the repo's git folder: watch that folder,
  // not the work tree. Remote spaces fall back to the timer.
  watch(gitDir, cx) {
    if (this.on || this.watched === gitDir) return;
    this.watched = gitDir;
    cx.spawn(async (cx) => {
      try {
        while (this.watched === gitDir) {
          await watchFolder(gitDir);
          if (this.watched === gitDir) this.refresh(cx);
        }
      } catch { this.watched = null; }
    });
  }

  reset() {
    this.root = null; this.on = null; this.sig = null; this.branch = ""; this.refs = []; this.commits = []; this.graph = []; this.more = false;
    this.open = null; this.files = []; this.file = null; this.setLines([]); this.error = null; this.note = null; this.watched = null; this.picking = false;
  }

  // The chosen mode, if its branch still exists; else the current branch.
  mode() {
    const m = this.modes[this.root] ?? "current";
    return m === "current" || m === "all" || this.refs.some(r => r.ref === m) ? m : "current";
  }

  revs() {
    const m = this.mode();
    return m === "current" ? ["HEAD"] : m === "all" ? ["--branches", "--remotes", "--tags", "HEAD"] : [m];
  }

  choose(mode, cx) {
    this.picking = false;
    if (mode !== this.mode()) {
      this.modes[this.root] = mode;
      try { localStorage.setItem("modes", JSON.stringify(this.modes)); } catch {}
      this.close(); this.commits = []; this.graph = []; this.more = false;
      this.refresh(cx, true);
    }
    cx.notify();
  }

  // Cheap when nothing moved: HEAD and the refs, and the log only when they changed.
  refresh(cx, force = false) {
    if (this.loading) { if (force) this.pending = true; return; }
    const { cwd, on } = location(), context = key();
    if (context !== this.context) { this.context = context; this.reset(); }
    if (!cwd) return;
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const top = await exec("git", ["rev-parse", "--show-toplevel", "--absolute-git-dir"], { cwd, on });
        if (key() !== context) return;
        if (top.code !== 0) { this.reset(); this.error = "Not a git repository"; return; }
        const [root, gitDir] = top.stdout.trim().split("\n");
        this.root = root; this.on = on;
        this.watch(gitDir, cx);
        const [head, branch, refList] = await Promise.all([
          this.git(["rev-parse", "--verify", "-q", "HEAD"]),
          this.git(["branch", "--show-current"]),
          this.git(["for-each-ref", "--format=%(refname)%09%(objectname)", "refs/heads", "refs/remotes", "refs/tags"]),
        ]);
        if (key() !== context) return;
        this.branch = branch.stdout.trim() || "detached HEAD";
        this.refs = refList.stdout.split("\n").filter(Boolean).map(l => l.split("\t")[0])
          .filter(ref => (ref.startsWith("refs/heads/") || ref.startsWith("refs/remotes/")) && !ref.endsWith("/HEAD"))
          .map(ref => ({ ref, name: ref.replace(/^refs\/(heads|remotes)\//, ""), remote: ref.startsWith("refs/remotes/") }));
        if (head.code !== 0) { this.sig = null; this.commits = []; this.graph = []; this.more = false; this.error = "No commits yet"; return; }
        const sig = [this.mode(), head.stdout, refList.stdout].join("\n");
        if (sig === this.sig && !force) return;
        const list = await this.log(0, Math.max(PAGE, this.commits.length));
        if (key() !== context) return;
        this.sig = sig; this.state = { lanes: [], colors: [], next: 0 };
        this.commits = list.commits; this.graph = graph(list.commits, this.state); this.more = list.more; this.error = null;
        // A commit that left the list (amend, reset, another branch) closes its details.
        if (this.open && !list.commits.some(c => c.hash === this.open.hash)) this.close();
      } catch (e) { if (key() === context) this.error = String(e); }
      finally {
        this.loading = false;
        if (this.pending) { this.pending = false; this.refresh(cx, true); }
        cx.notify();
      }
    });
  }

  async log(skip, count) {
    const r = await this.git(["log", "-z", `--skip=${skip}`, "-n", String(count + 1), "--date-order",
      `--format=%H${US}%h${US}%P${US}%an${US}%at${US}%D${US}%s`, ...this.revs(), "--"]);
    if (r.code !== 0) throw new Error(r.stderr.trim());
    const commits = r.stdout.split("\0").filter(Boolean).map((entry) => {
      const [hash, short, parents, author, time, decoration, subject] = entry.replace(/^\n/, "").split(US);
      return { hash, short, parents: parents ? parents.split(" ") : [], author, time: Number(time), refs: refs(decoration ?? ""), subject: subject ?? "" };
    });
    return { commits: commits.slice(0, count), more: commits.length > count };
  }

  loadMore(cx) {
    if (this.loading || !this.more) return;
    const context = this.context, sig = this.sig;
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const list = await this.log(this.commits.length, PAGE);
        if (key() !== context || this.sig !== sig) return;
        this.commits = [...this.commits, ...list.commits]; this.graph = [...this.graph, ...graph(list.commits, this.state)]; this.more = list.more;
      } catch (e) { if (key() === context) this.note = `Cannot read more history: ${e}`; }
      finally { this.loading = false; cx.notify(); }
    });
    cx.notify();
  }

  // What a commit's diff compares: a merge against its first parent, the first commit against nothing.
  base(commit) { return commit.parents.length ? [commit.parents[0], commit.hash] : ["--root", commit.hash]; }

  pick(commit, cx) {
    this.open = commit; this.body = []; this.files = []; this.file = null; this.setLines([]); this.note = null; this.picking = false;
    const context = this.context;
    cx.spawn(async (cx) => {
      try {
        const [message, numstat, status] = await Promise.all([
          this.git(["show", "-s", "--format=%B", commit.hash]),
          this.git(["diff-tree", "-r", "-z", "--numstat", ...DIFF, ...this.base(commit)]),
          this.git(["diff-tree", "-r", "-z", "--name-status", ...DIFF, ...this.base(commit)]),
        ]);
        if (key() !== context || this.open !== commit) return;
        for (const r of [message, numstat, status]) if (r.code !== 0) throw new Error(r.stderr.trim());
        // The subject is already in the header; the body is what's left.
        this.body = message.stdout.replace(/\s+$/, "").split("\n").slice(1).join("\n").replace(/^\n+/, "").split("\n").filter((l, i, all) => l || all.length > 1);
        const stats = {};
        // With -z, --root and a lone commit print its hash first.
        for (const entry of numstat.stdout.split("\0")) {
          const [a, d, ...parts] = entry.split("\t");
          if (parts.length) stats[parts.join("\t")] = { add: Number(a) || 0, del: Number(d) || 0, binary: a === "-" };
        }
        const s = status.stdout.split("\0").filter(Boolean), files = [];
        for (let i = 0; i < s.length; i++) {
          if (!/^[ACDMRTUX]\d*$/.test(s[i])) continue;
          const path = s[++i];
          if (path !== undefined) files.push({ path, status: s[i - 1][0], ...(stats[path] ?? { add: 0, del: 0 }) });
        }
        this.files = files.slice(0, 1000); this.limited = files.length > 1000;
        if (files.length) await this.load(files[0], context, commit);
      } catch (e) { if (key() === context && this.open === commit) this.note = `Cannot read this commit: ${e}`; }
      cx.notify();
    });
    cx.notify();
  }

  close() { this.open = null; this.files = []; this.file = null; this.body = []; this.setLines([]); this.note = null; }

  async load(file, context, commit) {
    this.file = file.path;
    const r = await this.git(["diff-tree", "-p", ...DIFF, ...this.base(commit), "--", file.path]);
    if (key() !== context || this.open !== commit || this.file !== file.path) return;
    if (r.code !== 0) throw new Error(r.stderr.trim());
    const all = r.stdout.replace(/\n$/, "").split("\n"), first = all.findIndex((l) => l.startsWith("@@"));
    const lines = first < 0 ? [file.binary ? "Binary file changed" : "No text diff"] : all.slice(first);
    if (lines.length > MAX_LINES) lines.splice(MAX_LINES, lines.length, `… ${lines.length - MAX_LINES} more lines`);
    this.setLines(lines.map(line => line.length > 4000 ? line.slice(0, 4000) + "… (line truncated)" : line));
  }

  pickFile(file, cx) {
    const context = this.context, commit = this.open;
    this.setLines([]);
    cx.spawn(async (cx) => {
      try { await this.load(file, context, commit); }
      catch (e) { if (key() === context && this.open === commit) this.note = `Cannot preview this diff: ${e}`; }
      cx.notify();
    });
    this.file = file.path;
    cx.notify();
  }

  setLines(lines) {
    this.rows = diffRows(lines);
    this.diffWidth = Math.max(300, ...lines.map(line => line.length * 7 + 50));
  }

  chip(ref, t) {
    const color = ref.head ? t.accent : ref.tag ? t.ansi3 : t.muted;
    return div().max_w(120).flex_none().px(5).rounded(4).border_1().border_color(ref.head ? t.accent : t.border).text_size(10).text_color(color).truncate().child(ref.name);
  }

  // One row's slice of the graph: its lines as paths, and the commit's dot
  // (hollow for a merge). Lanes past MAX_LANES are cut off by the cell.
  graphCell(row, merge, width, palette, t) {
    const x = (j) => LANE / 2 + j * LANE, y = (v) => v * ROW / 2, paint = (j) => palette[j % palette.length];
    const lines = row.lines.map(({ from, to, color }) => {
      const [x1, y1, x2, y2] = [x(from[0]), y(from[1]), x(to[0]), y(to[1])], mid = (y1 + y2) / 2;
      const path = PathBuilder.stroke(1.5).move_to(x1, y1);
      return window.paint_path((x1 === x2 ? path.line_to(x2, y2) : path.cubic_bezier_to(x2, y2, x1, mid, x2, mid)).build(), paint(color))
        .absolute().top(0).left(0).size_full();
    });
    const dot = div().absolute().left(x(row.col) - 4).top(ROW / 2 - 4).size(8).rounded(4)
      .when(merge, (e) => e.bg(t.background).border_2().border_color(paint(row.color)))
      .when(!merge, (e) => e.bg(paint(row.color)));
    return div().relative().w(width).h(ROW).flex_none().overflow_hidden().children(lines).child(dot);
  }

  commitRow(c, row, width, palette, t) {
    return h_flex().id(`commit-${c.hash}`).h(ROW).flex_none().pr(8).gap(4).rounded(7).cursor_pointer().hover((s) => s.bg(t.hover))
      .child(this.graphCell(row, c.parents.length > 1, width, palette, t))
      .child(v_flex().flex_1().min_w(0).justify_center().gap(2)
        .child(h_flex().gap(6).min_w(0).items_center()
          .children(c.refs.slice(0, 2).map(r => this.chip(r, t)))
          .child(div().flex_1().min_w(0).truncate().child(c.subject || "(no message)")))
        .child(h_flex().gap(6).min_w(0).text_size(11).text_color(t.dim)
          .child(div().flex_none().font_family(settings().font_family ?? "JetBrains Mono").child(c.short))
          .child(div().flex_1().min_w(0).truncate().child(c.author))
          .child(div().flex_none().child(ago(c.time)))));
  }

  diffRow({ kind, number, text }, t) {
    if (kind === "@") return div().w_full().px(12).h(20).flex_none().truncate().bg(t.raised).text_color(t.dim).child(text);
    return h_flex().w_full().h(20).flex_none().gap(10).when(kind === "+", (e) => e.bg(t.ansi2 + "18")).when(kind === "-", (e) => e.bg(t.ansi1 + "18"))
      .child(div().w(30).flex_none().text_right().text_color(t.dim).child(number === undefined ? "" : String(number)))
      .child(div().flex_1().min_w(0).truncate().child(text));
  }

  list(t) {
    const count = this.commits.length + (this.more ? 1 : 0);
    const palette = [t.accent, t.ansi4, t.ansi2, t.ansi5, t.ansi3, t.ansi6, t.ansi1];
    const width = Math.min(MAX_LANES, Math.max(1, ...this.graph.map(r => r.width))) * LANE;
    return div().flex_1().min_h(0).relative()
      .child(div().size_full().px(6).child(v_virtual_list("history-list", count, ROW, (i) => this.commits[i]?.hash ?? "more",
        (range) => {
          const rows = [];
          for (let i = range.start; i < range.end; i++) {
            const c = this.commits[i];
            rows.push(c ? this.commitRow(c, this.graph[i], width, palette, t) : h_flex().id("history-more").h(ROW).flex_none().justify_center().items_center().rounded(7).cursor_pointer()
              .text_size(12).text_color(t.muted).hover((s) => s.bg(t.hover))
              .child(this.loading ? "Loading…" : `Show ${PAGE} more`));
          }
          return rows;
        // Rows of a virtual list can't carry handlers: the list reports which one was clicked.
        }).on_item_click((hash, cx) => {
          const c = this.commits.find(c => c.hash === hash);
          if (c) this.pick(c, cx); else this.loadMore(cx);
        }).size_full()))
      .child(Scrollbar.vertical("history-list").viewport_from_layout().absolute().inset_0())
      .when(!this.commits.length, (e) => e.child(div().absolute().top(6).px(14).py(8).text_color(t.dim)
        .child(this.error || (this.loading ? "Loading history…" : this.root ? "No commits" : "No folder"))));
  }

  details(t) {
    const c = this.open, add = this.files.reduce((n, f) => n + f.add, 0), del = this.files.reduce((n, f) => n + f.del, 0);
    const mono = settings().font_family ?? "JetBrains Mono";
    return v_flex().flex_1().min_h(0)
      .child(v_flex().flex_none().px(14).py(10).gap(4).border_b(1).border_color(t.border)
        .child(div().font_semibold().child(c.subject || "(no message)"))
        .when(this.body.length > 0, (e) => e.child(div().relative().max_h(112).flex().flex_col()
          .child(v_flex().id("history-body").max_h(112).overflow_y_scroll().pr(8).text_size(12).text_color(t.muted)
            .children(this.body.slice(0, 200).map((line, i) => div().id(`body-${i}`).min_h(16).child(line))))
          .child(Scrollbar.vertical("history-body").absolute().inset_0())))
        .child(h_flex().gap(6).flex_wrap().text_size(11).text_color(t.dim)
          .child(div().font_family(mono).child(c.short)).child(div().child(c.author)).child(div().child(dateTime(c.time)))
          .when(c.parents.length > 1, (e) => e.child(div().child(`merge · diff against ${c.parents[0].slice(0, 7)}`))))
        .when(c.refs.length > 0, (e) => e.child(h_flex().gap(4).flex_wrap().children(c.refs.map(r => this.chip(r, t))))))
      .child(h_flex().h(30).flex_none().px(14).gap(8).items_center().border_b(1).border_color(t.border).text_size(11)
        .child(div().text_color(t.muted).child(`${this.files.length} files`))
        .child(div().flex_1()).child(div().text_color(t.ansi2).child(`+${add}`)).child(div().text_color(t.ansi1).child(`−${del}`)))
      .child(div().flex_1().min_h(44).max_h(this.files.length * 28 + 12).relative().border_b(1).border_color(t.border)
        .child(v_flex().id("history-files").absolute().inset_0().overflow_y_scroll().p(6).children(this.files.map((f) => {
          const parts = f.path.split("/"), name = parts.pop();
          return h_flex().id(`file-${f.path}`).h(28).flex_none().px(8).gap(8).items_center().rounded(7).cursor_pointer()
            .when(this.file === f.path, (e) => e.bg(t.selected)).hover((s) => s.bg(t.hover)).on_click((_e, cx) => this.pickFile(f, cx))
            .child(div().w(14).text_size(11).text_color(f.status === "A" ? t.ansi2 : f.status === "D" ? t.ansi1 : t.blocked).child(f.status))
            .child(h_flex().flex_1().min_w(0).child(div().text_color(t.dim).truncate().child(parts.length ? parts.join("/") + "/" : "")).child(div().max_w(260).min_w(0).truncate().child(name)))
            .when(f.add > 0, (e) => e.child(div().text_size(11).text_color(t.ansi2).child(`+${f.add}`))).when(f.del > 0, (e) => e.child(div().text_size(11).text_color(t.ansi1).child(`−${f.del}`)));
        })).when(!this.files.length, (e) => e.child(div().p(8).text_color(t.dim).child(this.note ? "" : "No files changed"))))
        .child(Scrollbar.vertical("history-files").absolute().inset_0()))
      .when(this.limited, (e) => e.child(div().px(12).py(4).text_size(11).text_color(t.dim).child("Showing the first 1,000 files")))
      .child(div().flex_1().flex_grow(2).min_h(0).relative().font_family(mono).text_size(11)
        .child(div().id("history-diff-x").size_full().overflow_x_scrollbar()
          .child(div().w_full().min_w(this.diffWidth).h_full().child(v_virtual_list("history-diff", this.rows.length, 20, (i) => String(i),
            (range) => this.rows.slice(range.start, range.end).map((row) => this.diffRow(row, t))).size_full())))
        .child(Scrollbar.vertical("history-diff").viewport_from_layout().absolute().inset_0()));
  }

  // The header's branch button: what the list shows.
  modeLabel() {
    const m = this.mode();
    return m === "current" ? this.branch : m === "all" ? "All branches" : this.refs.find(r => r.ref === m)?.name ?? m;
  }

  // The branch menu, over the list under the header. A press outside closes it;
  // the header button ignores the press that just closed it.
  picker(t) {
    const m = this.mode();
    const item = (id, label, mode, hint) => h_flex().id(id).h(28).flex_none().px(8).gap(8).items_center().rounded(6).cursor_pointer()
      .bg(m === mode ? t.selected : t.background).hover((s) => s.bg(t.hover)).on_click((_e, cx) => this.choose(mode, cx))
      .child(div().flex_1().min_w(0).truncate().child(label))
      .when(Boolean(hint), (e) => e.child(div().flex_none().text_size(11).text_color(t.dim).child(hint)));
    const section = (label) => div().px(8).pt(8).pb(2).text_size(10).text_color(t.dim).child(label);
    const local = this.refs.filter(r => !r.remote), remote = this.refs.filter(r => r.remote);
    return v_flex().absolute().top(46).right(8).w(260).max_h(360).rounded(8).border_1().border_color(t.border).bg(t.background).shadow_lg().overflow_hidden()
      .on_mouse_down_out((_e, cx) => { this.picking = false; this.closedAt = Date.now(); cx.notify(); })
      .child(v_flex().id("history-branches").max_h(360).overflow_y_scroll().p(4)
        .child(item("mode-current", "Current branch", "current", this.branch))
        .child(item("mode-all", "All branches", "all", `${this.refs.length}`))
        .when(local.length > 0, (e) => e.child(section("Local")).children(local.map(r => item(`mode-${r.ref}`, r.name, r.ref, r.name === this.branch ? "HEAD" : ""))))
        .when(remote.length > 0, (e) => e.child(section("Remote")).children(remote.map(r => item(`mode-${r.ref}`, r.name, r.ref, "")))));
  }

  render(cx) {
    if (key() !== this.context) this.refresh(cx);
    const t = theme();
    const header = h_flex().h(42).flex_none().px(14).gap(8).items_center().border_b(1).border_color(t.border);
    const mode = this.mode();
    return v_flex().id("history").relative().size_full().min_h(0).rounded(10).overflow_hidden().bg(t.background).border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .child(this.open
        ? header.pl(8)
          .child(h_flex().id("history-back").h(26).px(6).gap(4).items_center().rounded(6).cursor_pointer().text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground))
            .on_click((_e, cx) => { this.close(); cx.notify(); }).child(svg("mods/standard-history/back.svg").size(14)).child("History"))
          .child(div().flex_1())
          .child(div().text_size(11).text_color(t.dim).font_family(settings().font_family ?? "JetBrains Mono").child(this.open.short))
        : header
          .child(div().font_semibold().child("History"))
          .when(this.commits.length > 0, (e) => e.child(div().px(5).py(1).rounded(4).border_1().border_color(t.border).text_size(10).text_color(t.muted)
            .child(`${this.commits.length}${this.more ? "+" : ""} commits`)))
          .child(div().flex_1())
          .when(Boolean(this.root && this.branch), (e) => e.child(h_flex().id("history-mode").h(26).px(6).gap(5).min_w(0).items_center().rounded(6).cursor_pointer()
            .text_size(11).text_color(mode === "current" ? t.muted : t.foreground).bg(this.picking ? t.selected : t.background).hover((s) => s.bg(t.hover))
            .on_click((_e, cx) => {
              if (!this.picking && Date.now() - (this.closedAt ?? 0) < 300) return;
              this.picking = !this.picking; cx.notify();
            })
            .child(svg("mods/standard-history/history.svg").size(12).flex_none())
            .child(div().max_w(150).truncate().child(this.modeLabel()))
            .child(svg("mods/standard-history/down.svg").size(11).flex_none().text_color(t.dim)))))
      .child(this.open ? this.details(t) : this.list(t))
      .when(Boolean(this.note), (e) => e.child(div().px(10).py(8).text_size(11).text_color(t.ansi1).child(this.note)))
      .when(this.picking && !this.open, (e) => e.child(this.picker(t)));
  }
}
