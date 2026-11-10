// Ideas: one mod, three roles, chosen by where it's shown.
//   { view: "board" } in a tab pane  -> the kanban board (the space's "Board" tab)  board.js, review.js
//   a layout block (no props)         -> the side panel: the selected idea, or a compact list  side.js
//   an overlay (mod.open:ideas)       -> quick capture, from any space (ctrl-shift-i)  capture.js
// The selected idea is shared ("ideas.selected"), so the board and the panel move together.
// Each role's methods are a class body in its own file, copied onto Ideas.prototype below,
// so `this` is always this view, as if they were written here. What two roles use is in common.js.
import { View } from "gpui-kit";
import { InputState } from "gpui-base";
import { props, theme, watchFolder, shared, nextCommand, notify } from "herdr";
import { defaultConfig, ideasConfig } from "./config.js";
import { untypedFolders, untypedNotice } from "./store.js";
import { Common, REVIEW } from "./common.js";
import { Board } from "./board.js";
import { Review } from "./review.js";
import { Side } from "./side.js";
import { Capture } from "./capture.js";

const role = () => (props()?.overlay ? "capture" : props()?.view === "board" ? "board" : "side");

export default class Ideas extends View {
  init(_props, cx) {
    this.role = role();
    // The defaults until profiles.json is read (below, or in initCapture): the types, their
    // labels and the agent come from here, so nothing changes when nothing is configured.
    this.config = defaultConfig();
    if (this.role === "capture") return this.initCapture(cx);
    this.ideas = [];
    this.order = {};
    this.orderText = null;
    this.reviewed = null;               // the day of the last finished review
    this.review = null;                 // board: { queue, at, kept, parked, dropped, dropping }
    this.why = InputState.new({ placeholder: "Why drop it? One line" });
    this.why.on("submit", (_e, cx) => this.reviewDrop(cx));
    this.handle = cx.focus_handle();
    this.loaded = false;
    this.error = null;
    this.filter = null;                 // a type, or null
    this.query = "";
    this.search = InputState.new({ placeholder: "Search ideas" });
    this.search.on("change", (_e, cx) => { this.query = this.search.value(); cx.notify(); });
    this.showClosed = false;            // parked + dropped
    this.collapsed = this.loadCollapsed();
    this.drag = null;                   // board: the idea being dragged
    this.over = null;                   // board: the column under the pointer
    this.file = null;                   // side: a note file shown instead of idea.md
    this.fileText = null;
    this.lastTab = null;
    this.reviewToken = shared(REVIEW) ?? null;
    // "ideas.review" (a key, or `herdr-app do ideas.review`) starts the review on the board.
    cx.spawn(async () => { for (;;) { if ((await nextCommand()) === "review") this.requestReview(); } });
    cx.spawn(async (cx) => {
      this.config = await ideasConfig();
      this.folder = this.config.folder;
      // The side panel (one per window) keeps the folder committed and reports bad settings;
      // the board doesn't, to avoid twins.
      this.autocommit = this.role === "side" && this.config.autocommit;
      if (this.role === "side") {
        for (const body of this.config.warnings) notify({ title: "Ideas: check profiles.json", body, level: "warning", timeout: 10000 });
        const notice = untypedNotice(await untypedFolders(this.folder, this.config.types).catch(() => []));
        if (notice) notify({ ...notice, level: "warning", timeout: 10000 });
      }
      await this.reload(cx);
      this.scheduleCommit(cx);
      for (;;) {
        try { await watchFolder(this.folder); }
        catch { await new Promise((r) => cx.timer.after(5000, r)); }
        await this.reload(cx);
        this.scheduleCommit(cx);
      }
    });
  }

  render() {
    const t = theme();
    if (this.role === "capture") return this.capture(t);
    if (this.role === "board") return this.board(t);
    return this.side(t);
  }
}

// Same descriptors as methods written in the class: not enumerable, writable, configurable.
for (const part of [Common, Board, Review, Side, Capture]) {
  for (const [name, d] of Object.entries(Object.getOwnPropertyDescriptors(part.prototype))) {
    if (name === "constructor") continue;
    if (Object.hasOwn(Ideas.prototype, name)) throw new Error(`Ideas: ${name} is defined twice`);
    Object.defineProperty(Ideas.prototype, name, d);
  }
}
