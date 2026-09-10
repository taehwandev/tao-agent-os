from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.codex_permissions import merge_codex_worktree_roots


class CodexPermissionsTests(unittest.TestCase):
    def test_worktree_roots_create_workspace_profile_and_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            roots = [Path(directory) / "project" / ".tao" / "worktrees"]

            first = merge_codex_worktree_roots(target, roots, dry_run=False)
            first_text = target.read_text(encoding="utf-8")
            second = merge_codex_worktree_roots(target, roots, dry_run=False)
            second_text = target.read_text(encoding="utf-8")

        self.assertEqual("installed", first)
        self.assertEqual("ok", second)
        self.assertEqual(first_text, second_text)
        self.assertNotIn('default_permissions =', second_text)
        self.assertIn('[permissions.tao-workspace]', second_text)
        self.assertIn('extends = ":workspace"', second_text)
        self.assertIn(f'"{roots[0].resolve()}" = true', second_text)

    def test_worktree_roots_preserve_existing_profile_and_unrelated_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                'model = "gpt-test"\n'
                'default_permissions = "tao-workspace"\n\n'
                '[permissions.tao-workspace]\n'
                'description = "Custom local description"\n'
                'extends = ":workspace"\n\n'
                '[permissions.tao-workspace.workspace_roots]\n'
                '"/existing/root" = true\n\n'
                '[projects."/existing/project"]\n'
                'trust_level = "trusted"\n',
                encoding="utf-8",
            )
            root = Path(directory) / "project" / ".tao" / "worktrees"

            status = merge_codex_worktree_roots(target, [root], dry_run=False)
            text = target.read_text(encoding="utf-8")

        self.assertEqual("installed", status)
        self.assertIn('model = "gpt-test"', text)
        self.assertIn('description = "Custom local description"', text)
        self.assertIn('"/existing/root" = true', text)
        self.assertIn(f'"{root.resolve()}" = true', text)
        self.assertIn('[projects."/existing/project"]', text)
        self.assertIn('trust_level = "trusted"', text)

    def test_worktree_roots_preserve_user_permission_selection(self) -> None:
        configs = (
            'default_permissions = "personal-profile"\n',
            'approval_policy = "on-request"\n',
            'sandbox_mode = "workspace-write"\n',
            '[sandbox_workspace_write]\nwritable_roots = ["/personal"]\n',
            'default_permissions = "tao-workspace"\napproval_policy = "on-request"\n',
        )
        for original in configs:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "config.toml"
                target.write_text(original, encoding="utf-8")

                status = merge_codex_worktree_roots(
                    target,
                    [Path(directory) / "project" / ".tao" / "worktrees"],
                    dry_run=False,
                )

                self.assertEqual("installed", status)
                updated = target.read_text(encoding="utf-8")
                self.assertTrue(updated.startswith(original))
                self.assertEqual(original.count("default_permissions ="), updated.count("default_permissions ="))
                self.assertIn('[permissions.tao-workspace.workspace_roots]', updated)

    def test_nested_default_permissions_key_does_not_replace_profile_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            target.write_text(
                '[custom]\ndefault_permissions = "custom-value"\n',
                encoding="utf-8",
            )

            status = merge_codex_worktree_roots(
                target,
                [Path(directory) / "project" / ".tao" / "worktrees"],
                dry_run=False,
            )
            text = target.read_text(encoding="utf-8")

        self.assertEqual("installed", status)
        self.assertTrue(text.startswith('[custom]\n'))
        self.assertIn('[custom]\ndefault_permissions = "custom-value"', text)

    def test_explicit_profile_conflicts_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            root = Path(directory) / "worktrees"
            for original in (
                '[permissions.tao-workspace]\nextends = ":other"\n',
                '[permissions.tao-workspace.workspace_roots]\n'
                f'"{root.resolve()}" = false\n',
            ):
                with self.subTest(original=original):
                    target.write_text(original)
                    self.assertEqual("missing", merge_codex_worktree_roots(target, [root], False))
                    self.assertEqual(original, target.read_text())

    def test_dry_run_does_not_select_or_create_a_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.toml"
            self.assertEqual("missing", merge_codex_worktree_roots(target, [Path(directory)], True))
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
