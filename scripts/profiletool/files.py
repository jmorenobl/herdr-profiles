"""Reading and writing files safely."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# Called after each change install and uninstall make in a home: (event, path, renamed to).
# "write" (a file, whole), "rename" (a staged mod folder into place), "delete". Tests watch
# the order of writes with it (`watching`); nothing else does.
Watcher = Callable[[str, Path, Optional[Path]], None]
WATCHERS: list[Watcher] = []


@contextmanager
def watching(fn: Watcher) -> Iterator[None]:
    WATCHERS.append(fn)
    try:
        yield
    finally:
        WATCHERS.remove(fn)


def notify(event: str, path: Path, dest: Path | None = None) -> None:
    for fn in list(WATCHERS):
        fn(event, path, dest)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str | None:
    """The file's hash, or None when there's no file."""
    return sha_bytes(path.read_bytes()) if path.is_file() else None


def load_json(path: Path, default: Any) -> Any:
    """The file's JSON, or `default` when it doesn't exist. Invalid JSON raises ValueError."""
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dump_json(data: Any) -> bytes:
    """The one JSON format this tool writes: 2 spaces, UTF-8, final newline."""
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def write_json(path: Path, data: Any) -> None:
    atomic_write(path, dump_json(data))


def atomic_write(path: Path, data: bytes) -> None:
    """Writes through a temporary file, so Herdr never reads half a file. A symlink is written
    through (the file it points to changes, the link stays), and the file keeps its mode
    (a new one gets the usual 0644 less the umask, not mkstemp's 0600)."""
    if path.is_symlink():
        path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    notify("write", path)


@contextmanager
def finish_first() -> Iterator[None]:
    """Ctrl-C waits until the block is done, then stops as usual: a write phase (files, the
    person's files, the manifest) is never left half done by it."""
    pressed: list[int] = []

    def later(signum, _frame):
        if not pressed:
            print("\n  Ctrl-C: finishing what's being written first, so the Herdr home stays consistent",
                  file=sys.stderr, flush=True)
        pressed.append(signum)

    try:
        before = signal.signal(signal.SIGINT, later)
    except ValueError:  # not the main thread: signals can't be handled here
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, before)
    if pressed:
        raise KeyboardInterrupt
