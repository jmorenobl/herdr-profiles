// Profiles: switches the layout to the one the active space's project asks for.
// Invisible: lives as an empty floating block in every profile layout.
// Rules and profiles are in ~/.config/herdr-app/profiles.json.
//
// It only acts when the active space changes, so a manual layout.switch
// (cmd-shift-l) is respected until you go to another space.
import { View, div } from "gpui-kit";
import { spaces, panes, layouts, shared, setShared, run, exec, readTextFile, appHome, home } from "herdr";

const HANDLED = "profiles.space";
const MARKER = ".herdr-profile";

const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const own = (o, k) => typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);

// profiles.json as { default, profiles, rules }, whatever shape the file has:
// a profile is an object, a rule is an object, anything else is left out.
export async function loadConfig() {
  const empty = { default: null, profiles: {}, rules: [] };
  const text = await readTextFile(`${appHome()}/profiles.json`).catch(() => null);
  if (!text) return empty;
  let c;
  try {
    c = JSON.parse(text);
  } catch (e) {
    console.log(`profiles.json is not valid JSON: ${e}`);
    return empty;
  }
  if (!isObject(c)) {
    console.log("profiles.json is not a JSON object: using the default layout");
    return empty;
  }
  const profiles = isObject(c.profiles) ? Object.fromEntries(Object.entries(c.profiles).filter(([, p]) => isObject(p))) : {};
  return {
    default: typeof c.default === "string" ? c.default : null,
    profiles,
    rules: Array.isArray(c.rules) ? c.rules.filter(isObject) : [],
  };
}

export const expand = (p, machine) =>
  !machine && typeof p === "string" && (p === "~" || p.startsWith("~/")) ? home() + p.slice(1) : p;

// Where a space works: its first terminal's live folder, else where its new terminals start.
function spaceFolder(space) {
  const tabIds = space.tabs.map((t) => t.id);
  for (const tab of tabIds) {
    const p = panes().find((p) => p.tab === tab && p.terminal && p.cwd);
    if (p) return p.cwd;
  }
  return space.folder || (space.machine ? null : home());
}

// Looks for `name` in `folder` and its parents; prints the match's path.
// `~` is that machine's home; a folder that isn't absolute has no parents to look in.
export const FIND_UP = 'd=$1; case $d in "~") d=$HOME;; "~/"*) d=$HOME/${d#"~/"};; esac; case $d in /*) ;; *) exit 1;; esac; while :; do if [ -e "$d/$2" ]; then printf "%s" "$d/$2"; exit 0; fi; p=$(dirname "$d"); [ "$p" = "$d" ] && exit 1; d=$p; done';

async function findUp(folder, name, on) {
  const r = await exec("sh", ["-c", FIND_UP, "profiles", folder, name], { on, timeout: 5000 }).catch(() => null);
  return r?.code === 0 ? r.stdout : null;
}

const inside = (folder, root) => folder === root || folder.startsWith(root.replace(/\/$/, "") + "/");

export async function profileFor(space, config) {
  const folder = spaceFolder(space);
  if (!folder) return config.default;
  const on = space.machine;
  // 1. A `.herdr-profile` file in the project (or a parent) names its profile.
  const marker = await findUp(folder, MARKER, on);
  if (marker) {
    const name = (await readTextFile(marker, { on }).catch(() => null))?.trim();
    if (own(config.profiles, name)) return name;
  }
  // 2. The first rule that matches, in order.
  for (const rule of config.rules) {
    if (!own(config.profiles, rule.profile)) continue; // not built yet: skip it
    const path = typeof rule.path === "string" && rule.path ? rule.path : null;
    const has = typeof rule.has === "string" && rule.has ? rule.has : null;
    if ((rule.path != null && !path) || (rule.has != null && !has)) continue; // not a folder or a name
    if (!path && !has) continue;
    if (path && !inside(folder, expand(path, on))) continue;
    if (has && !(await findUp(folder, has, on))) continue;
    return rule.profile;
  }
  return config.default;
}

export default class Profiles extends View {
  init() {
    this.busy = null;
  }

  check(cx) {
    const space = spaces().find((s) => s.active);
    if (!space || shared(HANDLED) === space.id || this.busy === space.id) return;
    this.busy = space.id;
    cx.spawn(async () => {
      try {
        let config = { default: null, profiles: {}, rules: [] }, profile = null;
        try {
          config = await loadConfig();
          profile = await profileFor(space, config);
        } catch (e) {
          console.log(`profiles: can't choose a profile: ${e}`);
          profile = config.default;
        }
        const layout = own(config.profiles, profile) ? config.profiles[profile].layout : null;
        const name = typeof layout === "string" ? layout : null;
        // The person may have moved on while we looked.
        if (spaces().find((s) => s.active)?.id !== space.id) return;
        setShared(HANDLED, space.id);
        setShared("profiles.active", profile ?? null);
        if (name && layouts().includes(name) && shared("layout") !== name) run("layout.switch", { name });
      } finally {
        // Another space's check may have started meanwhile: that one is still busy.
        if (this.busy === space.id) this.busy = null;
      }
    });
  }

  render(cx) {
    this.check(cx);
    return div();
  }
}
