"""Invalid invocations stay short; explicit help retains the complete CLI."""

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("agent_hook_cli_errors", ROOT / "scripts/agent-hook.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class HookCliErrorsTests(unittest.TestCase):
    def test_unknown_option_keeps_error_and_exit_code_without_usage_dump(self):
        with contextlib.redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            hook.build_parser().parse_args(["start", "--unknown-option"])
        self.assertEqual(2, error.exception.code)
        self.assertIn("--unknown-option", output.getvalue())
        self.assertIn("--help", output.getvalue())
        self.assertNotIn("usage:", output.getvalue())
        self.assertLessEqual(len(output.getvalue().splitlines()), 2)

    def test_invalid_review_scope_lists_every_valid_value(self):
        with contextlib.redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            hook.build_parser().parse_args(["review", "--review-scope", "paths"])
        self.assertEqual(2, error.exception.code)
        for scope in ("working-tree", "pathspec", "repo-hygiene", "local-config", "commit-range"):
            self.assertIn(scope, output.getvalue())

    def test_explicit_help_still_displays_all_options(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as result:
            hook.build_parser().parse_args(["--help"])
        self.assertEqual(0, result.exception.code)
        self.assertIn("--review-scope", output.getvalue())
        self.assertIn("--commit-ready", output.getvalue())
        self.assertIn("usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
