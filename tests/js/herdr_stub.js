// A stand-in for Herdr's `herdr` module, for testing the ideas mod's pure parts under node.
// exec runs only `sh` (the mod's folder listings, on throwaway folders); anything else throws,
// so nothing like `open` can run.
import { execFileSync } from "node:child_process";

export const state = { profiles: null, home: "/home/u", appHome: "/home/u/.config/herdr-app", platform: "macos" };
export const home = () => state.home;
export const appHome = () => state.appHome;
export const window = () => ({ platform: state.platform });
export async function readTextFile(path) {
  if (path === `${state.appHome}/profiles.json` && state.profiles !== null) {
    return typeof state.profiles === "string" ? state.profiles : JSON.stringify(state.profiles);
  }
  throw new Error("No such file");
}
export async function exec(cmd, args) {
  if (cmd !== "sh") throw new Error(`exec ${cmd} is not allowed in tests`);
  const stdout = execFileSync("sh", args, { encoding: "utf8" });
  return { code: 0, stdout, stderr: "" };
}
const fail = (name) => () => { throw new Error(`${name} is not available in tests`); };
export const writeTextFile = fail("writeTextFile");
export const run = fail("run");
export const notify = fail("notify");
export const spaces = () => [];
export const panes = () => [];
export const shared = () => null;
export const setShared = fail("setShared");
export const props = () => ({});
export const closeOverlay = fail("closeOverlay");
