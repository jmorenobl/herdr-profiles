// The ideas folder: <type>/<slug>/idea.md, plus whatever notes live beside it.
// The format is described for agents in the folder's AGENTS.md (project/AGENTS.md here).
import { exec, readTextFile, writeTextFile, home } from "herdr";

export const STATUSES = ["seed", "exploring", "ripe", "active", "parked", "dropped"];
export const OPEN = ["seed", "exploring", "ripe", "active"];
// The default idea types (folders). profiles.json can set others (config.js), so the
// functions below take the list in use as an argument.
export const DEFAULT_TYPES = ["book", "code", "legal", "other"];

// Where an idea of no known type goes: "other" if it's a type, else the last one.
export const fallbackType = (types) => (types.includes("other") ? "other" : types.at(-1));

export const expand = (p) => (p === "~" || p?.startsWith("~/") ? home() + p.slice(1) : p);
export const tilde = (p) => (p?.startsWith(home() + "/") ? "~" + p.slice(home().length) : p);

export function parse(text) {
  const meta = {};
  let body = text;
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
  if (m) {
    for (const line of m[1].split(/\r?\n/)) {
      const kv = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
      if (kv) meta[kv[1]] = kv[2].trim().replace(/^["'](.*)["']$/, "$1");
    }
    body = text.slice(m[0].length);
  }
  return { meta, body: body.trim() };
}

// Every file under <type>/<slug>/ (NUL separated, relative to the ideas folder).
// $1 is the folder, the rest are the types: passed as arguments, never pasted into the script.
const LIST = 'cd "$1" 2>/dev/null || exit 0; shift; for t in "$@"; do [ -d "$t" ] && find "$t" -mindepth 2 -maxdepth 6 -type f ! -name .DS_Store ! -path "*/.git/*" -print0; done; true';

// Top-level folders holding ideas (<folder>/<name>/<slug>/idea.md) whose name isn't in `types`:
// their ideas don't show. Hidden (dot) folders are left out.
const OTHERS = 'cd "$1" 2>/dev/null || exit 0; for d in */; do d=${d%/}; for f in "$d"/*/idea.md; do [ -f "$f" ] && printf "%s\\0" "$d"; break; done; done; true';

// The ids (<type>/<slug>) whose type isn't in `types`.
export const untypedIds = (ids, types) => (Array.isArray(ids) ? ids : []).filter((id) => !types.includes(String(id).split("/")[0]));

export async function untypedFolders(folder, types) {
  const r = await exec("sh", ["-c", OTHERS, "ideas", folder]);
  return r.stdout.split("\0").filter((d) => d && !types.includes(d));
}

// The side panel's warning about those folders, or null when there are none.
export function untypedNotice(folders) {
  if (!folders.length) return null;
  return {
    title: "Ideas: some folders aren't types",
    body: `Ideas in ${folders.join(", ")} don't show: add ${folders.length > 1 ? "them" : "it"} to "types" in profiles.json, or move those ideas.`,
  };
}

// The folder with symlinks resolved (a terminal there may report either path), or null.
const REAL = 'cd "$1" 2>/dev/null && pwd -P';

export async function listIdeas(folder, types) {
  const [r, real] = await Promise.all([exec("sh", ["-c", LIST, "ideas", folder, ...types]),
    exec("sh", ["-c", REAL, "ideas", folder]).catch(() => null)]);
  const realFolder = real?.code === 0 && real.stdout.trim() !== folder ? real.stdout.trim() || null : null;
  const byId = new Map();
  for (const rel of r.stdout.split("\0").filter(Boolean)) {
    const [type, slug, ...rest] = rel.split("/");
    if (!types.includes(type) || !rest.length) continue;
    const id = `${type}/${slug}`;
    const entry = byId.get(id) ?? { id, type, slug, hasIdea: false, files: [] };
    const file = rest.join("/");
    if (file === "idea.md") entry.hasIdea = true; else entry.files.push(file);
    byId.set(id, entry);
  }
  // Read in parallel: a reload follows every batch of changes the folder watch reports.
  const read = await Promise.all([...byId.values()].filter((e) => e.hasIdea).map(async (e) => {
    const dir = `${folder}/${e.id}`;
    const path = `${dir}/idea.md`;
    return { e, dir, path, text: await readTextFile(path).catch(() => null) };
  }));
  const out = [];
  for (const { e, dir, path, text } of read) {
    if (text === null) continue;
    const { meta, body } = parse(text);
    const { hasIdea: _, ...rest } = e;
    out.push({
      ...rest, dir, path, text, body,
      realDir: realFolder ? `${realFolder}/${e.id}` : null,
      files: e.files.sort(),
      title: meta.title || e.slug.replace(/-/g, " "),
      status: STATUSES.includes(meta.status) ? meta.status : "seed",
      created: meta.created || "",
      updated: meta.updated || null,
      origin: meta.origin || null,
      project: meta.project || null,
      why: meta.why || null,
      tags: meta.tags ? meta.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
    });
  }
  return out.sort((a, b) => touched(b).localeCompare(touched(a)) || a.title.localeCompare(b.title));
}

export const touched = (idea) => idea.updated || idea.created || "";

export const today = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

// Whole days from `date` (YYYY-MM-DD) to today; null if there's no date. Rounded: across a
// daylight saving change two local midnights are 23 or 25 hours apart.
export function daysSince(date) {
  const then = date ? Date.parse(`${date}T00:00:00`) : NaN;
  if (Number.isNaN(then)) return null;
  return Math.round((Date.parse(`${today()}T00:00:00`) - then) / 86400000);
}

// Open ideas nobody has touched in a month: the review goes through these.
export const STALE_DAYS = 30;
export const REVIEW_EVERY = 7;
const UNDECIDED = ["seed", "exploring", "ripe"];
export const isStale = (idea) => UNDECIDED.includes(idea.status) && (daysSince(touched(idea)) ?? 0) > STALE_DAYS;

// "today", "3d", "2w", "4mo", "1y"
export function ago(date) {
  if (!date) return "";
  const days = daysSince(date);
  if (days === null) return date;
  if (days <= 0) return "today";
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}

// Letters the accents-off step below leaves alone, written the usual way in ASCII.
const SPELLED = { "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i", "ĸ": "k" };

// A folder name: lowercase letters and digits of any script, accents off Latin letters
// ("Ça va" -> "ca-va", "Straße" -> "strasse", "日本語" stays), the rest turned into dashes.
export function slugify(text) {
  let s = String(text).toLowerCase();
  try { s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").normalize("NFC"); } catch { /* keep going */ }
  s = s.replace(/[ßæœøłđðþıĸ]/g, (c) => SPELLED[c]).replace(/[^\p{L}\p{N}\p{M}]+/gu, "-").replace(/^-+|-+$/g, "");
  // Cut by characters, not UTF-16 units, so no emoji or CJK letter is split in half.
  return Array.from(s).slice(0, 48).join("").replace(/-+$/, "") || "idea";
}

// At most `n` characters (code points): never half of a surrogate pair.
export const cut = (text, n) => Array.from(String(text)).slice(0, n).join("");

const clean = (v) => String(v ?? "").replace(/[\r\n]+/g, " ").trim();

const exists = async (path) => (await exec("test", ["-e", path])).code === 0;

async function freeDir(folder, type, slug) {
  let dir = `${folder}/${type}/${slug}`;
  for (let n = 2; await exists(dir); n++) dir = `${folder}/${type}/${slug}-${n}`;
  return dir;
}

// Sets (or adds) front matter keys, stamps `updated`, and writes only if the
// file still is what we read (someone may have edited it meanwhile).
export async function updateIdea(idea, changes) {
  changes = { ...changes, updated: today() };
  const lines = idea.text.split("\n");
  const end = lines[0]?.trim() === "---" ? lines.findIndex((l, i) => i > 0 && l.trim() === "---") : -1;
  let text;
  if (end > 0) {
    const head = lines.slice(1, end);
    for (const [k, v] of Object.entries(changes)) {
      const i = head.findIndex((l) => l.startsWith(`${k}:`));
      if (i >= 0) head[i] = `${k}: ${clean(v)}`; else head.push(`${k}: ${clean(v)}`);
    }
    text = ["---", ...head, ...lines.slice(end)].join("\n");
  } else {
    const head = Object.entries({ title: idea.title, ...changes }).map(([k, v]) => `${k}: ${clean(v)}`);
    text = ["---", ...head, "---", idea.text].join("\n");
  }
  await writeTextFile(idea.path, text, idea.text);
}

// The type is the folder: changing it moves the idea's folder. Returns the new id.
export async function moveIdea(folder, idea, type, types) {
  if (!types.includes(type) || type === idea.type) return idea.id;
  const dir = await freeDir(folder, type, idea.slug);
  await exec("mkdir", ["-p", `${folder}/${type}`]);
  const r = await exec("mv", [idea.dir, dir]);
  if (r.code !== 0) throw new Error(r.stderr || "Could not move the idea");
  return dir.slice(folder.length + 1);
}

// The board's own state in <folder>/.board.json: the manual order
// ({ "<status>": ["<type>/<slug>", ...] }) and the day of the last review.
const BOARD = ".board.json";

export async function readBoard(folder) {
  const text = await readTextFile(`${folder}/${BOARD}`).catch(() => null);
  let data = {};
  try { data = (text && JSON.parse(text)) || {}; } catch { /* a broken file means no state */ }
  return { text, order: data.order || {}, reviewed: data.reviewed || null };
}

// Writes only if the file is still `expected` (null: it must not exist yet). Returns the new text.
export async function writeBoard(folder, { order, reviewed }, expected) {
  const text = JSON.stringify({ version: 1, order, ...(reviewed ? { reviewed } : {}) }, null, 2) + "\n";
  await writeTextFile(`${folder}/${BOARD}`, text, expected);
  return text;
}

// Returns the new idea's id (<type>/<slug>).
export async function createIdea(folder, { title, body, type, origin }, types) {
  type = types.includes(type) ? type : fallbackType(types);
  const dir = await freeDir(folder, type, slugify(title));
  await exec("mkdir", ["-p", dir]);
  const head = [`title: ${clean(title)}`, "status: seed", `created: ${today()}`];
  if (clean(origin)) head.push(`origin: ${clean(origin)}`);
  await writeTextFile(`${dir}/idea.md`, ["---", ...head, "---", String(body ?? "").trim(), ""].join("\n"), null);
  return dir.slice(folder.length + 1);
}

// Why git can't be committed to now (a merge, rebase, cherry-pick or revert under way, a
// sequence of picks not finished, conflicts, no branch). Committing then would conclude the
// person's operation, conflict markers and all, and `git add` would mark the conflicts resolved.
const BUSY = [["MERGE_HEAD", "a merge"], ["CHERRY_PICK_HEAD", "a cherry-pick"], ["REVERT_HEAD", "a revert"],
  ["rebase-merge", "a rebase"], ["rebase-apply", "a rebase or git am"], ["sequencer", "a cherry-pick or revert of several commits"]];
const UNMERGED = BUSY.length + 1, DETACHED = BUSY.length + 2;

// One process for what close() has little time for: prints "none" when nothing changed (new
// files count even with status.showUntrackedFiles=no), else the position (from 1) of the first
// of its git paths that exists, or UNMERGED / DETACHED, or "ok". $1 is the folder.
const CHECK = `cd "$1" || exit 1; shift
[ -n "$(git status --porcelain --untracked-files=all)" ] || { echo none; exit 0; }
n=0; for p in "$@"; do n=$((n+1)); [ -e "$p" ] && { echo $n; exit 0; }; done
[ -z "$(git ls-files --unmerged)" ] || { echo ${UNMERGED}; exit 0; }
git symbolic-ref -q HEAD >/dev/null || { echo ${DETACHED}; exit 0; }
echo ok`;

// Commits everything that changed in the ideas folder, if it's a git repo of its own.
// The subject names the idea when only one changed. Returns the subject, or null.
// Throws (the side panel warns once) when the folder is inside a bigger repo or git is busy.
// Five processes, so it mostly fits in close()'s time; cut short after `git add`, the next
// commit takes what was staged.
export async function autocommit(folder, ideas, types) {
  const git = (...args) => exec("git", ["-C", folder, ...args], { timeout: 20000 });
  const top = await git("rev-parse", "--is-inside-work-tree", "--show-prefix", ...BUSY.flatMap(([p]) => ["--git-path", p]));
  const lines = top.stdout.split("\n");
  if (top.code !== 0 || lines[0] !== "true") return null;
  // A folder inside a bigger repo (a notes or dotfiles repo): a commit there would take
  // whatever else is staged in it, so only a folder that is its repo's top is committed.
  const prefix = lines[1] ?? "";
  if (prefix) throw new Error(`The ideas folder is inside a bigger git repo (as ${prefix.replace(/\/$/, "")}): autocommit only commits a folder that is a repo of its own. Set "autocommit": false to stop this warning.`);
  const paths = lines.slice(2, 2 + BUSY.length);
  if (paths.length !== BUSY.length || paths.some((x) => !x)) throw new Error("git can't read the ideas folder's repo");
  const check = (await exec("sh", ["-c", CHECK, "ideas", folder, ...paths], { timeout: 20000 })).stdout.trim();
  if (check === "none") return null;
  if (check !== "ok") {
    const n = Number(check);
    const busy = n === UNMERGED ? "it has unresolved conflicts" : n === DETACHED ? "it isn't on a branch (detached HEAD)"
      : BUSY[n - 1] ? `${BUSY[n - 1][1]} is in progress` : "git can't read the repo";
    throw new Error(`Not committing while ${busy} in the ideas folder; finish it in a terminal.`);
  }
  // Everything but Finder's .DS_Store files, even when the folder's .gitignore doesn't list them.
  if ((await git("add", "-A", "--", ".", ":(exclude,glob)**/.DS_Store")).code !== 0) throw new Error("git add failed");
  // -z: paths as they are (no quoting of non-ASCII names), "<status>\0<path>\0" each.
  const z = (await git("diff", "--cached", "--name-status", "--no-renames", "-z")).stdout.split("\0");
  const changes = [];
  for (let n = 0; n + 1 < z.length; n += 2) if (z[n]) changes.push([z[n][0], z[n + 1]]);
  if (!changes.length) return null;
  const titles = new Map(ideas.map((i) => [i.id, i.title]));
  const touchedIds = new Map();             // id -> "add" | "remove" | "update"
  let other = false;
  for (const [st, path] of changes) {
    const [type, slug, ...rest] = path.split("/");
    if (!types.includes(type) || !rest.length) { other = true; continue; }
    const id = `${type}/${slug}`;
    const kind = rest.join("/") === "idea.md" && st === "A" ? "add" : rest.join("/") === "idea.md" && st === "D" ? "remove" : "update";
    if (kind !== "update" || !touchedIds.has(id)) touchedIds.set(id, kind);
  }
  const name = (id) => titles.get(id) ?? id.split("/")[1].replace(/-/g, " ");
  let subject;
  if (touchedIds.size === 1) {
    const [[id, kind]] = touchedIds;
    subject = `${{ add: "Add idea", remove: "Remove idea", update: "Update" }[kind]}: ${name(id)}`;
  } else if (touchedIds.size > 1) subject = `Update ${touchedIds.size} ideas`;
  else subject = changes.every(([, p]) => p === ".board.json") ? "Board: order and review" : "Update the ideas folder";
  const body = changes.map(([st, p]) => `${st} ${p}`).join("\n");
  const r = await git("commit", "-q", "-m", cut(subject, 72), "-m", body);
  if (r.code !== 0) throw new Error(r.stderr.trim() || "git commit failed");
  return subject;
}
