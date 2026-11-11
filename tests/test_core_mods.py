"""The core mods' pure parts, run under node with stand-in Herdr modules.

The Files panel's markdown image splitter (core/mods/standard-files/markdown.js)
and the profile switcher's config reading and rule matching
(core/mods/profiles/main.js), plus the switcher's FIND_UP shell script run with
sh on a throwaway folder, and the tab bar's bottom terminal
(core/mods/standard-tabs/terminal.js). Skipped when node isn't installed.
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
CORE = REPO / "core" / "mods"
JS = REPO / "tests" / "js"
NODE = shutil.which("node")


def picture(alt, src, link=None):
    p = {"alt": alt, "src": src}
    if link is not None:
        p["link"] = link
    return p


@unittest.skipUnless(NODE, "node is not installed")
class CoreModsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name).resolve()
        code = cls.root / "mod"
        code.mkdir()
        text = (CORE / "profiles" / "main.js").read_text()
        text = re.sub(r'from "(herdr|gpui-kit|gpui-base)"', 'from "./stubs.js"', text)
        (code / "profiles.js").write_text(text)
        shutil.copy(CORE / "standard-files" / "markdown.js", code / "markdown.js")
        shutil.copy(CORE / "standard-tabs" / "terminal.js", code / "terminal.js")
        shutil.copy(JS / "core_stubs.js", code / "stubs.js")
        shutil.copy(JS / "core_mods_test.js", code / "core_mods_test.js")
        (code / "package.json").write_text('{"type": "module"}\n')
        work = cls.root / "work"
        (work / "proj" / "sub").mkdir(parents=True)
        (work / "proj" / ".herdr-profile").write_text("ideas\n")
        cls.work = work
        r = subprocess.run([NODE, str(code / "core_mods_test.js"), str(work)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.out = json.loads(r.stdout)

    # The tab bar's bottom terminal.

    def test_the_toggle_starts_a_shell_when_the_space_has_none(self):
        t = self.out["terminal"]
        for case in ("none", "othersOnly", "finished", "remote"):
            with self.subTest(case):
                self.assertEqual(t[case], {"step": "start"})

    def test_the_toggle_shows_hides_or_moves_the_spaces_shell(self):
        t = self.out["terminal"]
        self.assertEqual(t["parked"], {"step": "show", "terminal": "t1"})
        self.assertEqual(t["here"], {"step": "hide", "terminal": "t1"})
        self.assertEqual(t["elsewhere"], {"step": "move", "terminal": "t1"})

    def test_only_parked_shells_of_closed_spaces_are_orphans(self):
        self.assertEqual(self.out["terminal"]["orphans"], ["t2"])

    # The Files panel's markdown images.

    def split(self, name):
        return self.out["split"][name]

    def assertText(self, name, *pieces):
        """The markdown stays one text part, with these pieces in it."""
        parts = self.split(name)
        self.assertEqual(len(parts), 1, parts)
        self.assertIsInstance(parts[0], str)
        for piece in pieces:
            self.assertIn(piece, parts[0])

    def test_a_badge_is_one_picture_that_keeps_its_link(self):
        self.assertEqual(self.split("badge"), [picture("CI", "https://x.test/badge.svg", "https://x.test/actions")])
        self.assertEqual(self.split("badgeAngle"), [picture("CI", "a b.svg", "docs/a b.md")])

    def test_a_row_of_badges_stays_text_with_its_links(self):
        self.assertText("badgeRow", "[CI](https://x.test/ci) [Cov](https://x.test/cov)")
        self.assertNotIn("![", self.split("badgeRow")[0])

    def test_images_in_tables_and_lists_become_their_alt_text(self):
        self.assertText("table", "| x | y |", "|---|---|")
        self.assertText("list", "- item i more\n- next")
        self.assertText("inline", "See logo here.")
        self.assertText("continuation", "Text\n    cont")

    def test_code_and_comments_are_left_alone(self):
        self.assertText("codeSpan", "`![alt](path)`", "``![b](c) `x` ``")
        self.assertText("indented", "    ![code](code.png)")
        self.assertText("longFence", "```\n![f](f.png)\n````")
        self.assertText("tilde", "![f](f.png)")
        self.assertText("escaped", "\\![no](x.png)")
        self.assertEqual(self.split("fenced"), ["```md\n![f](f.png)\n```\n", picture("after", "a.png")])
        self.assertEqual(self.split("comment"), ["<!-- ![c](c.png) -->\n", picture("real", "r.png")])
        self.assertEqual(self.split("multiComment"), ["<!--\n![c](c.png)\n-->\n", picture("real", "r.png")])

    def test_block_images(self):
        self.assertEqual(self.split("angle"), [picture("sp", "a b.png")])
        self.assertEqual(self.split("title"), [picture("t", "a.png")])
        intro, shot, after = self.split("block")
        self.assertEqual(shot, picture("shot", "docs/shot.png"))
        self.assertIn("Intro", intro)
        self.assertIn("After", after)
        self.assertEqual(self.split("html"), [picture("Logo", "logo.png")])
        self.assertEqual(self.split("htmlLinked"), [picture("", "b.svg", "https://x.test")])

    def test_block_images_in_lists_and_quotes(self):
        self.assertEqual(self.split("listItem")[1], picture("shot", "shot.png"))
        self.assertEqual(self.split("listBlock")[1], picture("i", "a.png"))
        self.assertText("lazy", "- item\n  lazy")
        self.assertEqual(self.split("quote"), [picture("q", "q.png")])
        self.assertEqual(self.split("afterList")[1], picture("x", "x.png"))
        self.assertEqual(self.split("afterBreak")[1], picture("x", "x.png"))
        self.assertEqual(self.split("indentedFence")[1], picture("x", "x.png"))  # indented ``` is code, not a fence
        self.assertText("listFence", "![f](f.png)")

    def test_odd_images(self):
        self.assertText("emptyAlt", "[a.svg](https://x.test/ci) b.png")  # never an empty, invisible link
        self.assertEqual(self.split("parens"), [picture("a", "foo_(bar).png")])
        self.assertEqual(self.split("selfClosing"), [picture("x", "x")])

    def test_long_lines_stay_fast(self):
        for line, ms in self.out["slow"].items():
            with self.subTest(line=line):
                self.assertLess(ms, 3000)

    def test_link_targets(self):
        links = self.out["links"]
        self.assertEqual(links["folder"], "docs")
        self.assertEqual(links["space"], "docs/a b.png")
        self.assertEqual(links["encoded"], "a b.png")
        self.assertIsNone(links["up"])

    # The profile switcher's config.

    def test_config_of_any_shape_is_normalised(self):
        empty = {"default": None, "profiles": {}, "rules": []}
        c = self.out["config"]
        for name in ("missing", "badJson", "nullJson", "array", "string"):
            with self.subTest(name):
                self.assertEqual(c[name], empty)
        self.assertEqual(c["rulesObject"], {"default": "standard", "profiles": {"standard": {"layout": "standard"}}, "rules": []})
        self.assertEqual(c["badShapes"], {"default": None, "profiles": {"a": {"layout": "a"}}, "rules": [{"path": "~/a", "profile": "a"}]})
        self.assertEqual(c["profilesArray"]["profiles"], {})
        logs = self.out["logs"]
        self.assertEqual(sum("not valid JSON" in line for line in logs), 1, logs)  # only for "{nope"
        self.assertEqual(sum("not a JSON object" in line for line in logs), 3, logs)

    def test_profile_for_a_space(self):
        p = self.out["pick"]
        self.assertEqual(p["marker"], {"profile": "ideas"})
        # Names that are only object built-ins aren't profiles.
        self.assertEqual(p["markerProto"], {"profile": "standard"})
        self.assertEqual(p["markerUnknown"], {"profile": "standard"})
        self.assertEqual(p["badRules"], {"profile": "standard"})
        self.assertEqual(p["path"], {"profile": "ideas"})
        self.assertEqual(p["has"], {"profile": "ideas"})
        self.assertEqual(p["hasMissing"], {"profile": "standard"})
        self.assertEqual(p["loaded"], {"profile": "standard"})  # ideas: null is no profile

    # FIND_UP, the switcher's shell script.

    def find_up(self, folder, name, home=None):
        env = dict(os.environ, HOME=str(home or self.work))
        return subprocess.run(["sh", "-c", self.out["findUp"], "profiles", folder, name],
                              capture_output=True, text=True, timeout=5, cwd=self.work, env=env)

    def test_find_up_finds_in_a_parent(self):
        r = self.find_up(str(self.work / "proj" / "sub"), ".herdr-profile")
        self.assertEqual((r.returncode, r.stdout), (0, f"{self.work}/proj/.herdr-profile"))

    def test_find_up_reads_tilde_as_that_machines_home(self):
        r = self.find_up("~/proj/sub", ".herdr-profile")
        self.assertEqual((r.returncode, r.stdout), (0, f"{self.work}/proj/.herdr-profile"))
        r = self.find_up("~", "proj")
        self.assertEqual((r.returncode, r.stdout), (0, f"{self.work}/proj"))

    def test_find_up_stops(self):
        for folder in ("proj/sub", ".", "x", "~x", "", "/", "//"):
            with self.subTest(folder=folder):
                r = self.find_up(folder, "no-such-name-here")  # a timeout raises
                self.assertEqual((r.returncode, r.stdout), (1, ""))
        r = self.find_up("proj/sub", ".herdr-profile")  # relative: no parents to look in
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
