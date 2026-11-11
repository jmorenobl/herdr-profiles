"""0.9.2: several checkouts sharing one Herdr home, a process killed while writing (the journal),
the person's formatting kept in keys.json and profiles.json, a full uninstall leaving the home as
it was, the order install writes in, and `check` with HERDR_APP_BIN pointing nowhere.

Run: python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_installer
from test_installer import REPO, SCRIPT, STANDARD_KEY, HomeCase

sys.path.insert(0, str(REPO / "scripts"))
from profiletool import jsonedit  # noqa: E402

IDEAS_KEY = ("ctrl-shift-i", "mod.open:ideas")

# Runs the tool, killed (SIGKILL: no cleanup of any kind) right after it writes the file whose
# path ends with argv[1]; the rest of argv is the command line.
KILLER = """
import os, signal, sys
sys.path.insert(0, sys.argv[1])
from profiletool import cli, files
target = sys.argv[2]
def kill(event, path, dest):
    if event == "write" and str(path).endswith(target):
        os.kill(os.getpid(), signal.SIGKILL)
files.WATCHERS.append(kill)
sys.exit(cli.main(sys.argv[3:]))
"""


def snapshot(home: Path) -> dict:
    """Every file in the home, with its bytes."""
    return {str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


class CheckoutTest(HomeCase):
    """Phase 4: two checkouts of the repo (a worktree, a copy) installing into one home."""

    def other(self, git_branch=None):
        repo, run = test_installer.InstallerTest.repo_copy(self)
        if git_branch:
            subprocess.run(["git", "init", "-q", "-b", git_branch, str(repo)], check=True, capture_output=True)
        return repo, run

    def test_another_checkout_stops_install_before_anything_is_written(self):
        repo, run = self.other()
        self.assertEqual(run("install").returncode, 0)
        before = snapshot(self.home)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("another checkout of this repo installed into this Herdr home last", r.stdout)
        self.assertIn(f"installed from  {repo.resolve()}", r.stdout)
        self.assertIn(f"this checkout   {REPO.resolve()}", r.stdout)
        self.assertIn("--take-over", r.stdout)
        self.assertEqual(snapshot(self.home), before)
        status = self.run_cmd("status").stdout
        self.assertIn(f"checkout  installed from {repo.resolve()}, not this checkout", status)
        pull = self.run_cmd("pull")
        self.assertEqual(pull.returncode, 1)
        self.assertIn("Not pulling: another checkout", pull.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_the_same_checkout_installs_as_before(self):
        self.assertEqual(self.run_cmd("install").returncode, 0)
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["checkout"]["path"], str(REPO.resolve()))
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Nothing to install", r.stdout)
        self.assertNotIn("checkout", self.run_cmd("status").stdout)

    def test_take_over_and_back(self):
        repo, run = self.other(git_branch="work")
        run("install")
        self.assertEqual(self.json(".herdr-profiles.json")["checkout"],
                         {"path": str(repo.resolve()), "branch": "work"})
        r = self.run_cmd("install", "--take-over")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"taking over from {repo.resolve()} (branch work)", r.stdout)
        self.assertEqual(self.json(".herdr-profiles.json")["checkout"]["path"], str(REPO.resolve()))
        self.assertIn("matches the repo", self.run_cmd("status").stdout)
        r = run("install")  # now the copy is the other one
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"installed from  {REPO.resolve()}", r.stdout)
        self.assertEqual(run("install", "--take-over").returncode, 0)

    def test_alternating_checkouts_never_lose_a_profile(self):
        repo, run = self.other()
        run("install", "standard")
        for _ in range(2):
            self.assertEqual(self.run_cmd("install").returncode, 1)
            self.assertEqual(run("install").returncode, 0)
        self.assertEqual(self.json(".herdr-profiles.json")["installed"], ["standard", "ideas"])
        self.assertTrue((self.home / "mods/ideas/mod.json").is_file())

    def test_a_checkout_that_is_gone_is_said(self):
        repo, run = self.other()
        run("install")
        shutil.rmtree(repo)
        self.addCleanup(repo.mkdir)  # for repo_copy's own cleanup, which runs after this one
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{repo.resolve()} (no longer there)", r.stdout)
        self.assertEqual(self.run_cmd("install", "--take-over").returncode, 0)

    def test_a_manifest_without_a_checkout_is_this_ones(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        del manifest["checkout"]
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        self.assertNotIn("checkout", self.run_cmd("status").stdout)
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.json(".herdr-profiles.json")["checkout"]["path"], str(REPO.resolve()))

    def test_uninstall_from_another_checkout_says_so_and_works(self):
        repo, run = self.other()
        run("install")
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("another checkout installed into this Herdr home last", r.stdout)
        self.assertEqual(self.written(), [])

    def test_a_profile_lost_in_a_take_over_is_still_taken_back(self):
        self.run_cmd("install")
        repo, run = self.other()
        shutil.rmtree(repo / "profiles" / "ideas")
        r = run("install", "--take-over")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Nothing to install", r.stdout)  # it removed ideas' files
        self.assertIn("Installed.", r.stdout)
        r = run("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("removed   key ctrl-shift-i -> mod.open:ideas", r.stdout)
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker"}})
        self.assertFalse((self.home / "profiles.json").exists())

    def test_a_broken_checkout_record_is_an_error(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        manifest["checkout"] = "here"
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a manifest this tool wrote", r.stderr)


class KilledTest(HomeCase):
    """A process killed (not Ctrl-C) in the write phase: the next run recovers from the journal."""

    def killed(self, after, *args):
        r = subprocess.run([sys.executable, "-c", KILLER, str(REPO / "scripts"), after, *args], env=self.env(),
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, -9, r.stdout + r.stderr)
        self.assertTrue((self.home / ".herdr-profiles.pending.json").is_file())
        return r

    def assert_uninstall_takes_everything_back(self):
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("older version", r.stdout)
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker"}})
        self.assertFalse((self.home / "profiles.json").exists())
        self.assertEqual(self.written(), [])

    def test_killed_after_the_personal_files_before_the_manifest(self):
        self.killed("/keys.json", "install")
        self.assertFalse((self.home / ".herdr-profiles.json").exists())  # never saved
        r = self.run_cmd("status")
        self.assertIn("recovered the last `install` was stopped (killed) before it saved", r.stdout)
        self.assertIn("matches the repo", r.stdout)
        self.assertFalse((self.home / ".herdr-profiles.pending.json").exists())
        added = self.json(".herdr-profiles.json")["added"]["ideas"]
        self.assertEqual([(k["key"], k["action"]) for k in added["keys"]], [IDEAS_KEY])
        self.assert_uninstall_takes_everything_back()

    def test_killed_between_the_two_personal_files_is_rolled_forward(self):
        self.killed("/profiles.json", "install")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("finished  keys.json: written now, as `install` meant to", r.stdout)
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assert_uninstall_takes_everything_back()

    def test_killed_between_the_two_in_an_uninstall_is_rolled_forward(self):
        (self.home / "profiles.json").write_text('{"zz": 1}\n')  # theirs: a full uninstall writes it, not deletes
        for args in (("uninstall", "ideas"), ("uninstall",)):
            with self.subTest(args):
                self.run_cmd("install")
                self.killed("/profiles.json", *args)
                r = self.run_cmd("status")
                self.assertIn("finished  keys.json", r.stdout)
                core = STANDARD_KEY if args[1:] else {}  # uninstalling ideas leaves the core's key
                self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker", **core}})
                self.run_cmd("uninstall")
                self.assertEqual((self.home / "profiles.json").read_text(), '{"zz": 1}\n')

    def test_both_files_edited_after_the_kill(self):
        self.killed("/keys.json", "install")  # both written; the journal marks profiles.json
        for name, extra in (("keys.json", ("global", "ctrl-w", "close")), ("profiles.json", ("zz", None, 1))):
            data = self.json(name)
            if extra[1]:
                data[extra[0]][extra[1]] = extra[2]
            else:
                data[extra[0]] = extra[2]
            (self.home / name).write_text(json.dumps(data))
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("recovered the last `install`", r.stdout)
        self.assertIn("keys.json: changed since it stopped", r.stdout)
        r = self.run_cmd("uninstall")
        self.assertEqual(self.json("keys.json"), {"global": {"cmd-p": "mod.open:picker", "ctrl-w": "close"}})
        self.assertEqual(self.json("profiles.json"), {"zz": 1})
        self.assertEqual(self.written(), [])

    def test_killed_early_in_a_first_install_keeps_the_folders_it_made(self):
        self.killed("layouts/standard.json", "install")
        self.run_cmd("install")
        self.assertEqual(sorted(self.json(".herdr-profiles.json")["folders"]), ["layouts", "mods", "themes"])
        self.run_cmd("uninstall")
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["installed.json", "keys.json"])

    def test_a_half_staged_mod_is_cleaned_up(self):
        self.run_cmd("install", "standard")
        self.killed(".ideas.staging/main.js", "install", "ideas")
        self.assertTrue((self.home / "mods/.ideas.staging").is_dir())
        r = self.run_cmd("status")
        self.assertIn("removed   mods/.ideas.staging/", r.stdout)
        self.assertFalse((self.home / "mods/.ideas.staging").exists())
        self.assert_uninstall_takes_everything_back()

    def test_killed_before_the_personal_files(self):
        self.killed("layouts/standard.json", "install")
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("before it wrote profiles.json or keys.json; run `install` again", r.stdout)
        self.assertEqual(self.json("keys.json")["global"]["ctrl-shift-i"], "mod.open:ideas")
        self.assertIn("matches the repo", self.run_cmd("status").stdout)
        self.assert_uninstall_takes_everything_back()

    def test_killed_in_a_profile_uninstall(self):
        self.run_cmd("install")
        self.killed("/keys.json", "uninstall", "ideas")
        r = self.run_cmd("status")
        self.assertIn("recovered the last `uninstall`", r.stdout)
        self.assertIn("left out  ideas", r.stdout)
        manifest = self.json(".herdr-profiles.json")
        self.assertEqual(manifest["installed"], ["standard"])
        self.assertNotIn("ideas", manifest["added"])
        self.assertFalse(any(rel.startswith("mods/ideas/") for rel in manifest["files"]))
        r = self.run_cmd("install", "ideas")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("key       ctrl-shift-i -> mod.open:ideas", r.stdout)  # a first time again

    def test_killed_in_a_full_uninstall(self):
        self.run_cmd("install")
        self.killed("/keys.json", "uninstall")
        r = self.run_cmd("status")
        self.assertIn("recovered the last `uninstall`", r.stdout)
        self.assertFalse((self.home / ".herdr-profiles.json").exists())
        self.assertIn("Nothing installed", r.stdout)

    def test_a_broken_journal_is_an_error_that_names_it(self):
        self.run_cmd("install")
        (self.home / ".herdr-profiles.pending.json").write_text('{"version": 1}')
        r = self.run_cmd("install")
        self.assertEqual(r.returncode, 1)
        self.assertIn(".herdr-profiles.pending.json: not a journal this tool wrote; move it away", r.stderr)
        (self.home / ".herdr-profiles.pending.json").write_text('{"version": 1, "command": "install",'
                                                               ' "after": null, "expect": {"../x": null}}')
        self.assertIn("not a journal", self.run_cmd("install").stderr)

    def test_no_journal_is_left_by_a_normal_run(self):
        self.run_cmd("install")
        self.run_cmd("uninstall", "ideas")
        self.run_cmd("install", "ideas")
        self.run_cmd("uninstall")
        self.assertFalse((self.home / ".herdr-profiles.pending.json").exists())


class FormattingTest(HomeCase):
    """keys.json and profiles.json keep the person's formatting; uninstall gives them back as they were."""

    KEYS = {
        "four spaces": '{\n    "global": {\n        "cmd-p": "mod.open:picker"\n    }\n}\n',
        "tabs": '{\n\t"global": {\n\t\t"cmd-p": "mod.open:picker"\n\t}\n}\n',
        "one line": '{"global": {"cmd-p": "mod.open:picker"}}',
        "compact": '{"global":{"cmd-p":"mod.open:picker"}}\n',
        "crlf": '{\r\n  "global": {\r\n    "cmd-p": "mod.open:picker"\r\n  }\r\n}\r\n',
        "other sections": '{\n  "layout:main": {"cmd-1": "a"},\n  "global": {\n    "cmd-p": "mod.open:picker"\n  }\n}',
        "no global": '{\n  "layout:main": {\n    "cmd-1": "a"\n  }\n}\n',
        "empty": "{}\n",
        "unicode": '{\n  "global": {\n    "cmd-p": "mod.open:picker",\n    "cmd-e": "\\u00e9t\\u00e9"\n  }\n}\n',
    }

    def test_keys_json_keeps_its_formatting_and_comes_back_byte_for_byte(self):
        for name, text in self.KEYS.items():
            with self.subTest(name):
                (self.home / "keys.json").write_bytes(text.encode())
                r = self.run_cmd("install")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                after = (self.home / "keys.json").read_bytes().decode()
                keys = json.loads(after)
                self.assertEqual(keys["global"]["ctrl-shift-i"], "mod.open:ideas")
                self.assertEqual({s: b for s, b in keys.items() if s != "global"},
                                 {s: b for s, b in json.loads(text).items() if s != "global"})
                if name in ("four spaces", "tabs", "crlf"):
                    unit = {"four spaces": "        ", "tabs": "\t\t", "crlf": "    "}[name]
                    self.assertIn(f'{unit}"ctrl-shift-i": "mod.open:ideas"', after)
                    self.assertEqual(after.count("\n"), text.count("\n") + 2)  # two lines more: the core's key and ideas'
                if name == "compact":
                    self.assertIn('"cmd-p":"mod.open:picker","ctrl-`":"standard-tabs.terminal","ctrl-shift-i":"mod.open:ideas"', after)
                if name == "one line":
                    self.assertEqual(after, '{"global": {"cmd-p": "mod.open:picker", "ctrl-`": "standard-tabs.terminal",'
                                            ' "ctrl-shift-i": "mod.open:ideas"}}')
                if name == "unicode":
                    self.assertIn('"\\u00e9t\\u00e9"', after)  # their escapes stay as written
                r = self.run_cmd("uninstall")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual((self.home / "keys.json").read_bytes().decode(), text, name)

    def test_a_profiles_json_they_had_comes_back_byte_for_byte(self):
        text = '{\n    "rules": [\n        {"path": "~/work", "profile": "standard"}\n    ],\n    "projectsRoot": "~/code"\n}\n'
        (self.home / "profiles.json").write_text(text)
        self.run_cmd("install")
        after = (self.home / "profiles.json").read_text()
        self.assertIn('        {"path": "~/work", "profile": "standard"},\n        {"path": "~/ideas", "profile": "ideas"}',
                      after)
        self.assertEqual(self.json("profiles.json")["default"], "standard")
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / "profiles.json").read_text(), text)

    def test_their_own_null_default_stays_null(self):
        text = '{"default": null, "profiles": {}, "rules": []}\n'
        (self.home / "profiles.json").write_text(text)
        self.run_cmd("install")
        self.assertEqual(self.json("profiles.json")["default"], "standard")
        self.run_cmd("uninstall")
        self.assertEqual((self.home / "profiles.json").read_text(), text)

    def test_a_pre_080_full_uninstall_leaves_their_file_as_they_had_it(self):
        text = '{\n  "rules": [\n    {"path": "~/w", "profile": "standard"}\n  ]\n}\n'
        (self.home / "profiles.json").write_text(text)
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        (self.home / ".herdr-profiles.json").write_text(json.dumps({"profiles": manifest["profiles"],
                                                                     "files": manifest["files"]}))
        r = self.run_cmd("install")  # records what is exactly as an install adds it
        self.assertIn("recorded", r.stdout)
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / "profiles.json").read_text(), text)

    def test_a_pre_080_uninstall_that_changes_nothing_leaves_the_file_alone(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        (self.home / ".herdr-profiles.json").write_text(json.dumps({"profiles": manifest["profiles"],
                                                                     "files": manifest["files"]}))
        before = (self.home / "profiles.json").read_bytes()
        self.run_cmd("uninstall")  # nothing recorded: nothing taken back
        self.assertEqual((self.home / "profiles.json").read_bytes(), before)


class SymlinkedPersonalFileTest(HomeCase):
    def test_a_dangling_profiles_json_link_stays_a_link(self):
        target = Path(self.tmp.name + "-dot") / "profiles.json"
        target.parent.mkdir()
        self.addCleanup(shutil.rmtree, target.parent)
        (self.home / "profiles.json").symlink_to(target)
        self.run_cmd("install")
        self.assertTrue(target.is_file())
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / "profiles.json").is_symlink())  # the person's link, as they had it
        self.assertFalse(target.exists())


class FoldersTest(HomeCase):
    def test_a_full_uninstall_removes_the_empty_folders_install_made(self):
        self.run_cmd("install")
        self.assertEqual(self.json(".herdr-profiles.json")["folders"], ["layouts", "themes", "mods"])
        (self.home / "mods/.DS_Store").write_text("")
        r = self.run_cmd("uninstall")
        self.assertIn("removed   mods/ (install made it; nothing is left in it)", r.stdout)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["installed.json", "keys.json"])

    def test_folders_that_were_there_or_arent_empty_stay(self):
        (self.home / "layouts").mkdir()  # Herdr's, or the person's
        self.run_cmd("install")
        self.assertNotIn("layouts", self.json(".herdr-profiles.json")["folders"])
        (self.home / "themes/mine.json").write_text("{}")
        (self.home / "mods/.state").mkdir()  # something Herdr wrote
        r = self.run_cmd("uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for kind in ("layouts", "themes", "mods"):
            self.assertTrue((self.home / kind).is_dir(), kind)
        self.assertTrue((self.home / "themes/mine.json").is_file())

    def test_a_profile_uninstall_never_removes_them(self):
        self.run_cmd("install")
        self.run_cmd("uninstall", "ideas")
        for kind in ("layouts", "themes", "mods"):
            self.assertTrue((self.home / kind).is_dir(), kind)

    def test_an_old_manifest_removes_none(self):
        self.run_cmd("install")
        manifest = self.json(".herdr-profiles.json")
        del manifest["folders"]
        (self.home / ".herdr-profiles.json").write_text(json.dumps(manifest))
        self.run_cmd("uninstall")
        for kind in ("layouts", "themes", "mods"):
            self.assertTrue((self.home / kind).is_dir(), kind)


class WriteOrderTest(HomeCase):
    """Phase 0's guarantees, seen through the write hook (files.watching)."""

    def watched(self, *argv):
        from profiletool import files
        events = []

        def record(event, path, dest):
            folder = None
            if event == "rename":  # what the mod folder holds the moment it appears
                folder = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
            events.append((event, path.relative_to(self.home).as_posix(),
                           dest and dest.relative_to(self.home).as_posix(), folder))
        with files.watching(record):
            code, out, err = test_installer.InstallerTest.in_process(self, False, False, input, argv)
        self.assertEqual(code, 0, out + err)
        return events

    def mod_files(self, mod):
        base = next(p for p in (REPO / "core", *(REPO / "profiles").iterdir()) if (p / "mods" / mod).is_dir())
        return sorted(str(p.relative_to(base / "mods" / mod)) for p in (base / "mods" / mod).rglob("*")
                      if p.is_file() and p.name not in {".DS_Store", "gpui-kit.d.ts", "jsconfig.json", "tsconfig.json"})

    def test_new_mod_folders_appear_whole_with_mod_json_first(self):
        events = self.watched("install")
        renames = [e for e in events if e[0] == "rename"]
        mods = sorted(p.name for p in (self.home / "mods").iterdir())
        self.assertEqual(sorted(e[2] for e in renames), [f"mods/{m}" for m in mods])
        for _, stage, dest, held in renames:
            mod = dest.split("/")[1]
            with self.subTest(mod):
                self.assertEqual(held, self.mod_files(mod))  # whole, the moment it appears
                writes = [e[1] for e in events if e[0] == "write"]
                self.assertFalse([w for w in writes if w.startswith(dest + "/")])  # nothing written in place
                staged = [w for w in writes if w.startswith(stage + "/")]
                self.assertEqual(staged[0], f"{stage}/mod.json")
                at = events.index(next(e for e in renames if e[2] == dest))
                self.assertTrue(all(events.index(e) < at for e in events if e[0] == "write" and e[1] in staged))

    def test_mod_json_is_written_first_into_a_mod_folder_that_exists(self):
        self.run_cmd("install")
        for rel in ("mods/ideas/main.js", "mods/ideas/mod.json", "mods/ideas/store.js", "mods/profiles/mod.json"):
            (self.home / rel).unlink()
        events = self.watched("install")
        writes = [e[1] for e in events if e[0] == "write"]
        self.assertFalse([e for e in events if e[0] == "rename"])
        first = writes.index("mods/ideas/mod.json")
        self.assertLess(first, writes.index("mods/ideas/main.js"))
        self.assertLess(first, writes.index("mods/ideas/store.js"))
        self.assertLess(writes.index("mods/profiles/mod.json"), writes.index("mods/ideas/main.js"))

    def test_the_journal_first_and_the_manifest_after_the_personal_files(self):
        writes = [e[1] for e in self.watched("install") if e[0] == "write"]
        self.assertEqual(writes[0], ".herdr-profiles.pending.json")
        journal = ".herdr-profiles.pending.json"  # marked after each personal file
        self.assertEqual(writes[-5:], ["profiles.json", journal, "keys.json", journal, ".herdr-profiles.json"])


class JsonEditTest(unittest.TestCase):
    def check(self, text, new):
        out = jsonedit.update(text, new)
        self.assertEqual(json.loads(out), new)
        return out

    def test_items_added_and_cut(self):
        text = '{\n  "a": [\n    1,\n    2\n  ],\n  "b": {"x": 1}\n}\n'
        self.assertEqual(self.check(text, {"a": [1, 2, 3], "b": {"x": 1}}),
                         '{\n  "a": [\n    1,\n    2,\n    3\n  ],\n  "b": {"x": 1}\n}\n')
        self.assertEqual(self.check(text, {"a": [2], "b": {"x": 1}}), '{\n  "a": [\n    2\n  ],\n  "b": {"x": 1}\n}\n')
        self.assertEqual(self.check(text, {"a": [1, 2]}), '{\n  "a": [\n    1,\n    2\n  ]\n}\n')
        self.assertEqual(self.check(text, {"b": {"x": 1}, "a": [1, 2]}), text)  # order isn't a change

    def test_a_changed_value_is_rewritten_in_place(self):
        self.assertEqual(self.check('{"a": null,  "b": 1}', {"a": "s", "b": 1}), '{"a": "s",  "b": 1}')
        self.assertEqual(self.check('{\n  "a": 1\n}', {"a": {"k": [1]}}), '{\n  "a": {\n    "k": [\n      1\n    ]\n  }\n}')
        self.assertEqual(self.check('{"a": true}', {"a": 1}), '{"a": 1}')

    def test_what_cant_be_edited_is_written_whole_in_its_indentation(self):
        dup = '{\n    "a": 1,\n    "a": 2\n}\n'
        self.assertEqual(self.check(dup, {"a": 3}), '{\n    "a": 3\n}\n')
        self.assertEqual(jsonedit.update("", {"a": 1}), '{\n  "a": 1\n}\n')
        self.assertEqual(jsonedit.update("﻿{}", {"a": 1}), '{"a": 1}')

    def test_nested_empty_objects(self):
        self.assertEqual(self.check('{\n  "g": {}\n}\n', {"g": {"k": "v"}}), '{\n  "g": {\n    "k": "v"\n  }\n}\n')
        self.assertEqual(self.check('{"g": {}}', {"g": {"k": "v"}}), '{"g": {"k": "v"}}')
        self.assertEqual(self.check('{\n  "g": {\n    "k": "v"\n  }\n}\n', {"g": {}}), '{\n  "g": {}\n}\n')


class CheckTest(HomeCase):
    def test_herdr_app_bin_pointing_nowhere_is_said_and_fails(self):
        nowhere = str(self.home / "no-such-herdr-app")
        for path, said in ((nowhere, "not found (no such file)"), (str(self.home), "a folder, not a program")):
            with self.subTest(said):
                r = subprocess.run([sys.executable, str(SCRIPT), "check"], env={**self.env(), "HERDR_APP_BIN": path},
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(f"FAILED    HERDR_APP_BIN={path}: {said}, so mods were not checked", r.stdout)
                self.assertNotIn("skipped", r.stdout)


if __name__ == "__main__":
    unittest.main()
