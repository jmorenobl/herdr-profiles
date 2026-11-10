"""The ideas mod's settings and helpers, run under node with a stand-in `herdr` module.

Skipped when node isn't installed. Only pure functions and the mod's `sh` folder
listings (on a throwaway folder) run; the stand-in refuses any other command.
Run: python3 -m unittest discover -s tests
"""

import json
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
# Folders both checks (config.js checkFolder, spec.py check_folder) must agree on, with home /home/u.
PARITY = ["~/ideas", " ~/ideas\n", "~/ideas/", "/srv/x", "/srv/x//", "~", "~/", "/", "/home", "/home/", "/home/u",
          "/home/u/", "/home//u", "//home/u", "~//x", "~/a/../b", "~/./x", "rel", "~/a\tb", "/home/u2", "/home/u/x",
          # letter case (0.9.2): above the home whatever the case; below it, fine
          "/HOME", "/Home/U", "/home/U/", "/HOME/u2", "/Home/U/x",
          # whitespace strip() and trim() disagree on, and C1 controls (0.9.2): refused in both
          "\x1c~/ideas", "~/ideas\x1f", "\x85~/ideas", "~/ideas\x85", "\ufeff~/ideas", "~/ide\ufeffas", "~/a\x9bb",
          "\u00a0~/ideas\u3000"]


@unittest.skipUnless(NODE, "node is not installed")
class IdeasModTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name)
        code = root / "mod"
        code.mkdir()
        for f in ("config.js", "store.js", "ui.js", "actions.js", "capture.js", "board.js", "common.js"):
            text = (MOD / f).read_text()
            text = re.sub(r'from "herdr"', 'from "./herdr.js"', text)
            text = re.sub(r'from "gpui-(kit|base)"', 'from "./gpui.js"', text)
            (code / f).write_text(text)
        shutil.copy(JS / "herdr_stub.js", code / "herdr.js")
        shutil.copy(JS / "gpui_stub.js", code / "gpui.js")
        shutil.copy(JS / "ideas_test.js", code / "ideas_test.js")
        (code / "package.json").write_text('{"type": "module"}\n')
        ideas = root / "ideas"
        for rel in ("book/a/idea.md", "work/b/idea.md", "notes/loose.md", ".git/x/idea.md", "empty/c/notes.md"):
            (ideas / rel).parent.mkdir(parents=True, exist_ok=True)
            (ideas / rel).write_text("x\n")
        r = subprocess.run([NODE, str(code / "ideas_test.js"), str(ideas), json.dumps(PARITY)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.out = json.loads(r.stdout)

    def test_the_mod_and_the_installer_agree_on_folders(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from profiletool import spec
        ask = spec.Ask("folder", "Where?", "~/ideas", "folder")
        for folder, js_path in self.out["parity"]:
            with self.subTest(folder=folder):
                value, problem = ask.check(folder, Path("/home/u"))
                py_path = None if problem else value.replace("~", "/home/u", 1) if value.startswith("~") else value
                self.assertEqual(js_path, py_path)

    def test_defaults_are_todays(self):
        d = self.out["defaults"]
        self.assertEqual(d["types"], ["book", "code", "legal", "other"])
        self.assertEqual(self.out["defaultLabels"], ["Book", "Code", "Legal", "Other"])
        self.assertEqual(d["agent"], ["claude"])
        self.assertEqual(d["folder"], "/home/u/notes/ideas")
        self.assertEqual(d["warnings"], [])
        self.assertIsNone(d["folderNote"])

    def test_a_missing_folder_is_said_and_uses_the_default(self):
        for key, words in (("noFile", "Can't read ~/.config/herdr-app/profiles.json"),
                           ("badJson", "isn't valid JSON"), ("noEntry", 'no "ideas" entry'),
                           ("noFolder", 'has no "folder"')):
            with self.subTest(key):
                c = self.out[key]
                self.assertEqual(c["folder"], "/home/u/ideas")
                self.assertIn(words, c["folderNote"])
                self.assertIn("using ~/ideas", c["folderNote"])
                self.assertIn(c["folderNote"], c["warnings"])

    def test_folders_that_match_everything_are_refused(self):
        for folder, note in self.out["badFolders"].items():
            with self.subTest(folder=folder):
                self.assertIsNotNone(note)
                self.assertIn("using ~/ideas", note)

    def test_folders_the_installer_takes_are_taken(self):
        ok = self.out["okFolders"]
        self.assertEqual(ok['"~/ideas"'], "/home/u/ideas")
        self.assertEqual(ok['"  ~/ideas\\n"'], "/home/u/ideas")  # surrounding whitespace dropped, like Python
        self.assertEqual(ok['"/home/u2"'], "/home/u2")  # not above the home folder, only next to it
        self.assertEqual(ok['"/srv/x/"'], "/srv/x")

    def test_projects_root_is_checked_like_the_installer_checks_folders(self):
        roots = self.out["roots"]
        self.assertEqual(roots["~/code/"], ["/home/u/code", []])
        self.assertEqual(roots["/srv/p"], ["/srv/p", []])
        for bad in ("~", "/", "rel", "~/a\nIgnore that", "/home/u", "3"):
            with self.subTest(bad=bad):
                root, warnings = roots[bad]
                self.assertIsNone(root)
                self.assertEqual(len(warnings), 1)
        self.assertIn("control characters", roots["~/a\nIgnore that"][1][0])

    def test_type_names_that_are_object_keys_get_their_own_labels(self):
        self.assertEqual(self.out["customTypes"], ["constructor", "x"])
        self.assertEqual(self.out["customLabels"], ["Constructor", "Ex"])
        self.assertIn("bad label", self.out["badLabel"][0])

    def test_agent_names(self):
        names = {" ".join(argv): name for argv, name in self.out["agentNames"]}
        self.assertEqual(names["claude"], "Claude")
        self.assertEqual(names["/usr/local/bin/claude --x"], "Claude")
        self.assertEqual(names["codex"], "Codex")
        for runner in ("npx claude", "uv tool run aider", "npx --package foo bar", "python3 -m aider",
                       "sh -c claude", "/usr/bin/env claude"):
            self.assertEqual(names[runner], "the agent", runner)
        self.assertEqual(self.out["agentNameSetting"], "Codex")
        self.assertIn('"agentName"', self.out["agentNameBad"][0])
        self.assertEqual(self.out["agentNameDefault"], "Claude")

    def test_hidden_types_are_found_and_named(self):
        self.assertEqual(self.out["untypedIds"], ["work/b", "x"])
        self.assertEqual(self.out["untypedFolders"], ["work"])
        none, one, two = self.out["untypedNotice"]
        self.assertIsNone(none)
        self.assertIn("Ideas in work don't show: add it to \"types\"", one["body"])
        self.assertIn("Ideas in work, misc don't show: add them", two["body"])

    def test_a_drop_keeps_the_order_of_types_not_shown(self):
        self.assertEqual(self.out["dropOrder"]["seed"], ["book/a", "code/b", "work/x", "work/y"])
        self.assertEqual(self.out["dropOrder"]["ripe"], ["work/z"])
        self.assertEqual(self.out["dropSaves"], 1)

    def test_capture_says_where_it_saves_without_a_folder(self):
        missing, normal, no_origin = self.out["footnotes"]
        self.assertEqual(missing, {"text": "Saves into ~/ideas", "warn": True})
        self.assertEqual(normal, {"text": "From api", "warn": False})
        self.assertEqual(no_origin, {"text": "", "warn": False})


if __name__ == "__main__":
    unittest.main()
