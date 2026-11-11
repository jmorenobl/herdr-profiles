// The bottom terminal: one shell per space that shows below the focused pane
// and hides without ending (Herdr parks it: no pane, still running). The shell
// carries the space's id in a label, which is how it's found again; Herdr's own
// labels go when a terminal is parked.
export const LABEL = "standard.terminal";

const local = (t) => !String(t.address).includes("/");

/** The space's bottom terminal, if it's running. */
export function terminalOf(space, terminals) {
  return terminals.find((t) => t.state === "live" && local(t) && t.labels?.[LABEL] === space.id) ?? null;
}

/** What the toggle does now:
 *  start (no shell yet), show (parked), hide (shown in this tab), move (shown in another tab). */
export function plan(space, terminals, panes) {
  const mine = terminalOf(space, terminals);
  if (!mine) return { step: "start" };
  const pane = panes.find((p) => p.terminal === mine.address);
  if (!pane) return { step: "show", terminal: mine.address };
  const here = space.tabs.find((t) => t.active)?.id;
  return { step: pane.tab === here ? "hide" : "move", terminal: mine.address };
}

/** Parked bottom terminals whose space was closed: nothing shows them any more.
 *  Closing a space ends its panes' terminals, and a parked one has no pane. */
export function orphans(spaces, terminals, panes) {
  const ids = new Set(spaces.map((s) => s.id));
  const shown = new Set(panes.map((p) => p.terminal));
  return terminals
    .filter((t) => t.state === "live" && local(t) && t.labels?.[LABEL] && !ids.has(t.labels[LABEL]) && !shown.has(t.address))
    .map((t) => t.address);
}
