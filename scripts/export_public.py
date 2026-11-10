#!/usr/bin/env python3
"""Export this repo's HEAD as a new one-commit repo, and check it has nothing personal.

  export_public.py DEST --author "Name <email>"   export, then check
  export_public.py --check DEST                    check an existing export

The export is exactly HEAD's tracked tree (uncommitted changes are left out),
committed once in a fresh `git init` at DEST with AUTHOR as author and
committer (dated now, in UTC), no remote. This repo and its history are not
touched.

The check fails on any denied string in the export's file contents, paths,
symlink targets, commit message and author/committer fields. Denied strings
are found at run time, never stored in the repo:

  - every `user.email` in this repo's git config, and every author/committer
    email in its history and reflogs (except the export's own author);
  - the home folder's path, and `/Users/<name>` and `/home/<name>` for its name;
  - one string per line of `.git/info/export-deny` (UTF-8 or UTF-16; blank
    lines and lines starting with `#` are skipped; surrounding spaces are
    dropped).

Matching ignores letter case and Unicode normalization (NFC/NFD). Contents
are searched as UTF-8, UTF-16 and UTF-32 bytes, and inside PNG text chunks,
gzip files and zip members (so .docx, .xlsx, .jar too). It can't see strings
in other encodings (base64, JSON escapes, other compression).

It also fails when ROADMAP.md or a file matched by `.git/info/exclude` is in
the export, when the export has more than one commit (or a parent, or is
shallow), other refs, a remote, a submodule, files that differ from its
commit, a commit time not in UTC, or a symlink that leads outside it.

Stdlib only; Python 3.9+.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import unicodedata
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MESSAGE = "Initial public release"
AUTHOR_RE = re.compile(r"^([^<>\n\r]*[^<>\s][^<>\n\r]*?)\s*<([^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>$")
# Environment that would point git at another repo, index or config, or set an identity or date.
SCRUB = re.compile(r"^GIT_(DIR|WORK_TREE|INDEX_FILE|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES|COMMON_DIR"
                   r"|NAMESPACE|CONFIG_PARAMETERS|CONFIG_COUNT|CONFIG_KEY_\d+|CONFIG_VALUE_\d+"
                   r"|AUTHOR_\w+|COMMITTER_\w+|GRAFT_FILE|REPLACE_REF_BASE|NO_REPLACE_OBJECTS|SHALLOW_FILE)$")
INNER_LIMIT = 64 * 1024 * 1024  # bytes inflated per file, at most
PATH_CHARS = re.compile(r"[A-Za-z0-9._-]")


class ExportError(Exception):
    pass


def git_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not SCRUB.match(k)}
    env.update(extra or {})
    return env


def git(cwd: Path, *args: str, env: dict | None = None) -> bytes:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, env=git_env(env))
    if r.returncode != 0:
        raise ExportError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def maybe(repo: Path, *args: str) -> str:
    """A git command's output, or "" when it fails (no such config, no commit)."""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env())
    return r.stdout.decode(errors="replace") if r.returncode == 0 else ""


def git_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--absolute-git-dir").decode().strip())


def parse_author(text: str) -> tuple[str, str]:
    m = AUTHOR_RE.match(text.strip())
    if not m:
        raise ExportError(f"AUTHOR must look like 'Name <email>', got {text!r}")
    return m.group(1).strip(), m.group(2)


# ---------------------------------------------------------------- deny list

class Deny:
    """One denied string. `label` says where it came from and never holds the string."""

    def __init__(self, label: str, text: str, whole_segment: bool = False):
        self.label = label
        self.text = unicodedata.normalize("NFC", text).casefold()
        self.whole_segment = whole_segment  # /home/bob must not match /home/bobby
        forms: list = []  # (lower-cased bytes, encoding)
        for norm in ("NFC", "NFD"):
            t = unicodedata.normalize(norm, text)
            for v in (t, t.lower(), t.upper(), t.casefold()):
                for enc in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                    b = v.encode(enc).lower()
                    if b and all(b != f for f, _ in forms):
                        forms.append((b, enc))
        self.forms = forms

    def find(self, hay, needle, enc: str | None = None) -> int:
        """First index of needle in hay (str, or bytes in enc) that ends a path segment if it must."""
        i = hay.find(needle)
        while i >= 0:
            end = i + len(needle)
            nxt = hay[end:end + 4]
            if isinstance(nxt, bytes):
                nxt = nxt.decode(enc, errors="ignore")
            if not self.whole_segment or not nxt or not PATH_CHARS.match(nxt[0]):
                return i
            i = hay.find(needle, i + 1)
        return -1


def deny_list(repo: Path, home: Path, keep_emails: set = frozenset()) -> list:
    out: list[Deny] = []
    for e in maybe(repo, "config", "--get-all", "user.email").split("\n"):
        if e.strip():
            out.append(Deny("this repo's git user.email", e.strip()))
    keep = {k.lower() for k in keep_emails if k}
    if maybe(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}"):
        for e in maybe(repo, "log", "--all", "--reflog", "--format=%ae%n%ce").split("\n"):
            if e.strip() and e.strip().lower() not in keep:
                out.append(Deny("an author/committer email in this repo's history", e.strip()))
    h = str(home).rstrip("/")
    if h:
        out.append(Deny("the home folder's path", h, whole_segment=True))
        name = Path(h).name
        if name:
            out.append(Deny("the home folder's name as a path", f"/Users/{name}", whole_segment=True))
            out.append(Deny("the home folder's name as a path", f"/home/{name}", whole_segment=True))
    for n, s in deny_file_lines(git_dir(repo) / "info" / "export-deny"):
        out.append(Deny(f".git/info/export-deny line {n}", s))
    seen, uniq = set(), []
    for d in out:
        if (d.text, d.whole_segment) not in seen:
            seen.add((d.text, d.whole_segment))
            uniq.append(d)
    return uniq


def deny_file_lines(path: Path) -> list:
    if not path.exists():
        return []
    raw = path.read_bytes()
    try:
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ExportError(f"{path} isn't UTF-8 or UTF-16 text") from None
    if "\0" in text:
        raise ExportError(f"{path} has NUL characters; write it as plain UTF-8 text")
    lines = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip().strip("﻿").strip()
        if s and not s.startswith("#"):
            lines.append((n, s))
    return lines


# ---------------------------------------------------------------- scanning

def find_hits(data: bytes, deny: list, where: str) -> list:
    """One line per denied string found: `where:line` for text, `where:byte N` otherwise."""
    is_text = b"\0" not in data[:8192]
    text = unicodedata.normalize("NFC", data.decode("utf-8", errors="replace")).casefold() if is_text else ""
    low = data.lower()
    hits = []
    for d in deny:
        if is_text:
            i = d.find(text, d.text)
            if i >= 0:
                hits.append(f"{where}:{text.count(chr(10), 0, i) + 1}: contains {d.label}")
                continue
        for f, enc in d.forms:
            i = d.find(low, f, enc)
            if i >= 0:
                pos = str(data.count(b"\n", 0, i) + 1) if is_text else f"byte {i}"
                hits.append(f"{where}:{pos}: contains {d.label}")
                break
    return hits


def inner(data: bytes, depth: int = 0) -> list:
    """[(label, bytes)]: what's inside a PNG's compressed chunks, a gzip file or a zip's members."""
    if depth > 3:
        return []
    out = []
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            i = 8
            while i + 8 <= len(data):
                length = int.from_bytes(data[i:i + 4], "big")
                kind, body = data[i + 4:i + 8], data[i + 8:i + 8 + length]
                i += 12 + length
                try:
                    if kind in (b"zTXt", b"iCCP"):
                        out.append(("compressed PNG chunk", inflate(body.split(b"\0", 1)[1][1:])))
                    elif kind == b"iTXt":
                        rest = body.split(b"\0", 1)[1]
                        if rest[:1] == b"\1":
                            out.append(("compressed PNG chunk", inflate(rest[2:].split(b"\0", 2)[2])))
                except (zlib.error, IndexError, ValueError):
                    pass
        elif data[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                out.append(("gzip", g.read(INNER_LIMIT)))
        elif data[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    out.append((f"zip member {info.filename}", info.filename.encode()))
                    with z.open(info) as m:
                        out.append((f"zip member {info.filename}", m.read(INNER_LIMIT)))
    except (OSError, EOFError, zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError):
        out.append(("unreadable archive", b""))
    deeper = []
    for label, body in out:
        deeper += [(f"{label} > {l2}", b2) for l2, b2 in inner(body, depth + 1)]
    return out + deeper


def inflate(body: bytes) -> bytes:
    return zlib.decompressobj().decompress(body, INNER_LIMIT)


# ---------------------------------------------------------------- export

def check_dest(dest: Path, repo: Path) -> Path:
    """The real folder to export into, refused if not empty or inside the repo."""
    real = Path(os.path.realpath(dest))
    if real.exists() and (not real.is_dir() or any(real.iterdir())):
        raise ExportError(f"{dest} exists and isn't an empty folder")
    top = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    for p in [real, *real.parents]:
        if p.exists() and os.path.samefile(p, top):
            raise ExportError(f"{dest} is inside the repo being exported")
    return real


def export(repo: Path, dest: Path, author: str, home: Path) -> int:
    name, email = parse_author(author)
    real = check_dest(dest, repo)
    if any(line.startswith(b"160000 ") for line in git(repo, "ls-tree", "-r", "-z", "HEAD").split(b"\0")):
        raise ExportError("HEAD has a submodule; git archive can't export it")
    if git(repo, "status", "--porcelain", "--untracked-files=normal").strip():
        print("note: the working tree has uncommitted changes; they are not exported (only HEAD is).")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    tar = git(repo, "archive", "--format=tar", head)

    existed = real.exists()
    real.mkdir(parents=True, exist_ok=True)
    now = f"{int(time.time())} +0000"
    ident = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": now,
             "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": now}
    clean = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
             "-c", "core.safecrlf=false", "-c", "core.fileMode=true"]
    try:
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            if hasattr(tarfile, "tar_filter"):
                tf.extractall(real, filter="tar")
            else:
                tf.extractall(real)
        git(real, "init", "-q", "--template=", "-b", "main")
        git(real, "config", "user.name", name)
        git(real, "config", "user.email", email)
        git(real, *clean, "add", "-A", "-f", ".")
        git(real, *clean, "commit", "-q", "--no-verify", "--no-gpg-sign", "-m", MESSAGE, env=ident)
    except (OSError, tarfile.TarError, ExportError) as err:
        shutil.rmtree(real, ignore_errors=True)
        if existed:
            real.mkdir(exist_ok=True)
        raise ExportError(f"export failed, {dest} left empty: {err}") from None
    print(f"Exported {head[:7]} to {dest} as one commit by {name} <{email}>.")
    return check(repo, real, home, author_email=email, source_head=head)


# ---------------------------------------------------------------- check

def check(repo: Path, dest: Path, home: Path, author_email: str | None = None,
          source_head: str | None = None) -> int:
    dest = Path(os.path.realpath(dest))
    if not (dest / ".git").is_dir():
        raise ExportError(f"{dest} isn't a git repo (no .git folder)")
    problems: list = []
    commits = git(dest, "rev-list", "--all").decode().split()
    if len(commits) != 1:
        problems.append(f"the export has {len(commits)} commits, not 1")
    refs = git(dest, "for-each-ref", "--format=%(refname)").decode().split()
    if len(refs) != 1:
        problems.append(f"the export has {len(refs)} refs, not 1: {', '.join(refs)}")
    keys = maybe(dest, "config", "--local", "--name-only", "--list").split()
    if git(dest, "remote").strip() or any(k.startswith("remote.") or re.match(r"branch\..*\.(remote|pushremote|merge)$", k)
                                          for k in keys):
        problems.append("the export has a remote (or remote settings in .git/config)")
    for f in ("shallow", "info/grafts"):
        if (dest / ".git" / f).exists():
            problems.append(f"the export has .git/{f}: history hidden behind it")
    if not commits:
        print("\n".join(f"FAIL {p}" for p in problems) or "FAIL no commit")
        return 1
    commit = commits[0]
    if author_email is None:  # --check: only the export's own configured author is not denied
        author_email = maybe(dest, "config", "--local", "user.email").strip()
    deny = deny_list(repo, home, keep_emails={author_email})

    # Commit fields and message (and the raw commit, for signatures, parents or extra headers).
    raw = git(dest, "cat-file", "commit", commit)
    header = raw.split(b"\n\n", 1)[0]
    problems += find_hits(raw, deny, "commit")
    if re.search(rb"(?m)^parent ", header):
        problems.append("commit: it has a parent (history behind it)")
    if re.search(rb"(?im)^(co-authored-by|signed-off-by):", raw):
        problems.append("commit: its message has an attribution trailer")
    if re.search(rb"(?m)^gpgsig", header):
        problems.append("commit: it is signed")
    if re.search(rb"(?m)^(author|committer) .* [-+](?!0000)\d{4}$", header):
        problems.append("commit: its time isn't in UTC (the zone tells where you are)")

    # What gets published: every blob, path and link of the commit's tree.
    for line in git(dest, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not line:
            continue
        meta, path_b = line.split(b"\t", 1)
        mode, kind, sha = meta.decode().split()
        path = path_b.decode("utf-8", errors="surrogateescape")
        problems += find_hits(path_b, deny, f"path {path}")
        if Path(path).name.lower() == "roadmap.md":
            problems.append(f"{path}: ROADMAP.md must not be exported")
        if kind == "commit":
            problems.append(f"{path}: a submodule")
            continue
        data = git(dest, "cat-file", "blob", sha)
        if mode == "120000":
            target = data.decode("utf-8", errors="surrogateescape")
            on_disk = os.path.realpath(dest / path)
            if target.startswith("/") or ".." in Path(os.path.normpath(Path(path).parent / target)).parts \
                    or not (on_disk + os.sep).startswith(str(dest) + os.sep):
                problems.append(f"{path}: a symlink leading outside the export")
            problems += find_hits(data, deny, f"{path} (symlink target)")
            continue
        problems += find_hits(data, deny, path)
        for label, body in inner(data):
            if label == "unreadable archive":
                problems.append(f"{path}: looks like an archive but can't be read; check it by hand")
            else:
                problems += find_hits(body, deny, f"{path} ({label})")
    problems += [f"{p}: matched by .git/info/exclude" for p in exclude_matches(repo, dest)]

    # The folder on disk must be what the commit holds.
    status = git(dest, "status", "--porcelain", "--ignored", "--untracked-files=all").decode(errors="replace")
    if status.strip():
        problems.append("the export's files differ from its commit:\n  " + "\n  ".join(status.splitlines()[:20]))
    if source_head:
        mine = git(repo, "rev-parse", f"{source_head}^{{tree}}").decode().strip()
        theirs = git(dest, "rev-parse", f"{commit}^{{tree}}").decode().strip()
        if mine != theirs:
            problems.append("the export's tree isn't HEAD's (.gitattributes export-ignore/export-subst, "
                            "or names that differ only in case on a case-insensitive disk?)")

    if problems:
        for p in problems:
            print(f"FAIL {p}")
        print(f"{len(problems)} problem(s); the export at {dest} is not fit to publish.")
        return 1
    print(f"OK: 1 commit, no remote, nothing personal found ({len(deny)} denied strings checked).")
    return 0


def exclude_matches(repo: Path, dest: Path) -> list:
    exclude = git_dir(repo) / "info" / "exclude"
    if not exclude.exists():
        return []
    out = git(dest, "ls-files", "-z", "--cached", "--ignored", f"--exclude-from={exclude}")
    return [p.decode("utf-8", errors="surrogateescape") for p in out.split(b"\0") if p]


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export HEAD as a new one-commit repo with nothing personal in it.")
    ap.add_argument("dest", nargs="?", help="folder for the new repo (must not exist, or be empty)")
    ap.add_argument("--author", help='"Name <email>" for the commit (required to export)')
    ap.add_argument("--check", metavar="DEST", help="only check an existing export")
    ap.add_argument("--repo", default=str(REPO), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    repo, home = Path(args.repo), Path.home()
    try:
        if args.check:
            if args.dest or args.author:
                ap.error("--check takes only the export's folder")
            return check(repo, Path(args.check), home)
        if not args.dest or not args.author:
            ap.error("export needs DEST and --author \"Name <email>\"")
        return export(repo, Path(args.dest), args.author, home)
    except ExportError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
