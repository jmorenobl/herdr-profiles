"""Installing for other people (0.8.0): profiles by name, uninstalling one, the Herdr version,
name clashes with the person's own files, old manifests and Ctrl-C; and (0.8.1) profiles
uninstalled on purpose and what an install before 0.8.0 added, recognised.

Run: python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import unittest
from pathlib import Path

import test_installer
from test_installer import REPO, STANDARD_KEY, HomeCase

IDEAS_KEY = {"ctrl-shift-i": "mod.open:ideas"}
IDEAS_RULE = {"path": "~/ideas", "profile": "ideas"}


class SubsetTest(HomeCase):
    def test_install_standard_installs_only_the_core(self):
        r = self.run_cmd("install", "standard")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / "layouts/standard.json").is_file())
        self.assertTrue((self.home / "mods/profiles/main.js").is_file())
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertFalse((self.home / "layouts/ideas.json").exists())
        config = self.json("profiles.json")
        self.assertEqual(list(config["profiles"]), ["standard"])
        self.assertEqual(config["rules"], [])
        self.assertNotIn("ctrl-shift-i", self.json("keys.json")["global"])
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard"])
        status = self.run_cmd("status").stdout
        self.assertIn("available ideas  (not installed: `install ideas`)", status)
        self.assertIn("matches the repo", status)

    def test_naming_a_profile_brings_the_core(self):
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("also      standard (the core)", r.stdout)
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard", "ideas"])
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_adding_a_profile_later(self):
        self.run_cmd("install", "standard")
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertIn(IDEAS_RULE, self.json("profiles.json")["rules"])

    def test_a_subset_never_removes_an_installed_profile(self):
        self.run_cmd("install")
        (self.home / "themes/ideas.json").unlink()  # something for the subset install to update
        r = self.run_cmd("install", "standard")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("also      ideas (installed already)", r.stdout)
        self.assertNotIn("removed", r.stdout)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())
        self.assertTrue((self.home / "themes/ideas.json").is_file())  # and kept in step
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard", "ideas"])

    def test_an_unknown_name_lists_the_available_ones(self):
        r = self.run_cmd("install", "idea")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no profile named 'idea'. Available: standard (the core, always installed), ideas", r.stderr)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.home / ".herdr-profiles.json").exists())

    def test_a_set_for_a_profile_not_installed_is_noted(self):
        r = self.run_cmd("install", "standard", "--set", "ideas.folder=~/x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--set ideas.… ignored: ideas isn't being installed", r.stdout)

    def test_status_of_an_empty_home(self):
        status = self.run_cmd("status").stdout
        self.assertIn("Nothing installed in this Herdr home yet.", status)
        self.assertIn("available standard", status)

    def test_make_passes_profiles_through_args(self):
        env = self.env()
        r = subprocess.run(["make", "-s", "install", "ARGS=standard"], cwd=REPO, env=env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard"])
        self.run_cmd("install", "ideas")
        r = subprocess.run(["make", "-s", "uninstall", "ARGS=ideas"], cwd=REPO, env=env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard"])


class UninstallProfileTest(HomeCase):
    def test_uninstall_one_profile_takes_back_what_install_added(self):
        self.run_cmd("install")
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertFalse((self.home / "layouts/ideas.json").exists())
        self.assertFalse((self.home / "themes/ideas.json").exists())
        self.assertTrue((self.home / "layouts/standard.json").is_file())
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker", **STANDARD_KEY}})  # the core's key stays
        config = self.json("profiles.json")
        self.assertEqual(config, {"default": "standard", "profiles": {"standard": {"layout": "standard"}},
                                  "rules": []})
        self.assertIn("removed   key ctrl-shift-i -> mod.open:ideas", r.stdout)
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["installed"], ["standard"])
        self.assertNotIn("ideas", manifest["profiles"])
        self.assertFalse([rel for rel in manifest["files"] if "ideas" in rel])
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_reinstalling_after_uninstall_is_a_first_time_again(self):
        self.run_cmd("install")
        self.run_cmd("uninstall", "ideas")
        r = self.run_cmd("install", "ideas", "--set", "ideas.folder=~/notes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("ignored", r.stdout)
        config = self.json("profiles.json")
        self.assertEqual(config["profiles"]["ideas"]["folder"], "~/notes")
        self.assertEqual(config["rules"], [{"path": "~/notes", "profile": "ideas"}])
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_what_the_person_changed_is_kept_and_said(self):
        self.run_cmd("install")
        keys = self.json("keys.json")
        keys["global"]["ctrl-shift-i"] = "app.help"     # rebound by hand
        keys["global"]["ctrl-shift-n"] = "mod.open:ideas"  # their own, to the same mod
        (self.home / "keys.json").write_text(json.dumps(keys))
        config = self.json("profiles.json")
        config["profiles"]["ideas"]["folder"] = "~/elsewhere"  # entry edited
        config["rules"] = [{"path": "~/elsewhere", "profile": "ideas"},  # the rule edited
                           {"has": ".mine", "profile": "standard"}]      # one of their own
        (self.home / "profiles.json").write_text(json.dumps(config))
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("kept      key ctrl-shift-i: now bound to 'app.help'", r.stdout)
        self.assertIn("kept      profiles.json entry 'ideas': changed since install", r.stdout)
        self.assertIn('kept      profiles.json rule {"path": "~/elsewhere", "profile": "ideas"}', r.stdout)
        self.assertEqual(self.json("keys.json")["global"],
                         {"cmd-p": "mod.open:picker", **STANDARD_KEY, "ctrl-shift-i": "app.help",
                          "ctrl-shift-n": "mod.open:ideas"})
        after = self.json("profiles.json")
        self.assertEqual(after["profiles"]["ideas"], {"layout": "ideas", "folder": "~/elsewhere"})
        self.assertEqual(after["rules"], config["rules"])

    def test_an_entry_the_person_had_before_install_stays(self):
        mine = {"layout": "ideas", "folder": "~/mine"}
        (self.home / "profiles.json").write_text(json.dumps(
            {"default": None, "profiles": {"ideas": mine}, "rules": []}))
        self.run_cmd("install")
        self.run_cmd("uninstall", "ideas")
        config = self.json("profiles.json")
        self.assertEqual(config["profiles"]["ideas"], mine)
        self.assertEqual(config["rules"], [])  # the rule install added from it is gone

    def test_the_core_cant_go_while_a_profile_needs_it(self):
        self.run_cmd("install")
        r = self.run_cmd("uninstall", "standard")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Not uninstalling standard: it's the core", r.stdout)
        self.assertIn("Uninstall ideas first, or run `uninstall` with no name", r.stdout)
        self.assertTrue((self.home / "layouts/standard.json").is_file())
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_the_core_alone_uninstalls_everything(self):
        self.run_cmd("install", "standard")
        r = self.run_cmd("uninstall", "standard")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.home / ".herdr-profiles.json").exists())
        self.assertFalse((self.home / "profiles.json").exists())

    def test_uninstalling_what_isnt_installed(self):
        self.run_cmd("install", "standard")
        for name, said in (("ideas", "ideas isn't installed"), ("nope", "no profile named 'nope'")):
            r = self.run_cmd("uninstall", name)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn(f"Nothing to uninstall: {said}. Installed: standard.", r.stdout)

    def test_full_uninstall_takes_back_everything_but_the_persons_own(self):
        self.run_cmd("install")
        config = self.json("profiles.json")
        config["rules"].append({"has": ".mine", "profile": "ideas"})
        (self.home / "profiles.json").write_text(json.dumps(config))
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.written(), [])
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker"}})
        # install made the file and every key in it: what's left is the person's rule (0.9.2)
        self.assertEqual(self.json("profiles.json"), {"rules": [{"has": ".mine", "profile": "ideas"}]})

    def test_a_keys_section_install_made_goes_when_empty(self):
        (self.home / "keys.json").write_text("{}")
        self.run_cmd("install")
        self.assertEqual(self.json("keys.json"), {"global": {**STANDARD_KEY, **IDEAS_KEY}})
        self.run_cmd("uninstall", "ideas")
        self.assertEqual(self.json("keys.json"), {"global": STANDARD_KEY})  # the core's key keeps it
        self.run_cmd("uninstall")
        self.assertEqual(self.json("keys.json"), {})

    def test_a_broken_personal_file_stops_uninstall_before_anything_goes(self):
        self.run_cmd("install")
        (self.home / "profiles.json").write_text("{nope")
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 1)
        self.assertIn("profiles.json", r.stderr)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())


class OldManifestTest(HomeCase):
    """A home installed before 0.8.0: the manifest has only "profiles" and "files"."""

    def make_old(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        old = {"profiles": manifest["profiles"], "files": manifest["files"]}
        (self.home / ".herdr-profiles.json").write_text(json.dumps(old))
        return old

    def test_status_and_install_read_it(self):
        self.make_old()
        self.assertIn("matches the repo", self.run_cmd("status").stdout)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nothing to install", r.stdout)
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["version"], 2)
        self.assertEqual(manifest["installed"], ["standard", "ideas"])
        self.assertEqual(manifest["owners"]["mods/ideas/main.js"], "ideas")
        # What is exactly as that install would have added it is recognised and recorded (0.8.1).
        self.assertIn("recorded  ideas: installed by an older version", r.stdout)
        self.assertEqual(manifest["added"]["ideas"], {
            "entry": {"layout": "ideas", "folder": "~/ideas"}, "rules": [IDEAS_RULE],
            "keys": [{"section": "global", "key": "ctrl-shift-i", "action": "mod.open:ideas", "new_section": False}],
            "default": False})
        self.assertEqual(manifest["added"]["standard"],
                         {"entry": {"layout": "standard"}, "rules": [], "default": True, "keys": [
                             {"section": "global", "key": "ctrl-`", "action": "standard-tabs.terminal",
                              "new_section": False}]})

    def test_a_subset_install_keeps_its_profiles(self):
        self.make_old()
        r = self.run_cmd("install", "standard")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())

    def test_uninstall_a_profile_keeps_what_it_cant_know_and_says_so(self):
        self.make_old()  # and no install since: nothing recorded
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertIn("installed by an older version that didn't record what it added", r.stdout)
        self.assertIn("an `install` first records", r.stdout)
        self.assertIn("profiles.json entry 'ideas'", r.stdout)
        self.assertIn("key ctrl-shift-i -> mod.open:ideas (keys.json, global)", r.stdout)
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        config = self.json("profiles.json")
        self.assertIn("ideas", config["profiles"])
        self.assertIn(IDEAS_RULE, config["rules"])
        # Installed again: known from profiles.json, so not asked and nothing added twice.
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.json("profiles.json")["rules"].count(IDEAS_RULE), 1)

    def test_full_uninstall_with_an_old_manifest(self):
        self.make_old()
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.written(), [])
        self.assertIn("older version", r.stdout)
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertIn("ideas", self.json("profiles.json")["profiles"])


class VersionTest(HomeCase):
    def install_with(self, output, code=0):
        self.herdr_app = self.fake_herdr_app(output, code)
        return self.run_cmd("install")

    def test_versions_accepted(self):
        for output in ("herdr-app 0.1.14", "herdr-app 0.1.15-rc.1", "herdr-app 0.2.0", "Herdr v1.0.0 (abc1234)"):
            with self.subTest(output=output):
                r = self.install_with(output)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("checked   Herdr app", r.stdout)

    def test_versions_refused_before_anything_is_written(self):
        cases = [("herdr-app 0.1.13", 0, "Herdr app 0.1.13 is too old"),
                 ("herdr-app 0.1.14-beta.1", 0, "a pre-release comes before it"),
                 ("herdr-app 0.0.99", 0, "too old"),
                 ("herdr-app", 0, "with no version number in it"),
                 ("herdr-app 1.2", 0, "with no version number in it"),
                 ("", 0, "with no version number in it"),
                 ("unknown option --version", 2, "failed (exit code 2): unknown option --version")]
        for output, code, said in cases:
            with self.subTest(output=output):
                r = self.install_with(output, code)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(said, r.stderr)
                self.assertIn("--skip-version-check", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(self.written(), [])
                self.assertFalse((self.home / ".herdr-profiles.json").exists())

    def test_herdr_app_missing(self):
        empty = Path(self.tmp.name + "-empty-path")
        empty.mkdir()
        self.addCleanup(shutil.rmtree, empty)
        env = {k: v for k, v in self.env().items() if k != "HERDR_APP_BIN"}
        env["PATH"] = str(empty)
        r = subprocess.run([sys.executable, str(test_installer.SCRIPT), "install"], env=env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("herdr-app isn't on PATH", r.stderr)
        self.assertEqual(self.written(), [])
        r = self.run_cmd("install", HERDR_APP_BIN=str(empty / "herdr-app"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("herdr-app: not found (no such file)", r.stderr)
        r = self.run_cmd("install", "--skip-version-check", HERDR_APP_BIN=str(empty / "herdr-app"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("checked", r.stdout)

    def test_a_herdr_app_that_hangs_is_given_up_on(self):
        sys.path.insert(0, str(REPO / "scripts"))
        from unittest import mock
        from profiletool import herdr
        slow = Path(self.fake_herdr_app("x", name="slow"))
        slow.write_text("#!/bin/sh\nsleep 5\n")
        with mock.patch.object(herdr, "TIMEOUT", 0.3):
            text, problem = herdr.read_version(str(slow))
        self.assertIsNone(text)
        self.assertIn("didn't answer in 0.3 seconds", problem)

    def test_uninstall_and_status_dont_need_herdr(self):
        self.run_cmd("install")
        for command in ("status", "uninstall"):
            r = self.run_cmd(command, HERDR_APP_BIN="/nonexistent/herdr-app")
            self.assertEqual(r.returncode, 0, command + r.stderr)


class ClashTest(HomeCase):
    def own_mod(self):
        (self.home / "mods/ideas").mkdir(parents=True)
        (self.home / "mods/ideas/mod.json").write_text('{"name": "mine"}\n')
        (self.home / "mods/ideas/main.js").write_text("// mine\n")

    def test_their_own_mod_stops_install_and_says_what_to_do(self):
        self.own_mod()
        for args in ((), ("ideas",), ("--force",)):
            with self.subTest(args=args):
                r = self.run_cmd("install", *args)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("clash     mods/ideas/  (profile ideas)", r.stdout)
                self.assertIn("Move or rename yours first", r.stdout)
                self.assertIn("Or leave out ideas: `install standard`", r.stdout)
                self.assertEqual(self.written(), ["mods/ideas", "mods/ideas/main.js", "mods/ideas/mod.json"])
                self.assertFalse((self.home / ".herdr-profiles.json").exists())
                self.assertFalse((self.home / "profiles.json").exists())
        r = self.run_cmd("install", "standard")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / "mods/ideas/main.js").read_text(), "// mine\n")

    def test_a_clash_in_the_core_has_to_move(self):
        (self.home / "layouts").mkdir()
        (self.home / "layouts/standard.json").write_text('{"id": "mine"}\n')
        r = self.run_cmd("install", "standard")
        self.assertEqual(r.returncode, 1)
        self.assertIn("clash     layouts/standard.json  (profile standard)", r.stdout)
        self.assertIn("standard is the core, installed with every profile: yours has to move.", r.stdout)
        self.assertNotIn("leave out", r.stdout)

    def test_a_clash_when_adding_a_profile_later(self):
        self.run_cmd("install", "standard")
        self.own_mod()
        status = self.run_cmd("status").stdout
        self.assertIn("available ideas", status)  # not installed: nothing to compare yet
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 1)
        self.assertIn("clash     mods/ideas/", r.stdout)
        self.assertIn("Or leave out ideas: `install standard`", r.stdout)

    def test_files_exactly_ours_are_not_a_clash(self):
        """The manifest was lost (a crash, or deleted): what's there is what install would write."""
        self.run_cmd("install")
        (self.home / ".herdr-profiles.json").unlink()
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_herdrs_own_files_in_a_mod_folder_are_not_a_clash(self):
        (self.home / "mods/ideas").mkdir(parents=True)
        (self.home / "mods/ideas/jsconfig.json").write_text("{}")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_file_kept_by_uninstall_is_theirs_then(self):
        self.run_cmd("install")
        (self.home / "themes/ideas.json").write_text('{"mine": true}\n')
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("kept      themes/ideas.json", r.stdout)
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 1)
        self.assertIn("clash     themes/ideas.json", r.stdout)
        self.assertEqual((self.home / "themes/ideas.json").read_text(), '{"mine": true}\n')


class InterruptTest(HomeCase):
    def test_ctrl_c_while_writing_finishes_the_writes_first(self):
        sys.path.insert(0, str(REPO / "scripts"))
        from unittest import mock
        from profiletool import commands, files
        calls = []

        def write_then_ctrl_c(path, data):
            files.atomic_write(path, data)
            if not calls:
                os.kill(os.getpid(), signal.SIGINT)
            calls.append(path)

        self.run_cmd("install", "standard")
        (self.home / "layouts/standard.json").unlink()  # so install writes with atomic_write
        with mock.patch.object(commands, "atomic_write", write_then_ctrl_c):
            code, out, err = test_installer.InstallerTest.in_process(self, False, False, input,
                                                                     ("install", "ideas"))
        self.assertEqual(code, 130, out + err)
        self.assertIn("finishing what's being written first", err)
        self.assertIn("Stopped.", err)
        self.assertGreater(len(calls), 0)
        self.assertIn("matches the repo", self.run_cmd("status").stdout)
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard", "ideas"])
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")


class VerifierFindingsTest(HomeCase):
    """What an independent check broke in 0.8.0 before release, kept fixed."""

    def test_pull_never_takes_a_file_of_the_persons_own(self):
        repo, run = test_installer.InstallerTest.repo_copy(self)
        run("install", "standard")
        (self.home / "themes").mkdir()
        (self.home / "themes/ideas.json").write_text('{"name": "my own theme"}\n')
        before = (repo / "profiles/ideas/themes/ideas.json").read_bytes()
        r = run("pull")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("pulled    themes/ideas.json", r.stdout)
        self.assertEqual((repo / "profiles/ideas/themes/ideas.json").read_bytes(), before)
        self.assertNotIn("themes/ideas.json", self.json(".herdr-profiles.json")["files"])
        run("uninstall")
        self.assertEqual((self.home / "themes/ideas.json").read_text(), '{"name": "my own theme"}\n')

    def test_pull_skips_a_clash_inside_an_installed_profile(self):
        repo, run = test_installer.InstallerTest.repo_copy(self)
        run("install")
        (self.home / "themes/ideas.json").unlink()
        (self.home / "themes/ideas.json").symlink_to(self.home / "elsewhere.json")
        (self.home / "elsewhere.json").write_text("{}")
        r = run("pull")
        self.assertIn("skipped   themes/ideas.json", r.stdout)

    def link_ideas_mod(self):
        """mods/ideas replaced by a link to a copy (as a developer might link it to the repo)."""
        behind = Path(self.tmp.name + "-behind")
        self.addCleanup(shutil.rmtree, behind, True)
        shutil.copytree(REPO / "profiles/ideas/mods/ideas", behind)
        shutil.rmtree(self.home / "mods/ideas", ignore_errors=True)
        (self.home / "mods").mkdir(exist_ok=True)
        (self.home / "mods/ideas").symlink_to(behind)
        return behind

    def test_a_symlinked_mod_is_a_clash_even_with_our_files_behind_it(self):
        behind = self.link_ideas_mod()
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("clash     mods/ideas/  (profile ideas — a symlink)", r.stdout)
        self.assertTrue((behind / "main.js").is_file())

    def test_nothing_is_deleted_through_a_symlink(self):
        self.run_cmd("install")
        behind = self.link_ideas_mod()  # after install: the manifest still lists mods/ideas/*
        for args in (("uninstall", "ideas"), ("uninstall",)):
            r = self.run_cmd(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertTrue((behind / "main.js").is_file(), args)
            if args == ("uninstall", "ideas"):
                self.assertIn("kept      mods/ideas/main.js (behind a symlink", r.stdout)
                self.assertNotIn("mods/ideas/main.js", self.json(".herdr-profiles.json")["files"])
        self.assertFalse((self.home / "layouts/standard.json").exists())

    def test_install_stops_on_a_mod_turned_into_a_link(self):
        self.run_cmd("install")
        behind = self.link_ideas_mod()
        (behind / "ui.js").write_text("// changed behind the link\n")
        r = self.run_cmd("install", "--force")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a symlink", r.stdout)
        self.assertEqual((behind / "ui.js").read_text(), "// changed behind the link\n")

    def test_a_dangling_link_is_a_clash_and_nothing_is_written(self):
        (self.home / "mods").mkdir()
        (self.home / "mods/standard-tabs").symlink_to("/nonexistent-target")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("clash     mods/standard-tabs/", r.stdout)
        self.assertEqual(self.written(), ["mods/standard-tabs"])

    def test_personal_files_are_written_through_links_and_keep_their_mode(self):
        dotfiles = Path(self.tmp.name + "-dotfiles")
        dotfiles.mkdir()
        self.addCleanup(shutil.rmtree, dotfiles)
        (dotfiles / "keys.json").write_text((self.home / "keys.json").read_text())
        (self.home / "keys.json").unlink()
        (self.home / "keys.json").symlink_to(dotfiles / "keys.json")
        (dotfiles / "keys.json").chmod(0o640)
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / "keys.json").is_symlink())
        self.assertEqual(json.loads((dotfiles / "keys.json").read_text())["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertEqual((dotfiles / "keys.json").stat().st_mode & 0o777, 0o640)
        for rel in ("layouts/ideas.json", "themes/ideas.json", "profiles.json", ".herdr-profiles.json"):
            self.assertEqual((self.home / rel).stat().st_mode & 0o777, 0o644, rel)

    def test_broken_herdr_files_are_errors_that_name_the_file(self):
        for name, text in (("installed.json", "{bad"), ("installed.json", "[1]"),
                           (".herdr-profiles.json", "{bad"), (".herdr-profiles.json", '{"installed": "ideas"}')):
            with self.subTest(name=name, text=text):
                (self.home / name).write_text(text)
                for command in ("install", "status", "uninstall"):
                    r = self.run_cmd(command)
                    if name == "installed.json" and command != "install":
                        continue  # only install reads what Herdr ships
                    self.assertEqual(r.returncode, 1, command + r.stdout)
                    self.assertIn(name, r.stderr, command)
                    self.assertNotIn("Traceback", r.stderr, command)
                self.assertEqual(self.written(), [])
                (self.home / name).unlink()
                (self.home / "installed.json").write_text("{}")

    def test_a_version_printed_on_stderr_is_read(self):
        bin_dir = Path(self.fake_herdr_app("x")).parent
        fake = bin_dir / "stderr-herdr"
        fake.write_text("#!/bin/sh\necho 'herdr-app 0.1.14' >&2\n")
        fake.chmod(0o755)
        r = self.run_cmd("install", HERDR_APP_BIN=str(fake))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("checked   Herdr app 0.1.14", r.stdout)

    def test_what_install_didnt_add_is_still_said_on_uninstall(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        (self.home / ".herdr-profiles.json").write_text(json.dumps(
            {"profiles": manifest["profiles"], "files": manifest["files"]}))
        self.run_cmd("uninstall", "ideas")
        self.run_cmd("install", "ideas")  # entry and key there already: not added, not recorded
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("kept      profiles.json entry 'ideas': install didn't add it", r.stdout)
        self.assertIn("kept      key ctrl-shift-i -> mod.open:ideas: install didn't add it", r.stdout)
        self.assertNotIn("of your own were left", r.stdout)

    def test_a_duplicated_rule_is_named_as_a_copy(self):
        self.run_cmd("install")
        config = self.json("profiles.json")
        config["rules"].append(dict(IDEAS_RULE))
        (self.home / "profiles.json").write_text(json.dumps(config))
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("a second copy of one install added", r.stdout)
        self.assertEqual(self.json("profiles.json")["rules"], [IDEAS_RULE])

    def test_uninstall_with_nothing_installed_says_so(self):
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to uninstall", r.stdout)


class RecogniseOldTest(HomeCase):
    """0.8.1: a profile installed before 0.8.0 has nothing in "added". The next install records what
    is still exactly as that install would have added it; the rest stays the person's."""

    def make_old(self, edit_config=None, edit_keys=None):
        """A home installed before 0.8.0, its manifest upgraded since (the owner's case: "added": {})."""
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        manifest["added"] = {}
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        if edit_config:
            config = self.json("profiles.json")
            edit_config(config)
            (self.home / "profiles.json").write_text(json.dumps(config))
        if edit_keys:
            keys = self.json("keys.json")
            edit_keys(keys)
            (self.home / "keys.json").write_text(json.dumps(keys))
        before = {n: (self.home / n).read_bytes() for n in ("profiles.json", "keys.json")}
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n, data in before.items():
            self.assertEqual((self.home / n).read_bytes(), data, f"{n} changed")  # read, never written
        return r, self.json(".herdr-profiles.json")["added"]

    def test_exactly_as_added_is_recorded_and_uninstall_takes_it_back(self):
        r, added = self.make_old()
        self.assertIn("              key ctrl-shift-i -> mod.open:ideas", r.stdout)
        self.assertEqual(added["ideas"]["entry"], {"layout": "ideas", "folder": "~/ideas"})
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker", **STANDARD_KEY}})
        self.assertEqual(self.json("profiles.json"), {"default": "standard",
                                                      "profiles": {"standard": {"layout": "standard"}}, "rules": []})
        self.assertIn("matches the repo", self.run_cmd("status").stdout)

    def test_the_owners_answer_counts_as_an_answer(self):
        def other_folder(config):
            config["profiles"]["ideas"]["folder"] = "~/work/ideas"
            config["rules"] = [{"path": "~/work/ideas", "profile": "ideas"}]
        _, added = self.make_old(other_folder)
        self.assertEqual(added["ideas"]["entry"], {"layout": "ideas", "folder": "~/work/ideas"})
        self.assertEqual(added["ideas"]["rules"], [{"path": "~/work/ideas", "profile": "ideas"}])

    def test_an_entry_the_person_edited_is_not_recorded(self):
        def edited(config):
            config["profiles"]["ideas"]["types"] = ["book", "code"]
        _, added = self.make_old(edited)
        self.assertIsNone(added["ideas"]["entry"])
        self.assertEqual(added["ideas"]["rules"], [IDEAS_RULE])  # the rule is still exactly install's
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("kept      profiles.json entry 'ideas': install didn't add it", r.stdout)
        self.assertEqual(self.json("profiles.json")["profiles"]["ideas"]["types"], ["book", "code"])
        self.assertEqual(self.json("profiles.json")["rules"], [])

    def test_a_rule_that_doesnt_follow_the_entry_is_not_recorded(self):
        def moved(config):
            config["profiles"]["ideas"]["folder"] = "~/notes"  # the rule still says ~/ideas
        _, added = self.make_old(moved)
        self.assertEqual(added["ideas"]["entry"], {"layout": "ideas", "folder": "~/notes"})
        self.assertEqual(added["ideas"]["rules"], [])
        self.run_cmd("uninstall", "ideas")
        self.assertEqual(self.json("profiles.json")["rules"], [IDEAS_RULE])

    def test_an_unusable_folder_records_neither_entry_nor_rules(self):
        def bad(config):
            config["profiles"]["ideas"]["folder"] = "~"
            config["rules"].append({"path": "~", "profile": "ideas"})
        _, added = self.make_old(bad)
        self.assertIsNone(added["ideas"]["entry"])
        self.assertEqual(added["ideas"]["rules"], [])

    def test_their_own_rules_and_a_copy_stay(self):
        def own(config):
            config["rules"] += [{"has": ".board.json", "profile": "ideas"}, dict(IDEAS_RULE)]
        _, added = self.make_old(own)
        self.assertEqual(added["ideas"]["rules"], [IDEAS_RULE])  # once
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("a second copy of one install added", r.stdout)
        self.assertEqual(self.json("profiles.json")["rules"], [{"has": ".board.json", "profile": "ideas"}, IDEAS_RULE])

    def test_a_rebound_key_is_not_recorded(self):
        def rebound(keys):
            keys["global"]["ctrl-shift-i"] = "app.help"
        _, added = self.make_old(edit_keys=rebound)
        self.assertEqual(added["ideas"]["keys"], [])
        self.run_cmd("uninstall", "ideas")
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "app.help")

    def test_a_key_section_is_never_deleted(self):
        def alone(keys):
            del keys["global"]["cmd-p"]  # ctrl-shift-i alone in its section
            del keys["global"]["ctrl-`"]
        self.make_old(edit_keys=alone)
        self.run_cmd("uninstall", "ideas")
        self.assertEqual(self.json("keys.json"), {"global": {}})

    def test_recorded_once(self):
        self.make_old()
        config = self.json("profiles.json")
        config["profiles"]["ideas"]["types"] = ["x"]  # changed after it was recorded
        (self.home / "profiles.json").write_text(json.dumps(config))
        r = self.run_cmd("install")
        self.assertNotIn("recorded", r.stdout)
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("kept      profiles.json entry 'ideas': changed since install", r.stdout)

    def test_a_profile_installed_now_is_not_recognised(self):
        r = self.run_cmd("install")
        self.assertNotIn("recorded", r.stdout)
        r = self.run_cmd("install")
        self.assertNotIn("recorded", r.stdout)


class UninstalledOnPurposeTest(HomeCase):
    """0.8.1: `install` with no names doesn't bring back a profile uninstalled on purpose."""

    def test_plain_install_leaves_it_out_and_naming_it_brings_it_back(self):
        self.run_cmd("install")
        r = self.run_cmd("uninstall", "ideas")
        self.assertIn("`install ideas` brings it back", r.stdout)
        self.assertEqual(self.json(".herdr-profiles.json")["uninstalled"], ["ideas"])
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("left out  ideas (uninstalled on purpose; `install ideas` brings it back)", r.stdout)
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertNotIn("ideas", self.json("profiles.json")["profiles"])
        self.assertNotIn("ctrl-shift-i", self.json("keys.json")["global"])
        status = self.run_cmd("status").stdout
        self.assertIn("left out  ideas  (uninstalled on purpose: plain `install` leaves it out;"
                      " `install ideas` brings it back)", status)
        self.assertIn("matches the repo", status)
        self.run_cmd("install", "standard")
        self.assertFalse((self.home / "mods/ideas").exists())
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())
        self.assertIn(IDEAS_RULE, self.json("profiles.json")["rules"])
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["uninstalled"], [])
        self.assertEqual(manifest["installed"], ["standard", "ideas"])

    def test_a_full_uninstall_forgets_it(self):
        self.run_cmd("install")
        self.run_cmd("uninstall", "ideas")
        self.run_cmd("uninstall")
        self.run_cmd("install")
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())

    def test_a_manifest_without_the_field_installs_new_profiles(self):
        self.run_cmd("install", "standard")
        manifest = self.json(".herdr-profiles.json")
        del manifest["uninstalled"]  # as 0.8.0 wrote it
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        self.assertIn("available ideas", self.run_cmd("status").stdout)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / "mods/ideas/main.js").is_file())

    def test_a_profile_built_on_it_is_left_out_too(self):
        repo = self.home.parent / f"{self.home.name}-repo"
        for part in ("scripts", "core", "profiles"):
            shutil.copytree(REPO / part, repo / part, ignore=shutil.ignore_patterns("__pycache__"))
        self.addCleanup(shutil.rmtree, repo)
        run = lambda *a: subprocess.run([sys.executable, str(repo / "scripts/herdr_profiles.py"), *a],  # noqa: E731
                                        env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        run("install")
        run("uninstall", "ideas")
        (repo / "profiles/more").mkdir()
        (repo / "profiles/more/profile.json").write_text(json.dumps(
            {"schema": 2, "name": "more", "layout": {"name": "more", "base": "ideas"}}))
        r = run("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("left out  more (it needs ideas, uninstalled on purpose;", r.stdout)
        self.assertFalse((self.home / "layouts/more.json").exists())
        self.assertFalse((self.home / "mods/ideas").exists())
        self.assertIn("left out  more  (it needs ideas, uninstalled on purpose:", run("status").stdout)
        r = run("install", "more")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("also      ideas (needed by what you named)", r.stdout)
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["installed"], ["standard", "ideas", "more"])
        self.assertEqual(manifest["uninstalled"], [])


class SecondVerifierTest(HomeCase):
    """Found by the 0.8.1/0.9.0 independent check."""

    def test_a_broken_uninstalled_list_is_an_error_not_a_traceback(self):
        self.run_cmd("install")
        for bad in (None, 5, "ideas"):
            with self.subTest(bad=bad):
                manifest = self.json(".herdr-profiles.json")
                manifest["uninstalled"] = bad
                (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
                r = self.run_cmd("install")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("not a manifest this tool wrote", r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_an_edited_mod_file_keeps_its_mod_json(self):
        self.run_cmd("install")
        with open(self.home / "mods/ideas/main.js", "a") as f:
            f.write("// mine\n")
        r = self.run_cmd("uninstall", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("kept      mods/ideas/mod.json (another file of this mod is kept", r.stdout)
        self.assertEqual(sorted(p.name for p in (self.home / "mods/ideas").iterdir()), ["main.js", "mod.json"])
        self.assertNotIn("mods/ideas/mod.json", self.json(".herdr-profiles.json")["files"])

    def test_without_keys_json_the_hint_is_json(self):
        (self.home / "keys.json").unlink()
        r = self.run_cmd("install")
        self.assertIn('add {"ctrl-shift-i": "mod.open:ideas"} under "global" yourself', r.stdout)


class LayoutKeysTest(HomeCase):
    """Keys a profile binds in its own layout (`layout:<name>`): a key the person binds globally
    counts as used there, since the layout's would hide it."""

    def repo_with(self, keys):
        repo = self.home.parent / f"{self.home.name}-repo"
        for part in ("scripts", "core", "profiles"):
            shutil.copytree(REPO / part, repo / part, ignore=shutil.ignore_patterns("__pycache__"))
        self.addCleanup(shutil.rmtree, repo)
        (repo / "profiles/more").mkdir()
        (repo / "profiles/more/profile.json").write_text(json.dumps(
            {"schema": 2, "name": "more", "layout": {"name": "more", "base": "standard"}, "keys": keys}))
        return lambda *a: subprocess.run([sys.executable, str(repo / "scripts/herdr_profiles.py"), *a],  # noqa: E731
                                         env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_a_layout_key_goes_in_its_section_and_leaves_with_it(self):
        before = {"global": {**self.json("keys.json")["global"], **STANDARD_KEY}}  # the core's key comes too
        run = self.repo_with({"layout:more": {"ctrl-shift-m": "app.help", "cmd-p": "app.palette"}})
        r = run("install", "more")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("key       ctrl-shift-m -> app.help", r.stdout)
        self.assertIn("skipped   cmd-p: bound in global to 'mod.open:picker'; in layout:more it would hide that",
                      r.stdout)
        self.assertEqual(self.json("keys.json"), {**before, "layout:more": {"ctrl-shift-m": "app.help"}})
        r = run("uninstall", "more")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json("keys.json"), before)

    def test_no_empty_section_when_every_key_is_taken(self):
        before = {"global": {**self.json("keys.json")["global"], **STANDARD_KEY}}  # the core's key comes too
        # A global key is added in the same install, so keys.json is written: no empty layout:more in it.
        run = self.repo_with({"global": {"ctrl-shift-n": "app.help"}, "layout:more": {"cmd-p": "app.palette"}})
        r = run("install", "more")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json("keys.json"), {"global": {**before["global"], "ctrl-shift-n": "app.help"}})

    def test_the_same_action_globally_is_no_clash(self):
        run = self.repo_with({"layout:more": {"cmd-p": "mod.open:picker"}})
        r = run("install", "more")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json("keys.json")["layout:more"], {"cmd-p": "mod.open:picker"})


if __name__ == "__main__":
    unittest.main()
