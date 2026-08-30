"""A protection has to leave the way to undo it open.

`setup-agent-hooks.py` is how a runtime is installed, repaired, and re-pointed
at its root. While the worktree policy is active it was classified `mutating`,
so it could not run against the protected checkout -- from anywhere, since any
command naming a path under that checkout resolves to it.

That happened: an installer run from a linked worktree wrote the worktree's own
path into `~/.tao/tao-root` and the three runtime bridges, and the command that
repairs them was refused. The gate had removed its own recovery path, and only a
`TAO_ALLOW_MAIN_CHECKOUT_EDIT=1` run by hand could restore it.

The installer joins the runtime control hooks: recognised by exact path next to
the gate module, the way `agent-hook.py` already is, so a script that merely
shares the name cannot claim the allowance.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claude_worktree_gate as worktree_gate  # noqa: E402

INSTALLER = SCRIPTS / "setup-agent-hooks.py"


def _kind(command: str) -> str:
    payload = {"tool_input": {"command": command}}
    _root, tokens, simple = worktree_gate.bash_invocation(payload, Path("/tmp"))
    return worktree_gate.bash_command_kind(tokens, simple)


class InstallerIsReachableTests(unittest.TestCase):
    def test_the_installer_is_runtime_control(self) -> None:
        self.assertEqual("bootstrap", _kind(f"{sys.executable} {INSTALLER}"))

    def test_its_arguments_do_not_change_that(self) -> None:
        # Repairing a bridge and installing into a project are the same tool.
        for arguments in ("--check", "--dry-run", "--target /tmp/proj", "--runtime claude"):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    "bootstrap", _kind(f"{sys.executable} {INSTALLER} {arguments}")
                )

    def test_a_look_alike_elsewhere_is_not_the_installer(self) -> None:
        """Recognised by exact path, never by name.

        A script an agent can write is not a script that may authorize itself,
        which is the rule the protected-checkout hardening already set.
        """

        self.assertEqual(
            "mutating", _kind(f"{sys.executable} /tmp/setup-agent-hooks.py")
        )

    def test_a_chained_command_does_not_inherit_the_allowance(self) -> None:
        # The allowance covers the installer, not whatever follows it.
        self.assertEqual(
            "mutating", _kind(f"{sys.executable} {INSTALLER} && rm -rf build")
        )

    def test_the_installer_exists_where_the_rule_looks(self) -> None:
        # A rule anchored to a path that moved would silently stop matching.
        self.assertTrue(INSTALLER.is_file(), INSTALLER)


if __name__ == "__main__":
    unittest.main()
