"""Keeping up with Herdr (scripts/profiletool/upstream.py): our clones against the originals of
the Herdr they came from, on a throwaway repo, Herdr home and fake herdr-app.

Run: python3 -m unittest discover -s tests
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import test_installer
from test_installer import HomeCase

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from profiletool import upstream  # noqa: E402
from profiletool.home import Home  # noqa: E402
from profiletool.spec import SpecError  # noqa: E402

LAYOUT = {"id": "root", "type": "row", "children": [{"id": "main", "type": "block", "content": {"mod": "files"}}]}
FILES = {"main.js": "export default 1;\n", "mod.json": "{}\n", "file.svg": "<svg/>\n", "old.svg": "<svg>old</svg>\n"}


def canonical(layout):
    return json.dumps(layout, separators=(",", ":"), sort_keys=True).encode()


class Fixture(unittest.TestCase):
    """A repo with upstream/ recorded at 0.1.14 and two clones (a layout, a mod), and a Herdr home
    shipping `version` with the originals given."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo, self.home = root / "repo", root / "home"
        rec = {"version": "0.1.14", "clones": {"core/layouts/standard.json": "layouts/main.json",
                                               "core/mods/standard-files": "mods/files"}}
        self.write(self.repo / "upstream/herdr.json", json.dumps(rec))
        self.write(self.repo / "upstream/layouts/main.json", json.dumps(LAYOUT, indent=2))
        for name, text in FILES.items():
            self.write(self.repo / "upstream/mods/files" / name, text)
        # Our clones: the layout renamed its mod; main.js changed; the svgs as Herdr's.
        ours = json.loads(json.dumps(LAYOUT))
        ours["children"][0]["content"]["mod"] = "standard-files"
        self.write(self.repo / "core/layouts/standard.json", json.dumps(ours))
        for name, text in FILES.items():
            self.write(self.repo / "core/mods/standard-files" / name, "ours\n" if name == "main.js" else text)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.fake = bin_dir / "herdr-app"
        self.ship("0.1.14", LAYOUT, FILES)

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def ship(self, version, layout, files, layout_text=None, extra=None):
        """The home as Herdr `version` leaves it: its originals and installed.json's hashes."""
        self.fake.write_text(f"#!/bin/sh\necho 'herdr-app {version}'\n")
        self.fake.chmod(0o755)
        if (self.home / "mods/files").exists():
            for p in (self.home / "mods/files").iterdir():
                p.unlink()
        self.write(self.home / "layouts/main.json", layout_text or json.dumps(layout, indent=2))
        installed = {"layout:main": {"json": upstream.fnv1a(canonical(layout))}, "files": {}}
        for name, text in files.items():
            self.write(self.home / "mods/files" / name, text)
            installed["files"][name] = upstream.fnv1a(text.encode())
        # Herdr writes type files into mod folders without recording them: never read.
        self.write(self.home / "mods/files/gpui-kit.d.ts", "// generated\n")
        installed.update(extra or {})
        self.write(self.home / "installed.json", json.dumps(installed))

    def run_upstream(self, **kw):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_APP_BIN": str(self.fake)}), redirect_stdout(out):
            code = upstream.run(self.repo, Home(self.home), **kw)
        return code, out.getvalue()


class UpstreamTest(Fixture):
    def test_the_hash_is_herdrs(self):
        # 64-bit FNV-1a test vectors; and the real installed.json records main.js this way.
        self.assertEqual(upstream.fnv1a(b""), "cbf29ce484222325")
        self.assertEqual(upstream.fnv1a(b"a"), "af63dc4c8601ec8c")
        self.assertEqual(upstream.fnv1a(b"foobar"), "85944171f73967e8")

    def test_up_to_date(self):
        code, out = self.run_upstream()
        self.assertEqual(code, 0)
        self.assertIn("Herdr app 0.1.14; the clones were last checked against 0.1.14.", out)
        self.assertIn("Up to date", out)

    def test_a_new_herdr_says_take_merge_new_and_gone(self):
        files = dict(FILES, **{"main.js": "export default 2;\n", "file.svg": "<svg>new</svg>\n",
                               "plus.svg": "<svg>+</svg>\n"})
        del files["old.svg"]
        layout = json.loads(json.dumps(LAYOUT))
        layout["children"][0]["min"] = 40
        self.ship("0.1.15", layout, files)
        code, out = self.run_upstream()
        self.assertEqual(code, 0)
        self.assertIn("Herdr app 0.1.15; the clones were last checked against 0.1.14.", out)
        self.assertIn("    merge   main.json", out)        # our layout differs from Herdr's
        self.assertIn("    take    file.svg", out)         # ours is still Herdr's 0.1.14
        self.assertIn("    merge   main.js", out)          # we changed it too
        self.assertIn("    new     plus.svg", out)
        self.assertIn("    gone    old.svg", out)
        self.assertNotIn("mod.json", out)                   # unchanged: not listed
        self.assertNotIn("gpui-kit", out)
        self.assertEqual((self.repo / "core/mods/standard-files/file.svg").read_text(), FILES["file.svg"],
                         "never changes a clone")

    def test_a_new_herdr_that_changed_nothing_we_cloned(self):
        self.ship("0.1.15", LAYOUT, FILES)
        _, out = self.run_upstream()
        self.assertIn("Nothing Herdr ships that we cloned changed.", out)

    def test_diff_shows_herdrs_change(self):
        self.ship("0.1.15", LAYOUT, dict(FILES, **{"main.js": "export default 2;\n"}))
        _, out = self.run_upstream(show_diff=True)
        self.assertIn("--- mods/files/main.js (0.1.14)", out)
        self.assertIn("+++ mods/files/main.js (0.1.15)", out)
        self.assertIn("-export default 1;", out)
        self.assertIn("+export default 2;", out)

    def test_an_edited_copy_in_the_home_is_never_taken_for_herdrs(self):
        self.ship("0.1.15", LAYOUT, FILES)
        (self.home / "mods/files/main.js").write_text("edited by hand\n")
        (self.home / "layouts/main.json").write_text(json.dumps({**LAYOUT, "type": "column"}))
        with self.assertRaisesRegex(SpecError, r"not as Herdr shipped them .*layouts/main.json, mods/files/main.js"
                                               r".*restart it"):
            self.run_upstream()

    def test_a_layout_reformatted_is_still_herdrs(self):
        # The layout's hash is of its JSON, compact with sorted keys: indentation and key order don't count.
        text = json.dumps(dict(reversed(list(LAYOUT.items()))), indent=4)
        self.ship("0.1.14", LAYOUT, FILES, layout_text=text)
        self.assertIn("Up to date", self.run_upstream()[1])

    def test_a_clone_herdr_no_longer_ships(self):
        self.ship("0.1.15", LAYOUT, {})
        installed = json.loads((self.home / "installed.json").read_text())
        del installed["files"]
        (self.home / "installed.json").write_text(json.dumps(installed))
        _, out = self.run_upstream()
        self.assertIn("    gone    (the whole mod)", out)

    def test_save_records_the_new_originals(self):
        files = dict(FILES, **{"file.svg": "<svg>new</svg>\n", "plus.svg": "<svg>+</svg>\n"})
        del files["old.svg"]
        self.ship("0.1.15", LAYOUT, files)
        code, out = self.run_upstream(save=True)
        self.assertEqual(code, 0)
        self.assertIn("saved     Herdr 0.1.15's originals in upstream/", out)
        self.assertIn("kept      core/mods/standard-files/file.svg: still 0.1.14's, not taken", out)
        self.assertIn("next      cloned_from.version", out)
        self.assertEqual(json.loads((self.repo / "upstream/herdr.json").read_text())["version"], "0.1.15")
        recorded = sorted(p.name for p in (self.repo / "upstream/mods/files").iterdir())
        self.assertEqual(recorded, ["file.svg", "main.js", "mod.json", "plus.svg"])  # no old.svg, no d.ts
        self.assertIn("Up to date", self.run_upstream()[1])

    def test_save_with_nothing_new(self):
        _, out = self.run_upstream(save=True)
        self.assertIn("Nothing to save.", out)

    def test_no_record_or_a_bad_one(self):
        (self.repo / "upstream/herdr.json").unlink()
        with self.assertRaisesRegex(SpecError, "no upstream/herdr.json"):
            self.run_upstream()
        self.assertEqual(upstream.problems(self.repo), [])
        (self.repo / "upstream/herdr.json").write_text('{"version": "new", "clones": {}}')
        with self.assertRaisesRegex(SpecError, 'needs a "version"'):
            self.run_upstream()
        self.assertEqual(len(upstream.problems(self.repo)), 1)

    def test_check_finds_a_missing_clone_or_original(self):
        self.assertEqual(upstream.problems(self.repo), [])
        (self.repo / "core/layouts/standard.json").unlink()
        (self.repo / "upstream/mods/files/main.js").unlink()
        for f in FILES:
            (self.repo / "upstream/mods/files" / f).unlink(missing_ok=True)
        problems = upstream.problems(self.repo)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("the clone core/layouts/standard.json isn't in the repo", problems[0])
        self.assertIn("no originals recorded for core/mods/standard-files", problems[1])

    def test_newer_note(self):
        self.assertIsNone(upstream.newer_note(self.repo, "0.1.14"))
        self.assertIsNone(upstream.newer_note(self.repo, "0.1.13"))
        self.assertIn("Herdr app 0.1.15 is newer than 0.1.14", upstream.newer_note(self.repo, "0.1.15"))
        self.assertIn("Herdr app 0.2.0 is newer", upstream.newer_note(self.repo, "0.2.0"))
        (self.repo / "upstream/herdr.json").write_text("{nope")
        self.assertIsNone(upstream.newer_note(self.repo, "0.1.15"))


class InstallNoteTest(HomeCase):
    """Install on a Herdr newer than the one recorded in upstream/: a note, and it goes on."""

    def test_install_notes_a_newer_herdr_and_goes_on(self):
        recorded = json.loads((REPO / "upstream/herdr.json").read_text())["version"]
        major, minor, patch = map(int, recorded.split("."))
        self.herdr_app = self.fake_herdr_app(f"herdr-app {major}.{minor}.{patch + 1}")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"is newer than {recorded}, the version these profiles were last checked against", r.stdout)
        self.assertTrue((self.home / "layouts/standard.json").is_file())

    def test_no_note_on_the_recorded_herdr(self):
        recorded = json.loads((REPO / "upstream/herdr.json").read_text())["version"]
        self.herdr_app = self.fake_herdr_app(f"herdr-app {recorded}")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("is newer than", r.stdout)


assert test_installer  # imported for HomeCase's helpers

if __name__ == "__main__":
    unittest.main()
