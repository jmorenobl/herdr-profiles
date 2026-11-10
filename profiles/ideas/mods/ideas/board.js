// The kanban board (a tab pane with { view: "board" }): columns by status, drag and drop, sorting.
// The weekly review it switches to is in review.js.
// Methods of the Ideas view (main.js), copied onto it: `this` is the view.
import { div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { run, notify, shared, setShared } from "herdr";
import { STATUSES, OPEN, updateIdea, writeBoard, isStale } from "./store.js";
import { STATUS_LABEL, statusColor, dot, chip, button } from "./ui.js";
import { select, selected } from "./actions.js";
import { sortMode, REVIEW } from "./common.js";

const SORTS = [["manual", "Manual"], ["recent", "Recent"], ["az", "A–Z"]];

export class Board {
  // Saves the order; `then` (the status change of a drop) runs only if that worked,
  // so a failed drop changes nothing, as its "try again" says.
  saveOrder(order, cx, then) {
    this.order = order;
    cx.spawn(async (cx) => {
      let saved = false;
      try { this.orderText = await writeBoard(this.folder, { order, reviewed: this.reviewed }, this.orderText); saved = true; }
      catch { notify({ title: "The board order changed on disk", body: "Reloaded it; try again.", level: "warning", timeout: 4000 }); }
      if (saved && then) await then();
      await this.reload(cx);
    });
  }

  // Forgets the drag: the card and the pointer. Not `over`: that's the column under the
  // pointer, kept right by its on_hover (enter/exit only), and still true after a drop.
  clearDrag() {
    this.drag = null;
    this.moved = false;
    this.pointer = null;
    this.overCard = null;
  }

  // Drops the dragged idea into `status`, before or after the card under the pointer.
  drop(status, cx) {
    const idea = this.drag && this.moved && this.ideas.find((i) => i.id === this.drag);
    const target = this.overCard, after = this.after;
    this.clearDrag();
    if (!idea || target === idea.id) return cx.notify();
    const order = {};
    for (const s of STATUSES) order[s] = this.sorted(this.ideas.filter((i) => i.status === s && i.id !== idea.id), s).map((i) => i.id);
    const col = order[status];
    let at = col.length;
    if (target && !target.startsWith("end:")) { const k = col.indexOf(target); if (k >= 0) at = after ? k + 1 : k; }
    col.splice(at, 0, idea.id);
    for (const s of STATUSES) order[s].push(...this.hiddenOrder(s));
    if (sortMode() !== "manual") setShared("ideas.sort", "manual");
    const moved = idea.status !== status;
    if (moved) this.ideas = this.ideas.map((i) => (i.id === idea.id ? { ...i, status } : i));
    this.saveOrder(order, cx, moved ? async () => {
      try { await updateIdea(idea, { status }); }
      catch { notify({ title: "The idea changed on disk", body: "Reloaded it; try again.", level: "warning", timeout: 4000 }); }
    } : null);
    cx.notify();
  }

  // ---------- board (kanban tab) ----------

  sortChips(t) {
    const mode = sortMode();
    return h_flex().flex_none().h(26).p(2).gap(2).items_center().rounded(8).bg(t.canvas)
      .children(SORTS.map(([key, label]) => div().id(`sort-${key}`).px(8).py(2).rounded(6).cursor_pointer().text_size(11.5)
        .bg(mode === key ? t.background : "#00000000").text_color(mode === key ? t.foreground : t.muted)
        .hover((s) => s.text_color(t.foreground))
        .on_click(() => setShared("ideas.sort", key)).child(label)));
  }

  cardContent(t, idea, el) {
    return el
      .child(div().text_size(13).font_medium().child(idea.title))
      .when(idea.tags.length > 0, (el) => el.child(div().text_size(11).text_color(t.accent).truncate().child(idea.tags.map((x) => `#${x}`).join(" "))))
      .child(this.meta(t, idea));
  }

  card(t, idea) {
    const isSel = selected() === idea.id;
    // While it's dragged, the card stays in place as a faint slot; a copy follows the pointer.
    if (this.drag === idea.id && this.moved) {
      return this.cardContent(t, idea, v_flex().id(`card-${idea.id}`).flex_none().p(10).gap(5).rounded(9)
        .border_1().border_color(t.input).bg(t.canvas).opacity(0.35));
    }
    return this.cardContent(t, idea, v_flex().id(`card-${idea.id}`).flex_none().p(10).gap(5).rounded(9).bg(t.background)
      .border_1().border_color(isSel ? t.accent : t.border).cursor_grab()
      .when(isStale(idea) && !isSel, (el) => el.opacity(0.6))
      .hover((s) => s.border_color(isSel ? t.accent : t.input).bg(t.raised))
      .on_mouse_down("left", (e, cx) => {
        this.drag = idea.id;
        this.moved = false;
        this.pressedAt = e.position;
        this.grab = e.local_position ?? { x: 24, y: 14 };
        this.ghostWidth = e.bounds?.width ?? 240;
      })
      .on_mouse_move((e, cx) => {
        if (!(this.drag && this.moved)) return;
        const after = e.local_position.y > e.bounds.height / 2;
        if (this.overCard !== idea.id || this.after !== after) { this.overCard = idea.id; this.after = after; cx.notify(); }
      })
      .on_click((_e, cx) => { select(idea.id); this.file = null; cx.notify(); }));
  }

  // Where the dragged card would land.
  slot(t) {
    return div().flex_none().h(3).mx(2).rounded(2).bg(t.accent);
  }

  // The copy under the pointer while a card is dragged.
  ghost(t) {
    const idea = this.drag && this.moved && this.pointer && this.ideas.find((i) => i.id === this.drag);
    if (!idea) return null;
    return this.cardContent(t, idea, v_flex().id("ghost").absolute()
      .left(this.pointer.x - this.grab.x).top(this.pointer.y - this.grab.y).w(this.ghostWidth)
      .p(10).gap(5).rounded(9).bg(t.popover).border_1().border_color(t.accent).shadow_lg().opacity(0.96));
  }

  // Dragging starts once the pointer has moved a few pixels, so a click stays a click.
  dragMove(e, cx) {
    if (!this.drag) return;
    this.pointer = e.local_position;
    if (!this.moved) {
      const dx = e.position.x - (this.pressedAt?.x ?? e.position.x), dy = e.position.y - (this.pressedAt?.y ?? e.position.y);
      if (dx * dx + dy * dy < 16) return;
      this.moved = true;
    }
    cx.notify();
  }

  endDrag(cx) {
    if (!this.drag) return;
    cx.timer.after(1, (cx) => { this.clearDrag(); cx.notify(); });
  }

  column(t, status, ideas) {
    const target = this.drag && this.moved && this.over === status;
    return v_flex().id(`col-${status}`).flex_1().min_w(0).h_full().rounded(10)
      .bg(target ? t.selected : t.canvas).border_1().border_color(target ? t.accent : "#00000000")
      .on_hover((h, cx) => {
        if (h) this.over = status;
        else if (this.over === status) { this.over = null; this.overCard = null; }
        if (this.drag) cx.notify();
      })
      .on_mouse_up("left", (_e, cx) => this.drop(status, cx))
      .child(h_flex().flex_none().h(36).px(12).gap(7).items_center()
        .child(dot(statusColor(t, status)))
        .child(div().text_size(12).font_semibold().child(STATUS_LABEL[status]))
        .child(div().text_size(11.5).text_color(t.dim).child(String(ideas.length))))
      .child(v_flex().id(`col-list-${status}`).flex_1().min_h(0).overflow_y_scrollbar().px(8).pb(10).gap(7)
        .children(ideas.flatMap((i) => {
          const here = this.drag && this.moved && this.overCard === i.id && i.id !== this.drag;
          return [here && !this.after ? this.slot(t) : null, this.card(t, i), here && this.after ? this.slot(t) : null].filter(Boolean);
        }))
        .when(Boolean(this.drag && this.moved && this.overCard === `end:${status}`), (el) => el.child(this.slot(t)))
        // The empty space below the cards: dropping there puts the card last.
        .child(div().id(`col-end-${status}`).flex_1().min_h(48)
          .on_mouse_move((_e, cx) => {
            if (this.drag && this.moved && this.overCard !== `end:${status}`) { this.overCard = `end:${status}`; cx.notify(); }
          })));
  }

  board(t) {
    const token = shared(REVIEW) ?? null;
    if (token !== this.reviewToken) { this.reviewToken = token; this.startReview(null); }
    if (this.review) return this.reviewView(t);
    const shown = this.shown();
    const stale = this.ideas.filter(isStale).length;
    const statuses = this.showClosed ? STATUSES : OPEN;
    const closed = shown.filter((i) => !OPEN.includes(i.status)).length;
    const ghost = this.ghost(t);
    return v_flex().id("board").relative().size_full().min_h(0).bg(t.background).text_color(t.foreground).text_size(13)
      .when(Boolean(this.drag && this.moved), (el) => el.cursor_grabbing())
      .on_mouse_move((e, cx) => this.dragMove(e, cx))
      .on_mouse_up("left", (_e, cx) => this.endDrag(cx))
      .on_hover((h, cx) => { if (!h && this.drag) { this.clearDrag(); cx.notify(); } })
      .child(h_flex().flex_none().px(14).py(10).gap(10).items_center().flex_wrap()
        .child(div().text_size(15).font_semibold().child("Ideas"))
        .child(this.searchBox(t, 240))
        .child(this.filters(t))
        .child(div().flex_1())
        .child(this.sortChips(t))
        .when(stale > 0, (el) => el.child(button(t, "b-review", `Review · ${stale}`, this.reviewDue(stale), (_e, cx) => this.startReview(cx))))
        .child(chip(t, "b-closed", `Parked & dropped · ${closed}`, this.showClosed, null, (_e, cx) => { this.showClosed = !this.showClosed; cx.notify(); }))
        .child(button(t, "b-new", "+ New", true, () => run("mod.open", { name: "ideas" }))))
      .when(Boolean(this.empty(t, shown)), (el) => el.child(this.empty(t, shown)))
      .child(h_flex().id("columns").flex_1().min_h(0).items_stretch().px(10).pb(10).gap(8)
        .children(statuses.map((s) => this.column(t, s, this.sorted(shown.filter((i) => i.status === s), s)))))
      .when(Boolean(ghost), (el) => el.child(ghost));
  }
}
