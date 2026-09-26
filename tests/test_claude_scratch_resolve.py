"""`resolve_target` gives one answer for symlink loops on every Python.

Python 3.9 raises `RuntimeError` for a loop, 3.13+ strict raises
`OSError(ELOOP)`, and 3.13+ non-strict returns the loop path as if it were an
ordinary file. Each case below runs under the native interpreter and under both
simulated behaviours, and must produce the same result in all three.
"""

from __future__ import annotations

import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from claude_bash_syntax import resolve_target

_real_resolve = Path.resolve


def _is_loop(path: Path) -> bool:
    try:
        _real_resolve(path, strict=True)
    except RuntimeError:
        return True
    except OSError as error:
        return error.errno == errno.ELOOP
    return False


def _raising_resolve(self, strict=False):
    """Python 3.9: a loop raises in both modes."""
    if _is_loop(self):
        raise RuntimeError(f"Symlink loop from {str(self)!r}")
    return _real_resolve(self, strict=strict)


def _silent_resolve(self, strict=False):
    """Python 3.13+: strict raises ELOOP, non-strict hands the loop back."""
    if _is_loop(self):
        if strict:
            raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), str(self))
        return Path(os.path.abspath(self))  # targets sit under a resolved root
    return _real_resolve(self, strict=strict)


class ResolveTargetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = _real_resolve(Path(temp.name))
        (self.root / "existing.txt").write_text("x")
        (self.root / "dangling").symlink_to(self.root / "missing.txt")
        (self.root / "first").symlink_to(self.root / "second")
        (self.root / "second").symlink_to(self.root / "first")
        (self.root / "self").symlink_to(self.root / "self")

    def expectations(self):
        return {
            "existing.txt": self.root / "existing.txt",
            "new.txt": self.root / "new.txt",
            "dangling": self.root / "missing.txt",
            "first": None,
            "self": None,
            "first/child.txt": None,
        }

    def test_same_answer_under_every_interpreter_behaviour(self):
        for label, behaviour in (("native", None), ("raising", _raising_resolve),
                                 ("silent", _silent_resolve)):
            for name, expected in self.expectations().items():
                with self.subTest(behaviour=label, target=name):
                    target = self.root / name
                    if behaviour is None:
                        self.assertEqual(expected, resolve_target(target))
                    else:
                        with patch.object(Path, "resolve", behaviour):
                            self.assertEqual(expected, resolve_target(target))


if __name__ == "__main__":
    unittest.main()
