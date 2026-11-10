// The markdown preview's pure parts: images split out for drawing, and link targets.
// No host calls here, so the tests can run it under node.

// Markdown's images: ![alt](src "title") with src bare or in <angle brackets>,
// a linked one [![alt](src)](link), and HTML's <img src=…>.
const DEST = String.raw`\s*(?:<([^<>\n]*)>|((?:[^\s()<>]|\([^\s()<>]*\))+))(?:\s+(?:"[^"]*"|'[^']*'|\([^()]*\)))?\s*\)`;
const IMG = String.raw`(?<!\\)!\[((?:[^\[\]\\]|\\.)*)\]\(` + DEST;
const LINKED = String.raw`\[\s*` + IMG + String.raw`\s*\]\(` + DEST;
const HTML_IMG = String.raw`<img\b[^<>\n]{0,2000}>`; // bounded: a long line of "<img" stays fast
const ANY = new RegExp(`${LINKED}|${IMG}|${HTML_IMG}`, "gi");
const attr = (tag, name) => tag.match(new RegExp(String.raw`\s${name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+?))(?=\s|\/?>|$)`, "i"))?.slice(1).find(v => v !== undefined) ?? null;

// One image unit as { alt, src, link? }, or null when `m` (a match of ANY) is none.
function unit(m) {
  if (m[1] !== undefined) return { alt: m[1], src: m[2] ?? m[3], link: m[4] ?? m[5] };
  if (m[6] !== undefined) return { alt: m[6], src: m[7] ?? m[8] };
  const src = attr(m[0], "src");
  return src ? { alt: attr(m[0], "alt") ?? "", src } : null;
}

// A line that is only one image (with an optional link, and for HTML optional
// <p>/<div>/<center> and <a href> around it): that image, else null.
const WRAP = /^(?:<(?:p|div|center)\b[^>]*>\s*)*(?:<a\b([^>]*)>\s*)?(<img\b[^<>\n]{0,2000}>)\s*(?:<\/a>\s*)?(?:<\/(?:p|div|center)>\s*)*$/i;
function blockImage(line) {
  const s = line.trim();
  const md = s.match(new RegExp(`^(?:${LINKED}|${IMG})$`, "i"));
  if (md) {
    ANY.lastIndex = 0;
    return unit(ANY.exec(s));
  }
  const html = s.match(WRAP);
  if (!html) return null;
  const src = attr(html[2], "src");
  if (!src) return null;
  const link = html[1] !== undefined ? attr(` ${html[1]}`, "href") : null;
  return { alt: attr(html[2], "alt") ?? "", src, ...(link ? { link } : {}) };
}

// Where in `line` markdown isn't markdown: code spans and HTML comments, as
// [start, end) ranges. `comment` says the line starts inside a comment; the
// result says whether it ends inside one.
function masked(line, comment) {
  const ranges = [];
  let i = 0;
  while (i < line.length) {
    if (comment) {
      const end = line.indexOf("-->", i);
      ranges.push([i, end < 0 ? line.length : end + 3]);
      if (end < 0) return { ranges, comment: true };
      i = end + 3; comment = false;
    } else if (line[i] === "`") {
      let n = 0;
      while (line[i + n] === "`") n++;
      let j = i + n, close = -1;
      while (j < line.length) {
        if (line[j] !== "`") { j++; continue; }
        let k = 0;
        while (line[j + k] === "`") k++;
        if (k === n) { close = j; break; }
        j += k;
      }
      if (close < 0) i += n;
      else { ranges.push([i, close + n]); i = close + n; }
    } else if (line.startsWith("<!--", i)) {
      comment = true;
      ranges.push([i, i + 4]); i += 4;
    } else i++;
  }
  return { ranges, comment };
}

// An image in running text: its alt text stays, as a link's text when it's linked.
function inlineText(line, ranges) {
  ANY.lastIndex = 0;
  return line.replace(ANY, (...args) => {
    const whole = args[0], at = args[args.length - 2];
    if (ranges.some(([a, b]) => at < b && at + whole.length > a)) return whole;
    const u = unit(args);
    if (!u) return whole;
    const alt = u.alt || u.src.replace(/[?#].*$/, "").split("/").filter(Boolean).pop() || "image";
    return u.link !== undefined ? `[${alt}](${args[4] !== undefined ? `<${args[4]}>` : u.link})` : alt;
  });
}

const FENCE = /^(\s*)(`{3,}|~{3,})/;
const BREAK = /^ {0,3}(?:#{1,6}(?:\s|$)|([-*_])(?:\s*\1){2,}\s*$)/; // a heading or a thematic break
const QUOTE = /^ {0,3}>\s?/;
const LIST = /^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)/;
const INDENTED = /^(?: {4}|\t| {1,3}\t)/;

// Markdown split around its images, which TextView doesn't draw: text parts and
// { alt, src, link? } parts. Only an image alone on its line (a block image) is
// split out (also a list item's own paragraph, a quote's line); one in running
// text (a table, a sentence, a badge row) becomes its alt
// text. Code (fenced, indented, spans) and HTML comments are left alone.
export function splitImages(md) {
  const parts = [];
  let text = "", fence = null, comment = false, list = false, prev = "blank";
  for (const line of md.split("\n")) {
    const blank = !line.trim();
    if (fence) {
      const f = line.match(/^\s*(`{3,}|~{3,})\s*$/);
      if (f && f[1][0] === fence[0] && f[1].length >= fence.length) fence = null;
      text += line + "\n";
      continue;
    }
    const indent = line.match(/^[ \t]*/)[0].replace(/\t/g, "    ").length;
    if (!comment) {
      if (BREAK.test(line)) list = false;
      // A fence: up to 3 spaces in, or more inside a list item (else it's indented code).
      const f = line.match(FENCE);
      if (f && (indent <= 3 || list) && !(f[2][0] === "`" && line.slice(f[0].length).includes("`"))) {
        if (!indent) list = false;
        fence = f[2]; text += line + "\n"; prev = "code";
        continue;
      }
      // Indented code: after a blank line (or more code), outside a list.
      if (INDENTED.test(line) && !blank && !list && (prev === "blank" || prev === "code")) {
        text += line + "\n"; prev = "code";
        continue;
      }
    }
    const startsInComment = comment;
    const m = masked(line, comment);
    comment = m.comment;
    if (!blank && !startsInComment) {
      if (LIST.test(line) && !BREAK.test(line)) list = true;
      else if (!indent && prev === "blank") list = false;
    }
    // A block image: alone on its line (or alone in a quote's line), and in a
    // list only as an item's own paragraph (indented, after a blank line).
    const where = list ? indent > 0 && prev === "blank" : indent <= 3;
    const block = !startsInComment && !m.ranges.length && where ? blockImage(line.replace(QUOTE, "")) : null;
    if (block) {
      if (text.trim()) parts.push(text);
      text = "";
      parts.push(block);
    } else text += inlineText(line, m.ranges) + "\n";
    prev = blank ? "blank" : "text";
  }
  if (text.trim()) parts.push(text);
  return parts;
}

// A markdown link's target as a path relative to the panel's root, or null when
// it isn't a local file there. `from` is the linking file, relative to the root.
export function linkTarget(url, root, from) {
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
