// Where the ideas folder is: this computer, or another machine (profiles.json "machine", one
// of `hc machine ls`). Everything that touches the folder goes through here, so it runs there:
// programs, reads and writes. config.js sets the place each time it reads the settings.
// Module scope is shared by every copy of the mod (side panel, board, capture), which all
// read the same settings.
import { exec, readTextFile, writeTextFile, home } from "herdr";

const here = { machine: null, home: null };

/** The machine the ideas folder is on, or null for this computer. */
export const machine = () => here.machine;

/** That machine's home folder (this computer's when the folder is here). */
export const homeDir = () => (here.machine ? here.home : home());

export function setPlace(name, machineHome) {
  here.machine = name || null;
  here.home = name ? machineHome : null;
}

/** A machine's name as `hc machine ls` could list it: letters, digits, `.`, `_` and `-`. */
export const MACHINE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** The home folder of machine `name`, asked of it. Rejects when it can't be reached. */
export async function machineHome(name) {
  const r = await exec("sh", ["-c", 'printf "%s" "$HOME"'], { on: name, timeout: 10000 });
  const h = r.code === 0 ? r.stdout.trim() : "";
  if (!h.startsWith("/")) throw new Error(r.stderr?.trim() || "it gave no home folder");
  return h;
}

/** The machine a space, tab or pane id belongs to (`box/sp1` → "box"), null for this computer. */
export const machineOf = (id) => (String(id ?? "").includes("/") ? String(id).split("/")[0] : null);

/** Whether a space, tab or pane id is on the ideas folder's machine. */
export const onPlace = (id) => machineOf(id) === here.machine;

/** Runs a program where the ideas folder is. */
export const run = (command, args, options = {}) => exec(command, args, here.machine ? { ...options, on: here.machine } : options);

/** Reads a text file where the ideas folder is, or null if it's absent. */
export const read = (path) => (here.machine ? readTextFile(path, { on: here.machine }) : readTextFile(path));

// One argument holds the text (and another what the file must still be): Linux takes up to
// 128 KiB in one. Ideas and the board's order are far smaller.
export const MAX_WRITE = 120000;
const bytes = (s) => { let n = 0; for (const ch of s) { const c = ch.codePointAt(0); n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; } return n; };

// $1 the file, $2 "new" (it mustn't exist) or "same" (it must still be $3), $4 the text.
// Exit 3: the file isn't what was read (writeTextFile's stale snapshot). Written beside it and
// moved into place, so a reader never sees half a file. `$(cat; printf x)` keeps trailing newlines.
export const WRITE = `f=$1
if [ "$2" = new ]; then [ -e "$f" ] && exit 3
else [ -f "$f" ] || exit 3; now=$(cat "$f"; printf x); [ "$now" = "$3x" ] || exit 3; fi
tmp="$f.ideas-$$"; printf '%s' "$4" > "$tmp" && mv "$tmp" "$f" || { rm -f "$tmp"; exit 1; }`;

/** Writes `text` only if the file is still `expected` (null: it must not exist yet), as
 *  writeTextFile does. Rejects on a stale snapshot. */
export async function write(path, text, expected) {
  if (!here.machine) return writeTextFile(path, text, expected);
  if (bytes(text) > MAX_WRITE || bytes(expected ?? "") > MAX_WRITE) throw new Error(`Too large to save on ${here.machine}`);
  const r = await exec("sh", ["-c", WRITE, "ideas", path, expected === null ? "new" : "same", expected ?? "", text], { on: here.machine, timeout: 20000 });
  if (r.code === 3) throw new Error("The file changed since it was read");
  if (r.code !== 0) throw new Error(r.stderr?.trim() || `Could not save on ${here.machine}`);
  return null;
}
