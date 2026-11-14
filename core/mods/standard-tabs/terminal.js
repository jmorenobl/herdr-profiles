// The bottom terminal: one shell per space that shows below the focused pane
// and hides without ending (Herdr parks it: no pane, still running). The shell
// carries the space's id in a label, which is how it's found again; Herdr's own
// labels go when a terminal is parked.
//
// A space on another machine gets its shell on that machine (`hc run --on`):
// its address is `machine/t7`, and its label holds the space's id as that
// machine knows it, without the `machine/` the app puts before remote ids.
export const LABEL = "standard.terminal";

/** The machine a terminal or space id lives on (`box/t7` → "box"), null for this computer. */
export const machineOf = (id) => (String(id).includes("/") ? String(id).split("/")[0] : null);

/** The label's value for a space: its id on its own machine. */
export const labelFor = (space) =>
  space.machine && String(space.id).startsWith(`${space.machine}/`) ? String(space.id).slice(space.machine.length + 1) : String(space.id);

// The space id a labelled shell belongs to, as the app names spaces (a label
// the app already gave with its machine is taken as it is).
function spaceOf(t) {
  const label = t.labels?.[LABEL], m = machineOf(t.address);
  if (!label) return null;
  return m && !String(label).startsWith(`${m}/`) ? `${m}/${label}` : String(label);
}

/** The space's bottom terminal, if it's running: on the space's machine, labelled with its id. */
export function terminalOf(space, terminals) {
  return terminals.find((t) => t.state === "live" && machineOf(t.address) === (space.machine ?? null) && spaceOf(t) === space.id) ?? null;
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

/** `hc run` for the space's shell: in the background, labelled, on its machine, in `cwd`. */
export function startArgs(space, cwd) {
  const args = ["run", "--bg", "--json", "--no-parent", "--label", `${LABEL}=${labelFor(space)}`];
  if (space.machine) args.push("--on", space.machine);
  if (cwd) args.push("--cwd", cwd);
  return args;
}

/** Parked bottom terminals whose space was closed: nothing shows them any more.
 *  Closing a space ends its panes' terminals, and a parked one has no pane.
 *  `ready`: the machines (null: this computer) whose spaces are all known; on any
 *  other, every space would look closed. */
export function orphans(spaces, terminals, panes, ready = [null]) {
  const ids = new Set(spaces.map((s) => s.id));
  const shown = new Set(panes.map((p) => p.terminal));
  const known = new Set(ready);
  return terminals
    .filter((t) => t.state === "live" && known.has(machineOf(t.address)) && spaceOf(t) && !ids.has(spaceOf(t)) && !shown.has(t.address))
    .map((t) => t.address);
}
