from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.stable_launcher import (
    ensure_stable_launcher,
    stable_launcher_path,
    stable_root_pointer_path,
)


class StableLauncherTests(unittest.TestCase):
    def test_launcher_resolves_the_dynamic_home_root_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_home:
            with patch.dict(os.environ, {"HOME": temporary_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                pointer = stable_root_pointer_path()
                expected_root = Path(temporary_home) / ".tao"

                self.assertEqual(expected_root / "bin" / "tao-hook", launcher)
                self.assertEqual(expected_root / "tao-root", pointer)

                pointer.write_text("/missing/tao-agent-os\n", encoding="utf-8")
                environment = dict(os.environ)
                environment["TAO_HOOK_SOFT_FAIL"] = "1"
                result = subprocess.run(
                    [str(launcher), "workflow", "validate"],
                    cwd=temporary_home,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("Tao Agent OS hook skipped", result.stderr)
        self.assertNotIn("NameError", result.stderr)


class SharedRootIsNotDowngradedTests(unittest.TestCase):
    """The pointer must not be aimed at a checkout that is about to vanish.

    Every runtime on the machine reads `~/.tao/tao-root`, so pointing it at a
    task worktree leaves the bridge dangling the moment that task is cleaned
    up -- and the repair then needs the tooling the pointer no longer finds.
    It happens by accident, because running the installer from a worktree is
    how you test it and the side effect is machine-wide and silent. It happened
    three times while this gate was being built, and twice the repair had to be
    done by hand.

    Refusing to install from a worktree outright was the first attempt and was
    wrong: developing Tao in a worktree against a throwaway home is ordinary,
    and the block broke it. The loss is narrower -- replacing a durable root
    that still exists with a disposable one -- so only that is refused.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.home = base / "home"
        (self.home / ".tao").mkdir(parents=True)
        self.durable = base / "tao-agent-os"
        (self.durable / ".tao").mkdir(parents=True)
        self.worktree = self.durable / ".tao" / "worktrees" / "abc123def4567890"
        self.worktree.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _install(self, root: Path) -> str:
        with patch("support.stable_launcher.Path.home", return_value=self.home):
            results = ensure_stable_launcher(root, dry_run=False)
        return str(results[0]["status"])

    def _point_at(self, target: Path) -> None:
        (self.home / ".tao" / "tao-root").write_text(f"{target}\n", encoding="utf-8")

    def test_a_durable_root_is_not_replaced_by_a_worktree(self) -> None:
        self._point_at(self.durable)

        self.assertEqual("blocked", self._install(self.worktree))
        # And the pointer is left as it was, not half-written.
        self.assertEqual(
            f"{self.durable}\n",
            (self.home / ".tao" / "tao-root").read_text(encoding="utf-8"),
        )

    def test_a_first_install_from_a_worktree_still_works(self) -> None:
        # Nothing to lose: developing Tao in a worktree against a throwaway
        # home is what the earlier, broader guard broke.
        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_repeating_the_same_worktree_target_is_not_a_downgrade(self) -> None:
        self._point_at(self.worktree)
        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_one_worktree_may_replace_another(self) -> None:
        # The pointer is already disposable; this loses nothing new.
        other = self.durable / ".tao" / "worktrees" / "0123456789abcdef"
        other.mkdir(parents=True)
        self._point_at(other)

        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_a_pointer_naming_a_vanished_checkout_is_replaceable(self) -> None:
        """A dangling pointer is the damage, not something worth preserving."""

        self._point_at(self.durable / ".tao" / "worktrees" / "deletedaaaaaaaaa")

        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_repointing_back_at_the_main_checkout_is_always_allowed(self) -> None:
        # This is the repair path; refusing it would recreate the deadlock.
        self._point_at(self.worktree)

        self.assertNotEqual("blocked", self._install(self.durable))
        # Resolved, because the installer writes a resolved path and the
        # temporary directory sits behind a symlink on macOS.
        self.assertEqual(
            self.durable.resolve(),
            Path((self.home / ".tao" / "tao-root").read_text(encoding="utf-8").strip()),
        )


if __name__ == "__main__":
    unittest.main()
