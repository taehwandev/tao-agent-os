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


if __name__ == "__main__":
    unittest.main()
