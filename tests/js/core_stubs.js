// Stand-ins for Herdr's `herdr`, `gpui-kit` and `gpui-base` modules, for testing
// the core mods' pure parts under node (tests/test_core_mods.py). exec runs only
// `sh` (the switcher's FIND_UP, on throwaway folders); anything else throws.
import { execFileSync } from "node:child_process";

export const state = { profiles: null, home: "/home/u", appHome: "/home/u/.config/herdr-app", panes: [], files: {} };
export const home = () => state.home;
export const appHome = () => state.appHome;
export async function readTextFile(path) {
  if (path === `${state.appHome}/profiles.json` && state.profiles !== null) {
    return typeof state.profiles === "string" ? state.profiles : JSON.stringify(state.profiles);
  }
  if (path in state.files) return state.files[path];
  throw new Error("No such file");
}
export async function exec(cmd, args) {
  if (cmd !== "sh") throw new Error(`exec ${cmd} is not allowed in tests`);
  try {
    return { code: 0, stdout: execFileSync("sh", args, { encoding: "utf8", timeout: 5000 }), stderr: "" };
  } catch (e) {
    if (typeof e.status !== "number") throw e;
    return { code: e.status, stdout: e.stdout ?? "", stderr: e.stderr ?? "" };
  }
}
const fail = (name) => () => { throw new Error(`${name} is not available in tests`); };
export const spaces = () => [];
export const panes = () => state.panes;
export const layouts = () => [];
export const shared = () => null;
export const setShared = fail("setShared");
export const run = fail("run");

// gpui: the builders aren't used by the functions under test.
export class View {}
const nothing = fail("UI");
export const div = nothing, svg = nothing, image = nothing, h_flex = nothing, v_flex = nothing;
