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

export async function loadConfig() {
  const text = await readTextFile(`${appHome()}/profiles.json`).catch(() => null);
  if (!text) return { default: null, profiles: {}, rules: [] };
  try {
    const c = JSON.parse(text);
    return { default: c.default ?? null, profiles: c.profiles ?? {}, rules: c.rules ?? [] };
  } catch (e) {
    console.log(`profiles.json is not valid JSON: ${e}`);
    return { default: null, profiles: {}, rules: [] };
  }
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
const FIND_UP = 'd=$1; while :; do if [ -e "$d/$2" ]; then printf "%s" "$d/$2"; exit 0; fi; [ "$d" = / ] || [ -z "$d" ] && exit 1; d=$(dirname "$d"); done';

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
    if (name && config.profiles[name]) return name;
  }
  // 2. The first rule that matches, in order.
  for (const rule of config.rules) {
    if (!config.profiles[rule.profile]) continue; // not built yet: skip it
    if (rule.path && !inside(folder, expand(rule.path, on))) continue;
    if (rule.has && !(await findUp(folder, rule.has, on))) continue;
    if (!rule.path && !rule.has) continue;
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
        const config = await loadConfig();
        const profile = await profileFor(space, config);
        const name = config.profiles[profile]?.layout;
        // The person may have moved on while we looked.
        if (spaces().find((s) => s.active)?.id !== space.id) return;
        setShared(HANDLED, space.id);
        setShared("profiles.active", profile ?? null);
        if (name && layouts().includes(name) && shared("layout") !== name) run("layout.switch", { name });
      } finally {
        this.busy = null;
      }
    });
  }

  render(cx) {
    this.check(cx);
    return div();
  }
}
