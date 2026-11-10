// The weekly review, shown by the board in place of its columns.
// Methods of the Ideas view (main.js), copied onto it: `this` is the view.
import { div } from "gpui-kit";
import { v_flex, h_flex, Input, TextView } from "gpui-base";
import { notify, setShared } from "herdr";
import { updateIdea, writeBoard, ago, today, touched, isStale } from "./store.js";
import { STATUS_LABEL, statusColor, dot, button } from "./ui.js";
import { ideasSpace, openBoard, lastMove, followMoves } from "./actions.js";
import { REVIEW } from "./common.js";

export class Review {
  // ---------- review (board) ----------
  // Stale ideas one at a time, oldest first: keep going, park, drop (with a line on why) or skip.
  // Finishing the queue stamps `reviewed` in .board.json; a week later the Review button darkens.

  // From any copy: the board starts a review when the shared token changes.
  requestReview() {
    setShared(REVIEW, Date.now());
    const space = this.role === "side" && this.folder && ideasSpace(this.folder);
    if (space) openBoard(space);
  }

  startReview(cx) {
    const queue = this.ideas.filter(isStale).sort((a, b) => touched(a).localeCompare(touched(b))).map((i) => i.id);
    if (!queue.length) return;
    // moveSeq: only type changes made after the review starts are followed (see actions.js).
    this.review = { queue, at: 0, kept: 0, parked: 0, dropped: 0, dropping: false, moveSeq: lastMove() };
    this.why.set_value("");
    // Started from render (the shared token) there's no cx, and focus must wait for a click.
    if (cx) { this.handle.focus(); cx.notify(); }
  }

  // The idea under review, following ideas whose type changed meanwhile (their id did)
  // and skipping any that left the folder.
  reviewIdea() {
    const r = this.review;
    if (r) ({ ids: r.queue, seq: r.moveSeq } = followMoves(r.queue, r.moveSeq));
    while (r && r.at < r.queue.length) {
      const idea = this.ideas.find((i) => i.id === r.queue[r.at]);
      if (idea) return idea;
      r.at++;
    }
    return null;
  }

  // Runs board writes one after another, then reloads.
  queueWrite(cx, write) {
    this.writes = (this.writes ?? Promise.resolve()).then(write).catch(() =>
      notify({ title: "The idea changed on disk", body: "Reloaded it; review it again later.", level: "warning", timeout: 4000 }));
    cx.spawn(async (cx) => { await this.writes; await this.reload(cx); });
  }

  reviewAct(kind, cx) {
    const r = this.review, idea = this.reviewIdea();
    if (!idea) return;
    const why = this.why.value().trim();
    if (kind === "drop" && !why) { r.dropping = true; this.why.focus(); return cx.notify(); }
    const changes = kind === "keep" ? (idea.status === "seed" ? { status: "exploring" } : {})
      : kind === "park" ? { status: "parked" }
      : kind === "drop" ? { status: "dropped", why } : null;
    if (kind === "keep") r.kept++;
    if (kind === "park") r.parked++;
    if (kind === "drop") r.dropped++;
    r.at++;
    r.dropping = false;
    this.why.set_value("");
    this.handle.focus();
    if (changes) this.queueWrite(cx, () => updateIdea(idea, changes));
    if (!this.reviewIdea()) {
      this.queueWrite(cx, async () => {
        this.reviewed = today();
        this.orderText = await writeBoard(this.folder, { order: this.order, reviewed: this.reviewed }, this.orderText);
      });
    }
    cx.notify();
  }

  reviewDrop(cx) {
    if (this.review?.dropping && this.why.value().trim()) this.reviewAct("drop", cx);
  }

  endReview(cx) {
    this.review = null;
    cx.notify();
  }

  reviewKey(e, cx) {
    const r = this.review;
    if (!r) return;
    if (e.keystroke === "escape") {
      if (r.dropping) { r.dropping = false; this.why.set_value(""); this.handle.focus(); }
      else this.review = null;
      cx.stop_propagation();
      return cx.notify();
    }
    if (r.dropping || !this.reviewIdea()) return;
    const kind = { k: "keep", p: "park", d: "drop", s: "skip", right: "skip" }[e.keystroke];
    if (kind) { this.reviewAct(kind, cx); cx.stop_propagation(); }
  }

  reviewView(t) {
    const r = this.review, idea = this.reviewIdea();
    const total = r.queue.length;
    const root = v_flex().id("review").track_focus(this.handle).on_key_down((e, cx) => this.reviewKey(e, cx))
      .on_mouse_down("left", () => { if (!r.dropping) this.handle.focus(); })
      .size_full().min_h(0).bg(t.background).text_color(t.foreground).text_size(13)
      .child(h_flex().flex_none().px(14).py(10).gap(10).items_center()
        .child(div().text_size(15).font_semibold().child("Review"))
        .child(div().text_size(12).text_color(t.dim).child(idea ? `${Math.min(r.at + 1, total)} of ${total} · untouched for over a month` : `${total} reviewed`))
        .child(div().flex_1())
        .child(button(t, "r-done", idea ? "Done · Esc" : "Back to the board", !idea, (_e, cx) => this.endReview(cx))));
    if (!idea) {
      const bits = [[r.kept, "kept going"], [r.parked, "parked"], [r.dropped, "dropped"]].filter(([n]) => n).map(([n, w]) => `${n} ${w}`);
      return root.child(v_flex().flex_1().items_center().justify_center().gap(8)
        .child(div().text_size(18).font_semibold().child("Review done"))
        .child(div().text_size(13).text_color(t.muted).child(bits.length ? `${bits.join(", ")}.` : "Nothing changed."))
        .child(div().text_size(12).text_color(t.dim).child("See you next week.")));
    }
    const age = ago(touched(idea));
    const act = (id, label, key, primary, kind) => button(t, id, `${label}  ${key}`, primary, (_e, cx) => this.reviewAct(kind, cx));
    const keepLabel = idea.status === "seed" ? "Keep going → Exploring" : "Keep going";
    const card = v_flex().id("r-card").w_full().max_w(680).flex_none().p(26).gap(12).rounded(14)
      .bg(t.popover).border_1().border_color(t.border).shadow_lg()
      .child(h_flex().gap(8).items_center().text_size(12).text_color(t.dim)
        .child(dot(statusColor(t, idea.status)))
        .child(div().text_color(t.muted).child(STATUS_LABEL[idea.status]))
        .child("·").child(this.labelOf(idea.type))
        .child("·").child(div().text_color(t.ansi3).font_medium().child(age === "today" ? "touched today" : `untouched ${age}`)))
      .child(div().text_size(22).font_semibold().child(idea.title))
      .when(idea.tags.length > 0, (el) => el.child(div().text_size(12).text_color(t.accent).child(idea.tags.map((x) => `#${x}`).join(" "))))
      .when(Boolean(idea.origin), (el) => el.child(div().text_size(12).text_color(t.dim).child(`From ${idea.origin}`)))
      .child(div().id("r-body").max_h(460).overflow_y_scrollbar().pt(4).text_size(13.5)
        .child(idea.body ? TextView.markdown(`r-md-${idea.id}`, idea.body).selectable(true)
          : div().text_color(t.dim).child("Nothing written beyond the title.")))
      .when(idea.files.length > 0, (el) => el.child(div().text_size(11.5).text_color(t.dim)
        .child(`Also here: ${idea.files.slice(0, 6).join(", ")}${idea.files.length > 6 ? "…" : ""}`)));
    const actions = r.dropping
      ? h_flex().w_full().max_w(680).gap(8).items_center()
        .child(Input.new(this.why).flex_1().h(32).px(10).rounded(8).border_1().border_color(t.accent).bg(t.background).text_size(13).text_color(t.foreground))
        .child(button(t, "r-why", "Drop", true, (_e, cx) => this.reviewDrop(cx)))
        .child(button(t, "r-why-cancel", "Cancel", false, (_e, cx) => { r.dropping = false; this.why.set_value(""); this.handle.focus(); cx.notify(); }))
      : h_flex().w_full().max_w(680).gap(8).items_center()
        .child(act("r-keep", keepLabel, "K", true, "keep"))
        .child(act("r-park", "Park", "P", false, "park"))
        .child(act("r-drop", "Drop…", "D", false, "drop"))
        .child(div().flex_1())
        .child(act("r-skip", "Skip", "S", false, "skip"));
    return root.child(v_flex().flex_1().min_h(0).items_center().justify_center().px(20).pt(8).pb(40).gap(14).child(card).child(actions));
  }
}
