"""Keeping up with Herdr: our clones in core/ against the Herdr they were cloned from.

upstream/herdr.json   {"version": "0.1.14",
                       "clones": {"<our clone, from the repo root>": "<Herdr's original, in the home>"}}
upstream/<original>   Herdr's originals exactly as that version shipped them: a layout's JSON, or a
                      mod's files (those Herdr records for it in installed.json).

`upstream` (make upstream) reads the originals the installed Herdr ships, from the Herdr home,
checked against the hashes Herdr keeps in installed.json (64-bit FNV-1a: of a mod file's bytes,
and of a layout's JSON written compact with sorted keys), so a copy someone edited is never taken
for Herdr's. For each clone it says, file by file, what changed since the recorded
version:

  take    Herdr changed it and ours is still the original: Herdr's can be copied over ours
  merge   Herdr changed it and so did we: merge by hand (--diff shows Herdr's change)
  new     Herdr added it
  gone    Herdr removed it

`--diff` prints Herdr's changes (recorded original -> installed one). `--save`, once the clones
are merged, records the installed Herdr's originals and version in upstream/. Nothing here ever
changes a clone: merging is the developer's, by hand.
"""

from __future__ import annotations

import difflib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import herdr
from .files import load_json
from .home import Home
from .spec import SpecError

FOLDER = "upstream"
RECORD = "herdr.json"
FNV_OFFSET, FNV_PRIME, MASK = 0xCBF29CE484222325, 0x100000001B3, (1 << 64) - 1


def fnv1a(data: bytes) -> str:
    """The hash Herdr records for a shipped file in installed.json."""
    h = FNV_OFFSET
    for byte in data:
        h = ((h ^ byte) * FNV_PRIME) & MASK
    return f"{h:016x}"


def shipped_hash(data: bytes, layout: bool) -> str | None:
    """installed.json's hash of a shipped file: a layout's is of its JSON, compact with sorted keys
    (so Herdr's own reformatting doesn't count as an edit). None when a layout isn't valid JSON."""
    if not layout:
        return fnv1a(data)
    try:
        value = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return fnv1a(json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8"))


def parse_version(text: str) -> tuple[int, int, int] | None:
    found = herdr.parse(text)
    return found[0] if found else None


@dataclass(frozen=True)
class Clone:
    ours: str      # from the repo root: core/layouts/standard.json, core/mods/standard-files
    original: str  # in the Herdr home: layouts/main.json, mods/files

    @property
    def is_layout(self) -> bool:
        return self.original.startswith("layouts/")

    @property
    def installed_key(self) -> str:
        """Its entry in installed.json: "layout:main" for a layout, the mod's name for a mod."""
        name = Path(self.original).stem if self.is_layout else Path(self.original).name
        return f"layout:{name}" if self.is_layout else name

    def files(self, recorded: dict[str, str]) -> dict[str, str]:
        """{file inside the clone ("" for a layout's one file): hash} from an installed.json entry."""
        return {"": recorded["json"]} if self.is_layout else dict(recorded)

    def path(self, root: Path, base: str, rel: str) -> Path:
        return root / base if rel == "" else root / base / rel


def load_record(repo: Path) -> tuple[str, list[Clone]] | None:
    """(version, clones) from upstream/herdr.json, or None when the repo has none."""
    path = repo / FOLDER / RECORD
    if not path.exists():
        return None
    try:
        data = load_json(path, None)
    except ValueError as err:
        raise SpecError(f"{path}: invalid JSON: {err}") from None
    clones = data.get("clones") if isinstance(data, dict) else None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or parse_version(version) is None or not isinstance(clones, dict) \
            or not clones or not all(isinstance(k, str) and isinstance(v, str) for k, v in clones.items()) \
            or not all(v.startswith(("layouts/", "mods/")) for v in clones.values()):
        raise SpecError(f"{path}: needs a \"version\" (x.y.z) and \"clones\": {{our path: layouts/... or mods/...}}")
    return version, [Clone(ours, original) for ours, original in clones.items()]


def problems(repo: Path) -> list[str]:
    """What `check` reports about upstream/: a bad record, a clone or recorded original missing."""
    try:
        record = load_record(repo)
    except SpecError as err:
        return [str(err)]
    if record is None:
        return []
    out = []
    for clone in record[1]:
        if not (repo / clone.ours).exists():
            out.append(f"{FOLDER}/{RECORD}: the clone {clone.ours} isn't in the repo")
        if not recorded(repo, clone):
            out.append(f"{FOLDER}/{RECORD}: no originals recorded for {clone.ours} in {FOLDER}/{clone.original}")
    return out


def recorded_version(repo: Path) -> tuple[int, int, int] | None:
    """The Herdr version the clones were last checked against, or None (no record, or unreadable)."""
    try:
        record = load_record(repo)
    except SpecError:
        return None
    return parse_version(record[0]) if record else None


def newer_note(repo: Path, installed: str) -> str | None:
    """Install's note when the installed Herdr is newer than the one the clones were checked
    against; None when it isn't (or either version can't be read)."""
    checked, now = recorded_version(repo), parse_version(installed)
    if checked is None or now is None or now <= checked:
        return None
    return (f"  note      Herdr app {installed} is newer than {herdr.show(checked)}, the version these profiles"
            f" were last checked against; if something looks wrong, report it (developers: make upstream)")


def installed_version() -> str:
    program = herdr.binary()
    if program is None:
        raise SpecError("can't find herdr-app (PATH, or HERDR_APP_BIN): upstream compares against the Herdr installed")
    text, problem = herdr.read_version(program)
    if problem:
        raise SpecError(f"can't tell which Herdr app this is: {problem}")
    return herdr.parse(text)[2]


def shipped(home: Home, clones: list[Clone]) -> dict[Clone, dict[str, bytes] | None]:
    """The installed Herdr's originals: {clone: {file: bytes}}, None for one Herdr no longer ships.
    A SpecError when a copy in the home isn't as Herdr shipped it."""
    installed_path = home.path / "installed.json"
    try:
        installed = load_json(installed_path, None)
    except ValueError as err:
        raise SpecError(f"{installed_path}: invalid JSON: {err}") from None
    if not isinstance(installed, dict):
        raise SpecError(f"{installed_path}: missing or not Herdr's record of what it shipped")
    out: dict[Clone, dict[str, bytes] | None] = {}
    edited: list[str] = []
    for clone in clones:
        entry = installed.get(clone.installed_key)
        if not isinstance(entry, dict) or (clone.is_layout and not isinstance(entry.get("json"), str)):
            out[clone] = None
            continue
        files: dict[str, bytes] = {}
        for rel, want in clone.files(entry).items():
            path = clone.path(home.path, clone.original, rel)
            data = path.read_bytes() if path.is_file() else None
            if data is None or shipped_hash(data, clone.is_layout) != want:
                edited.append(str(Path(clone.original) / rel) if rel else clone.original)
            else:
                files[rel] = data
        out[clone] = files
    if edited:
        raise SpecError("not as Herdr shipped them (edited, or missing): " + ", ".join(edited) +
                        ". Herdr puts its own back when it starts (an edited one is moved aside): restart it,"
                        " then run this again.")
    return out


def recorded(repo: Path, clone: Clone) -> dict[str, bytes]:
    """The originals recorded in upstream/ for a clone: {file: bytes}."""
    base = repo / FOLDER / clone.original
    if clone.is_layout:
        return {"": base.read_bytes()} if base.is_file() else {}
    if not base.is_dir():
        return {}
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def ours(repo: Path, clone: Clone, rel: str) -> bytes | None:
    path = clone.path(repo, clone.ours, rel)
    return path.read_bytes() if path.is_file() else None


def same(a: bytes | None, b: bytes | None, layout: bool) -> bool:
    """Equal files; for a layout, equal JSON (Herdr reformatting one isn't a change)."""
    if a is None or b is None or not layout:
        return a == b
    return shipped_hash(a, True) is not None and shipped_hash(a, True) == shipped_hash(b, True)


def classify(old: dict[str, bytes], new: dict[str, bytes] | None, repo: Path, clone: Clone) -> list[tuple[str, str]]:
    """[(what, file)] for the files whose original changed between the record and the installed Herdr."""
    if new is None:
        return [("gone", "(the whole " + ("layout" if clone.is_layout else "mod") + ")")]
    out = []
    for rel in sorted(set(old) | set(new)):
        before, after = old.get(rel), new.get(rel)
        if same(before, after, clone.is_layout):
            continue
        if before is None:
            what = "new"
        elif after is None:
            what = "gone"
        else:
            what = "take" if same(ours(repo, clone, rel), before, clone.is_layout) else "merge"
        out.append((what, rel))
    return out


def diff(old: bytes | None, new: bytes | None, name: str, version_old: str, version_new: str) -> list[str]:
    def lines(b: bytes | None) -> list[str]:
        return [] if b is None else b.decode("utf-8", errors="replace").splitlines(keepends=True)
    out = list(difflib.unified_diff(lines(old), lines(new), f"{name} ({version_old})", f"{name} ({version_new})"))
    return [line if line.endswith("\n") else line + "\n" for line in out]


def run(repo: Path, home: Home, show_diff: bool = False, save: bool = False) -> int:
    record = load_record(repo)
    if record is None:
        raise SpecError(f"no {FOLDER}/{RECORD} in {repo}: nothing records what the clones came from")
    version, clones = record
    now = installed_version()
    originals = shipped(home, clones)
    print(f"Herdr app {now}; the clones were last checked against {version}.")
    pending = 0
    kept: list[str] = []
    for clone in clones:
        old, new = recorded(repo, clone), originals[clone]
        changes = classify(old, new, repo, clone)
        if not changes:
            continue
        print(f"  {clone.ours}  (from Herdr's {clone.original})")
        for what, rel in changes:
            name = rel or Path(clone.original).name
            print(f"    {what:<7} {name}")
            pending += 1
            if what == "take":
                kept.append(f"{clone.ours}/{rel}" if rel else clone.ours)
            if show_diff and new is not None:
                print("".join(diff(old.get(rel), new.get(rel), str(Path(clone.original) / rel) if rel
                                   else clone.original, version, now)), end="")
    if not pending:
        print("  Nothing Herdr ships that we cloned changed." if now != version
              else "  Up to date: the clones match this Herdr's originals.")
    elif not save:
        print("  take: copy Herdr's over ours · merge: by hand (--diff shows Herdr's change) ·"
              " then `upstream --save`")
    if save:
        if now == version and not pending:
            print("  Nothing to save.")
            return 0
        for clone in clones:
            write_record(repo, clone, originals[clone])
        data = json.loads((repo / FOLDER / RECORD).read_text(encoding="utf-8"))
        data["version"] = now
        (repo / FOLDER / RECORD).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"  saved     Herdr {now}'s originals in {FOLDER}/")
        for k in kept:
            print(f"  kept      {k}: still {version}'s, not taken; from now on it counts as a change of ours")
        print(f"  next      cloned_from.version in core/layouts/standard.json, NOTICE (\"cloned from Herdr"
              f" {now}\"), CHANGELOG, MIN_VERSION in herdr.py if a new API is used; make check,"
              f" herdr-app check on the mods and a look with herdr-app shot")
    return 0


def write_record(repo: Path, clone: Clone, files: dict[str, bytes] | None) -> None:
    """Replaces the recorded originals of a clone with `files` (None: Herdr no longer ships it)."""
    base = repo / FOLDER / clone.original
    if base.is_dir():
        shutil.rmtree(base)
    elif base.exists():
        base.unlink()
    for rel, data in (files or {}).items():
        path = clone.path(repo / FOLDER, clone.original, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
