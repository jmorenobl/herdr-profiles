// The side panel (a layout block): the overview beside the board, the selected idea,
// or a compact list. One per window, it also commits the ideas folder.
// Methods of the Ideas view (main.js), copied onto it: `this` is the view.
import { div } from "gpui-kit";
import { v_flex, h_flex, TextView } from "gpui-base";
import { spaces, run, notify, readTextFile } from "herdr";
import { STATUSES, updateIdea, moveIdea, autocommit, writeBoard, ago, daysSince, tilde, touched, isStale } from "./store.js";
import { STATUS_LABEL, statusColor, dot, chip, button, sectionLabel } from "./ui.js";
import { select, selected, noteMove, ideasSpace, tabFor, workingIn, develop, startProject, agentName, openProject, reveal, revealLabel, boardTab, openBoard } from "./actions.js";

const COMMIT_AFTER = 60000;             // ms of quiet before the side panel commits the folder

export class Side {
  // Commits the folder once it has been quiet for a minute (a Claude session writes in bursts).
  scheduleCommit(cx) {
    if (!this.autocommit) return;
    const n = (this.commitGen = (this.commitGen ?? 0) + 1);
    this.commitPending = true;          // close() commits right away instead of losing it
    cx.timer.after(COMMIT_AFTER, (cx) => {
      if (n !== this.commitGen) return;
      // A commit still running: wait for another quiet minute after it, so nothing is left behind.
      if (this.committing) { this.commitAgain = true; return; }
      cx.spawn(async (cx) => {
        await this.commitNow();
        if (this.commitAgain) { this.commitAgain = false; this.scheduleCommit(cx); }
      });
    });
  }

  async commitNow() {
    this.committing = true;
    this.commitPending = false;
    try { await autocommit(this.folder, this.ideas, this.config.types); this.commitWarned = false; }
    catch (e) {
      if (!this.commitWarned) notify({ title: "Could not commit the ideas folder", body: String(e.message ?? e), level: "warning", timeout: 6000 });
      this.commitWarned = true;
    }
    this.committing = false;
  }

  // The panel goes (the layout switches away, or the app quits): a commit still waiting for
  // its quiet minute is made now, within close()'s short time; one already running goes on.
  async closeSide() {
    if (this.autocommit && this.commitPending && !this.committing && this.folder) await this.commitNow();
  }

  loadCollapsed() {
    try { return new Set(JSON.parse(localStorage.getItem("collapsed") ?? '["parked","dropped"]')); }
    catch { return new Set(["parked", "dropped"]); }
  }

  toggleSection(status, cx) {
    if (this.collapsed.has(status)) this.collapsed.delete(status); else this.collapsed.add(status);
    try { localStorage.setItem("collapsed", JSON.stringify([...this.collapsed])); } catch { /* fine */ }
    cx.notify();
  }

  // ---------- changes ----------

  // One change at a time per idea: a second click before the first lands would work from the
  // old text (or the folder that just moved) and fail.
  busyWith(idea) {
    this.changing ??= new Set();
    if (this.changing.has(idea.id)) return true;
    this.changing.add(idea.id);
    return false;
  }

  setStatus(idea, status, cx) {
    if (idea.status === status || this.busyWith(idea)) return;
    cx.spawn(async (cx) => {
      try { await updateIdea(idea, { status }); }
      catch { notify({ title: "The idea changed on disk", body: "Reloaded it; try again.", level: "warning", timeout: 4000 }); }
      await this.reload(cx);
      this.changing.delete(idea.id);
    });
  }

  setType(idea, type, cx) {
    if (idea.type === type) return;
    // Moving the folder under a terminal working in it (an agent, an editor) would split the
    // idea: whatever it writes next recreates the old folder. Its tab has to go first.
    const tab = workingIn(idea);
    if (tab) {
      const which = !tab.id ? tab.name : tab.named ? `"${tab.name}"` : `Tab ${tab.index}`;
      notify({ title: "Not moving the idea", body: `${which} is working in its folder. Close that tab, then change the type.`, level: "warning", timeout: 6000 });
      return;
    }
    if (this.busyWith(idea)) return;
    cx.spawn(async (cx) => {
      try {
        const id = await moveIdea(this.folder, idea, type, this.config.types);
        if (id !== idea.id) noteMove(idea.id, id);
        select(id);
        this.file = null;               // like every other change of the shown idea
        this.fileText = null;
        const order = Object.fromEntries(Object.entries(this.order).map(([s, ids]) => [s, ids.map((x) => (x === idea.id ? id : x))]));
        if (JSON.stringify(order) !== JSON.stringify(this.order)) {
          try { this.orderText = await writeBoard(this.folder, { order, reviewed: this.reviewed }, this.orderText); } catch { /* order falls back */ }
        }
      }
      catch (e) { notify({ title: "Could not move the idea", body: String(e), level: "error", timeout: 6000 }); }
      await this.reload(cx);
      this.changing.delete(idea.id);
    });
  }

  // The note file shown instead of idea.md belongs to one idea (`fileFor`): selecting another
  // one (here, on the board or by capturing) shows that one's idea.md.
  shownFile(idea) {
    return this.file && this.fileFor === idea.id && idea.files.includes(this.file) ? this.file : null;
  }

  showFile(idea, file, cx) {
    this.file = file;
    this.fileFor = idea.id;
    this.fileText = null;
    if (!file) return cx.notify();
    cx.spawn(async (cx) => { await this.readShownFile(); cx.notify(); });
    cx.notify();
  }

  // (Re)reads the shown note file: on showing it and on every reload, so an agent writing it is followed.
  async readShownFile() {
    const file = this.file, id = this.fileFor;
    const idea = file && this.ideas.find((i) => i.id === id);
    if (!idea || !idea.files.includes(file)) return;
    const text = await readTextFile(`${idea.dir}/${file}`).catch(() => null);
    if (this.file === file && this.fileFor === id) this.fileText = text ?? "Cannot read this file.";
  }

  // The overview's reminder of the weekly review.
  reviewNote(t) {
    const stale = this.ideas.filter(isStale).length;
    const days = daysSince(this.reviewed);
    const last = days === null ? "No review yet." : `Last review ${days <= 0 ? "today" : `${ago(this.reviewed)} ago`}.`;
    const due = this.reviewDue(stale);
    return v_flex().gap(6).child(sectionLabel(t, "WEEKLY REVIEW"))
      .child(div().text_size(12.5).text_color(stale ? t.foreground : t.muted)
        .child(stale ? `${stale} idea${stale > 1 ? "s" : ""} untouched for over a month.` : "Nothing has gone stale."))
      .child(div().text_size(11.5).text_color(due ? t.ansi3 : t.dim).child(due ? `${last} It takes five minutes.` : last))
      .when(stale > 0, (el) => el.child(h_flex().child(button(t, "o-review", `Review ${stale}`, due, () => this.requestReview()))));
  }

  // ---------- side panel ----------

  // Following the shown tab: an agent tab made for an idea selects that idea.
  follow() {
    const space = spaces().find((s) => s.active);
    const tab = space?.tabs.find((x) => x.active);
    if (!tab || tab.id === this.lastTab) return;
    this.lastTab = tab.id;
    const idea = this.ideas.find((i) => tabFor(i, space)?.id === tab.id);
    if (idea && selected() !== idea.id) { select(idea.id); this.file = null; }
  }

  // The ideas space gets a Board tab once, the first time this panel sees it without one.
  ensureBoard() {
    const space = this.folder && ideasSpace(this.folder);
    if (!space || this.boardChecked === space.id) return;
    this.boardChecked = space.id;
    if (!boardTab(space)) {
      openBoard(space);
      this.moveBoardFirst = space.id;
    }
  }

  placeBoard() {
    if (!this.moveBoardFirst) return;
    const space = spaces().find((s) => s.id === this.moveBoardFirst);
    const tab = boardTab(space);
    if (!tab) return;
    this.moveBoardFirst = null;
    if (tab.index !== 1) run("tab.move", { id: tab.id, index: 1 });
  }

  row(t, idea) {
    const isSel = selected() === idea.id;
    return h_flex().id(`row-${idea.id}`).flex_none().h(30).px(8).gap(8).items_center().rounded(7).cursor_pointer()
      .bg(isSel ? t.selected : "#00000000").hover((s) => s.bg(t.hover))
      .on_click((_e, cx) => { select(idea.id); this.file = null; cx.notify(); })
      .child(div().flex_1().min_w(0).truncate().text_size(12.5).child(idea.title))
      .child(h_flex().flex_none().gap(3).text_size(10.5).text_color(t.dim).child(`${this.labelOf(idea.type)} ·`)
        .child(isStale(idea) ? div().text_color(t.ansi3).child(ago(touched(idea))) : ago(touched(idea))));
  }

  list(t) {
    const shown = this.shown();
    const space = this.folder && ideasSpace(this.folder);
    return v_flex().id("side-list").size_full().min_h(0)
      .child(v_flex().flex_none().px(12).pt(12).pb(10).gap(9).border_b(1).border_color(t.border)
        .child(h_flex().items_center().gap(8)
          .child(div().text_size(15).font_semibold().child("Ideas"))
          .child(div().flex_1().text_size(11.5).text_color(t.dim).child(`${this.ideas.length}`))
          .when(Boolean(space), (el) => el.child(button(t, "s-board", "Board", false, () => openBoard(space))))
          .child(button(t, "s-new", "+ New", true, () => run("mod.open", { name: "ideas" }))))
        .child(h_flex().child(this.searchBox(t)))
        .child(this.filters(t)))
      .child(v_flex().id("side-rows").flex_1().min_h(0).overflow_y_scrollbar().px(6).py(6).gap(1)
        .child(this.empty(t, shown) ?? div())
        .children(STATUSES.map((s) => [s, this.sorted(shown.filter((i) => i.status === s), s)]).filter(([, l]) => l.length).map(([s, l]) => {
          const open = !this.collapsed.has(s) || !!this.query;
          return v_flex().id(`side-sec-${s}`).flex_none().gap(1).pb(4)
            .child(h_flex().id(`side-head-${s}`).h(28).px(6).gap(7).items_center().cursor_pointer().rounded(6)
              .hover((x) => x.bg(t.hover)).on_click((_e, cx) => this.toggleSection(s, cx))
              .child(div().w(10).text_size(10).text_color(t.dim).child(open ? "▾" : "▸"))
              .child(dot(statusColor(t, s)))
              .child(div().text_size(11.5).font_semibold().text_color(t.muted).child(STATUS_LABEL[s]))
              .child(div().text_size(11).text_color(t.dim).child(String(l.length))))
            .when(open, (el) => el.children(l.map((i) => this.row(t, i))));
        })));
  }

  detail(t, idea) {
    const space = this.folder && ideasSpace(this.folder);
    const revealText = revealLabel();
    const agent = agentName(this.config.agent, this.config.agentName);
    const files = idea.files.filter((f) => /\.(md|txt)$/i.test(f));
    const others = idea.files.length - files.length;
    const shown = this.shownFile(idea);
    const fileTab = (id, label, file) => div().id(id).px(8).py(3).rounded(6).cursor_pointer().text_size(11.5)
      .bg(shown === file ? t.selected : "#00000000").text_color(shown === file ? t.foreground : t.muted)
      .hover((s) => s.bg(t.hover)).on_click((_e, cx) => this.showFile(idea, file, cx)).child(label);
    const body = shown ? (this.fileText ?? "Loading…") : idea.body;
    return v_flex().id("side-detail").size_full().min_h(0)
      .child(v_flex().flex_none().px(14).pt(12).pb(12).gap(10).border_b(1).border_color(t.border)
        .child(h_flex().gap(8).items_center()
          .child(div().id("d-back").text_size(12).text_color(t.muted).cursor_pointer().hover((s) => s.text_color(t.foreground))
            .on_click((_e, cx) => { select(null); this.file = null; cx.notify(); }).child("← All ideas"))
          .child(div().flex_1())
          .child(div().text_size(11).text_color(t.dim).child(idea.created ? `created ${ago(idea.created)} ago`.replace("today ago", "today") : "")))
        .child(div().text_size(16).font_semibold().child(idea.title))
        .when(Boolean(idea.origin), (el) => el.child(div().text_size(11.5).text_color(t.dim).child(`From ${idea.origin}`)))
        .when(idea.status === "dropped" && Boolean(idea.why), (el) => el.child(div().text_size(12).text_color(t.muted).child(`Dropped: ${idea.why}`)))
        .child(v_flex().gap(6)
          .child(sectionLabel(t, "STATUS"))
          .child(h_flex().gap(5).flex_wrap().children(STATUSES.map((s) =>
            chip(t, `d-st-${s}`, STATUS_LABEL[s], idea.status === s, statusColor(t, s), (_e, cx) => this.setStatus(idea, s, cx))))))
        .child(v_flex().gap(6)
          .child(sectionLabel(t, "TYPE"))
          .child(h_flex().gap(5).flex_wrap().children(this.config.types.map((ty) =>
            chip(t, `d-ty-${ty}`, this.labelOf(ty), idea.type === ty, null, (_e, cx) => this.setType(idea, ty, cx))))))
        .child(h_flex().gap(6).flex_wrap()
          .child(button(t, "d-develop", tabFor(idea, space) ? `Back to ${agent}` : `Develop with ${agent}`, true, () => develop(idea, space, this.config.agent)))
          .when(Boolean(idea.project), (el) => el.child(button(t, "d-project", "Open project", false, () => openProject(idea))))
          .when(!idea.project && idea.status === "ripe", (el) => el.child(button(t, "d-start", "Start project", false, () => startProject(idea, space, this.config.agent, this.config.projectsRoot))))
          .when(Boolean(revealText), (el) => el.child(button(t, "d-reveal", revealText, false, () => reveal(idea)))))
        .when(Boolean(idea.project), (el) => el.child(div().text_size(11.5).text_color(t.dim).truncate().child(`Project: ${tilde(idea.project)}`))))
      .when(files.length > 0 || others > 0, (el) => el.child(h_flex().flex_none().px(10).py(6).gap(4).flex_wrap().border_b(1).border_color(t.border)
        .child(fileTab("d-f-idea", "idea.md", null))
        .children(files.map((f, n) => fileTab(`d-f-${n}`, f, f)))
        .when(others > 0, (el) => el.child(div().px(6).text_size(11).text_color(t.dim).child(`+${others} other`)))))
      .child(div().id("d-body").flex_1().min_h(0).overflow_y_scrollbar().px(14).py(12).text_size(13)
        .child(body ? TextView.markdown(`d-md-${idea.id}-${shown ?? "idea"}`, body).selectable(true)
          : div().text_color(t.dim).child(`No notes yet. Develop it with ${agent}, or write in idea.md.`)));
  }

  overview(t) {
    const count = (f) => this.ideas.filter(f).length;
    const recent = this.ideas.slice(0, 8);
    const stat = (id, label, n, color) => h_flex().id(id).h(26).gap(8).items_center()
      .when(Boolean(color), (el) => el.child(dot(color)))
      .child(div().flex_1().text_size(12.5).child(label))
      .child(div().text_size(12).text_color(t.muted).child(String(n)));
    return v_flex().id("side-overview").size_full().min_h(0)
      .child(h_flex().flex_none().px(14).pt(12).pb(10).items_center().border_b(1).border_color(t.border)
        .child(div().flex_1().text_size(15).font_semibold().child("Overview"))
        .child(button(t, "o-new", "+ New", true, () => run("mod.open", { name: "ideas" }))))
      .child(v_flex().id("o-body").flex_1().min_h(0).overflow_y_scrollbar().px(14).py(12).gap(16)
        .child(div().text_size(12).text_color(t.dim).child("Select an idea on the board to see it here. Drag cards between columns to change their status."))
        .child(this.reviewNote(t))
        .child(v_flex().gap(2).child(sectionLabel(t, "BY STATUS"))
          .children(STATUSES.map((s) => stat(`o-s-${s}`, STATUS_LABEL[s], count((i) => i.status === s), statusColor(t, s)))))
        .child(v_flex().gap(2).child(sectionLabel(t, "BY TYPE"))
          .children(this.config.types.map((ty) => stat(`o-t-${ty}`, this.labelOf(ty), count((i) => i.type === ty), null))))
        .when(recent.length > 0, (el) => el.child(v_flex().gap(1).child(sectionLabel(t, "RECENTLY TOUCHED"))
          .children(recent.map((i) => this.row(t, i))))));
  }

  side(t) {
    this.ensureBoard();
    this.placeBoard();
    this.follow();
    const idea = this.ideas.find((i) => i.id === selected());
    if (this.file && this.fileFor !== idea?.id) { this.file = null; this.fileText = null; }
    const space = this.folder && ideasSpace(this.folder);
    const onBoard = !!space && boardTab(space)?.active;
    if (!idea && onBoard) return v_flex().id("ideas-side").size_full().min_h(0).rounded(10).overflow_hidden().bg(t.surface)
      .border_1().border_color(t.border).text_color(t.foreground).text_size(13).child(this.overview(t));
    return v_flex().id("ideas-side").size_full().min_h(0).rounded(10).overflow_hidden().bg(t.surface)
      .border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .child(idea ? this.detail(t, idea) : this.list(t));
  }
}
