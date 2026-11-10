// Small building blocks shared by the board, the side panel and the capture dialog.
import { div } from "gpui-kit";
import { h_flex } from "gpui-base";

export const STATUS_LABEL = {
  seed: "Seed", exploring: "Exploring", ripe: "Ripe", active: "Active", parked: "Parked", dropped: "Dropped",
};

export const TYPE_LABEL = { book: "Book", code: "Code", legal: "Legal", other: "Other" };

// A type's label: the one profiles.json gives it, else the default one, else its folder name
// with a capital and spaces ("side-projects" -> "Side projects").
// Own keys only: a type called "constructor" mustn't get Object's.
export const typeLabel = (type, labels = {}) =>
  (Object.hasOwn(labels, type) ? labels[type] : null) ?? (Object.hasOwn(TYPE_LABEL, type) ? TYPE_LABEL[type] : null)
  ?? type.charAt(0).toUpperCase() + type.slice(1).replace(/[-_]+/g, " ");

export const statusColor = (t, s) => ({
  seed: t.ansi3, exploring: t.ansi4, ripe: t.accent, active: t.ansi2, parked: t.muted, dropped: t.dim,
}[s] ?? t.dim);

export const dot = (color, size = 8) => div().flex_none().size(size).rounded(size / 2).bg(color);

export const chip = (t, id, text, on, color, action) => h_flex().id(id).h(24).px(9).gap(6).flex_none().items_center().rounded(12)
  .border_1().border_color(on ? (color ?? t.accent) : t.border).bg(on ? t.selected : t.background)
  .text_size(11.5).text_color(on ? t.foreground : t.muted).cursor_pointer().hover((s) => s.bg(t.hover))
  .on_click(action)
  .when(Boolean(color), (el) => el.child(dot(color, 7)))
  .child(text);

export const button = (t, id, text, primary, action) => h_flex().id(id).h(28).px(11).flex_none().items_center().rounded(8)
  .border_1().border_color(primary ? t.solid : t.input).bg(primary ? t.solid : t.raised)
  .text_color(primary ? t.solid_foreground : t.foreground).text_size(12).font_medium().cursor_pointer()
  .hover((s) => s.opacity(0.88)).on_click(action).child(text);

export const sectionLabel = (t, text) => div().text_size(11).font_semibold().text_color(t.dim).child(text);

// Matches every word of the query against title, body and tags.
export function matches(idea, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const hay = `${idea.title}\n${idea.body}\n${idea.tags.join(" ")}\n${idea.slug}`.toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}
