from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.codex_approval_setup import merge_codex_approvals_reviewer


class CodexApprovalSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.target = self.base / ".codex" / "config.toml"

    def write(self, content: bytes) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(content)

    def merge(self, *, dry_run: bool = False, enabled: bool = True) -> str:
        return merge_codex_approvals_reviewer(
            self.target, dry_run, enable_auto_review=enabled,
        )

    def test_default_does_not_create_or_read_configuration(self) -> None:
        self.assertTrue(self.merge(enabled=False).startswith("ok"))
        self.assertFalse(self.target.parent.exists())
        for content in (b'approval_policy = "on-request"\n', b"invalid \xff bytes"):
            with self.subTest(content=content):
                self.write(content)
                before = self.target.stat().st_mtime_ns
                self.assertTrue(self.merge(enabled=False).startswith("ok"))
                self.assertEqual(content, self.target.read_bytes())
                self.assertEqual(before, self.target.stat().st_mtime_ns)

    def test_explicit_fresh_pc_opt_in_and_check(self) -> None:
        self.assertEqual("would_update", self.merge(dry_run=True))
        self.assertFalse(self.target.parent.exists())
        self.assertEqual("installed", self.merge())
        self.assertEqual(b'approvals_reviewer = "auto_review"\n', self.target.read_bytes())
        before = self.target.stat().st_mtime_ns
        self.assertEqual("ok", self.merge())
        self.assertEqual("ok", self.merge(dry_run=True))
        self.assertEqual(before, self.target.stat().st_mtime_ns)

    def test_user_setting_replacement_preserves_every_other_byte(self) -> None:
        original = (
            b'# personal choices\r\n  approvals_reviewer\t=\t\'user\'  # keep comment\r\n'
            b'approval_policy = "on-request"\r\nsandbox_mode="workspace-write"\r\n'
            b'default_permissions = ":workspace"\r\n[hooks]\r\nnotify = ["my-hook"]\r\n'
        )
        self.write(original)
        self.assertEqual("would_update", self.merge(dry_run=True))
        self.assertEqual(original, self.target.read_bytes())
        self.assertEqual("installed", self.merge())
        self.assertEqual(original.replace(b"'user'", b"'auto_review'", 1), self.target.read_bytes())

    def test_missing_root_value_is_inserted_before_real_table(self) -> None:
        original = (
            b'model="some-model"\n# approvals_reviewer = "user"\n'
            b'[profiles.personal]\napprovals_reviewer="user"\n'
            b'[[servers]]\napprovals_reviewer="user"\n'
        )
        self.write(original)
        self.assertEqual("installed", self.merge())
        self.assertEqual(original.replace(
            b"[profiles.personal]", b'approvals_reviewer = "auto_review"\n[profiles.personal]', 1,
        ), self.target.read_bytes())

    def test_strings_comments_and_multiline_arrays_do_not_define_headers(self) -> None:
        for quote in (b'"""', b"'''"):
            with self.subTest(quote=quote):
                original = (
                    b"instructions=" + quote + b'\n[pretend]\napprovals_reviewer="user"\n'
                    + quote + b'\nitems = [\n"[another]", # comment\n"value",\n]\n'
                    b'approvals_reviewer="user" # my setting\n[actual]\nx=true\n'
                )
                self.write(original)
                self.assertEqual("installed", self.merge())
                self.assertEqual(original.replace(
                    b'approvals_reviewer="user" # my setting',
                    b'approvals_reviewer="auto_review" # my setting',
                ), self.target.read_bytes())

    def test_quoted_root_keys_are_handled_without_changing_key_spelling(self) -> None:
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                original = f'{quote}approvals_reviewer{quote} = "user" # keep\n'.encode()
                self.write(original)
                self.assertEqual("installed", self.merge())
                self.assertEqual(original.replace(b'"user"', b'"auto_review"'), self.target.read_bytes())

    def test_windows_trust_tables_preserve_literal_and_basic_quoted_paths(self) -> None:
        for header in (
            br"[projects.'C:\Users\alice\repo']",
            br'[projects."C:\\Users\\alice\\repo"]',
        ):
            with self.subTest(header=header):
                original = header + b'\ntrust_level = "trusted"\n'
                self.write(original)
                self.assertEqual("would_update", self.merge(dry_run=True))
                self.assertEqual(original, self.target.read_bytes())
                self.assertEqual("installed", self.merge())
                self.assertEqual(
                    b'approvals_reviewer = "auto_review"\n' + original,
                    self.target.read_bytes(),
                )

    def test_escaped_root_alias_changes_existing_value_without_inserting_duplicate(self) -> None:
        for key in (br'"approvals\u005freviewer"', br'"\u0061pprovals_reviewer"'):
            with self.subTest(key=key):
                original = key + b' = "user" # keep spelling\n'
                self.write(original)
                self.assertEqual("installed", self.merge())
                self.assertEqual(original.replace(b'"user"', b'"auto_review"'), self.target.read_bytes())
                self.assertEqual("ok", self.merge())

    def test_duplicate_escaped_root_aliases_never_modify_configuration(self) -> None:
        for original in (
            br'"approvals\u005freviewer" = "user"' + b'\napprovals_reviewer = "user"\n',
            b'approvals_reviewer = "auto_review"\n' + br'"\u0061pprovals_reviewer"="user"' + b'\n',
            br'"approvals\u005freviewer"="user"' + b'\n' + br'"\u0061pprovals_reviewer"="user"' + b'\n',
        ):
            with self.subTest(original=original):
                self.write(original)
                before = self.target.stat().st_mtime_ns
                for dry_run in (True, False):
                    self.assertEqual("conflict", self.merge(dry_run=dry_run))
                    self.assertEqual(original, self.target.read_bytes())
                    self.assertEqual(before, self.target.stat().st_mtime_ns)

    def test_nested_and_dotted_reviewers_remain_unchanged(self) -> None:
        original = (
            b'profiles.personal.approvals_reviewer="user"\n'
            b'["profiles"."personal"]\napprovals_reviewer="user"\n'
        )
        self.write(original)
        self.assertEqual("installed", self.merge())
        self.assertEqual(
            original.replace(b'["profiles"', b'approvals_reviewer = "auto_review"\n["profiles"', 1),
            self.target.read_bytes(),
        )

    def test_unsafe_shapes_never_modify_the_file(self) -> None:
        cases = (
            b'approvals_reviewer="user"\napprovals_reviewer="auto_review"\n',
            b'approvals_reviewer="auto_review"\n"approvals_reviewer"="user"\n',
            b'approvals_reviewer="unknown"\n',
            b'approvals_reviewer=true\n',
            b'approvals_reviewer=["user"]\n',
            b'approvals_reviewer="user" trailing\n',
            b'approvals_reviewer=\n',
            b'approvals_reviewer="user\n',
            b'approvals_reviewer.foo="user"\n',
            b'[approvals_reviewer]\nx="user"\n',
            b'[["approvals_reviewer"]]\nx="user"\n',
            b'"\\U00000061pprovals_reviewer"="user"\n',
            b'"\\ud800"="user"\n',
            b'model="\\q"\n',
            b'broken statement\n',
            b'[profiles\n',
            b'[\nprofiles]\n',
            b'model=["x"\n',
            b'model="""unterminated\n[profiles]\n',
        )
        for original in cases:
            with self.subTest(original=original):
                self.write(original)
                before = self.target.stat().st_mtime_ns
                for dry_run in (True, False):
                    self.assertEqual("conflict", self.merge(dry_run=dry_run))
                    self.assertEqual(original, self.target.read_bytes())
                    self.assertEqual(before, self.target.stat().st_mtime_ns)

    def test_no_trailing_newline_and_crlf_insertions_preserve_original_bytes(self) -> None:
        for original, expected in (
            (b'model="x"', b'model="x"\napprovals_reviewer = "auto_review"\n'),
            (b'# hi\r\n[model]\r\nx=true\r\n', b'# hi\r\napprovals_reviewer = "auto_review"\r\n[model]\r\nx=true\r\n'),
            (b'  [model]\nx=true\n', b'approvals_reviewer = "auto_review"\n  [model]\nx=true\n'),
        ):
            with self.subTest(original=original):
                self.write(original)
                self.assertEqual("installed", self.merge())
                self.assertEqual(expected, self.target.read_bytes())

    def test_existing_auto_review_is_ready_and_not_rewritten(self) -> None:
        for value in (b'"auto_review"', b"'auto_review'"):
            original = b'approvals_reviewer\t= ' + value + b' # keep\n'
            self.write(original)
            before = self.target.stat().st_mtime_ns
            for dry_run in (True, False):
                self.assertEqual("ok", self.merge(dry_run=dry_run))
                self.assertEqual(original, self.target.read_bytes())
                self.assertEqual(before, self.target.stat().st_mtime_ns)

    def test_symlink_targets_and_directories_are_refused(self) -> None:
        external = self.base / "external.toml"
        original = b'approvals_reviewer="user"\n'
        external.write_bytes(original)
        self.target.parent.mkdir()
        self.target.symlink_to(external)
        for dry_run in (True, False):
            self.assertEqual("conflict", self.merge(dry_run=dry_run))
            self.assertTrue(self.target.is_symlink())
            self.assertEqual(original, external.read_bytes())
        self.target.unlink()
        self.target.symlink_to(self.base / "missing")
        self.assertEqual("conflict", self.merge())
        self.assertTrue(self.target.is_symlink())
        self.target.unlink()
        self.target.parent.rmdir()
        external_dir = self.base / "external-dir"
        external_dir.mkdir()
        self.target.parent.symlink_to(external_dir, target_is_directory=True)
        self.assertEqual("conflict", self.merge())
        self.assertTrue(self.target.parent.is_symlink())
        self.assertEqual([], list(external_dir.iterdir()))

    def test_preserves_existing_file_mode(self) -> None:
        self.write(b'approvals_reviewer="user"\n')
        os.chmod(self.target, 0o640)
        self.assertEqual("installed", self.merge())
        self.assertEqual(0o640, stat.S_IMODE(self.target.stat().st_mode))

    def test_non_file_target_or_parent_and_invalid_encoding_are_safe(self) -> None:
        self.target.parent.mkdir()
        self.target.mkdir()
        self.assertEqual("conflict", self.merge())
        self.assertTrue(self.target.is_dir())
        self.target.rmdir()
        self.target.parent.rmdir()
        self.target.parent.write_bytes(b"preserve")
        self.assertEqual("conflict", self.merge())
        self.assertEqual(b"preserve", self.target.parent.read_bytes())
        self.target.parent.unlink()
        self.write(b"\xff")
        self.assertEqual("missing", self.merge())
        self.assertEqual(b"\xff", self.target.read_bytes())


if __name__ == "__main__":
    unittest.main()
