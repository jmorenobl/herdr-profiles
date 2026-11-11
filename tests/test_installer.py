"""Black-box tests for scripts/herdr_profiles.py against a throwaway Herdr home.

Run: python3 -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "herdr_profiles.py"
GOLDEN = REPO / "tests" / "golden"
# The core's own key (the bottom terminal): added with standard, so it stays when a profile goes.
STANDARD_KEY = {"ctrl-`": "standard-tabs.terminal"}


class HomeCase(unittest.TestCase):
    """A throwaway Herdr home (and a fake herdr-app) for each test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "installed.json").write_text(json.dumps({"files": {}, "layout:main": {}}))
        (self.home / "keys.json").write_text(json.dumps({"global": {"cmd-p": "mod.open:picker"}}))
        self.herdr_app = self.fake_herdr_app("herdr-app 0.1.14")

    def tearDown(self):
        self.tmp.cleanup()

    def fake_herdr_app(self, version_output, code=0, name="herdr-app"):
        """A herdr-app that prints `version_output` for --version: tests never use the real one."""
        bin_dir = Path(self.tmp.name + "-bin")
        bin_dir.mkdir(exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(bin_dir, ignore_errors=True))
        fake = bin_dir / name
        fake.write_text(f"#!/bin/sh\nprintf '%s\\n' {json.dumps(version_output)}\nexit {code}\n")
        fake.chmod(0o755)
        return str(fake)

    def env(self, **extra):
        return {**os.environ, "HERDR_APP_HOME": str(self.home), "HERDR_APP_BIN": self.herdr_app, **extra}

    def run_cmd(self, *args, **extra_env):
        env = self.env(**extra_env)
        # No terminal on stdin, ever: install would otherwise ask its questions.
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def written(self):
        return sorted(str(p.relative_to(self.home)) for kind in ("layouts", "mods", "themes")
                      for p in (self.home / kind).rglob("*"))

    def json(self, name):
        return json.loads((self.home / name).read_text())


class InstallerTest(HomeCase):
    def test_fresh_install_copies_files_and_personal_config(self):
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in ("mods/profiles/main.js", "mods/profiles/mod.json", "mods/ideas/store.js",
                    "layouts/standard.json", "layouts/ideas.json", "themes/ideas.json"):
            self.assertTrue((self.home / rel).is_file(), rel)
        config = json.loads((self.home / "profiles.json").read_text())
        self.assertEqual(config["default"], "standard")
        self.assertEqual(config["profiles"]["ideas"]["layout"], "ideas")
        self.assertIn({"path": "~/ideas", "profile": "ideas"}, config["rules"])
        keys = json.loads((self.home / "keys.json").read_text())
        self.assertEqual(keys["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertEqual(keys["global"]["cmd-p"], "mod.open:picker")
        self.assertFalse(list((self.home / "mods").glob(".*staging")))

    def test_install_matches_the_golden_snapshot(self):
        """What install writes. The layouts and keys.json are what install wrote on 2026-11-09,
        before layouts were built from recipes (keys.json plus the core's key, 2026-11-11); profiles.json too, except that the ideas folder
        became the asked one's default (~/ideas) on 2026-11-10. files.txt follows the repo's files."""
        self.assertEqual(self.run_cmd("install").returncode, 0)
        written = sorted(str(p.relative_to(self.home)) for kind in ("layouts", "mods", "themes")
                         for p in (self.home / kind).rglob("*") if p.is_file())
        self.assertEqual(written, (GOLDEN / "files.txt").read_text().split())
        for name in ("standard", "ideas"):
            self.assertEqual(json.loads((self.home / f"layouts/{name}.json").read_text()),
                             json.loads((GOLDEN / f"layouts/{name}.json").read_text()), name)
        for name in ("profiles.json", "keys.json"):
            self.assertEqual(json.loads((self.home / name).read_text()),
                             json.loads((GOLDEN / name).read_text()), name)
        for rel in written:  # everything but layouts is copied byte for byte
            if not rel.endswith(".json") or not rel.startswith("layouts/"):
                src = next(p for p in (REPO / "core", *(REPO / "profiles").iterdir())
                           if (p / rel).is_file()) / rel
                self.assertEqual((self.home / rel).read_bytes(), src.read_bytes(), rel)

    def test_every_layout_gets_the_switcher_once(self):
        self.run_cmd("install")
        for name in ("standard", "ideas"):
            layout = json.loads((self.home / f"layouts/{name}.json").read_text())
            mods = [f["content"]["mod"] for f in layout.get("floating", [])]
            self.assertEqual(mods.count("profiles"), 1, name)

    def test_second_install_changes_nothing(self):
        self.run_cmd("install")
        r = self.run_cmd("install")
        self.assertIn("Nothing to install", r.stdout)

    def test_personal_config_is_never_overwritten(self):
        self.run_cmd("install")
        config_path = self.home / "profiles.json"
        config = json.loads(config_path.read_text())
        config["rules"] = []  # the person removed the suggested rule
        config_path.write_text(json.dumps(config))
        self.run_cmd("install")
        self.assertEqual(json.loads(config_path.read_text())["rules"], [])

    def test_bound_key_is_not_replaced(self):
        (self.home / "keys.json").write_text(json.dumps({"global": {"ctrl-shift-i": "app.help"}}))
        r = self.run_cmd("install")
        self.assertIn("skipped", r.stdout)
        self.assertEqual(json.loads((self.home / "keys.json").read_text())["global"]["ctrl-shift-i"], "app.help")

    def test_edit_in_herdr_blocks_install_and_status_reports_it(self):
        self.run_cmd("install")
        (self.home / "themes/ideas.json").write_text("{}\n")
        self.assertIn("edited", self.run_cmd("status").stdout)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.home / "themes/ideas.json").read_text(), "{}\n")

    def test_unknown_file_in_the_way_is_a_clash(self):
        """Before 0.8.0 this was a "conflict" that --force overwrote: the person's own theme."""
        (self.home / "themes").mkdir()
        (self.home / "themes/ideas.json").write_text("{}\n")
        for args in ((), ("--force",)):
            r = self.run_cmd("install", *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("clash     themes/ideas.json  (profile ideas)", r.stdout, args)
            self.assertEqual((self.home / "themes/ideas.json").read_text(), "{}\n")
            self.assertFalse((self.home / "layouts").exists())

    def test_force_overwrites(self):
        self.run_cmd("install")
        (self.home / "themes/ideas.json").write_text("{}\n")
        self.assertEqual(self.run_cmd("install", "--force").returncode, 0)
        self.assertEqual((self.home / "themes/ideas.json").read_bytes(),
                         (REPO / "profiles/ideas/themes/ideas.json").read_bytes())

    def test_uninstall_removes_only_unedited_files(self):
        self.run_cmd("install")
        (self.home / "layouts/ideas.json").write_text("{}\n")
        self.run_cmd("uninstall")
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertFalse((self.home / "themes/ideas.json").exists())
        self.assertTrue((self.home / "layouts/ideas.json").exists())
        # install created profiles.json and nothing of the person's is in it: gone too (0.8.0)
        self.assertFalse((self.home / "profiles.json").exists())
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker"}})

    def repo_copy(self):
        """A throwaway copy of the repo, for commands that write into it."""
        import shutil
        repo = self.home.parent / f"{self.home.name}-repo"
        for part in ("scripts", "core", "profiles"):
            shutil.copytree(REPO / part, repo / part, ignore=shutil.ignore_patterns("__pycache__"))
        self.addCleanup(shutil.rmtree, repo)
        env = self.env()
        script = [sys.executable, str(repo / "scripts" / "herdr_profiles.py")]
        run = lambda *a: subprocess.run([*script, *a], env=env, capture_output=True, text=True,  # noqa: E731
                                        stdin=subprocess.DEVNULL)
        return repo, run

    def test_pull_brings_a_herdr_edit_back_into_the_repo(self):
        repo, run = self.repo_copy()
        run("install")
        (self.home / "themes/ideas.json").write_text('{"tweaked": true}\n')
        r = run("pull")
        self.assertIn("pulled", r.stdout)
        self.assertEqual((repo / "profiles/ideas/themes/ideas.json").read_text(), '{"tweaked": true}\n')
        self.assertIn("matches the repo", run("status").stdout)

    def test_pull_puts_a_plain_layout_back_into_its_source(self):
        repo, run = self.repo_copy()
        run("install")
        layout = json.loads((self.home / "layouts/standard.json").read_text())
        layout["background"] = "surface"
        (self.home / "layouts/standard.json").write_text(json.dumps(layout))
        self.assertIn("pulled", run("pull").stdout)
        source = json.loads((repo / "core/layouts/standard.json").read_text())
        self.assertEqual(source["background"], "surface")
        self.assertNotIn("floating", source)  # the switcher stays a build step
        self.assertEqual((self.home / "layouts/standard.json").read_text(), json.dumps(layout))  # pull never writes Herdr's home
        status = run("status").stdout
        self.assertIn("outdated  layouts/standard.json", status)  # same content, our format: install rewrites it
        self.assertIn("outdated  layouts/ideas.json", status)  # built on standard, so it follows
        self.assertEqual(run("install").returncode, 0)
        self.assertEqual(json.loads((self.home / "layouts/ideas.json").read_text())["background"], "surface")
        self.assertIn("matches the repo", run("status").stdout)

    def test_pull_leaves_an_edited_switcher_alone(self):
        repo, run = self.repo_copy()
        run("install")
        before = (repo / "core/layouts/standard.json").read_text()
        layout = json.loads((self.home / "layouts/standard.json").read_text())
        layout["floating"][0]["edge"] = "top"
        (self.home / "layouts/standard.json").write_text(json.dumps(layout, indent=2))
        r = run("pull")
        self.assertEqual(r.returncode, 1)
        self.assertIn("switcher block is added by the build", r.stdout)
        self.assertEqual((repo / "core/layouts/standard.json").read_text(), before)
        self.assertIn("edited", run("status").stdout)

    def test_pull_records_what_it_pulled(self):
        repo, run = self.repo_copy()
        run("install")
        (self.home / "themes/ideas.json").write_text('{"tweaked": true}\n')
        run("pull")
        (repo / "profiles/ideas/themes/ideas.json").write_text('{"again": true}\n')
        self.assertIn("outdated  themes/ideas.json", run("status").stdout)  # not a conflict

    def test_files_gone_from_the_repo_are_removed_on_install(self):
        repo, run = self.repo_copy()
        run("install")
        (repo / "profiles/ideas/mods/ideas/ui.js").unlink()
        r = run("install")
        self.assertIn("removed   mods/ideas/ui.js", r.stdout)
        self.assertFalse((self.home / "mods/ideas/ui.js").exists())

    def test_upgrade_from_a_hand_kept_layout_install(self):
        """A home installed before layouts were built: its layouts show as outdated, then match."""
        import hashlib
        self.run_cmd("install")
        manifest = json.loads((self.home / ".herdr-profiles.json").read_text())
        for name in ("standard", "ideas"):
            old = (GOLDEN / f"layouts/{name}.json").read_bytes()
            (self.home / f"layouts/{name}.json").write_bytes(old)
            manifest["files"][f"layouts/{name}.json"] = hashlib.sha256(old).hexdigest()
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        status = self.run_cmd("status").stdout
        self.assertIn("outdated  layouts/standard.json", status)
        self.assertEqual(self.run_cmd("install").returncode, 0)
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_broken_layout_source_is_an_error_not_a_traceback(self):
        repo, run = self.repo_copy()
        (repo / "core/layouts/standard.json").write_text("{ <<<<<<< merge")
        for command in ("status", "install", "pull"):
            r = run(command)
            self.assertEqual(r.returncode, 1, command)
            self.assertIn("invalid JSON", r.stderr, command)
            self.assertNotIn("Traceback", r.stderr, command)

    def test_a_stray_profiles_folder_is_skipped_with_a_note(self):
        repo, run = self.repo_copy()
        (repo / "profiles/wip").mkdir()
        r = run("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("profiles/wip/ has no profile.json", r.stdout)

    def test_an_unused_layout_file_is_an_error(self):
        repo, run = self.repo_copy()
        (repo / "profiles/ideas/layouts/ideas-wide.json").write_text("{}")
        r = run("install")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no recipe uses", r.stderr)

    def test_pull_shows_a_built_layout_edit_instead_of_guessing(self):
        repo, run = self.repo_copy()
        run("install")
        before = (repo / "profiles/ideas/profile.json").read_text()
        layout = json.loads((self.home / "layouts/ideas.json").read_text())
        layout["background"] = "surface"
        (self.home / "layouts/ideas.json").write_text(json.dumps(layout, indent=2))
        r = run("pull")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not pulled layouts/ideas.json", r.stdout)
        self.assertIn("profiles/ideas/profile.json", r.stdout)
        self.assertIn('"background": "surface"', r.stdout)
        self.assertNotIn("Nothing edited", r.stdout)
        self.assertEqual((repo / "profiles/ideas/profile.json").read_text(), before)
        self.assertIn("edited", run("status").stdout)

    # ----- questions asked the first time a profile is added -----

    def ideas_entry(self):
        config = json.loads((self.home / "profiles.json").read_text())
        rules = [r for r in config["rules"] if r["profile"] == "ideas"]
        return config["profiles"]["ideas"], rules

    def test_without_a_terminal_the_default_is_used_and_said(self):
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ideas.folder = ~/ideas (the default: no terminal to ask", r.stdout)
        entry, rules = self.ideas_entry()
        self.assertEqual(entry["folder"], "~/ideas")
        self.assertEqual(rules, [{"path": "~/ideas", "profile": "ideas"}])

    def test_set_answers_in_advance_and_the_rule_follows(self):
        r = self.run_cmd("install", "--set", "ideas.folder=~/notes/ideas")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("no terminal", r.stdout)
        entry, rules = self.ideas_entry()
        self.assertEqual(entry["folder"], "~/notes/ideas")
        self.assertEqual(rules, [{"path": "~/notes/ideas", "profile": "ideas"}])

    def test_a_bad_set_stops_before_writing(self):
        for bad in ("ideas.colour=red", "nope.folder=~/x", "ideas.folder=", "ideas=~/x"):
            r = self.run_cmd("install", "--set", bad)
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("--set", r.stderr, bad)
            self.assertFalse((self.home / "layouts").exists(), bad)

    def test_a_known_profile_is_never_asked_again(self):
        self.run_cmd("install")
        config = json.loads((self.home / "profiles.json").read_text())
        config["profiles"]["ideas"]["folder"] = "~/mine"
        (self.home / "profiles.json").write_text(json.dumps(config))
        (self.home / "themes/ideas.json").unlink()  # something to install
        r = self.run_cmd("install", "--set", "ideas.folder=~/other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("setting   ideas.folder", r.stdout)
        self.assertIn("--set ideas.folder ignored", r.stdout)
        self.assertEqual(self.ideas_entry()[0]["folder"], "~/mine")

    def test_a_profile_already_in_profiles_json_is_not_asked_and_its_rule_follows_it(self):
        """The person wrote the entry by hand before installing: their folder wins, no question."""
        (self.home / "profiles.json").write_text(json.dumps(
            {"default": None, "profiles": {"ideas": {"layout": "ideas", "folder": "~/mine"}}, "rules": []}))
        r = self.run_cmd("install")
        self.assertNotIn("setting   ideas.folder", r.stdout)
        entry, rules = self.ideas_entry()
        self.assertEqual(entry["folder"], "~/mine")
        self.assertEqual(rules, [{"path": "~/mine", "profile": "ideas"}])

    def test_an_entry_that_isnt_an_object_is_noted_not_a_crash(self):
        """At 6579b20 this installed; a non-object entry must not crash the merge."""
        for entry in ("oops", None, 3):
            with self.subTest(entry=entry):
                for p in ("profiles.json", ".herdr-profiles.json"):
                    (self.home / p).unlink(missing_ok=True)
                (self.home / "profiles.json").write_text(json.dumps(
                    {"default": None, "profiles": {"ideas": entry}, "rules": []}))
                r = self.run_cmd("install", "--force")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("ideas's entry isn't an object", r.stdout)
                config = json.loads((self.home / "profiles.json").read_text())
                self.assertEqual(config["profiles"]["ideas"], entry)  # left as it is
                self.assertIn({"path": "~/ideas", "profile": "ideas"}, config["rules"])
                self.assertIn("ideas", json.loads((self.home / ".herdr-profiles.json").read_text())["profiles"])
                self.assertIn("Nothing to install", self.run_cmd("install").stdout)

    def test_broken_personal_files_stop_install_before_anything_is_written(self):
        cases = [("profiles.json", "{not json"), ("profiles.json", "[]"),
                 ("profiles.json", '{"profiles": [], "rules": []}'), ("profiles.json", '{"profiles": {}, "rules": {}}'),
                 ("keys.json", "{nope"), ("keys.json", '{"global": 1}')]
        for name, text in cases:
            with self.subTest(name=name, text=text):
                (self.home / name).write_text(text)
                r = self.run_cmd("install")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(name, r.stderr)
                self.assertEqual(self.written(), [])
                self.assertFalse((self.home / ".herdr-profiles.json").exists())
                (self.home / name).unlink()
                (self.home / "keys.json").write_text(json.dumps({"global": {}}))

    def test_a_folder_answer_that_matches_everything_is_refused(self):
        home = os.path.expanduser("~")
        for bad in ("~", "/", "~/", "ideas", "~/a/../b", "~/x\ty", home, os.path.dirname(home), "~//x", "/srv//x"):
            r = self.run_cmd("install", "--set", f"ideas.folder={bad}")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("--set", r.stderr, bad)
            self.assertEqual(self.written(), [], bad)
        r = self.run_cmd("install", "--set", "ideas.folder=/srv/ideas/")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ideas_entry()[0]["folder"], "/srv/ideas")

    def test_a_bad_value_already_in_profiles_json_adds_no_rule(self):
        """The person's own entry (unknown to the manifest) with a folder that matches everything."""
        for folder in ("~", "/", os.path.dirname(os.path.expanduser("~")), 3):
            with self.subTest(folder=folder):
                for p in ("profiles.json", ".herdr-profiles.json"):
                    (self.home / p).unlink(missing_ok=True)
                mine = {"layout": "ideas", "folder": folder}
                (self.home / "profiles.json").write_text(json.dumps(
                    {"default": None, "profiles": {"ideas": mine}, "rules": []}))
                r = self.run_cmd("install", "--force")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"ideas.folder = {json.dumps(folder)} won't do", r.stdout)
                entry, rules = self.ideas_entry()
                self.assertEqual(entry, mine)  # untouched
                self.assertEqual(rules, [])

    def test_a_bad_set_for_a_known_profile_is_ignored(self):
        self.run_cmd("install")
        (self.home / "themes/ideas.json").unlink()
        r = self.run_cmd("install", "--set", "ideas.folder=~")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--set ideas.folder ignored: it's already in profiles.json", r.stdout)
        self.assertEqual(self.ideas_entry()[0]["folder"], "~/ideas")

    def test_a_default_that_cant_be_used_here_stops_install(self):
        """profile.json's default passes against no real home, but here it's the home folder."""
        repo, run = self.repo_copy()
        profile = repo / "profiles/ideas/profile.json"
        data = json.loads(profile.read_text())
        data["ask"][0]["default"] = os.path.expanduser("~")
        profile.write_text(json.dumps(data))
        r = run("install")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("the default for 'folder'", r.stderr)
        self.assertIn("--set ideas.folder=", r.stderr)
        self.assertEqual(self.written(), [])
        r = run("install", "--set", "ideas.folder=~/ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ideas_entry()[0]["folder"], "~/ok")

    def test_the_ignored_set_note_says_why(self):
        self.run_cmd("install")
        config = json.loads((self.home / "profiles.json").read_text())
        del config["profiles"]["ideas"]
        (self.home / "profiles.json").write_text(json.dumps(config))
        (self.home / "themes/ideas.json").unlink()
        r = self.run_cmd("install", "--set", "ideas.folder=~/other")
        self.assertIn("ignored: it was installed before", r.stdout)

    def in_process(self, stdin_tty, stdout_tty, answer, argv=("install",)):
        """cli.main in this process, with fake terminals and input(): returns (code, stdout, stderr)."""
        import builtins
        import contextlib
        import io
        from unittest import mock
        sys.path.insert(0, str(REPO / "scripts"))
        from profiletool import cli

        class Fake(io.StringIO):
            def __init__(self, tty):
                super().__init__()
                self.tty = tty

            def isatty(self):
                return self.tty

        out, err = Fake(stdout_tty), io.StringIO()
        with mock.patch.dict(os.environ, {"HERDR_APP_HOME": str(self.home), "HERDR_APP_BIN": self.herdr_app}), \
                mock.patch.object(sys, "stdin", Fake(stdin_tty)), \
                mock.patch.object(builtins, "input", answer), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except KeyboardInterrupt:
                code = "KeyboardInterrupt escaped cli.main"
        return code, out.getvalue(), err.getvalue()

    def test_stopping_at_the_question_leaves_the_home_untouched(self):
        def ctrl_c(_prompt):
            raise KeyboardInterrupt

        code, _out, err = self.in_process(True, True, ctrl_c)
        self.assertEqual(code, 130)
        self.assertIn("Stopped.", err)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.home / "profiles.json").exists())
        self.assertFalse((self.home / ".herdr-profiles.json").exists())

    def test_it_asks_only_when_stdin_and_stdout_are_terminals(self):
        def never(_prompt):
            raise AssertionError("asked without a terminal on stdout")

        code, out, _ = self.in_process(True, False, never)
        self.assertEqual(code, 0)
        self.assertIn("no terminal to ask", out)

    def run_on_a_terminal(self, typed, *args):
        """install with stdin and stdout on a pty (a terminal); returns (exit code, what it printed)."""
        import pty
        import select
        main, child = pty.openpty()
        env = self.env()
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "install", *args], env=env,
                                stdin=child, stdout=child, stderr=child)  # input() prompts on stderr there
        os.close(child)
        os.write(main, typed.encode())
        out = b""
        while True:
            ready, _, _ = select.select([main], [], [], 30)
            if not ready:
                proc.kill()
                self.fail(f"install hung; printed so far: {out.decode(errors='replace')}")
            try:
                chunk = os.read(main, 65536)
            except OSError:  # the child closed its side
                break
            if not chunk:
                break
            out += chunk
        os.close(main)
        code = proc.wait(timeout=30)
        return code, out.decode(errors="replace")

    def test_on_a_terminal_it_asks_and_enter_takes_the_default(self):
        for typed, folder in (("~/my ideas\n", "~/my ideas"), ("\n", "~/ideas"),
                              ("~\n/\nideas\n~/ok/\n", "~/ok")):  # bad answers are asked again
            with self.subTest(typed=typed):
                for p in ("profiles.json", ".herdr-profiles.json"):
                    (self.home / p).unlink(missing_ok=True)
                code, out = self.run_on_a_terminal(typed, "--force")
                self.assertEqual(code, 0, out)
                self.assertIn("ideas: Where do your ideas live? [~/ideas]", out)
                entry, rules = self.ideas_entry()
                self.assertEqual(entry["folder"], folder)
                self.assertEqual(rules, [{"path": folder, "profile": "ideas"}])
                if folder == "~/ok":
                    self.assertEqual(out.count("won't do"), 3, out)
                    self.assertIn("your home folder", out)

    def test_refuses_to_replace_a_shipped_name(self):
        for shipped in ("ideas", "layout:ideas"):  # a mod, a layout
            (self.home / "installed.json").write_text(json.dumps({shipped: {}}))
            r = self.run_cmd("install")
            self.assertNotEqual(r.returncode, 0, shipped)
            self.assertIn("Herdr ships", r.stderr, shipped)
            self.assertFalse((self.home / "layouts").exists(), shipped)  # nothing written


if __name__ == "__main__":
    unittest.main()
