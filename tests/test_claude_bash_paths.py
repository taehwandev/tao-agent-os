from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_pretool_gate as gate
import claude_worktree_gate as worktree_gate


def _opt_in_project(base: Path) -> Path:
    project = base / "proj"
    (project / ".tao").mkdir(parents=True)
    (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
    return project


def _require_linked_worktree(project: Path) -> None:
    (project / ".git").mkdir()
    policy = project / gate.WORKTREE_POLICY_PATH
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "require_linked_worktree": True,
                "protected_branches": ["develop", "main"],
            }
        ),
        encoding="utf-8",
    )


class CopySourcePathRoleTests(unittest.TestCase):
    """A copy's sources are read, so they name no protected target.

    Judged by paths alone, seeding a linked worktree from the main checkout
    read as a write into the checkout it only reads from, so the gate refused
    the exact move its own denial message asks for. Only the destination
    decides now; every other shape keeps the stricter reading.
    """

    def setUp(self) -> None:
        self._root = tempfile.TemporaryDirectory()
        self.addCleanup(self._root.cleanup)
        base = Path(self._root.name).resolve()
        self.main = _opt_in_project(base)
        _require_linked_worktree(self.main)
        self.worktree = base / "linked"
        self.worktree.mkdir()
        self.source = self.main / "keystore.jks"
        self.source.write_bytes(b"key")
        self.destination = self.worktree / "keystore.jks"

    @staticmethod
    def _roots(command: str, cwd: Path) -> list[Path]:
        payload = {"tool_input": {"command": command}}
        _, tokens, _ = worktree_gate.bash_invocation(payload, cwd)
        return gate.bash_target_project_roots(tokens, cwd)

    def test_a_copy_source_names_no_target(self) -> None:
        roots = self._roots(f"cp {self.source} {self.destination}", self.worktree)
        self.assertNotIn(self.main, roots)

    def test_the_destination_is_still_judged(self) -> None:
        roots = self._roots(f"cp {self.destination} {self.source}", self.worktree)
        self.assertIn(self.main, [path for path in roots])

    def test_a_target_directory_flag_keeps_every_path(self) -> None:
        roots = self._roots(f"cp -t {self.main} {self.destination}", self.worktree)
        self.assertIn(self.main, [path for path in roots])

    def test_a_single_operand_keeps_every_path(self) -> None:
        roots = self._roots(f"cp {self.source}", self.worktree)
        self.assertIn(self.main, [path for path in roots])

    def test_a_verifying_follow_up_does_not_reclaim_the_source(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} && ls -l {self.destination}",
            self.worktree,
        )
        self.assertNotIn(self.main, roots)

    def test_a_redirection_keeps_every_path(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} > {self.main}/log",
            self.worktree,
        )
        self.assertIn(self.main, [path for path in roots])

    def test_a_second_segment_naming_the_checkout_still_claims_it(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} && touch {self.main}/x",
            self.worktree,
        )
        self.assertIn(self.main, [path for path in roots])

    def test_a_later_identical_source_spelling_still_names_a_target(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} && touch {self.source}",
            self.worktree,
        )
        self.assertIn(self.main, [path for path in roots])

    def test_a_descriptor_redirection_gives_the_copy_no_source_exemption(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} 2>/dev/null", self.worktree
        )
        self.assertIn(self.main, [path for path in roots])

    def test_descriptor_duplication_gives_the_copy_no_source_exemption(self) -> None:
        roots = self._roots(
            f"cp {self.source} {self.destination} 2>&1", self.worktree
        )
        self.assertIn(self.main, [path for path in roots])

    def test_a_spoofed_cp_path_gives_no_source_exemption(self) -> None:
        spoofed_cp = self.worktree / "cp"
        spoofed_cp.write_text("#!/bin/sh\n", encoding="utf-8")
        spoofed_cp.chmod(0o755)

        roots = self._roots(
            f"{spoofed_cp} {self.source} {self.destination}", self.worktree
        )

        self.assertIn(self.main, [path for path in roots])

    def test_plain_cp_resolving_to_an_untrusted_path_gives_no_source_exemption(self) -> None:
        fake_bin = self.worktree / "bin"
        fake_bin.mkdir()
        spoofed_cp = fake_bin / "cp"
        spoofed_cp.write_text("#!/bin/sh\n", encoding="utf-8")
        spoofed_cp.chmod(0o755)

        with patch.dict(os.environ, {"PATH": str(fake_bin)}):
            roots = self._roots(
                f"cp {self.source} {self.destination}", self.worktree
            )

        self.assertIn(self.main, [path for path in roots])

    def test_a_recursive_copy_is_still_modelled(self) -> None:
        roots = self._roots(f"cp -r {self.source} {self.destination}", self.worktree)
        self.assertNotIn(self.main, roots)

    def test_only_cp_is_modelled(self) -> None:
        roots = self._roots(f"mv {self.source} {self.destination}", self.worktree)
        self.assertIn(self.main, [path for path in roots])


class CopyShapedCommandTests(CopySourcePathRoleTests):
    """The same shape, however the copy is spelled.

    Modelling `cp` alone meant the permitted move worked one way and was
    refused every other way: `rsync -a`, `install` and `ln -s` copy sources
    first and destination last exactly as `cp` does, and none of them writes to
    a source. A person seeding a worktree does not pick between them for
    safety reasons, so a gate that does is only teaching a spelling.
    """

    def _skip_unless_present(self, name: str) -> None:
        import shutil

        if not shutil.which(name):
            self.skipTest(f"{name} is not installed on this host")

    def test_rsync_sources_name_no_target(self) -> None:
        self._skip_unless_present("rsync")
        roots = self._roots(f"rsync -a {self.source} {self.destination}", self.worktree)
        self.assertNotIn(self.main, roots)

    def test_install_sources_name_no_target(self) -> None:
        self._skip_unless_present("install")
        roots = self._roots(f"install -p {self.source} {self.destination}", self.worktree)
        self.assertNotIn(self.main, roots)

    def test_a_link_target_names_no_target(self) -> None:
        self._skip_unless_present("ln")
        roots = self._roots(f"ln -s {self.source} {self.destination}", self.worktree)
        self.assertNotIn(self.main, roots)

    def test_a_flag_that_writes_the_source_keeps_every_path(self) -> None:
        """`--remove-source-files` deletes what it read, so it is not a copy."""

        self._skip_unless_present("rsync")
        roots = self._roots(
            f"rsync -a --remove-source-files {self.source} {self.destination}",
            self.worktree,
        )
        self.assertIn(self.main, [path for path in roots])

    def test_a_destination_first_flag_keeps_every_path(self) -> None:
        self._skip_unless_present("install")
        roots = self._roots(
            f"install -t {self.worktree} {self.source}", self.worktree
        )
        self.assertIn(self.main, [path for path in roots])

    def test_each_command_keeps_its_own_safe_flags(self) -> None:
        """A shared flag set would lend one command another's guarantees."""

        from claude_bash_paths import COPY_SHAPED_COMMANDS

        self.assertIsNone(COPY_SHAPED_COMMANDS["rsync"][0].fullmatch("-n"))
        self.assertIsNotNone(COPY_SHAPED_COMMANDS["cp"][0].fullmatch("-n"))
        self.assertIsNone(COPY_SHAPED_COMMANDS["cp"][0].fullmatch("-s"))
        self.assertIsNotNone(COPY_SHAPED_COMMANDS["ln"][0].fullmatch("-s"))

    def test_a_spoofed_binary_earns_nothing_for_any_command(self) -> None:
        for name in ("rsync", "install", "ln"):
            with self.subTest(command=name):
                roots = self._roots(
                    f"/tmp/{name} -a {self.source} {self.destination}", self.worktree
                )
                self.assertIn(self.main, [path for path in roots])


if __name__ == "__main__":
    unittest.main()
