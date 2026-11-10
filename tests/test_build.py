"""Unit tests for profile.json parsing and layout building (scripts/profiletool).

Run: python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from profiletool import build, spec  # noqa: E402

BASE = {
    "id": "root", "cloned_from": {"name": "main", "version": "0"}, "type": "row",
    "children": [{"id": "work", "type": "column", "children": [{"id": "main", "type": "block"}]}],
}


class Packages:
    """Throwaway packages: write(name, profile, layout file) -> Package."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, name, profile, layout=None):
        folder = self.root / name
        (folder / "layouts").mkdir(parents=True)
        if layout is not None:
            (folder / "layouts" / f"{name}.json").write_text(json.dumps(layout))
        (folder / "profile.json").write_text(json.dumps({"schema": 2, "name": name, **profile}))
        return spec.load(folder)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.p = Packages(self)
        self.base = self.p.write("base", {"layout": {"name": "base", "source": "layouts/base.json"}}, BASE)

    def test_source_layout_gets_the_switcher(self):
        tree = build.build(self.base, [self.base])
        self.assertEqual(tree["floating"], [build.SWITCHER])
        self.assertEqual(tree["cloned_from"], BASE["cloned_from"])  # the source's own provenance stays

    def test_switcher_is_not_added_twice(self):
        own = self.p.write("own", {"layout": {"name": "own", "source": "layouts/own.json"}},
                           {**BASE, "floating": [build.SWITCHER]})
        self.assertEqual(len(build.build(own, [own])["floating"]), 1)

    def test_derived_layout_inserts_sets_and_drops_provenance(self):
        node = {"id": "side", "type": "block", "content": {"mod": "side"}}
        derived = self.p.write("derived", {"layout": {
            "name": "derived", "base": "base",
            "insert": [{"into": "work", "after": "main", "node": node}],
            "set": {"theme": "warm"},
        }})
        tree = build.build(derived, [self.base, derived])
        self.assertNotIn("cloned_from", tree)
        self.assertEqual([c["id"] for c in tree["children"][0]["children"]], ["main", "side"])
        self.assertEqual(tree["theme"], "warm")
        self.assertEqual(build.mods_in(tree), {"side", "profiles"})
        self.assertNotIn("side", build.mods_in(build.build(self.base, [self.base, derived])))  # base untouched

    def test_insert_before_and_last(self):
        derived = self.p.write("derived", {"layout": {"name": "derived", "base": "base", "insert": [
            {"into": "work", "before": "main", "node": {"id": "first"}},
            {"into": "work", "node": {"id": "last"}},
        ]}})
        tree = build.build(derived, [self.base, derived])
        self.assertEqual([c["id"] for c in tree["children"][0]["children"]], ["first", "main", "last"])

    def test_insert_errors_name_the_problem(self):
        cases = [({"into": "nowhere", "node": {"id": "x"}}, "no node 'nowhere'"),
                 ({"into": "work", "after": "ghost", "node": {"id": "x"}}, "no child 'ghost'"),
                 ({"into": "work", "node": {"id": "main"}}, "already exists")]
        for n, (item, message) in enumerate(cases):
            derived = self.p.write(f"bad{n}", {"layout": {"name": f"bad{n}", "base": "base", "insert": [item]}})
            with self.assertRaisesRegex(spec.SpecError, message):
                build.build(derived, [self.base, derived])

    def test_missing_base_and_loops_are_errors(self):
        a = self.p.write("a", {"layout": {"name": "a", "base": "b"}})
        with self.assertRaisesRegex(spec.SpecError, "not in any package"):
            build.build(a, [a])
        b = self.p.write("b", {"layout": {"name": "b", "base": "a"}})
        with self.assertRaisesRegex(spec.SpecError, "loop"):
            build.build(a, [a, b])

    def test_unbuild_removes_only_the_switcher(self):
        tree = build.build(self.base, [self.base])
        self.assertEqual(build.unbuild(self.base, tree), BASE)
        other = {"id": "clock", "content": {"mod": "clock"}}
        tree["floating"].append(other)
        self.assertEqual(build.unbuild(self.base, tree)["floating"], [other])

    def test_unbuild_refuses_what_it_cant_put_back(self):
        tree = build.build(self.base, [self.base])
        tree["floating"][0]["edge"] = "top"  # the switcher itself was edited
        self.assertIsNone(build.unbuild(self.base, tree))
        derived = self.p.write("derived", {"layout": {"name": "derived", "base": "base"}})
        self.assertIsNone(build.unbuild(derived, build.build(derived, [self.base, derived])))

    def test_invalid_source_json_is_a_spec_error(self):
        (self.base.path / "layouts/base.json").write_text("{ nope")
        with self.assertRaisesRegex(spec.SpecError, "invalid JSON"):
            build.build(self.base, [self.base])


class SpecTest(unittest.TestCase):
    def setUp(self):
        self.p = Packages(self)

    def test_schema_1_layout_name_still_reads(self):
        folder = self.p.root / "old"
        (folder / "layouts").mkdir(parents=True)
        (folder / "layouts/old.json").write_text(json.dumps(BASE))
        (folder / "profile.json").write_text(json.dumps({"name": "old", "layout": "old"}))
        pkg = spec.load(folder)
        self.assertEqual((pkg.layout.name, pkg.layout.source), ("old", "layouts/old.json"))

    def test_invalid_profiles_say_why(self):
        layout = {"name": "x", "source": "layouts/x.json"}
        cases = [
            ({"layout": layout, "colour": 1}, "unknown keys"),
            ({"layout": {"name": "x"}}, "exactly one of"),
            ({"layout": {"name": "x", "source": "layouts/x.json", "base": "y"}}, "exactly one of"),
            ({"layout": {"name": "x", "source": "nope.json"}}, "not a file"),
            ({"layout": layout, "rules": [{"profile": "x", "path": "~"}]}, "'rules'"),
            ({"layout": layout, "keys": {"global": {"k": 1}}}, "'keys'"),
            ({"layout": {**layout, "set": {"children": []}}, }, "can't replace"),
            ({"schema": 9, "layout": layout}, "not supported"),
        ]
        for n, (profile, message) in enumerate(cases):
            with self.subTest(message=message):
                with self.assertRaisesRegex(spec.SpecError, message):
                    self.write_x(n, profile)

    def test_invalid_asks_say_why(self):
        layout = {"name": "x", "source": "layouts/x.json"}
        ok = {"setting": "folder", "question": "Where?", "default": "~/x"}
        cases = [
            ({"ask": {"setting": "folder"}}, "'ask' must be a list"),
            ({"ask": [{"setting": "folder", "question": "Where?"}]}, r"'ask\[0\]' needs exactly"),
            ({"ask": [{**ok, "extra": 1}]}, r"'ask\[0\]' needs exactly"),
            ({"ask": [{**ok, "setting": "a.b"}]}, "must be a setting name"),
            ({"ask": [{**ok, "setting": "layout"}]}, "must be a setting name"),
            ({"ask": [{**ok, "question": "  "}]}, "question' must be a non-empty"),
            ({"ask": [{**ok, "default": ""}]}, "default' must be a non-empty"),
            ({"ask": [{**ok, "default": 3}]}, "default' must be a non-empty"),
            ({"ask": [ok, ok]}, "asked twice"),
            ({"ask": [ok], "settings": {"folder": "~/y"}}, "also in 'settings'"),
            ({"rules": [{"path": "{folder}"}]}, r"uses \{folder\}, which no 'ask' sets"),
            ({"ask": [{**ok, "kind": "path"}]}, "kind' must be one of"),
            ({"ask": [{**ok, "kind": "folder", "default": "~"}]}, "home folder"),
            ({"ask": [{**ok, "kind": "folder", "default": "notes"}]}, "starting with / or ~/"),
            ({"ask": [{**ok, "default": "a\nb"}]}, "control characters"),
            ({"ask": [ok], "rules": [{"path": "{folders}"}]}, r"uses \{folders\}"),
        ]
        for n, (profile, message) in enumerate(cases):
            with self.subTest(message=message):
                with self.assertRaisesRegex(spec.SpecError, message):
                    self.write_x(100 + n, {"layout": layout, **profile})

    def test_ask_and_a_rule_using_it_read(self):
        pkg = self.write_x(200, {"layout": {"name": "x", "source": "layouts/x.json"},
                                 "ask": [{"setting": "folder", "question": " Where? ", "default": "~/x"}],
                                 "rules": [{"path": "{folder}/inbox"}]})
        self.assertEqual(pkg.ask, (spec.Ask("folder", "Where?", "~/x"),))

    def write_x(self, n, profile):
        """A package named x in its own folder, with layouts/x.json."""
        folder = self.p.root / f"case{n}"
        (folder / "layouts").mkdir(parents=True)
        (folder / "layouts/x.json").write_text(json.dumps(BASE))
        (folder / "profile.json").write_text(json.dumps({"schema": 2, "name": "x", **profile}))
        return spec.load(folder)

    def test_the_repo_packages_are_valid(self):
        names = [p.name for p in spec.discover(REPO)]
        self.assertEqual(names[0], "standard")
        self.assertIn("ideas", names)


class PersonalTest(unittest.TestCase):
    """The first-time questions, in process: the prompt is injected."""

    def setUp(self):
        from profiletool import home
        self.p = Packages(self)
        self.home = home.Home(self.p.root / "home")
        self.home.path.mkdir()
        self.pkg = self.p.write("x", {"layout": {"name": "x", "source": "layouts/x.json"},
                                      "ask": [{"setting": "folder", "question": "Where?", "default": "~/x"},
                                              {"setting": "name", "question": "Name?", "default": "X"}],
                                      "rules": [{"path": "{folder}/{name}"}]}, BASE)

    def test_answers_blank_and_eof_take_the_default_and_fill_the_rule(self):
        from profiletool import personal
        asked = []

        def prompt(text):
            asked.append(text)
            if len(asked) == 2:
                raise EOFError
            return "  "

        manifest = {}
        answers = personal.ask_first_time([self.pkg], self.home, manifest, {}, prompt)
        self.assertEqual(asked, ["  x: Where? [~/x] ", "  x: Name? [X] "])
        self.assertEqual(answers, {"x": {"folder": "~/x", "name": "X"}})
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            personal.merge_first_time([self.pkg], self.home, manifest, {"x": {"folder": "/f", "name": "n"}})
        config = json.loads(self.home.profiles_path.read_text())
        self.assertEqual(config["profiles"]["x"], {"layout": "x", "folder": "/f", "name": "n"})
        self.assertEqual(config["rules"], [{"path": "/f/n", "profile": "x"}])
        self.assertEqual(personal.ask_first_time([self.pkg], self.home, manifest, {}, prompt), {})
        self.assertEqual(len(asked), 2)  # known now: not asked again


if __name__ == "__main__":
    unittest.main()
