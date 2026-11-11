// Herdr's tab bar, cloned from its `tabs` (0.1.14) for the standard profile: a
// History button after Changes opens the panel's commit history (`standard-history`),
// and a Terminal button (`standard-tabs.terminal` for a key) shows and hides the
// space's bottom terminal (terminal.js).
import { View, div, svg, image } from "gpui-kit";
import { h_flex } from "gpui-base";
import { spaces, panes, terminals, machines, focused, run, exec, nextCommand, notify, openOverlay, theme, window, shared, layout, settings } from "herdr";
import { LABEL, plan, orphans } from "./terminal.js";

function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}

// Module scope lasts the app's run and is shared by every copy: each layout
// starts its own copy (a layout switch, by hand or by the profile switcher,
// starts this bar afresh), and localStorage is per copy. So the per-space panel
// memory and whether this run has already shown a space live here, and a
// layout switch counts as a space change, not as the app starting.
// `busy` (a toggle under way) and `ended` (orphans already told to end) are
// here too: the bar's copies must not act twice on one terminal.
const memory = { panels: null, started: false, busy: false, ended: new Set() };

export default class Tabs extends View {
  init(_props, cx) {
    this.pressed = null;
    cx.spawn(async (cx) => { for (;;) { if ((await nextCommand()) === "terminal") this.toggleTerminal(cx); } });
    memory.panels ??= JSON.parse(localStorage.getItem("panels") ?? "{}");
    this.panels = memory.panels;
  }

  // The side panel is remembered per space: switching shows that space's choice
  // (closed if it never had one), and opening or closing it records it.
  syncPanel(space, panel, body, enabled) {
    if (!space || !panel) return;
    const now = panel.hidden ? null : body?.active ?? null;
    if (space.id !== this.space) {
      const first = this.space === undefined && !memory.started;
      memory.started = true;
      this.space = space.id; this.pending = null;
      if (!(first && !(space.id in this.panels))) {
        const stored = this.panels[space.id] ?? null, want = enabled.includes(stored) ? stored : null;
        if (want !== now) {
          this.pending = { want, until: Date.now() + 1000 };
          if (want) { run("layout.select", { stack: "panel-body", child: want }); run("layout.show", { id: "panel" }); }
          else run("layout.hide", { id: "panel" });
          return;
        }
      }
    }
    // Until the restore lands (or something else won), the old state isn't a choice.
    if (this.pending) {
      if (this.pending.want !== now && Date.now() < this.pending.until) return;
      this.pending = null;
    }
    if (this.panels[space.id] === now) return;
    this.panels[space.id] = now;
    localStorage.setItem("panels", JSON.stringify(this.panels));
  }

  // Shows the space's bottom terminal below the focused pane, or hides it. Hidden
  // is parked: the shell and what's on it stay. A space on another machine gets a
  // plain split: its terminals are that machine's, which this doesn't park.
  toggleTerminal(cx) {
    const space = spaces().find(p => p.active);
    if (!space || memory.busy) return;
    if (space.machine) { run("pane.split", { direction: "down" }); return; }
    const now = plan(space, terminals(), panes());
    if (now.step === "hide") { run("terminal.park", { terminal: now.terminal }); return; }
    if (now.step === "show") { run("terminal.keep", { terminal: now.terminal, place: "down" }); return; }
    memory.busy = true;
    cx.spawn(async (cx) => {
      try {
        let terminal = now.terminal;
        if (now.step === "start") {
          const args = ["run", "--bg", "--json", "--no-parent", "--label", `${LABEL}=${space.id}`];
          const cwd = focused()?.cwd || space.folder;
          const r = await exec("hc", cwd ? [...args, "--cwd", cwd] : args);
          if (r.code !== 0) throw new Error(r.stderr.trim() || "hc run failed");
          terminal = JSON.parse(r.stdout).address;
          // The app hears of it a moment later, and can't place one it doesn't know yet.
          for (let i = 0; i < 30 && !terminals().some(t => t.address === terminal); i++) await cx.sleep(100);
        } else {
          // Shown in another tab: parked first, and here once its pane is gone.
          run("terminal.park", { terminal });
          for (let i = 0; i < 30 && panes().some(p => p.terminal === terminal); i++) await cx.sleep(100);
        }
        run("terminal.keep", { terminal, place: "down" });
      } catch (e) {
        notify({ title: "Terminal", body: String(e.message ?? e), level: "error" });
      } finally {
        memory.busy = false;
        cx.notify();
      }
    });
  }

  render() {
    const t = theme();
    const space = spaces().find(p => p.active);
    const shown = space?.tabs ?? [];
    const stop = (_e, cx) => cx.stop_propagation();
    const button = (id, label, action) => div().id(id).size(26).flex_none().flex().items_center().justify_center().rounded(6).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
      .on_mouse_down("left", stop).on_click(action).child(label);
    const item = (c, i) => {
      const program = panes().find(p => p.tab === c.id && p.program?.agent)?.program ?? panes().find(p => p.tab === c.id)?.program;
      const name = /^tb\d+$/.test(c.name) ? program?.name ?? "Terminal" : c.name;
      return h_flex().id(`tab-${c.id}`).h(29).px(10).gap(7).rounded(7).items_center().flex_none().text_size(12.8)
        .border(1).border_color(c.active ? t.border : t.chrome).bg(c.active ? t.raised : t.chrome).text_color(c.active ? t.foreground : t.muted)
        .hover(s => s.bg(t.hover))
        .on_mouse_down("left", (e, cx) => { cx.stop_propagation(); this.pressed = i; if (e.click_count === 2) run("tab.rename", { id: c.id }); })
        .on_mouse_up("left", () => {
          const from = this.pressed; this.pressed = null;
          if (from !== null && from !== i) run("tab.move", { id: shown[from].id, index: space.tabs.findIndex(x => x.id === c.id) + 1 });
          else run("tab.select", { id: c.id });
        })
        .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); openOverlay({ mod: "menu", kind: "popup", width: 200, props: { tab: "tab", target: { id: c.id, space: space.id } } }); })
        .when(Boolean(program?.icon), el => el.child(program.tint ? svg(program.icon).size(14).text_color(t.muted) : image(program.icon).size(14)))
        .child(div().max_w(170).truncate().child(c.zoomed ? `${name} Z` : name))
        .when(c.status === "working", el => el.child(svg("mods/workspace-chrome/spinner.svg").size(12).flex_none().text_color(t.working).spin(900)))
        .when(c.status === "blocked" || c.status === "done", el => el.child(div().size(6).rounded(3).bg(t[c.status])))
        .when(c.active, el => el.child(div().id(`close-${c.id}`).text_color(t.dim).on_mouse_down("left", stop).on_click((_e, cx) => { cx.stop_propagation(); run("tab.close", { id: c.id }); }).child(svg("mods/pane/close.svg").size(12))));
    };
    const root = layout(), sidebar = find(root, "sidebar"), w = window();
    // Old saved rails and a dragged-narrow sidebar can be smaller than the window buttons.
    const lightsPadding = w?.platform === "macos" && w.titlebar === "none" && !w.fullscreen && root?.traffic_lights
      ? Math.max(10, (root.traffic_lights[0] + 64) / settings().zoom - (sidebar?.hidden ? 0 : sidebar?.size?.px ?? 0))
      : 10;
    const panel = find(root, "panel"), body = find(root, "panel-body");
    const chosen = shared("workspace.panels") ?? ["files", "changes"];
    // History goes with Changes: both are about the repo.
    const enabled = chosen.includes("changes") ? [...chosen, "history"] : chosen;
    this.syncPanel(space, panel, body, enabled);
    // Bottom terminals parked in a space that was closed. Only once this
    // computer's spaces are known: before that, every space looks closed.
    if (machines().some(m => m.name === null && m.layout === "ready") && spaces().length)
      for (const terminal of orphans(spaces(), terminals(), panes())) {
        if (memory.ended.has(terminal)) continue;
        memory.ended.add(terminal);
        run("terminal.kill", { terminal });
      }
    const terminalOn = Boolean(space) && !space.machine && plan(space, terminals(), panes()).step === "hide";
    const panelButton = (id, label, icon) => {
      const on = panel && !panel.hidden && body?.active === id;
      return h_flex().id(`panel-${id}`).h(26).px(8).gap(5).flex_none().items_center().rounded(6)
        .text_size(12).bg(on ? t.selected : t.chrome).text_color(on ? t.foreground : t.muted)
        .hover(s => s.bg(t.hover)).on_mouse_down("left", stop)
        .on_click(() => {
          if (on) run("layout.hide", { id: "panel" });
          else { run("layout.select", { stack: "panel-body", child: id }); run("layout.show", { id: "panel" }); }
        }).child(svg(icon).size(14)).child(label);
    };
    return h_flex().size_full().min_w(0).px(10).pl(lightsPadding).gap(3).items_center().bg(t.chrome).border_b(1).border_color(t.border)
      .on_mouse_up("left", () => { this.pressed = null; })
      .on_scroll_wheel(e => { if (Math.abs(e.delta.y) >= 1) run(e.delta.y > 0 ? "tab.prev" : "tab.next"); })
      .child(h_flex().id("tab-scroll").flex_1().min_w(0).h_full().items_center().gap(3).overflow_x_scrollbar().children(shown.map(item)))
      .child(button("tab-new", "+", () => openOverlay({ mod: "new-menu", kind: "popup", width: 250, height: 512 })))
      .when(enabled.includes("files"), el => el.child(panelButton("files", "Files", "mods/files/file.svg")))
      .when(enabled.includes("changes"), el => el.child(panelButton("changes", "Changes", "mods/changes/changes.svg")))
      .when(enabled.includes("history"), el => el.child(panelButton("history", "History", "mods/standard-history/history.svg")))
      .child(h_flex().id("terminal-toggle").h(26).px(8).gap(5).flex_none().items_center().rounded(6)
        .text_size(12).bg(terminalOn ? t.selected : t.chrome).text_color(terminalOn ? t.foreground : t.muted)
        .hover(s => s.bg(t.hover)).on_mouse_down("left", stop)
        .on_click((_e, cx) => this.toggleTerminal(cx))
        .child(svg("mods/standard-tabs/terminal.svg").size(14)).child("Terminal"))
      .when(w?.buttons, el => el.child(button("minimize", w.platform === "windows" ? svg("mods/standard-tabs/win-min.svg").size(16) : "−", () => run("window.minimize")))
        .child(button("maximize", w.platform === "windows" ? svg(`mods/standard-tabs/${w.maximized ? "win-restore" : "win-max"}.svg`).size(16) : "□", () => run("window.maximize")))
        .child(button("close-window", w.platform === "windows" ? svg("mods/standard-tabs/win-close.svg").size(16) : svg("mods/pane/close.svg").size(13), () => run("window.close"))));
  }
}
