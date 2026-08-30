"""Every project that installs Tao Agent OS should get the worktree rules.

A task runs in its own linked worktree under `.tao/worktrees/<16-hex>`, and that
directory name is fresh every time. Without a rule covering the whole root, a
permission approved for one worktree never matches the next, so the prompts
never stop and the honest response is to switch permissions off -- which is how
a protection gets discarded.

The rules belong to the installer rather than to one checkout: adding them by
hand fixes one machine and leaves every other project prompting.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_worktree_identity import WORKTREE_DIRNAME  # noqa: E402
from support.permission_entries import (  # noqa: E402
    claude_project_permission_entries,
)


def _entries() -> list[str]:
    return claude_project_permission_entries(SCRIPTS, spill_available=False)


class WorktreePermissionEntryTests(unittest.TestCase):
    def test_the_worktree_root_is_covered_for_reading_and_writing(self) -> None:
        entries = _entries()

        for tool in ("Read", "Edit", "Write"):
            with self.subTest(tool=tool):
                self.assertIn(f"{tool}(.tao/{WORKTREE_DIRNAME}/**)", entries)

    def test_entering_a_worktree_is_covered(self) -> None:
        # `cd` into a fresh worktree is the first thing a task does there.
        self.assertIn(f"Bash(cd .tao/{WORKTREE_DIRNAME}/*)", _entries())

    def test_the_rules_name_the_directory_the_dispatcher_uses(self) -> None:
        """Written against `agent_worktree_identity`, not a repeated literal.

        The dispatcher decides where worktrees live. A rule that spells the
        name separately is a second definition, and the copy nobody edits is
        the one that stops matching.
        """

        self.assertEqual("worktrees", WORKTREE_DIRNAME)
        self.assertTrue(
            any(f".tao/{WORKTREE_DIRNAME}/" in entry for entry in _entries())
        )

    def test_the_rules_stay_portable(self) -> None:
        """Project settings are committed, so no rule may carry a home path.

        The module already states this for its git rules; a machine path here
        would be wrong for everyone but the person who ran the installer.
        """

        offenders = [
            entry
            for entry in _entries()
            if "/Users/" in entry or "/home/" in entry or entry.startswith("Bash(/")
        ]

        self.assertEqual([], offenders)

    def test_nothing_destructive_is_granted(self) -> None:
        # Removing a worktree deletes work. It stays a decision, not a default.
        for forbidden in ("worktree remove", "rm ", "rm -rf"):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(forbidden in entry for entry in _entries()),
                    forbidden,
                )


if __name__ == "__main__":
    unittest.main()
