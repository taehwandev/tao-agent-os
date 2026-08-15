from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_state_lock import state_lock


class StateLockTests(unittest.TestCase):
    def test_hidden_state_path_uses_a_single_leading_dot_for_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)

            with state_lock(directory / ".state.lock"):
                self.assertTrue((directory / ".state.lock.lock").exists())

            self.assertFalse((directory / "..state.lock.lock").exists())

    def test_regular_state_path_keeps_hidden_lock_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)

            with state_lock(directory / "state.json"):
                self.assertTrue((directory / ".state.json.lock").exists())


if __name__ == "__main__":
    unittest.main()
