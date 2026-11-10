"""The ideas mod's folder, autocommit and views, on throwaway folders and git repos.

Runs tests/js/ideas_store_test.js under node with a stand-in `herdr` backed by real files and
git (tests/js/herdr_git_stub.js) and a stand-in UI (tests/js/gpui_view_stub.js). Skipped
without node or git. git there has its own identity and none of the person's config.
Run: python3 -m unittest discover -s tests
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOD = REPO / "profiles" / "ideas" / "mods" / "ideas"
JS = REPO / "tests" / "js"
NODE = shutil.which("node")
GIT = shutil.which("git")


@unittest.skipUnless(NODE and GIT, "node or git is not installed")
class IdeasStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        code = root / "mod"
        code.mkdir()
        for f in MOD.glob("*.js"):
            text = f.read_text(encoding="utf-8")
            text = text.replace('from "herdr"', 'from "./herdr.js"')
            text = re.sub(r'from "gpui-(kit|base)"', 'from "./gpui.js"', text)
            (code / f.name).write_text(text, encoding="utf-8")
        shutil.copy(JS / "herdr_git_stub.js", code / "herdr.js")
        shutil.copy(JS / "gpui_view_stub.js", code / "gpui.js")
        shutil.copy(JS / "ideas_store_test.js", code / "ideas_store_test.js")
        (code / "package.json").write_text('{"type": "module"}\n')
        work = root / "work"
        work.mkdir()
        env = dict(os.environ, TZ="Europe/Madrid", LC_ALL="C")
        r = subprocess.run([NODE, str(code / "ideas_store_test.js"), str(work)], capture_output=True,
                           text=True, encoding="utf-8", timeout=180, env=env)
        if r.returncode != 0 or not r.stdout.strip():
            raise AssertionError(r.stderr or "no output")
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_every_case(self):
        self.assertGreater(len(self.out), 20)
        for name, error in self.out.items():
            with self.subTest(name):
                self.assertIsNone(error, error)


if __name__ == "__main__":
    unittest.main()
