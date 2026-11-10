"""The Herdr app itself: finding `herdr-app` and checking its version before installing.

`herdr-app --version` prints "herdr-app 0.1.14". These profiles need 0.1.14 or
newer (the layout format, `layout.switch`, the mod API they use). HERDR_APP_BIN
names the binary instead of looking on PATH (tests use it for a fake one).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from .spec import SpecError

MIN_VERSION = (0, 1, 14)
TIMEOUT = 10  # seconds `herdr-app --version` may take
VERSION = re.compile(r"(?<![\d.])(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(?![\d.]*\d)")
SKIP = "or install anyway with --skip-version-check"


def show(version: tuple[int, ...]) -> str:
    return ".".join(map(str, version))


def binary() -> str | None:
    """The herdr-app to run: HERDR_APP_BIN if set (None when it isn't a program), else PATH's."""
    override = os.environ.get("HERDR_APP_BIN")
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    return shutil.which("herdr-app")


def parse(text: str) -> tuple[tuple[int, int, int], bool, str] | None:
    """The first x.y.z in `text`, whether it's a pre-release (x.y.z-beta) and as written; or None."""
    m = VERSION.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4) is not None, m.group(0)


def read_version(program: str) -> tuple[str | None, str | None]:
    """(the version string Herdr printed, None) or (None, why it couldn't be read)."""
    try:
        r = subprocess.run([program, "--version"], capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"`{program} --version` didn't answer in {TIMEOUT} seconds"
    except OSError as err:
        return None, f"can't run {program}: {err.strerror or err}"
    said = (r.stdout.strip() or r.stderr.strip())[:200]
    if r.returncode != 0:
        return None, f"`{program} --version` failed (exit code {r.returncode})" + (f": {said}" if said else "")
    for out in (r.stdout, r.stderr):  # some programs print their version on stderr
        if parse(out) is not None:
            return out.strip(), None
    return None, f"`{program} --version` printed {said!r}, with no version number in it"


def require(minimum: tuple[int, int, int] = MIN_VERSION) -> str:
    """The installed Herdr's version ("0.1.14"); a SpecError says why install can't go on."""
    need = f"Herdr app {show(minimum)} or newer"
    program = binary()
    if program is None:
        where = (f"HERDR_APP_BIN={os.environ['HERDR_APP_BIN']} isn't a program you can run"
                 if os.environ.get("HERDR_APP_BIN") else "herdr-app isn't on PATH")
        raise SpecError(f"{where}. These profiles need {need} (https://herdr.dev). If it's installed,"
                        f" put herdr-app on PATH or set HERDR_APP_BIN to it; {SKIP}.")
    text, problem = read_version(program)
    if problem:
        raise SpecError(f"can't tell which Herdr app this is: {problem}. These profiles need {need}; {SKIP}.")
    version, pre, written = parse(text)
    if version < minimum or (version == minimum and pre):
        older = " (a pre-release comes before it)" if pre and version == minimum else ""
        raise SpecError(f"Herdr app {written} is too old: these profiles need {need}{older}."
                        f" Update Herdr app, {SKIP}.")
    return written
