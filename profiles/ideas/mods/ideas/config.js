// The mod's settings: profiles.json -> profiles.ideas. The only place that reads them.
// Read fresh on every call (when the mod starts, when capture saves): edits apply then.
import { readTextFile, appHome, home } from "herdr";
import { DEFAULT_TYPES, expand, tilde } from "./store.js";

const DEFAULT_AGENT = ["claude"];
// The folder when profiles.json doesn't give one: install asks, and ~/ideas is its default too.
const DEFAULT_FOLDER = "~/ideas";

// A type is a folder name: lowercase letters, digits, - and _, starting with a letter or digit.
const TYPE_NAME = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const MAX_TYPES = 12;
const CONTROL = /[\u0000-\u001f\u007f]/;

// profiles.json -> profiles.ideas: { s, problem }. `problem` says why there are no settings to read.
async function settings() {
  const file = `${tilde(appHome())}/profiles.json`;
  let text;
  try { text = await readTextFile(`${appHome()}/profiles.json`); }
  catch (e) { return { s: {}, problem: `Can't read ${file} (${String(e?.message ?? e)})` }; }
  let data;
  try { data = JSON.parse(text); }
  catch { return { s: {}, problem: `${file} isn't valid JSON` }; }
  const s = data?.profiles?.ideas;
  if (s === undefined) return { s: {}, problem: `${file} has no "ideas" entry under "profiles"` };
  if (!s || typeof s !== "object" || Array.isArray(s)) return { s: {}, problem: `${file}: "profiles" → "ideas" isn't an object` };
  return { s, problem: null };
}

// The same rule the installer uses for a folder answer (scripts/profiletool/spec.py, check_folder):
// surrounding whitespace dropped, then one line, starting with / or ~/, no // and no . or .. parts,
// and not /, the home folder or a folder above it. Returns { path (expanded) } or { problem }.
export function checkFolder(value) {
  if (typeof value !== "string" || !value.trim()) return { problem: "must be a folder (a string)" };
  let v = value.trim();
  if (CONTROL.test(v)) return { problem: "can't contain control characters (tabs, newlines, …)" };
  if (v !== "/" && v.endsWith("/")) v = v.replace(/\/+$/, "") || "/";
  if (v === "/" || v === "~") return { problem: "can't be / or the home folder" };
  if (!v.startsWith("/") && !v.startsWith("~/")) return { problem: "must start with / or ~/" };
  if (v.includes("//")) return { problem: "can't have // in it" };
  if (v.split("/").some((p) => p === "." || p === "..")) return { problem: "can't have . or .. in it" };
  const path = v.startsWith("~/") ? home().replace(/\/+$/, "") + v.slice(1) : v;
  const h = home().replace(/\/+$/, "") || "/";
  if (path === h || h.startsWith(path + "/")) return { problem: "can't be / or the home folder, or a folder above it" };
  return { path };
}

// "types": ["book", "code", ...] or [{ "name": "book", "label": "Books" }, ...].
// Anything wrong in it and the whole list falls back to the defaults, with a warning.
// Labels are a map without a prototype, so a type called "constructor" has no inherited label.
function readTypes(value) {
  const none = { types: DEFAULT_TYPES, labels: Object.create(null) };
  if (value === undefined) return none;
  const bad = (why) => ({ ...none, warning: `"types" ${why}; using the default types.` });
  if (!Array.isArray(value) || !value.length) return bad("must be a non-empty list");
  if (value.length > MAX_TYPES) return bad(`can have at most ${MAX_TYPES} entries`);
  const types = [], labels = Object.create(null);
  for (const entry of value) {
    const name = typeof entry === "string" ? entry : entry?.name;
    if (typeof name !== "string" || !TYPE_NAME.test(name)) {
      return bad(`has ${JSON.stringify(name ?? entry)}, not a folder name (lowercase letters, digits, - and _)`);
    }
    if (types.includes(name)) return bad(`lists "${name}" twice`);
    const label = typeof entry === "object" ? entry.label : undefined;
    if (label !== undefined && (typeof label !== "string" || !label.trim() || label.length > 24 || CONTROL.test(label))) {
      return bad(`has a bad label for "${name}" (1 to 24 characters on one line)`);
    }
    types.push(name);
    if (label !== undefined) labels[name] = label.trim();
  }
  return { types, labels };
}

// "agent": "codex", "claude --model opus" (split on spaces) or ["claude", "--model", "opus"].
function readAgent(value) {
  if (value === undefined) return { agent: DEFAULT_AGENT };
  const argv = typeof value === "string" ? value.trim().split(/\s+/).filter(Boolean) : value;
  const ok = Array.isArray(argv) && argv.length > 0 && argv.every((a) => typeof a === "string" && a.length > 0 && !a.includes("\0"));
  return ok ? { agent: argv } : { agent: DEFAULT_AGENT, warning: '"agent" must be a command or a list of its arguments; using claude.' };
}

// "agentName": what the buttons call the agent ("Develop with <name>"). 1 to 24 characters on one line.
function readAgentName(value) {
  if (value === undefined) return { agentName: null };
  if (typeof value === "string" && value.trim() && value.trim().length <= 24 && !CONTROL.test(value.trim())) return { agentName: value.trim() };
  return { agentName: null, warning: '"agentName" must be 1 to 24 characters on one line; the buttons use the command\'s name.' };
}

// "projectsRoot": where Start project puts new projects ("~/code"); a folder as checkFolder says, else ignored.
function readProjectsRoot(value) {
  if (value === undefined || value === null) return { projectsRoot: null };
  const { path, problem } = checkFolder(value);
  return path ? { projectsRoot: path } : { projectsRoot: null, warning: `"projectsRoot" ${problem}; Start project will ask where.` };
}

// "folder": the ideas folder. Missing or wrong, ~/ideas is used and `folderNote` says why
// (the side panel warns, and capture shows where it will save).
function readFolder(value, problem) {
  const fallback = expand(DEFAULT_FOLDER);
  if (problem) return { folder: fallback, folderNote: `${problem}: using ${DEFAULT_FOLDER}.` };
  if (value === undefined) return { folder: fallback, folderNote: `profiles.json → profiles.ideas has no "folder": using ${DEFAULT_FOLDER}.` };
  const check = checkFolder(value);
  if (check.problem) return { folder: fallback, folderNote: `"folder" ${check.problem}: using ${DEFAULT_FOLDER}.` };
  return { folder: check.path, folderNote: null };
}

// What the view starts with until the settings are read: exactly the defaults.
export const defaultConfig = () => ({
  folder: expand(DEFAULT_FOLDER),
  folderNote: null,
  autocommit: true,
  types: DEFAULT_TYPES,
  labels: Object.create(null),
  agent: DEFAULT_AGENT,
  agentName: null,
  projectsRoot: null,
  warnings: [],
});

// { folder, folderNote, autocommit, types, labels, agent, agentName, projectsRoot, warnings }:
// every setting checked, defaults filled in.
export async function ideasConfig() {
  const { s, problem } = await settings();
  const config = defaultConfig();
  const f = readFolder(s.folder, problem);
  config.folder = f.folder;
  config.folderNote = f.folderNote;
  // On unless profiles.json says "autocommit": false.
  config.autocommit = s.autocommit !== false;
  const t = readTypes(s.types);
  config.types = t.types;
  config.labels = t.labels;
  const a = readAgent(s.agent);
  config.agent = a.agent;
  const n = readAgentName(s.agentName);
  config.agentName = n.agentName;
  const r = readProjectsRoot(s.projectsRoot);
  config.projectsRoot = r.projectsRoot;
  config.warnings = [f.folderNote, t.warning, a.warning, n.warning, r.warning].filter(Boolean);
  return config;
}
