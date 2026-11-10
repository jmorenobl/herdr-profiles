// The commit history of the focused pane's repo, read-only: a graph of commits
// (the current branch, all branches, or one), and a commit's message, files and
// diffs. A panel of the standard profile, opened with History in the tab bar
// (`standard-tabs`). Its look follows Herdr's Changes.
import { View, div, svg, PathBuilder } from "gpui-kit";
import { v_flex, h_flex, Scrollbar, v_virtual_list } from "gpui-base";
import { spaces, panes, focused, exec, watchFolder, theme, settings, layout } from "herdr";
import { READ, DIFF, PAGE, MAX_FILES, gitVersion, lazyArgs, partialClone, repoPaths, branchRefs, logArgs, parseLog,
  appendPage, parseBody, parseFiles, diffLines, diffRows, graph, dotLane, graphSpan, layoutShows } from "./model.js";

function location() {
  const space = spaces().find((s) => s.active), f = focused();
  const pane = f?.pane ? panes().find(p => p.pane === f.pane) : null;
  const on = f?.pane === null ? (f.terminal?.includes("/") ? f.terminal.split("/")[0] : null) : space?.machine ?? null;
  return { cwd: pane?.cwd || f?.cwd || space?.folder, on };
}
const key = () => JSON.stringify(location());
const ROW = 44, LANE = 12;
const NOT_DOWNLOADED = "Not on this computer: this is a partial clone, and History doesn't download.";

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

// Which commits the list shows, remembered per repo: "current" (HEAD), "all"
// (every branch, remote branch and tag), or one branch's full ref name.
const loadModes = () => { try { return JSON.parse(localStorage.getItem("modes") ?? "{}"); } catch { return {}; } };

export default class History extends View {
  init(_props, cx) {
    this.gen = 0; this.versions = {};
    this.modes = loadModes();
    this.reset();
    this.refresh(cx);
    // Remote spaces have no folder watch; a hidden panel reads nothing, and catches up when shown.
    cx.timer.every(10000, (cx) => { if (this.shown()) this.refresh(cx); else this.stale = true; });
  }

  // Hidden: the panel's column is hidden, or the stack shows another panel.
  shown() { return layoutShows(layout(), "standard-history") !== false; }

  git(args) { return exec("git", [...READ, ...(this.lazy ?? []), ...args], { cwd: this.root, on: this.on }); }

  // A commit moves HEAD and a ref in the repo's git folder (a worktree's refs are
  // in the common one): watch those, not the work tree. Remote spaces fall back to
  // the timer. A loop ends at its next event once another repo is watched.
  watch(dirs, cx) {
    const watching = dirs.join("\n");
    if (this.on || this.watching === watching) return;
    const token = this.watchToken = {};
    this.watching = watching;
    for (const dir of dirs) cx.spawn(async (cx) => {
      try {
        while (this.watchToken === token) {
          await watchFolder(dir);
          if (this.watchToken !== token) break;
          if (this.shown()) this.refresh(cx); else this.stale = true;
        }
      } catch {} // too big to watch: the timer still refreshes
    });
  }

  // Forgets the repo. Work started for it sees `gen` change and drops its result.
  reset() {
    this.gen++;
    this.repo = null; this.root = null; this.on = null; this.lazy = null; this.partial = false;
    this.sig = null; this.branch = ""; this.refs = []; this.setCommits([], false); this.picking = false;
    this.close(); this.error = null; this.moreError = null; this.watching = null; this.watchToken = null;
  }

  setCommits(commits, more) {
    this.commits = commits; this.more = more;
    this.state = { lanes: [], colors: [], next: 0 };
    this.graph = graph(commits, this.state); this.span = graphSpan(this.graph);
  }

  // The chosen mode, if its branch still exists; else the current branch.
  mode(refs = this.refs) {
    const m = this.modes[this.root] ?? "current";
    return m === "current" || m === "all" || refs.some(r => r.ref === m) ? m : "current";
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
      this.gen++; this.close(); this.sig = null; this.setCommits([], false); this.moreError = null;
      this.refresh(cx, true);
    }
    cx.notify();
  }

  // HEAD and the refs: what the list depends on, as one string to compare.
  async tips() {
    const [head, branch, refList] = await Promise.all([
      this.git(["rev-parse", "--verify", "-q", "HEAD"]),
      this.git(["branch", "--show-current"]),
      this.git(["for-each-ref", "--format=%(refname)%09%(objectname)", "refs/heads", "refs/remotes", "refs/tags"]),
    ]);
    const refs = branchRefs(refList.stdout);
    return { head: head.code === 0, branch: branch.stdout.trim() || "detached HEAD", refs, sig: [this.mode(refs), head.stdout, refList.stdout].join("\n") };
  }

  // Reads the first `count` commits again, from scratch.
  async reload(tips, count, gen) {
    this.branch = tips.branch; this.refs = tips.refs;
    if (!tips.head) { this.sig = null; this.setCommits([], false); this.error = "No commits yet"; return; }
    const list = await this.log(0, count);
    if (gen !== this.gen) return;
    this.sig = tips.sig; this.setCommits(list.commits, list.more); this.error = null; this.moreError = null;
    // A commit that left the list (amend, reset, another branch) closes its details.
    if (this.open && !list.commits.some(c => c.hash === this.open.hash)) this.close();
  }

  // Cheap when nothing moved: HEAD and the refs, and the log only when they changed.
  // A new folder in the same repo keeps what's shown; another repo starts over.
  refresh(cx, force = false) {
    // Busy: a forced read follows this one; any other is noted and runs at the next render.
    if (this.loading) { if (force) this.pending = true; else this.stale = true; return; }
    const { cwd, on } = location(), where = key();
    this.where = where; this.stale = false;
    if (!cwd) { if (this.repo || this.error) this.reset(); return; }
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const top = await exec("git", ["rev-parse", "--show-toplevel", "--absolute-git-dir", "--path-format=absolute", "--git-common-dir"], { cwd, on });
        if (key() !== where) return;
        if (top.code !== 0) { this.reset(); this.error = "Not a git repository"; return; }
        const { root, dirs } = repoPaths(top.stdout), repo = JSON.stringify([root, on]);
        // Another repo: start over. It counts as read once git's version and the
        // clone's kind are known (they decide what may be read without downloading).
        if (repo !== this.repo) {
          this.reset(); this.root = root; this.on = on;
          const machine = on ?? "";
          const [version, config] = await Promise.all([
            this.versions[machine] ?? exec("git", ["--version"], { on }).then((r) => (this.versions[machine] = gitVersion(r.stdout))),
            this.git(["config", "--get-regexp", "^(extensions\\.partialclone|remote\\..*\\.promisor)$"]),
          ]);
          if (this.root !== root || this.on !== on || this.repo) return;
          this.lazy = lazyArgs(version); this.partial = partialClone(config.stdout); this.repo = repo;
        }
        this.watch(dirs, cx);
        const gen = this.gen, tips = await this.tips();
        if (gen !== this.gen) return;
        if (tips.sig === this.sig && !force) { this.branch = tips.branch; this.refs = tips.refs; return; }
        await this.reload(tips, Math.max(PAGE, this.commits.length), gen);
      } catch (e) { if (key() === where) this.error = e.message ?? String(e); }
      finally { this.finish(cx); }
    });
  }

  finish(cx) {
    this.loading = false;
    if (this.pending) { this.pending = false; this.refresh(cx, true); }
    cx.notify();
  }

  async log(skip, count) {
    const r = await this.git(logArgs(skip, count, this.revs()));
    if (r.code !== 0) throw new Error(r.stderr.trim());
    return parseLog(r.stdout, count);
  }

  // The next page, read with --skip: only while HEAD and the refs are as the list
  // was read, else the list is read again, a page longer.
  loadMore(cx) {
    if (this.loading || !this.more) return;
    const gen = this.gen;
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const tips = await this.tips();
        if (gen !== this.gen) return;
        if (tips.sig === this.sig) {
          const page = await this.log(this.commits.length, PAGE);
          if (gen !== this.gen) return;
          const commits = appendPage(this.commits, page.commits);
          if (commits) {
            const rows = graph(page.commits, this.state);
            this.commits = commits; this.graph = [...this.graph, ...rows]; this.span = graphSpan(rows, this.span); this.more = page.more;
            this.moreError = null;
            return;
          }
        }
        await this.reload(tips, this.commits.length + PAGE, gen);
        if (gen === this.gen) this.moreError = null;
      } catch (e) { if (gen === this.gen) this.moreError = `Cannot read more history: ${e.message ?? e}`; }
      finally { this.finish(cx); }
    });
    cx.notify();
  }

  // What a commit's diff compares: a merge against its first parent, the first commit against nothing.
  base(commit) { return commit.parents.length ? [commit.parents[0], commit.hash] : ["--root", commit.hash]; }

  // A partial clone with git older than 2.44 can't read a diff without downloading.
  canDiff() { return !this.partial || this.lazy !== null; }
  failure(e) { const text = e.message ?? String(e); return this.partial ? `${NOT_DOWNLOADED} (${text})` : text; }

  pick(commit, cx) {
    this.close(); this.open = commit; this.picking = false;
    cx.spawn(async (cx) => {
      try {
        const diff = this.canDiff();
        const [message, numstat, status] = await Promise.all([
          this.git(["show", "-s", "--format=%b", commit.hash]),
          diff ? this.git(["diff-tree", "-r", "-z", "--numstat", ...DIFF, ...this.base(commit)]) : null,
          diff ? this.git(["diff-tree", "-r", "-z", "--name-status", ...DIFF, ...this.base(commit)]) : null,
        ]);
        if (this.open !== commit) return;
        if (message.code !== 0) throw new Error(message.stderr.trim());
        // The subject is already in the header; the body is what's left.
        this.body = parseBody(message.stdout);
        if (!diff) { this.note = `${NOT_DOWNLOADED} Diffs here need git 2.44 or newer.`; return; }
        if (status.code !== 0) throw new Error(status.stderr.trim());
        // A partial clone may lack a file's contents: list the files anyway, without counts.
        if (numstat.code !== 0 && !this.partial) throw new Error(numstat.stderr.trim());
        const files = parseFiles(numstat.code === 0 ? numstat.stdout : "", status.stdout);
        this.files = files.slice(0, MAX_FILES); this.limited = files.length > MAX_FILES;
        this.byPath = new Map(this.files.map(f => [f.path, f]));
        this.add = 0; this.del = 0;
        for (const f of this.files) { this.add += f.add; this.del += f.del; }
        if (files.length) await this.load(files[0], commit);
      } catch (e) { if (this.open === commit) this.note = `Cannot read this commit: ${this.failure(e)}`; }
      cx.notify();
    });
    cx.notify();
  }

  close() {
    this.open = null; this.files = []; this.byPath = new Map(); this.add = 0; this.del = 0; this.limited = false;
    this.file = null; this.body = []; this.setLines([]); this.note = null;
  }

  async load(file, commit) {
    this.file = file.path;
    const r = await this.git(["diff-tree", "-p", ...DIFF, ...this.base(commit), "--", file.path]);
    if (this.open !== commit || this.file !== file.path) return;
    if (r.code !== 0) throw new Error(r.stderr.trim());
    this.setLines(diffLines(r.stdout, file.binary));
  }

  pickFile(file, cx) {
    const commit = this.open;
    this.setLines([]); this.note = null;
    cx.spawn(async (cx) => {
      try { await this.load(file, commit); }
      catch (e) { if (this.open === commit && this.file === file.path) this.note = `Cannot preview this diff: ${this.failure(e)}`; }
      cx.notify();
    });
    this.file = file.path;
    cx.notify();
  }

  setLines(lines) {
    this.rows = diffRows(lines);
    let longest = 0;
    for (const line of lines) longest = Math.max(longest, line.length);
    this.diffWidth = Math.max(300, longest * 7 + 50);
  }

  chip(ref, t) {
    const color = ref.head ? t.accent : ref.tag ? t.ansi3 : t.muted;
    return div().max_w(120).flex_none().px(5).rounded(4).border_1().border_color(ref.head ? t.accent : t.border).text_size(10).text_color(color).truncate().child(ref.name);
  }

  // One row's slice of the graph: its lines as paths, and the commit's dot
  // (hollow for a merge). Lanes past MAX_LANES are cut off by the cell; a dot
  // past them stays on the last lane, with a mark that it's further right.
  graphCell(row, merge, width, palette, t) {
    const x = (j) => LANE / 2 + j * LANE, y = (v) => v * ROW / 2, paint = (j) => palette[j % palette.length];
    const lines = row.lines.map(({ from, to, color }) => {
      const [x1, y1, x2, y2] = [x(from[0]), y(from[1]), x(to[0]), y(to[1])], mid = (y1 + y2) / 2;
      const path = PathBuilder.stroke(1.5).move_to(x1, y1);
      return window.paint_path((x1 === x2 ? path.line_to(x2, y2) : path.cubic_bezier_to(x2, y2, x1, mid, x2, mid)).build(), paint(color))
        .absolute().top(0).left(0).size_full();
    });
    const { lane, over } = dotLane(row.col), dx = x(lane);
    if (over) {
      const tip = dx + 5;
      lines.push(window.paint_path(PathBuilder.stroke(1.5).move_to(tip, ROW / 2 - 3).line_to(tip + 3, ROW / 2).line_to(tip, ROW / 2 + 3).build(), paint(row.color))
        .absolute().top(0).left(0).size_full());
    }
    const dot = div().absolute().left(dx - 4).top(ROW / 2 - 4).size(8).rounded(4)
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

  fileRow(f, t) {
    return h_flex().id(`file-${f.path}`).h(28).flex_none().px(8).gap(8).items_center().rounded(7).cursor_pointer()
      .when(this.file === f.path, (e) => e.bg(t.selected)).hover((s) => s.bg(t.hover))
      .child(div().w(14).text_size(11).text_color(f.status === "A" ? t.ansi2 : f.status === "D" ? t.ansi1 : t.blocked).child(f.status))
      .child(h_flex().flex_1().min_w(0).child(div().text_color(t.dim).truncate().child(f.dir)).child(div().max_w(260).min_w(0).truncate().child(f.name)))
      .when(f.add > 0, (e) => e.child(div().text_size(11).text_color(t.ansi2).child(`+${f.add}`))).when(f.del > 0, (e) => e.child(div().text_size(11).text_color(t.ansi1).child(`−${f.del}`)));
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
    const width = this.span.lanes * LANE + (this.span.over ? 6 : 0);
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
        .child(this.error || (this.loading ? "Loading history…" : this.root ? "No commits" : "No folder"))))
      .when(Boolean(this.moreError), (e) => e.child(div().absolute().bottom(0).left(0).right(0).px(10).py(8).bg(t.background).text_size(11).text_color(t.ansi1).child(this.moreError)));
  }

  details(t) {
    const c = this.open;
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
        .child(div().flex_1()).child(div().text_color(t.ansi2).child(`+${this.add}`)).child(div().text_color(t.ansi1).child(`−${this.del}`)))
      .child(div().flex_1().min_h(44).max_h(this.files.length * 28 + 12).relative().border_b(1).border_color(t.border)
        // Up to 1,000 files: a virtual list builds only the rows on screen.
        .child(div().absolute().inset_0().p(6).child(v_virtual_list("history-files", this.files.length, 28, (i) => this.files[i].path,
          (range) => this.files.slice(range.start, range.end).map((f) => this.fileRow(f, t)))
          .on_item_click((path, cx) => { const f = this.byPath.get(path); if (f) this.pickFile(f, cx); }).size_full()))
        .when(!this.files.length, (e) => e.child(div().absolute().inset_0().p(14).text_color(t.dim).child(this.note ? "" : "No files changed")))
        .child(Scrollbar.vertical("history-files").viewport_from_layout().absolute().inset_0()))
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
    // Shown again, moved to another folder, or something changed while hidden: read again.
    if ((this.stale || key() !== this.where) && this.shown()) this.refresh(cx);
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
