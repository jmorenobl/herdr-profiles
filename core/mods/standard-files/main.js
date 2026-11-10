// A lazy file browser for the focused pane's folder, with bounded read-only previews.
// Cloned from Herdr's `files` (0.1.14) for the standard profile: markdown files open
// rendered, with a toggle back to their source.
import { View, div, svg, image } from "gpui-kit";
import { v_flex, h_flex, Editor, EditorState, TextView } from "gpui-base";
import { spaces, panes, focused, exec, readTextFile, watchFolder, theme, settings, window, appHome } from "herdr";

function location() {
  const space = spaces().find(s => s.active), f = focused();
  const pane = f?.pane ? panes().find(p => p.pane === f.pane) : null;
  const on = f?.pane === null ? (f.terminal?.includes("/") ? f.terminal.split("/")[0] : null) : space?.machine ?? null;
  return { cwd: pane?.cwd || f?.cwd || space?.folder, on, space: space?.id };
}
const key = () => JSON.stringify(location());
const LANG = { ts: "js", tsx: "js", mts: "js", cts: "js", jsx: "js", mjs: "js", toml: "yaml", jsonc: "json", svelte: "html", vue: "html" };
const PER_FOLDER = 500, TOTAL = 5000;
const MARKDOWN = new Set(["md", "markdown", "mdown", "mkd"]);
const isMarkdown = path => MARKDOWN.has(path?.split(".").pop()?.toLowerCase());

// Markdown split around its images, which TextView doesn't draw: text parts and
// { alt, src } parts. Fenced code is left alone.
const IMAGE = /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)|<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;
function splitImages(md) {
  const parts = []; let text = "", fence = null;
  for (const line of md.split("\n")) {
    const f = line.match(/^\s*(```|~~~)/);
    if (fence) { if (f && f[1] === fence) fence = null; text += line + "\n"; continue; }
    if (f) { fence = f[1]; text += line + "\n"; continue; }
    let last = 0, m;
    IMAGE.lastIndex = 0;
    while ((m = IMAGE.exec(line))) {
      text += line.slice(last, m.index);
      if (text.trim()) parts.push(text); text = "";
      parts.push({ alt: m[1] ?? "", src: m[2] ?? m[3] });
      last = IMAGE.lastIndex;
    }
    text += line.slice(last) + "\n";
  }
  if (text.trim()) parts.push(text);
  return parts;
}

// Copies $1 (a file, or a URL when $4 is "url") into the cache folder $2 as
// <key>.$3 and prints that name. The key changes with the file's time and size,
// so an edited image is shown fresh; files unused for 30 days are removed.
const CACHE = `src=$1 dir=$2 ext=$3
if [ "$4" = url ]; then v=; else v=$(stat -c '%Y %s' "$src" 2>/dev/null || stat -f '%m %z' "$src") || exit 1; fi
key=$(printf '%s %s' "$src" "$v" | cksum | cut -d' ' -f1)
out="$dir/$key.$ext"
mkdir -p "$dir" || exit 1
if [ ! -s "$out" ]; then
  find "$dir" -type f -atime +30 -delete 2>/dev/null
  if [ "$4" = url ]; then curl -fsSL --max-time 20 --max-filesize 20000000 -o "$out.part" "$src" || { rm -f "$out.part"; exit 1; }
  else cp "$src" "$out.part" || exit 1; fi
  mv "$out.part" "$out"
fi
printf '%s' "$key.$ext"`;

// A markdown link's target as a path relative to the panel's root, or null when
// it isn't a local file there. `from` is the linking file, relative to the root.
function linkTarget(url, root, from) {
  let p = url;
  if (/^file:\/\//i.test(p)) p = p.replace(/^file:\/\/[^/]*/i, "");
  else if (/^[a-z][a-z0-9+.-]*:/i.test(p)) return null;
  p = p.replace(/[?#].*$/, "");
  try { p = decodeURIComponent(p); } catch { return null; }
  if (!p) return null;
  if (p.startsWith("/")) {
    if (!root || !p.startsWith(root + "/")) return null;
    p = p.slice(root.length + 1);
  } else p = [...from.split("/").slice(0, -1), p].join("/");
  const parts = [];
  for (const part of p.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") { if (!parts.length) return null; parts.pop(); }
    else parts.push(part);
  }
  return parts.length ? parts.join("/") : null;
}

async function directory(path, on) {
  const windowsDirectory = async () => {
    // Windows PowerShell otherwise uses the console code page; exec decodes UTF-8.
    // Links keep directory attributes even when dangling; check their target.
    // Other reparse points (OneDrive's folders) have no LinkType and are folders.
    // PowerShell reads curly single quotes as quotes too, so they're doubled like '.
    const r = await exec("powershell", ["-NoProfile", "-Command", "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); & { param($p) @(Get-ChildItem -LiteralPath $p -Force -ErrorAction Stop | Where-Object Name -ne '.git' | Select-Object -First 501 | ForEach-Object { @{ name=$_.Name; dir=($_.PSIsContainer -and (-not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not $_.LinkType -or ($_.Target -and [IO.Directory]::Exists(([IO.Path]::Combine([IO.Path]::GetDirectoryName($_.FullName), $_.Target[0])))))) } }) | ConvertTo-Json -Compress } '" + path.replace(/['‘’‚‛]/g, "$&$&") + "'"], { on });
    if (r.code !== 0) throw new Error(r.stderr || "Cannot list this folder");
    const result = JSON.parse(r.stdout || "[]");
    return Array.isArray(result) ? result : [result];
  };
  if (!on && window()?.platform === "windows") return windowsDirectory();
  const script = 'n=0; for p in "$1"/* "$1"/.[!.]* "$1"/..?*; do [ -e "$p" ] || [ -L "$p" ] || continue; name=${p##*/}; [ "$name" = .git ] && continue; if [ -d "$p" ]; then kind=d; else kind=f; fi; printf "%s\\0%s\\0" "$kind" "$name"; n=$((n+1)); [ "$n" -gt 500 ] && break; done; test -d "$1"';
  let r;
  try { r = await exec("sh", ["-c", script, "files", path], { on }); }
  catch (e) {
    if (on && String(e).includes("cannot start sh: program not found")) return windowsDirectory();
    throw e;
  }
  if (r.code !== 0) throw new Error(r.stderr || "Cannot list this folder");
  const fields = r.stdout.split("\0"), out = [];
  for (let i = 0; i + 1 < fields.length; i += 2) out.push({ name: fields[i + 1], dir: fields[i] === "d" });
  return out;
}

export default class Files extends View {
  init(_props, cx) {
    this.saved = new Map();
    this.entries = new Map(); this.folders = new Set(); this.pending = new Set(); this.marks = {};
    this.refresh(cx);
    cx.timer.every(10000, cx => this.refresh(cx));
  }

  watch(root, cx) {
    if (this.on || this.watched === root) return;
    this.watched = root;
    const context = this.context;
    cx.spawn(async cx => {
      try { while (this.context === context) { await watchFolder(root); if (this.current(context)) this.refresh(cx); } }
      catch { if (this.context === context) this.watched = null; }
    });
  }

  current(context) {
    return this.context === context && key() === context.key;
  }

  async loadFolder(path, context) {
    const { on, cwd: root } = context;
    const entries = await directory(path ? `${root}/${path}` : root, on);
    if (!this.current(context) || (path && !this.folders.has(path))) return;
    const used = [...this.entries.entries()].filter(([p]) => p !== path).reduce((n, [, e]) => n + e.length, 0);
    this.entries.set(path, entries.slice(0, Math.max(0, Math.min(PER_FOLDER, TOTAL - used))).sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)));
    if (entries.length > PER_FOLDER || used + entries.length > TOTAL) this.limited = true;
  }

  refresh(cx) {
    const { cwd, on } = location(), next = key();
    if (next !== this.context?.key) {
      if (this.context) this.saved.set(this.context.key, { folders: this.folders, file: this.file });
      const saved = this.saved.get(next);
      this.context = { key: next, cwd, on }; this.root = cwd; this.on = on; this.entries = new Map(); this.folders = new Set(saved?.folders);
      this.pending = new Set(); this.marks = {}; this.show(null); this.history = []; this.watched = null; this.error = null; this.limited = false;
      this.loading = false;
      if (saved?.file) this.show(saved.file, cx);
    }
    if (!cwd || this.loading) return;
    const context = this.context;
    this.loading = true;
    this.limited = false;
    cx.spawn(async cx => {
      try {
        for (const path of ["", ...this.folders]) {
          if (!this.current(context)) return;
          await this.loadFolder(path, context);
        }
        const top = await exec("git", ["rev-parse", "--show-toplevel"], { cwd, on }).catch(() => null);
        const marks = {};
        if (top?.code === 0) {
          // Writes nothing under .git (index lock, fsmonitor cookie): the folder watch would refresh again.
          const status = await exec("git", ["--no-optional-locks", "-c", "core.fsmonitor=false", "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"], { cwd, on }).catch(() => null);
          if (status?.code === 0) for (const entry of status.stdout.split("\0").filter(Boolean).slice(0, TOTAL)) {
            const xy = entry.slice(0, 2);
            marks[`${top.stdout.trim()}/${entry.slice(3)}`] = xy === "??" || xy.includes("A") ? "A" : xy.includes("U") ? "U" : xy.includes("D") ? "D" : "M";
          }
        }
        if (!this.current(context)) return;
        this.marks = marks; this.error = null; this.watch(cwd, cx);
      } catch (e) { if (this.current(context)) this.error = String(e); }
      finally { if (this.context === context) this.loading = false; cx.notify(); }
    });
  }

  toggle(path, cx) {
    if (this.folders.has(path)) {
      for (const folder of [...this.folders]) if (folder === path || folder.startsWith(path + "/")) {
        this.folders.delete(folder);
        this.entries.delete(folder);
      }
    } else {
      this.folders.add(path);
      if (!this.entries.has(path) && !this.pending.has(path)) {
        const context = this.context;
        this.pending.add(path);
        cx.spawn(async cx => {
          try { await this.loadFolder(path, context); }
          catch (e) { if (this.current(context)) this.error = String(e); }
          finally { if (this.context === context) this.pending.delete(path); cx.notify(); }
        });
      }
    }
    cx.notify();
  }

  show(path, cx) {
    this.code?.release(); this.code = null; this.file = path; this.fileError = null; this.markdown = null; this.parts = null; this.pictures = null; this.source = false;
    if (!path || !cx) return;
    const context = this.context, root = this.root, on = this.on;
    cx.spawn(async cx => {
      try {
        const text = await readTextFile(`${root}/${path}`, { on });
        if (this.file !== path || !this.current(context)) return;
        if (text === null) { this.fileError = "This file is no longer available"; return; }
        if (text.includes("\0")) { this.fileError = "Binary file · no text preview"; return; }
        if (isMarkdown(path)) {
          this.markdown = text.length > 400000 ? text.slice(0, 400000) + "\n\n… (file truncated)" : text;
          this.parts = splitImages(this.markdown);
          this.loadPictures(this.parts, cx);
        }
        const t = theme(), ext = path.includes(".") ? path.split(".").pop() : "txt";
        this.code = EditorState.new({ language: LANG[ext] ?? ext, readonly: true,
          value: text.length > 400000 ? text.slice(0, 400000) + "\n… (file truncated)" : text,
          font_family: settings().font_family, font_size: 12,
          syntax: { keyword: t.ansi5, string: t.ansi2, comment: t.dim, function: t.ansi4, type: t.ansi3, number: t.ansi1, constant: t.ansi6 } });
      } catch { if (this.file === path && this.current(context)) this.fileError = "Cannot preview this file (binary, too large, or unreadable)"; }
      finally { cx.notify(); }
    });
  }

  // Links to http(s) open in the browser; links to files under the root open
  // here, and ← comes back. Anything else (mailto:, outside the root) is ignored.
  follow(url, cx) {
    if (/^https?:\/\//i.test(url)) return cx.open_url(url);
    const target = linkTarget(url, this.root, this.file ?? "");
    if (!target || target === this.file) return;
    this.history.push(this.file);
    this.show(target, cx);
    cx.notify();
  }

  // An image the markdown shows. image() reads only inside the Herdr home, so
  // the file (or download) is copied to .cache/standard-files there first.
  picture({ alt, src }, i, t) {
    const state = this.pictures?.get(src);
    if (state?.path) return div().py(6).child(image(state.path).max_w_full());
    return div().id(`files-img-${i}`).my(6).px(10).py(6).rounded(6).border_1().border_color(t.border).text_size(12).text_color(t.dim)
      .child(`${state?.error ? "⚠ " : "▢ "}${alt || src}${state?.error ? ` · ${state.error}` : state ? "" : " · loading…"}`);
  }

  // Copies each image of the shown markdown into the cache, once per version.
  loadPictures(parts, cx) {
    const file = this.file, root = this.root, on = this.on;
    this.pictures = new Map();
    for (const part of parts) {
      if (typeof part === "string" || this.pictures.has(part.src)) continue;
      const src = part.src, remote = /^https?:\/\//i.test(src);
      const target = remote ? null : linkTarget(src, root, file);
      if (!remote && !target) { this.pictures.set(src, { error: "not in this folder" }); continue; }
      if (on && !remote) { this.pictures.set(src, { error: "on another machine" }); continue; }
      const ext = ((remote ? src.replace(/[?#].*$/, "") : target).match(/\.([a-z0-9]{2,5})$/i)?.[1] ?? "img").toLowerCase();
      this.pictures.set(src, { pending: true });
      cx.spawn(async cx => {
        let state;
        try {
          const r = await exec("sh", ["-c", CACHE, "files", remote ? src : `${root}/${target}`, `${appHome()}/.cache/standard-files`, ext, remote ? "url" : "file"], { timeout: 30000 });
          state = r.code === 0 && r.stdout.trim() ? { path: `.cache/standard-files/${r.stdout.trim()}` } : { error: remote ? "can't download it" : "can't read it" };
        } catch { state = { error: "can't load it" }; }
        if (this.file === file && this.pictures?.get(src)?.pending) { this.pictures.set(src, state); cx.notify(); }
      });
    }
  }

  rows(prefix, depth, out, t) {
    if (out.length >= TOTAL || depth > 40) return out;
    for (const entry of this.entries.get(prefix) ?? []) {
      if (out.length >= TOTAL) break;
      const path = prefix ? `${prefix}/${entry.name}` : entry.name, open = this.folders.has(path), mark = this.marks[`${this.root}/${path}`];
      out.push(h_flex().id(`file-${path}`).h(28).flex_none().pl(8 + depth * 18).pr(8).gap(7).items_center().rounded(7).cursor_pointer().hover(s => s.bg(t.hover))
        .on_click((_e, cx) => { if (entry.dir) this.toggle(path, cx); else { this.history = []; this.show(path, cx); } })
        .child(entry.dir ? svg(`mods/standard-files/chevron-${open ? "down" : "right"}.svg`).size(12).flex_none().text_color(t.dim) : div().w(12).flex_none())
        .child(svg(`mods/standard-files/${entry.dir ? "folder" : "file"}.svg`).size(14).flex_none().text_color(t.muted))
        .child(div().flex_1().min_w(0).truncate().child(entry.name))
        .when(Boolean(mark), el => el.child(div().text_size(11).text_color(mark === "A" ? t.ansi2 : mark === "D" || mark === "U" ? t.ansi1 : t.blocked).child(mark))));
      if (entry.dir && open) this.rows(path, depth + 1, out, t);
    }
    return out;
  }

  render(cx) {
    if (key() !== this.context?.key) this.refresh(cx);
    const t = theme();
    return v_flex().id("files").size_full().min_h(0).rounded(10).overflow_hidden().bg(t.background).border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .child(h_flex().h(42).flex_none().px(14).gap(8).items_center().border_b(1).border_color(t.border)
        .when(Boolean(this.file), el => el.child(div().id("files-back").w(20).cursor_pointer().text_color(t.muted).on_click((_e, cx) => { this.show(this.history.pop() ?? null, cx); cx.notify(); }).child("←")))
        .child(div().font_semibold().child("Files"))
        .child(div().flex_1().min_w(0).truncate().text_right().text_size(12).text_color(t.dim).child(this.file ?? this.root?.split(/[\\/]/).pop() ?? ""))
        .when(this.markdown !== null, el => el.child(div().id("files-md-toggle").flex_none().px(8).py(2).rounded(6).cursor_pointer().text_size(11)
          .text_color(t.muted).border_1().border_color(t.border).hover(s => s.bg(t.hover))
          .on_click((_e, cx) => { this.source = !this.source; cx.notify(); }).child(this.source ? "Preview" : "Source"))))
      .when(!this.file, el => el.child(v_flex().id("files-tree").flex_1().min_h(0).overflow_y_scrollbar().p(6).children(this.rows("", 0, [], t))
        .when(Boolean(this.error) || !this.entries.get("")?.length, el => el.child(div().p(8).text_size(12).text_color(t.dim).child(this.error || (this.loading ? "Loading files…" : this.root ? "No files" : "No folder"))))
        .when(this.limited, el => el.child(div().p(8).text_size(11).text_color(t.dim).child("File list limited to 500 entries per folder and 5,000 total")))))
      .when(this.markdown !== null && !this.source, el => el.child(div().id("files-md").flex_1().min_h(0).overflow_y_scrollbar().px(18).py(14).text_size(14)
        .children((this.parts ?? []).map((part, i) => typeof part === "string"
          ? TextView.markdown(`files-md-${this.file}-${i}`, part).selectable(true).on_link_click((url, cx) => this.follow(url, cx))
          : this.picture(part, i, t)))))
      .when(Boolean(this.file) && (this.markdown === null || this.source), el => el.child(this.code ? Editor.new(this.code).flex_1().min_h(0) : div().p(12).text_color(t.dim).child(this.fileError || "Loading file…")));
  }
}
