"""Regression checks for baseline-aware Compose action review."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_review_structure import android_action_delta_failures


class AndroidActionDeltaTests(unittest.TestCase):
    baseline = "@Composable\nfun Screen() {\n    router.navigate(route)\n}"
    path = Path("feature/Screen.kt")

    def review(self, current, baseline=None, status="M", returncode=0, previous_path=None):
        commands = []

        def run_command(command, project):
            commands.append(command)
            return {"returncode": returncode, "stdout": baseline or self.baseline}

        metadata = {"status": status, "previous_path": previous_path}
        result = android_action_delta_failures(
            Path("."), self.path, current.splitlines(), metadata, run_command,
        )
        return result, commands

    def test_unmodified_violation_after_line_shift_is_warning(self):
        (failures, warnings), _ = self.review("// unrelated copy change\n" + self.baseline)
        self.assertEqual([], failures)
        self.assertEqual(1, len(warnings))
        self.assertIn(":4:", warnings[0])

    def test_added_violation_still_blocks(self):
        current = self.baseline.replace("\n}", "\n    router.navigate(otherRoute)\n}")
        (failures, warnings), _ = self.review(current)
        self.assertEqual(1, len(failures))
        self.assertEqual(1, len(warnings))

    def test_modified_violation_still_blocks(self):
        (failures, warnings), _ = self.review(self.baseline.replace("route)", "otherRoute)"))
        self.assertEqual(1, len(failures))
        self.assertEqual([], warnings)

    def test_new_file_still_blocks_and_never_reads_baseline(self):
        (failures, warnings), commands = self.review(self.baseline, status="A")
        self.assertEqual(1, len(failures))
        self.assertEqual([], warnings)
        self.assertEqual([], commands)

    def test_unavailable_baseline_fails_closed(self):
        (failures, warnings), _ = self.review(self.baseline, returncode=128)
        self.assertEqual(1, len(failures))
        self.assertEqual([], warnings)

    def test_renamed_file_reads_original_path(self):
        (failures, warnings), commands = self.review(self.baseline, status="R", previous_path="old/Screen.kt")
        self.assertEqual([], failures)
        self.assertEqual(1, len(warnings))
        self.assertEqual(["git", "show", "HEAD:old/Screen.kt"], commands[0])

    def test_new_violation_on_existing_line_still_blocks(self):
        baseline = self.baseline.replace("@Composable\n", "")
        (failures, warnings), _ = self.review(self.baseline, baseline=baseline)
        self.assertEqual(1, len(failures))
        self.assertEqual([], warnings)


if __name__ == "__main__":
    unittest.main()
