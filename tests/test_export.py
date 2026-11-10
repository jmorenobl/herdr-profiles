"""Tests for scripts/export_public.py on throwaway git repos (fake home, fake git config).

Run: python3 -m unittest discover -s tests
"""

import gzip
import io
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "export_public.py"
OWNER = "owner.private@mail.example"
AUTHOR = "Pub Lisher <pub@example.invalid>"


class Fixture:
    """A source repo with one commit by OWNER, under a fake home named `someone`."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.home = self.root / "someone"
        self.home.mkdir()
        (self.home / ".gitconfig").write_text("")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"), LC_ALL="C")
        self.src = self.root / "src"
        self.src.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", OWNER)
        self.git("config", "user.name", "Owner")
        (self.src / ".git" / "info").mkdir(exist_ok=True)
        (self.src / ".git" / "info" / "exclude").write_text("ROADMAP.md\nnotes/\n*.local\n")
        self.write("README.md", "# Demo\n\nNothing personal.\n")
        self.write("docs/a.txt", "hello\n")
        self.write("ROADMAP.md", "private plans\n")  # excluded, untracked
        self.commit()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.src), *args], check=True,
                              capture_output=True, env=self.env).stdout.decode()

    def write(self, path, content):
        p = self.src / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)

    def commit(self, *force):
        self.git("add", "-A")
        for f in force:
            self.git("add", "-f", f)
        self.git("commit", "-q", "-m", "work")

    def deny(self, text):
        (self.src / ".git" / "info" / "export-deny").write_text(text)

    def run(self, *args, env=None):
        r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.src), *args],
                           capture_output=True, text=True, env=dict(self.env, **(env or {})))
        return r.returncode, r.stdout + r.stderr

    def export(self, dest="out", author=AUTHOR):
        return self.run(str(self.root / dest), "--author", author)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.dest = self.f.root / "out"

    def assertFails(self, result, *needles):
        code, out = result
        self.assertNotEqual(code, 0, out)
        for n in needles:
            self.assertIn(n, out)

    def test_happy_path(self):
        code, out = self.f.export()
        self.assertEqual(code, 0, out)
        self.assertIn("OK: 1 commit", out)
        g = lambda *a: self.f.git(*a, cwd=self.dest)  # noqa: E731
        self.assertEqual(g("log", "--format=%an|%ae|%cn|%ce|%B").strip(),
                         "Pub Lisher|pub@example.invalid|Pub Lisher|pub@example.invalid|Initial public release")
        self.assertEqual(g("rev-list", "--all", "--count").strip(), "1")
        self.assertEqual(g("remote").strip(), "")
        self.assertEqual(g("config", "user.email").strip(), "pub@example.invalid")
        self.assertEqual(g("ls-files").split(), ["README.md", "docs/a.txt"])
        self.assertEqual(g("rev-parse", "HEAD^{tree}"), self.f.git("rev-parse", "HEAD^{tree}"))
        self.assertNotIn("private", (self.dest / "README.md").read_text())
        self.assertEqual(self.f.run("--check", str(self.dest))[0], 0)
        # The source repo is untouched.
        self.assertEqual(self.f.git("rev-list", "--count", "HEAD").strip(), "1")

    def test_dest_not_empty(self):
        self.dest.mkdir()
        (self.dest / "x").write_text("")
        self.assertFails(self.f.export(), "isn't an empty folder")
        (self.f.root / "file").write_text("")
        self.assertFails(self.f.export("file"), "isn't an empty folder")

    def test_dest_inside_repo(self):
        self.assertFails(self.f.export("src/sub/out"), "inside the repo")
        self.assertFalse((self.f.src / "sub").exists())
        upper = self.f.root / "SRC"
        if upper.exists():  # case-insensitive disk: same folder, other spelling
            self.assertFails(self.f.export("SRC/out"), "inside the repo")
        os.symlink(self.f.src, self.f.root / "link")
        self.assertFails(self.f.export("link/out"), "inside the repo")

    def test_bad_author(self):
        for bad in ["nobody", "Name <bad>", "<a@b.example>", "Name a@b.example", "Name <a@b.example> x", ""]:
            self.assertFails(self.f.export(author=bad), "Name <email>")
        self.assertFalse(self.dest.exists())
        self.assertFails(self.f.run(str(self.dest)))  # no --author

    def test_owner_email_in_a_file(self):
        self.f.write("docs/b.md", f"line one\nwrite to {OWNER.upper()}\n")
        self.f.commit()
        self.assertFails(self.f.export(), "docs/b.md:2: contains this repo's git user.email")

    def test_home_path_and_user_folder(self):
        self.f.write("a.txt", f"see {self.f.home}/x\n")
        self.f.write("b.txt", "\n\ncd /home/someone/code\n")
        self.f.commit()
        self.assertFails(self.f.export(), "a.txt:1: contains the home folder's path",
                         "b.txt:3: contains the home folder's name as a path")

    def test_history_email_is_denied(self):
        self.f.git("config", "user.email", "new@mail.example")
        self.f.write("c.txt", f"old {OWNER}\n")
        self.f.commit()
        self.assertFails(self.f.export(), "c.txt:1: contains an author/committer email")

    def test_denied_string_in_binary(self):
        self.f.write("img.bin", b"\x89\x00\x01" + OWNER.encode() + b"\x00\xff")
        self.f.write("utf16.bin", b"\xff\xfe" + "Owner: SecretCo".encode("utf-16-le"))
        self.f.deny("secretco\n")
        self.f.commit()
        self.assertFails(self.f.export(), "img.bin:byte 3: contains", "utf16.bin:byte 16: contains")

    def test_denied_string_in_compressed_png_chunk(self):
        def chunk(kind, body):
            return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\0" * 13)
               + chunk(b"zTXt", b"Author\0\0" + zlib.compress(b"by SecretCo"))
               + chunk(b"IEND", b""))
        self.f.write("shot.png", png)
        self.f.deny("SecretCo\n")
        self.f.commit()
        self.assertFails(self.f.export(), "shot.png (compressed PNG chunk)")

    def test_deny_file(self):
        self.f.write("notes.md", "a\nworking on acmeplan now\n")
        self.f.commit()
        self.assertEqual(self.f.export("clean")[0], 0)
        self.f.deny("# comment\n\n   \n   AcmePlan  \n")
        code, out = self.f.export()
        self.assertFails((code, out), "notes.md:2: contains .git/info/export-deny line 4")
        self.assertNotIn("AcmePlan", out)  # the report names the rule, not the string

    def test_denied_string_in_path(self):
        self.f.deny("SecretCo\n")
        self.f.write("for-secretco/x.txt", "x\n")
        self.f.commit()
        self.assertFails(self.f.export(), "path for-secretco/x.txt")

    def test_roadmap_and_excluded_files(self):
        code, out = self.f.export()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.dest / "ROADMAP.md").exists())
        self.f.write("docs/roadmap.md", "x\n")
        self.f.write("notes/n.txt", "x\n")
        self.f.write("a.local", "x\n")
        self.f.commit("notes/n.txt", "a.local", "ROADMAP.md", "docs/roadmap.md")
        self.assertFails(self.f.export("out2"), "docs/roadmap.md: ROADMAP.md must not be exported",
                         "ROADMAP.md: ROADMAP.md", "notes/n.txt: matched by .git/info/exclude",
                         "a.local: matched by .git/info/exclude")

    def test_dirty_tree_notice(self):
        self.f.write("README.md", f"uncommitted {OWNER}\n")
        code, out = self.f.export()
        self.assertEqual(code, 0, out)
        self.assertIn("uncommitted changes; they are not exported", out)
        self.assertEqual((self.dest / "README.md").read_text(), "# Demo\n\nNothing personal.\n")

    def test_check_catches_later_changes(self):
        self.assertEqual(self.f.export()[0], 0)
        g = lambda *a: self.f.git(*a, cwd=self.dest)  # noqa: E731
        g("remote", "add", "origin", "https://example.invalid/x.git")
        self.assertFails(self.f.run("--check", str(self.dest)), "has a remote")
        g("remote", "remove", "origin")
        g("commit", "-q", "--amend", "-m", f"Initial\n\nCo-Authored-By: X <{OWNER}>")
        self.assertFails(self.f.run("--check", str(self.dest)), "commit:", "attribution trailer")
        (self.dest / "new.txt").write_text("x\n")
        g("add", "new.txt")
        g("commit", "-q", "-m", "second")
        self.assertFails(self.f.run("--check", str(self.dest)), "2 commits")
        (self.dest / "stray.txt").write_text("x\n")
        self.assertFails(self.f.run("--check", str(self.dest)), "differ from its commit")
        self.assertFails(self.f.run("--check", str(self.f.root)), "isn't a git repo")

    def test_committer_identity_is_checked(self):
        self.assertEqual(self.f.export()[0], 0)
        env = dict(self.f.env, GIT_COMMITTER_EMAIL=OWNER)
        subprocess.run(["git", "-C", str(self.dest), "commit", "-q", "--amend", "--no-edit"],
                       check=True, env=env, capture_output=True)
        self.assertFails(self.f.run("--check", str(self.dest)), "commit:", "user.email")

    def test_symlink_outside(self):
        os.symlink("../../etc/passwd", self.f.src / "docs" / "up")
        os.symlink("/etc/hosts", self.f.src / "abs")
        os.symlink("a.txt", self.f.src / "docs" / "ok")
        self.f.commit()
        code, out = self.f.export()
        self.assertFails((code, out), "docs/up: a symlink leading outside", "abs: a symlink leading outside")
        self.assertNotIn("docs/ok:", out)

    def test_submodule_refused(self):
        sub = self.f.root / "sub"
        sub.mkdir()
        self.f.git("init", "-q", cwd=sub)
        self.f.git("config", "user.email", OWNER, cwd=sub)  # CI has no identity to fall back on
        self.f.git("config", "user.name", "Owner", cwd=sub)
        self.f.git("commit", "-q", "--allow-empty", "-m", "s", cwd=sub)
        head = self.f.git("rev-parse", "HEAD", cwd=sub).strip()
        self.f.git("update-index", "--add", "--cacheinfo", f"160000,{head},vendor")
        self.f.git("commit", "-q", "-m", "sub")
        self.assertFails(self.f.export(), "submodule")
        self.assertFalse(self.dest.exists())



class FoundByReviewTest(unittest.TestCase):
    """Leaks and false passes an independent review found (2026-11-10)."""

    def setUp(self):
        self.f = Fixture(self)
        self.dest = self.f.root / "out"

    assertFails = ExportTest.assertFails

    def test_case_beyond_ascii(self):
        self.f.deny("josé\n")
        self.f.write("a.txt", "x\nJOSÉ was here\n")
        self.f.commit()
        self.assertFails(self.f.export(), "a.txt:2: contains .git/info/export-deny line 1")

    def test_unicode_normalization(self):
        self.f.deny("josé\n")
        self.f.write("a.txt", unicodedata.normalize("NFD", "by josé\n"))
        self.f.write("b.bin", b"\0" + unicodedata.normalize("NFD", "JOSÉ").encode())
        self.f.commit()
        self.assertFails(self.f.export(), "a.txt:1: contains", "b.bin:byte 1: contains")

    def test_deny_file_with_bom_or_utf16(self):
        self.f.write("a.txt", "a secretword\n")
        self.f.commit()
        (self.f.src / ".git/info/export-deny").write_bytes(b"\xef\xbb\xbfsecretword\r\n")
        self.assertFails(self.f.export("o1"), "a.txt:1: contains .git/info/export-deny line 1")
        (self.f.src / ".git/info/export-deny").write_bytes("# c\nsecretword\n".encode("utf-16"))
        self.assertFails(self.f.export("o2"), "a.txt:1: contains .git/info/export-deny line 2")
        (self.f.src / ".git/info/export-deny").write_bytes(b"\xff\x00\x80bad")
        self.assertFails(self.f.export("o3"), "isn't UTF-8 or UTF-16")

    def test_symlink_chain_escapes(self):
        (self.f.src / "sub").mkdir()
        os.symlink("..", self.f.src / "sub" / "d")
        os.symlink("d/..", self.f.src / "sub" / "x")
        self.f.commit()
        self.assertFails(self.f.export(), "sub/x: a symlink leading outside")

    def test_email_only_in_reflog(self):
        self.f.write("a.txt", f"{OWNER}\n")
        self.f.commit()
        self.f.git("checkout", "-q", "--orphan", "new")
        self.f.git("config", "user.email", "pub2@example.invalid")
        self.f.git("commit", "-q", "-m", "fresh")
        self.f.git("branch", "-D", "main")
        self.assertFails(self.f.export(), "a.txt:1: contains an author/committer email")

    def test_inside_gzip_zip_and_utf32(self):
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", f"<w>{OWNER}</w>")
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("deep.txt", OWNER)
        self.f.write("a.gz", gzip.compress(OWNER.encode()))
        self.f.write("a.docx", z.getvalue())
        self.f.write("nested.gz", gzip.compress(inner.getvalue()))
        self.f.write("u32.txt", OWNER.encode("utf-32"))
        self.f.commit()
        self.assertFails(self.f.export(), "a.gz (gzip)", "a.docx (zip member word/document.xml)",
                         "nested.gz (gzip > zip member deep.txt)", "u32.txt:byte")

    def test_check_does_not_excuse_history_email(self):
        self.f.git("config", "user.email", "new@mail.example")  # the owner's email is only in history now
        out = self.f.root / "hand"
        out.mkdir()
        (out / "f").write_text(f"{OWNER}\n")
        self.f.git("init", "-q", cwd=out)
        self.f.git("config", "user.email", "pub@example.invalid", cwd=out)
        self.f.git("add", "f", cwd=out)
        env = dict(self.f.env, GIT_AUTHOR_EMAIL=OWNER, GIT_COMMITTER_EMAIL=OWNER,
                   GIT_AUTHOR_DATE="1700000000 +0000", GIT_COMMITTER_DATE="1700000000 +0000")
        subprocess.run(["git", "-C", str(out), "commit", "-q", "-m", "x"], check=True, env=env)
        self.assertFails(self.f.run("--check", str(out)), "commit:", "f:1: contains an author/committer email")

    def test_shallow_clone_is_not_one_commit(self):
        self.f.write("b.txt", "more\n")
        self.f.commit()
        out = self.f.root / "shallow"
        self.f.git("clone", "-q", "--depth", "1", f"file://{self.f.src}", str(out), cwd=self.f.root)
        self.f.git("remote", "remove", "origin", cwd=out)
        self.assertFails(self.f.run("--check", str(out)), "has a parent", ".git/shallow")

    def test_dest_through_symlink_or_dotdot_into_repo(self):
        (self.f.src / "emptydir").mkdir()
        os.symlink(self.f.src / "emptydir", self.f.root / "lnk")
        self.assertFails(self.f.export("lnk"), "inside the repo")
        self.assertFails(self.f.export("nope/../src/x"), "inside the repo")
        self.assertFalse((self.f.root / "nope").exists())
        self.assertFalse((self.f.src / "x").exists())

    def test_git_environment_cannot_redirect_to_source(self):
        self.f.write("new.txt", "staged\n")
        self.f.git("add", "new.txt")
        code, out = self.f.run(str(self.dest), "--author", AUTHOR,
                               env={"GIT_DIR": str(self.f.src / ".git"), "GIT_INDEX_FILE": str(self.f.src / ".git/index"),
                                    "GIT_AUTHOR_DATE": "1700000000 +0500"})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.f.git("config", "user.email").strip(), OWNER)
        self.assertIn("A  new.txt", self.f.git("status", "--porcelain"))

    def test_time_is_utc(self):
        code, out = self.f.run(str(self.dest), "--author", AUTHOR, env={"TZ": "America/Bogota"})
        self.assertEqual(code, 0, out)
        self.assertTrue(self.f.git("log", "--format=%ai %ci", cwd=self.dest).strip().endswith("+0000"))
        env = dict(self.f.env, GIT_COMMITTER_DATE="1700000000 -0500")
        subprocess.run(["git", "-C", str(self.dest), "commit", "-q", "--amend", "--no-edit"], check=True, env=env)
        self.assertFails(self.f.run("--check", str(self.dest)), "isn't in UTC")

    def test_other_user_folder_is_not_ours(self):
        self.f.write("a.txt", "see /home/someoneelse/docs and /Users/someone_2\n")
        self.f.commit()
        code, out = self.f.export()
        self.assertEqual(code, 0, out)
        self.f.write("b.txt", "see /home/someone/docs\n")
        self.f.commit()
        self.assertFails(self.f.export("o2"), "b.txt:1: contains the home folder's name as a path")


if __name__ == "__main__":
    unittest.main()
