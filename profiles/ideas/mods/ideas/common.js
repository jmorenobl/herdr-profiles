// What the board and the side panel share: loading the folder, sorting, the filter
// and search row, the empty state and a card's meta line.
// Methods of the Ideas view (main.js), copied onto it: `this` is the view.
import { div } from "gpui-kit";
import { h_flex, Input } from "gpui-base";
import { shared } from "herdr";
import { listIdeas, untypedIds, readBoard, ago, daysSince, touched, isStale, REVIEW_EVERY } from "./store.js";
import { typeLabel, chip, matches } from "./ui.js";

export const sortMode = () => shared("ideas.sort") ?? "manual";
export const byRecent = (a, b) => touched(b).localeCompare(touched(a)) || a.title.localeCompare(b.title);

export const REVIEW = "ideas.review";   // shared: a new value (Date.now()) asks the board to start a review
// A request this recent, found by a board that just opened, was made for it.
const FRESH = 15000;
export const freshRequest = (token, now = Date.now()) => typeof token === "number" && now - token >= 0 && now - token < FRESH;

export class Common {
  async reload(cx) {
    try {
      const [ideas, board] = await Promise.all([listIdeas(this.folder, this.config.types), readBoard(this.folder)]);
      this.ideas = ideas;
      ({ text: this.orderText, order: this.order, reviewed: this.reviewed } = board);
      this.error = null;
      if (this.role === "side") await this.readShownFile();
    }
    catch (e) { this.error = String(e); }
    this.loaded = true;
    cx.notify();
  }

  // The saved order of ideas in folders that aren't types now (so not on the board): kept as it
  // is when the board rewrites the order, so going back to those types finds it again.
  hiddenOrder(status) {
    return untypedIds(this.order[status], this.config.types);
  }

  // Manual: ideas not placed yet come first (newest first), then the saved order.
  sorted(list, status) {
    const mode = sortMode();
    if (mode === "az") return [...list].sort((a, b) => a.title.localeCompare(b.title));
    if (mode === "recent") return [...list].sort(byRecent);
    const rank = new Map((this.order[status] ?? []).map((id, n) => [id, n]));
    return [
      ...list.filter((i) => !rank.has(i.id)).sort(byRecent),
      ...list.filter((i) => rank.has(i.id)).sort((a, b) => rank.get(a.id) - rank.get(b.id)),
    ];
  }

  // The idea types in use (profiles.json, or the defaults) and their labels.
  labelOf(type) {
    return typeLabel(type, this.config.labels);
  }

  shown() {
    return this.ideas.filter((i) => (!this.filter || i.type === this.filter) && matches(i, this.query));
  }

  filters(t) {
    return h_flex().gap(5).flex_wrap()
      .child(chip(t, "f-all", "All", !this.filter, null, (_e, cx) => { this.filter = null; cx.notify(); }))
      .children(this.config.types.map((ty) => chip(t, `f-${ty}`, this.labelOf(ty), this.filter === ty, null,
        (_e, cx) => { this.filter = this.filter === ty ? null : ty; cx.notify(); })));
  }

  searchBox(t, width) {
    const el = Input.new(this.search).h(28).px(9).rounded(8).border_1().border_color(t.input).bg(t.background).text_size(12.5).text_color(t.foreground);
    return width ? el.w(width) : el.flex_1();
  }

  empty(t, shown) {
    if (!this.loaded) return div().p(12).text_size(12).text_color(t.dim).child("Loading ideas…");
    if (this.error) return div().p(12).text_size(12).text_color(t.blocked).child(this.error);
    if (shown.length) return null;
    const text = this.query || this.filter ? "No ideas match." : "No ideas yet. Press ctrl-shift-i anywhere to capture one.";
    return div().p(12).text_size(12.5).text_color(t.dim).child(text);
  }

  // Type · age · files · project, with the age in amber when the idea is stale.
  meta(t, idea) {
    const bits = [this.labelOf(idea.type)];
    if (idea.files.length) bits.push(`${idea.files.length} file${idea.files.length > 1 ? "s" : ""}`);
    if (idea.project) bits.push("project");
    const age = ago(touched(idea));
    return h_flex().gap(4).text_size(11).text_color(t.dim)
      .child(bits[0])
      .when(Boolean(age), (el) => el.child("·").child(isStale(idea) ? div().text_color(t.ansi3).font_medium().child(age) : age))
      .children(bits.slice(1).flatMap((b) => ["·", b]));
  }

  // When the weekly review is due: stale ideas waiting, and no review in a week.
  reviewDue(stale) {
    if (!stale) return false;
    const days = daysSince(this.reviewed);
    return days === null || days >= REVIEW_EVERY;
  }
}
