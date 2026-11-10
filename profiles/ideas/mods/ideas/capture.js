// Quick capture (an overlay, mod.open:ideas): a title, notes and a type, saved as a new seed.
// Methods of the Ideas view (main.js), copied onto it: `this` is the view.
import { div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, TextareaState, Textarea } from "gpui-base";
import { props, spaces, notify, closeOverlay } from "herdr";
import { createIdea, fallbackType, tilde } from "./store.js";
import { ideasConfig } from "./config.js";
import { chip, button } from "./ui.js";
import { select } from "./actions.js";

// The line beside the buttons: where the idea came from, or, when profiles.json gives no usable
// folder, where it will be saved (in amber: `warn`).
export function captureFootnote(config, origin) {
  if (config.folderNote) return { text: `Saves into ${tilde(config.folder)}`, warn: true };
  return { text: origin ? `From ${origin.replace(/^Herdr space /, "")}` : "", warn: false };
}

export class Capture {
  // ---------- capture ----------

  initCapture(cx) {
    this.type = fallbackType(this.config.types);
    this.saving = false;
    // The configured types: the chips show the defaults until they're read.
    cx.spawn(async (cx) => {
      this.config = await ideasConfig();
      if (!this.config.types.includes(this.type)) this.type = fallbackType(this.config.types);
      cx.notify();
    });
    const here = spaces().find((s) => s.active);
    this.origin = here ? `Herdr space ${here.name}` : "";
    this.title = InputState.new({ placeholder: "What's the idea?" });
    this.note = TextareaState.new({ placeholder: "Anything else (optional)", rows: 5 });
    this.note.set_auto_grow(5, 12);
    this.title.on("submit", (_e, cx) => this.save(cx));
    this.note.on("submit", (e, cx) => { if (e.secondary) this.save(cx); });
    this.title.on("change", (_e, cx) => cx.notify());
    this.title.focus();
    cx.timer.after(400, () => this.title.focus());
    this.handle = cx.focus_handle();
  }

  save(cx) {
    const title = this.title.value().trim();
    if (!title || this.saving) return;
    this.saving = true;
    const overlay = props().overlay;
    cx.spawn(async (cx) => {
      try {
        const config = await ideasConfig();
        const id = await createIdea(config.folder, { title, body: this.note.value(), type: this.type, origin: this.origin }, config.types);
        closeOverlay(overlay);
        select(id);
        notify({ title: "Idea saved", body: title, level: "success", timeout: 3000 });
      } catch (e) {
        this.saving = false;
        this.error = String(e);
        cx.notify();
      }
    });
  }

  capture(t) {
    const overlay = props().overlay;
    const foot = captureFootnote(this.config, this.origin);
    const label = (text) => div().pt(14).pb(6).text_size(11.5).text_color(t.dim).child(text);
    return v_flex().id("idea-capture").track_focus(this.handle)
      .on_key_down((e, cx) => { if (e.key === "escape") { closeOverlay(overlay); cx.stop_propagation(); } })
      .w_full().p(18).bg(t.popover).text_color(t.foreground)
      .child(h_flex().items_center()
        .child(div().flex_1().text_size(15).font_semibold().child("New idea"))
        .child(div().text_size(11).text_color(t.dim).child("Enter saves · Esc")))
      .child(label("Idea"))
      .child(Input.new(this.title).h(36).px(10).rounded(9).border_1().border_color(t.input).bg(t.background).text_size(13).text_color(t.foreground))
      .child(label("Notes"))
      .child(Textarea.new(this.note).px(10).py(8).rounded(9).border_1().border_color(t.input).bg(t.background).text_size(13).text_color(t.foreground))
      .child(label("Type"))
      .child(h_flex().gap(6).children(this.config.types.map((ty) =>
        chip(t, `ct-${ty}`, this.labelOf(ty), this.type === ty, null, (_e, cx) => { this.type = ty; cx.notify(); }))))
      .when(Boolean(this.error), (el) => el.child(div().pt(10).text_size(12).text_color(t.blocked).child(this.error)))
      .child(h_flex().pt(18).gap(8).items_center()
        .child(div().flex_1().min_w(0).truncate().text_size(11).text_color(foot.warn ? t.ansi3 : t.dim).child(foot.text))
        .child(button(t, "ic-cancel", "Cancel", false, () => closeOverlay(overlay)))
        .child(button(t, "ic-save", this.saving ? "Saving…" : "Save", true, (_e, cx) => this.save(cx))));
  }
}
