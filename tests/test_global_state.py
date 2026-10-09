from __future__ import annotations

import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support import global_state


def _env_without_test_markers() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {global_state.STATE_HOME_ENV, global_state.UNDER_TEST_ENV}
    }


class UserStoreWriteGuardTest(unittest.TestCase):
    def test_a_test_case_is_refused_whatever_started_the_runner(self) -> None:
        # A test file run as a script, `python -c` or agent_unittest_result.py
        # leaves a plain __main__ with no unittest spec.
        plain_main = types.ModuleType("__main__")
        with (
            patch.dict(os.environ, _env_without_test_markers(), clear=True),
            patch.dict(sys.modules, {"__main__": plain_main}),
        ):
            self.assertIn("test run", global_state.user_store_write_error())

    def test_a_state_home_still_permits_the_write(self) -> None:
        with patch.dict(os.environ, {global_state.STATE_HOME_ENV: "/tmp/tao-test-state"}):
            self.assertEqual("", global_state.user_store_write_error())

    def test_a_process_outside_any_test_may_write(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from support.global_state import user_store_write_error as e; print(repr(e()))",
                str(ROOT / "scripts"),
            ],
            capture_output=True,
            text=True,
            env=_env_without_test_markers(),
            check=True,
        )
        self.assertEqual("''", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
