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
from pathlib import Path, PurePosixPath

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


def _path_rule(entry: str) -> str:
    return entry.split("(", 1)[1].rsplit(")", 1)[0]


def _resolves_to(rule: str, *, project: Path, cwd: Path) -> PurePosixPath:
    """Where a settings path rule points, by Claude's own anchoring.

    A rule beginning with `/` is read from the directory holding the settings
    file -- the project root. Anything else is read from the working directory.
    Written out because the difference is invisible in the rule string, which is
    exactly why asserting the string told us nothing.
    """

    if rule.startswith("/"):
        return PurePosixPath(project) / rule.lstrip("/")
    return PurePosixPath(cwd) / rule


class WorktreePermissionEntryTests(unittest.TestCase):
    def test_the_worktree_root_is_covered_for_reading_and_writing(self) -> None:
        entries = _entries()

        for tool in ("Read", "Edit", "Write"):
            with self.subTest(tool=tool):
                self.assertIn(f"{tool}(/.tao/{WORKTREE_DIRNAME}/**)", entries)

    def test_the_rules_point_at_the_worktree_root_from_inside_a_worktree(self) -> None:
        """The anchoring, checked by where the rule lands -- not by its spelling.

        An agent working on a task is *inside* `<project>/.tao/worktrees/<hex>`,
        so that is the working directory these rules are read against. Written
        without the leading slash they ask for a second `.tao/worktrees` nested
        under the first, match nothing, and every path prompts again -- the
        failure the entries exist to end. The earlier test asserted the string
        was present, which both spellings satisfy.
        """

        project = PurePosixPath("/repo")
        inside = project / ".tao" / WORKTREE_DIRNAME / "0123456789abcdef"
        want = project / ".tao" / WORKTREE_DIRNAME / "**"

        for entry in _entries():
            if not entry.startswith(("Read(", "Edit(", "Write(")):
                continue
            with self.subTest(entry=entry):
                rule = _path_rule(entry)
                self.assertEqual(
                    want, _resolves_to(rule, project=project, cwd=Path(inside))
                )
                # And from the root, where the unanchored form also worked.
                self.assertEqual(
                    want, _resolves_to(rule, project=project, cwd=Path(project))
                )

    def test_entering_a_worktree_is_covered(self) -> None:
        # `cd` into a fresh worktree is the first thing a task does there.
        # A Bash rule matches command text, so it keeps the relative spelling.
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

    def test_no_branch_rule_reaches_a_deletion_or_a_rename(self) -> None:
        """`Bash(git -C * branch *)` approved `git branch -D main` too.

        The matcher's `*` is any remainder and cannot be given an exception, so
        a rule that ends there covers the destructive flags along with the
        listing ones -- and refs are shared by every worktree, so that is the
        protected checkout's history going without a prompt.
        """

        destructive = ("-D", "-M", "--delete", "-m", "--move")
        for entry in _entries():
            if " branch" not in entry:
                continue
            remainder = _path_rule(entry).split("branch", 1)[1].lstrip()
            if not remainder.endswith("*"):
                # No trailing wildcard: the rule is the whole command, and a
                # flag cannot follow it.
                continue
            literal = remainder[:-1]
            for flag in destructive:
                with self.subTest(entry=entry, flag=flag):
                    self.assertFalse(
                        flag.startswith(literal),
                        f"{entry} reaches `git branch {flag}`",
                    )

    def test_the_branch_rules_come_from_the_gate_classifier(self) -> None:
        """One list, so the rules cannot grant more than the gate reads."""

        from claude_bash_git import BRANCH_READ_ONLY_OPTIONS, git_command_kind

        granted = {
            _path_rule(entry).split("branch", 1)[1].strip().rstrip("*")
            for entry in _entries()
            if " branch" in entry
        } - {""}

        self.assertEqual(set(BRANCH_READ_ONLY_OPTIONS), granted)
        for option in granted:
            with self.subTest(option=option):
                self.assertEqual("read_only", git_command_kind(["git", "branch", option]))

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
