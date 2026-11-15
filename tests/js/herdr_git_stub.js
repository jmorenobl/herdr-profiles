// A stand-in for Herdr's `herdr` module backed by real files and real git, for testing the
// ideas mod's store and views under node (tests/test_ideas_store.py). Throwaway folders only.
// exec runs only sh, git, mkdir, mv and test; anything else (open, claude, …) throws.
// git runs with its own identity and without the person's git config (no hooks, no signing).
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export const state = {
  home: "/home/u", appHome: "/home/u/.config/herdr-app", platform: "macos",
  profiles: null,          // profiles.json's content (an object or text), or null: no file
  props: {},
  spaces: [], panes: [],
  shared: new Map(),
  notes: [],               // notify() calls
  runs: [],                // run() calls: [name, args]
  failWrite: null,         // (path) => true makes writeTextFile reject for that path
  beforeWrite: null,       // (path) => void runs just before a write is checked
  failExec: null,          // (cmd, args) => true makes exec reject for that call
  // Other machines: each name's home folder. exec and readTextFile with { on } still run here,
  // with HOME set to that home, and are recorded; an `unreachable` machine rejects them.
  machines: {},
  unreachable: new Set(),
  calls: [],               // [{ on, what }]: every exec and readTextFile, and where it ran
  writes: [],              // paths writeTextFile (this computer's) wrote
  agents: [],              // what knownAgents() answers
};

export const GIT_ENV = {
  ...process.env,
  GIT_AUTHOR_NAME: "Ideas Test", GIT_AUTHOR_EMAIL: "ideas-test@example.invalid",
  GIT_COMMITTER_NAME: "Ideas Test", GIT_COMMITTER_EMAIL: "ideas-test@example.invalid",
  GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1",
};

const ALLOWED = new Set(["sh", "git", "mkdir", "mv", "test"]);
const reach = (on) => {
  if (on && state.unreachable.has(on)) throw new Error(`cannot reach ${on}`);
  if (on && !(on in state.machines)) throw new Error(`no machine called ${on}`);
};
export async function exec(cmd, args = [], opts = {}) {
  if (!ALLOWED.has(cmd)) throw new Error(`exec ${cmd} is not allowed in tests`);
  if (state.failExec?.(cmd, args)) throw new Error("exec refused by the test");
  state.calls.push({ on: opts.on ?? null, what: cmd });
  reach(opts.on);
  state.execs = (state.execs ?? 0) + 1;
  const env = opts.on ? { ...GIT_ENV, HOME: state.machines[opts.on] } : GIT_ENV;
  const r = spawnSync(cmd, args, { encoding: "utf8", cwd: opts.cwd, env, timeout: opts.timeout ?? 30000 });
  if (r.error) throw r.error;
  return { code: r.status ?? -1, stdout: r.stdout ?? "", stderr: r.stderr ?? "" };
}

export const home = () => state.home;
export const appHome = () => state.appHome;
export const window = () => ({ platform: state.platform });

export async function readTextFile(p, opts = {}) {
  state.calls.push({ on: opts.on ?? null, what: "read" });
  reach(opts.on);
  if (p === `${state.appHome}/profiles.json` && !opts.on) {
    if (state.profiles === null) return null;
    return typeof state.profiles === "string" ? state.profiles : JSON.stringify(state.profiles);
  }
  try { return fs.readFileSync(p, "utf8"); } catch { return null; }
}

// Like Herdr's: only if the file is still `expected` (null: it must not exist), replaced atomically.
export async function writeTextFile(p, text, expected) {
  state.beforeWrite?.(p);
  if (state.failWrite?.(p)) throw new Error("write refused by the test");
  const cur = fs.existsSync(p) ? fs.readFileSync(p, "utf8") : null;
  if (cur !== expected) throw new Error("stale snapshot");
  state.writes.push(p);
  const tmp = path.join(path.dirname(p), `.${path.basename(p)}.tmp-${process.pid}`);
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, p);
  return null;
}

export const shared = (k) => (state.shared.has(k) ? state.shared.get(k) : null);
export const setShared = (k, v) => { state.shared.set(k, v); return null; };
export const notify = (n) => { state.notes.push(n); return String(state.notes.length); };
export const run = (name, args) => { state.runs.push([name, args]); return null; };
export const knownAgents = async (opts = {}) => { state.calls.push({ on: opts.on ?? null, what: "knownAgents" }); return state.agents; };
export const spaces = () => state.spaces;
export const panes = () => state.panes;
export const props = () => state.props;
export const closeOverlay = () => null;
// Never resolve: the views' command and watch loops just wait.
export const nextCommand = () => new Promise(() => {});
export const watchFolder = () => new Promise(() => {});
// Each color is its own name (t.dim is "dim"), so a test can tell which one was used.
export const theme = () => new Proxy({}, { get: (_t, k) => (typeof k === "string" ? k : undefined) });
