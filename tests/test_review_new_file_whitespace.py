import subprocess
import tempfile
import unittest
from pathlib import Path


class ReviewNewFileWhitespaceTests(unittest.TestCase):
    def test_staged_new_file_checks_trailing_blank_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            source = root / "LayoutPolicy.kt"
            source.write_text("internal fun inset() = 12\n\n")
            # An ordinary diff has no visibility into the untracked source.
            self.assertEqual(0, subprocess.run(["git", "diff", "--check"], cwd=root).returncode)
            subprocess.run(["git", "add", "LayoutPolicy.kt"], cwd=root, check=True)
            check = subprocess.run(["git", "diff", "--cached", "--check"], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(0, check.returncode)
            self.assertIn("new blank line at EOF", check.stdout)
            source.write_text("internal fun inset() = 12\n")
            subprocess.run(["git", "add", "LayoutPolicy.kt"], cwd=root, check=True)
            self.assertEqual(0, subprocess.run(["git", "diff", "--cached", "--check"], cwd=root).returncode)
