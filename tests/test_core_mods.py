"""The core mods' pure parts, run under node with stand-in Herdr modules.

The Files panel's markdown image splitter (core/mods/standard-files/markdown.js)
and its copy of an image on another machine (pictures.js, its shell scripts run
with sh),
and the profile switcher's config reading and rule matching
(core/mods/profiles/main.js), plus the switcher's FIND_UP shell script run with
sh on a throwaway folder, and the tab bar's bottom terminal
(core/mods/standard-tabs/terminal.js). Skipped when node isn't installed.
Run: python3 -m unittest discover -s tests
"""

import base64
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
        shutil.copy(CORE / "standard-files" / "pictures.js", code / "pictures.js")
        shutil.copy(CORE / "standard-tabs" / "terminal.js", code / "terminal.js")
        shutil.copy(JS / "core_stubs.js", code / "stubs.js")
        shutil.copy(JS / "core_mods_test.js", code / "core_mods_test.js")
        (code / "package.json").write_text('{"type": "module"}\n')
        work = cls.root / "work"
        (work / "proj" / "sub").mkdir(parents=True)
        (work / "proj" / ".herdr-profile").write_text("ideas\n")
        (work / "img").mkdir()
        cls.image = bytes(range(256)) * 1000 + os.urandom(44_000)  # 300,000 bytes: 4 pieces of base64
        (work / "img" / "a.png").write_bytes(cls.image)
        with open(work / "img" / "big.png", "wb") as f:
            f.truncate(5_000_001)
        cls.work = work
        r = subprocess.run([NODE, str(code / "core_mods_test.js"), str(work)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.out = json.loads(r.stdout)

    # The tab bar's bottom terminal.

    def test_the_toggle_starts_a_shell_when_the_space_has_none(self):
        t = self.out["terminal"]
        for case in ("none", "othersOnly", "finished", "remote"):  # remote: box/t1 is box's, not this space's
            with self.subTest(case):
                self.assertEqual(t[case], {"step": "start"})

    def test_the_toggle_shows_hides_or_moves_the_spaces_shell(self):
        t = self.out["terminal"]
        self.assertEqual(t["parked"], {"step": "show", "terminal": "t1"})
        self.assertEqual(t["here"], {"step": "hide", "terminal": "t1"})
        self.assertEqual(t["elsewhere"], {"step": "move", "terminal": "t1"})

    def test_only_parked_shells_of_closed_spaces_are_orphans(self):
        self.assertEqual(self.out["terminal"]["orphans"], ["t2"])

    def test_the_shell_starts_labelled_in_the_folder(self):
        label = ["run", "--bg", "--json", "--no-parent", "--label", "standard.terminal=sp1"]
        self.assertEqual(self.out["terminal"]["startLocal"], [*label, "--cwd", "/work/repo"])
        self.assertEqual(self.out["terminal"]["startNoFolder"], label)

    def test_a_remote_space_gets_its_shell_on_its_machine(self):
        r = self.out["remote"]
        self.assertEqual(r["start"], ["run", "--bg", "--json", "--no-parent", "--label", "standard.terminal=sp1",
                                      "--on", "box", "--cwd", "/home/me/repo"])
        self.assertEqual(r["none"], {"step": "start"})  # shells here or on another machine aren't box's
        self.assertEqual(r["parked"], {"step": "show", "terminal": "box/t1"})
        self.assertEqual(r["qualified"], {"step": "show", "terminal": "box/t1"})
        self.assertEqual(r["here"], {"step": "hide", "terminal": "box/t1"})
        self.assertEqual(r["elsewhere"], {"step": "move", "terminal": "box/t1"})
        self.assertEqual(r["localTwin"], {"step": "start"})

    def test_remote_orphans_only_once_their_machine_is_known(self):
        r = self.out["remote"]
        self.assertEqual(r["orphansReady"], ["box/t2", "box/t3", "t4"])
        self.assertEqual(r["orphansLoading"], ["t4"])

    # The Files panel's images on another machine.

    def test_a_remote_image_is_copied_into_the_cache_once(self):
        p = self.out["pictures"]
        first, again = p["first"], p["again"]
        self.assertRegex(first.get("name", ""), r"^[0-9a-f]{8}\.png$", first)
        self.assertEqual((self.work / "cache" / first["name"]).read_bytes(), self.image)
        pieces = -(-len(base64.b64encode(self.image)) // p["piece"])
        self.assertGreater(pieces, 1)
        self.assertEqual([c["step"] for c in first["calls"]], ["read", "check", "read", *["add"] * pieces, "done"])
        # Only the reads go to the other machine; the cache is this computer's.
        self.assertEqual([c["on"] for c in first["calls"]], ["box", None, "box", *[None] * pieces, None])
        self.assertEqual(again["name"], first["name"])
        self.assertEqual([c["step"] for c in again["calls"]], ["read", "check"])
        self.assertEqual(sorted(f.name for f in (self.work / "cache").iterdir()), [first["name"]])  # no part files left

    def test_a_remote_image_too_big_or_gone_says_why(self):
        p = self.out["pictures"]
        self.assertEqual(p["max"], 5_000_000)
        self.assertEqual(p["big"]["error"], "too big to copy here")
        self.assertEqual(len(p["big"]["calls"]), 1)  # nothing read
        self.assertEqual(p["gone"]["error"], "can't read it")

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

    def test_rules_naming_a_machine(self):
        m = self.out["machineRules"]
        self.assertEqual(m["boxFull"], "ideas")
        self.assertEqual(m["boxTilde"], "ideas")  # ~ is box's home
        self.assertEqual(m["localSpace"], "standard")  # a space here isn't box's
        self.assertEqual(m["otherMachine"], "standard")
        self.assertEqual(m["noMachineRule"], "ideas")  # without machine: any space, as before
        self.assertEqual(m["noMachineTilde"], "standard")  # ... and ~ is this computer's, not read there
        self.assertEqual(m["badMachine"], "standard")
        self.assertEqual(m["boxHas"], "ideas")
        self.assertEqual(m["unreachable"], "standard")

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
