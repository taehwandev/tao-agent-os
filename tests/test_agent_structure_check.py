from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent-structure-check.py"


class StructurePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.git("init")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "baseline")
        (self.project / "src").mkdir()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.project, check=True,
                              capture_output=True, text=True).stdout

    def preview(self, *args):
        before = self.git("status", "--porcelain=v1", "--untracked-files=all")
        result = subprocess.run(
            ["python3", str(SCRIPT), "--project", str(self.project), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(before, self.git("status", "--porcelain=v1", "--untracked-files=all"))
        self.assertFalse((self.project / ".tao").exists())
        return result.returncode, json.loads(result.stdout)

    def test_catches_long_function_before_build(self):
        (self.project / "src" / "save.ts").write_text(
            "export function save() {\n" + "  doWork();\n" * 121 + "}\n")
        code, report = self.preview()
        self.assertEqual(code, 1)
        self.assertTrue(any("120" in failure for failure in report["failures"]))

    def test_catches_multiple_public_contracts(self):
        (self.project / "src" / "contracts.ts").write_text(
            "export interface Draft { id: string }\n"
            "export interface Options { enabled: boolean }\n")
        code, report = self.preview()
        self.assertEqual(code, 1)
        self.assertTrue(any("public/exported" in failure for failure in report["failures"]))

    def test_scope_is_explicit_and_success_is_not_review_approval(self):
        (self.project / "src" / "save.ts").write_text("export function save() { return 1; }\n")
        (self.project / "src" / "unrelated.ts").write_text(
            "export function other() {\n" + "  work();\n" * 121 + "}\n")
        code, report = self.preview("--review-path", "src/save.ts")
        self.assertEqual(code, 0)
        self.assertEqual(report["checked_paths"], ["src/save.ts"])
        self.assertIn("not behavior verification", report["scope"])

    def test_tracks_existing_baseline_instead_of_rejecting_unchanged_debt(self):
        path = self.project / "src" / "legacy.ts"
        path.write_text("export function legacy() {\n" + "  work();\n" * 121 + "}\n")
        self.git("add", "src/legacy.ts")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-m", "legacy")
        path.write_text(path.read_text() + "// Clarify existing behavior.\n")
        code, report = self.preview()
        self.assertEqual(code, 0)
        self.assertTrue(report["warnings"])

    def test_invalid_project_does_not_report_success(self):
        result = subprocess.run(["python3", str(SCRIPT), "--project",
                                 str(self.project / "missing")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
