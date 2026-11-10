"""The History mod's pure parts (model.js), run under node on throwaway git repos.

Skipped when node or git isn't installed. Git runs with its own identity and no
global or system config, in a temporary folder; nothing else is touched.
Run: python3 -m unittest discover -s tests
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOD = REPO / "core" / "mods" / "standard-history"
JS = REPO / "tests" / "js"
NODE = shutil.which("node")
GIT = shutil.which("git")


@unittest.skipUnless(NODE and GIT, "node or git is not installed")
class HistoryModTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        code, repos = root / "mod", root / "repos"
        code.mkdir()
        repos.mkdir()
        shutil.copy(MOD / "model.js", code / "model.js")
        shutil.copy(JS / "history_test.js", code / "history_test.js")
        (code / "package.json").write_text('{"type": "module"}\n')
        r = subprocess.run([NODE, str(code / "history_test.js"), str(repos)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.out = json.loads(r.stdout)

    def test_records_parse_with_odd_subjects_and_authors(self):
        rec = self.out["records"]
        self.assertEqual(rec["hashes"], rec["expected"])
        self.assertEqual(rec["subjects"], ["no body", "two line subject", "sub\x1fject", "first"])
        self.assertEqual(rec["authors"], ["Tester", "Tester", "Ann\x1fBee", "Tester"])
        self.assertEqual(rec["parents"], [1, 1, 1, 0])
        self.assertEqual(rec["refs"], [{"name": "main", "head": True}])
        self.assertFalse(rec["more"])
        self.assertEqual(rec["limited"], {"n": 2, "more": True})

    def test_a_two_line_subject_is_not_repeated_in_the_body(self):
        self.assertEqual(self.out["records"]["bodies"], [[], ["the body", "", "more body"], [], []])

    def test_signatures_shown_by_config_dont_break_the_list(self):
        signed = self.out["signed"]
        if signed is None:
            self.skipTest("ssh-keygen or git 2.34 is not available")
        self.assertTrue(signed["plainHasSignature"], "the repo's config should print signatures without the mod's arguments")
        self.assertEqual(signed["hashes"], signed["expected"])
        self.assertEqual(signed["subjects"], ["signed two", "signed one"])
        self.assertEqual(signed["body"], [])

    def test_a_page_after_history_moved_is_refused(self):
        p = self.out["paging"]
        self.assertEqual(p["joined"], ["c6", "c5", "c4", "c3", "c2", "c1"])
        self.assertEqual(p["unique"], 6)
        self.assertIsNone(p["moved"])
        self.assertIsNone(self.out["appendDup"])
        self.assertTrue(p["graphJoins"])

    def test_each_files_diff_is_its_own_whatever_its_name(self):
        paths = self.out["paths"]
        for path, text in paths["expected"].items():
            with self.subTest(path=path):
                self.assertEqual(paths["diffs"][path], ["@@ -0,0 +1 @@", "+" + text])
        self.assertEqual(paths["diffs"]["bin.dat"], ["Binary file changed"])
        files = {f[0]: f for f in paths["files"]}
        self.assertEqual(files["dir/nested?.md"][1:3], ["dir/", "nested?.md"])
        self.assertTrue(files["bin.dat"][5])
        self.assertEqual(len(files), len(paths["expected"]) + 1)

    def test_long_diffs_are_cut(self):
        self.assertEqual(self.out["diffCut"], {"n": 1501, "last": "… 102 more lines"})

    def test_worktrees_watch_the_common_folder(self):
        wt = self.out["worktree"]
        self.assertTrue(wt["main"])
        self.assertEqual(wt["other"], [wt["common"]])
        self.assertTrue(wt["otherGitDir"].startswith(wt["common"] + "/"))
        self.assertEqual(self.out["watchDirs"], [["/r/.git"], ["/r/.git"], ["/w/.git", "/elsewhere/common"], ["/r/.git"], ["/r/.git"]])

    def test_a_partial_clone_is_read_without_downloading(self):
        p = self.out["partial"]
        self.assertTrue(p["isPartial"])
        self.assertFalse(p["sourcePartial"])
        self.assertEqual(self.out["partialConfig"], [True, True, False, False])
        if p["lazy"] is None:
            self.skipTest("git older than 2.44 can't read a partial clone without downloading")
        self.assertTrue(p["logOk"])
        self.assertTrue(p["diffFailed"], "a missing blob should fail, not be downloaded")
        self.assertTrue(p["unchanged"], "nothing under .git may change")

    def test_git_versions_decide_the_lazy_fetch_flag(self):
        self.assertEqual(self.out["versions"], [None, ["--no-lazy-fetch"], ["--no-lazy-fetch"], None])

    def test_the_dot_stays_visible_past_ten_lanes(self):
        lanes = self.out["lanes"]
        self.assertEqual(lanes["cols"], [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        for col, dot in zip(lanes["cols"], lanes["dots"]):
            self.assertEqual(dot, {"lane": min(col, 9), "over": col >= 10})
        self.assertEqual(lanes["span"], {"lanes": 10, "over": True})
        self.assertEqual(lanes["spanFirst"], {"lanes": 10, "over": False})
        self.assertEqual(lanes["spanJoined"], lanes["span"])

    def test_refs_and_branches(self):
        self.assertEqual(self.out["refs"], [{"name": "main", "head": True}, {"name": "origin/main"}, {"name": "v1", "tag": True}])
        self.assertEqual([b["ref"] for b in self.out["branches"]], ["refs/heads/main", "refs/remotes/origin/x"])

    def test_whether_the_layout_shows_the_panel(self):
        self.assertEqual(self.out["shows"], {"shown": True, "otherChild": False, "hiddenPanel": False,
                                             "none": None, "floating": True, "nothing": None})


if __name__ == "__main__":
    unittest.main()
