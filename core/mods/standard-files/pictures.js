// An image on another machine, copied into the Herdr home's cache so image()
// can show it. Nothing there can write binary over the connection, so it comes
// as base64: the other machine prints it, and this computer writes it into the
// cache in pieces (one argument each), then decodes it. Each version of the
// file (its time and size) gets its own name, so an edited image shows fresh
// and an unchanged one is copied once.

export const MAX_BYTES = 5000000; // base64 of it stays under exec's 8 MiB of output
export const PIECE = 100000; // characters per argument: Linux takes up to 128 KiB in one

// On the other machine: the file's time and size, then its bytes as base64.
export const STAT = `stat -c '%Y %s' "$1" 2>/dev/null || stat -f '%m %z' "$1"`;
export const READ = `base64 < "$1" | tr -d '\\n'`;

// Here: $1 the cache folder, $2 the file's name in it, $3 the step, $4 this copy's
// token (two copies of one image don't share a part file), $5 a piece of base64.
// check prints the name when it's there already (else exit 3, after dropping files
// unused for 30 days); add appends a piece; done decodes it into place.
export const STORE = `dir=$1 name=$2 out="$1/$2" part="$1/.$2.$4"
case $3 in
check) if [ -s "$out" ]; then printf '%s' "$name"; exit 0; fi
  mkdir -p "$dir" || exit 1; find "$dir" -type f -atime +30 -delete 2>/dev/null; exit 3;;
add) printf '%s' "$5" >> "$part.b64";;
done) if base64 --decode < "$part.b64" > "$part" && [ -s "$part" ] && mv "$part" "$out"; then rm -f "$part.b64"; printf '%s' "$name"; exit 0; fi
  rm -f "$part" "$part.b64"; exit 1;;
drop) rm -f "$part" "$part.b64";;
esac`;

// FNV-1a over UTF-16 units, 32 bits, as hex: a short, stable name for the machine,
// path and version.
export function hash(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, "0");
}

/** Copies `path` on machine `on` into `dir` (this computer) with extension `ext`.
 *  `exec` is herdr's. Resolves to { name } (the file in `dir`) or { error }. */
export async function fetchRemote(exec, { on, path, dir, ext }) {
  const stat = await exec("sh", ["-c", STAT, "files", path], { on, timeout: 10000 });
  const [time, size] = stat.code === 0 ? stat.stdout.trim().split(/\s+/) : [];
  if (!size) return { error: "can't read it" };
  if (Number(size) > MAX_BYTES) return { error: "too big to copy here" };
  const name = `${hash(`${on}:${path} ${time} ${size}`)}.${ext}`;
  const store = (step, token = "", piece = "") => exec("sh", ["-c", STORE, "files", dir, name, step, token, piece], { timeout: 30000 });
  const cached = await store("check");
  if (cached.code === 0) return { name: cached.stdout.trim() };
  if (cached.code !== 3) return { error: "can't cache it" };
  const data = await exec("sh", ["-c", READ, "files", path], { on, timeout: 60000 });
  if (data.code !== 0 || !data.stdout) return { error: "can't read it" };
  const token = Math.random().toString(36).slice(2, 10);
  try {
    for (let i = 0; i < data.stdout.length; i += PIECE) {
      if ((await store("add", token, data.stdout.slice(i, i + PIECE))).code !== 0) throw new Error("add");
    }
    const done = await store("done", token);
    return done.code === 0 ? { name: done.stdout.trim() } : { error: "can't cache it" };
  } catch {
    await store("drop", token).catch(() => null);
    return { error: "can't cache it" };
  }
}
