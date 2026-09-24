from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _structure(net_deletions: list[dict]) -> dict:
    return {
        "scope": "test scope",
        "checked_paths": [],
        "checked_path_count": 0,
        "net_deletions": net_deletions,
    }


GUIDE_REMOVAL = {"path": "guide.md", "additions": 1, "deletions": 100, "net": 99}


class RemovalNoticeOnEveryPathTests(unittest.TestCase):
    """A measured removal stays visible whatever the review outcome is."""

    def _verdict_details(self, failures: list[str]) -> tuple[list[str], dict]:
        from agent_review_hook import _review_verdict

        captured: dict = {}

        def finish(_name, ok, details, _output, _checks, _cycle, invocation_error=False):
            captured.update(ok=ok, invocation_error=invocation_error)
            captured["details"] = list(details)
            return 0 if ok else 1

        args = SimpleNamespace(output=None, repair_cycle=0, evidence=None, project=Path("."))
        _review_verdict(
            args,
            {},
            list(failures),
            _structure([GUIDE_REMOVAL]),
            "working-tree",
            finish,
            lambda: None,
        )
        return captured["details"], captured

    def test_vibeguard_needs_review_invocation_failure_keeps_the_notice(self):
        details, captured = self._verdict_details(["VibeGuard overall is Needs review"])
        self.assertTrue(captured["invocation_error"])
        self.assertIn("guide.md", "\n".join(details))
        self.assertIn("net -99", "\n".join(details))

    def test_structure_evidence_invocation_failure_keeps_the_notice(self):
        details, captured = self._verdict_details(
            ["structure review evidence is required: owner missing"]
        )
        self.assertTrue(captured["invocation_error"])
        self.assertIn("guide.md", "\n".join(details))

    def test_every_details_builder_includes_the_notice(self):
        from agent_review_hook import (
            review_failure_details,
            review_input_invocation_failure_details,
            review_success_details,
        )

        structure = _structure([GUIDE_REMOVAL])
        for details in (
            review_success_details(structure, "working-tree"),
            review_failure_details(["git diff --check failed"], structure, "working-tree"),
            review_input_invocation_failure_details(
                ["VibeGuard overall is Needs review"], structure, "working-tree"
            ),
        ):
            with self.subTest(first=details[0]):
                self.assertIn("net -99", "\n".join(details))


def _run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return {"returncode": result.returncode, "stdout": result.stdout,
            "stderr": result.stderr, "command": command, "cwd": str(cwd)}


def _repository(root: Path, files: dict[str, str]) -> None:
    _run(["git", "init", "-q"], root)
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    _run(["git", "add", "."], root)
    result = _run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                   "commit", "-qm", "baseline"], root)
    assert result["returncode"] == 0, result["stderr"]


def _structure_for(root: Path, calls: list | None = None) -> dict:
    from agent_review_structure import structure_review

    def run(command, cwd):
        if calls is not None:
            calls.append(command)
        return _run(command, cwd)

    return structure_review(root, 500, 120, run)


PROCEDURE = "# Deploy procedure\n" + "".join(
    f"Step {i}: run the recovery command number {i}\n" for i in range(99)
)


class MovedOrRemovedTests(unittest.TestCase):
    """The notice names the destination of moved content and what vanished otherwise."""

    def test_moved_content_names_its_destination(self):
        from agent_review_hook import net_deletion_details

        body = "".join(f"Guide paragraph line {i}\n" for i in range(100))
        for staged in (False, True):
            with self.subTest(staged=staged), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _repository(root, {"guide.md": body})
                (root / "guide.md").write_text("# Short guide\n", encoding="utf-8")
                (root / "details.md").write_text(body, encoding="utf-8")
                if staged:
                    _run(["git", "add", "details.md"], root)

                structure = _structure_for(root)

                finding = structure["net_deletions"][0]
                self.assertEqual("moved", finding["classification"])
                self.assertEqual(["details.md"], finding["moved_to"])
                notice = "\n".join(net_deletion_details(structure))
                self.assertIn("guide.md: net -99, moved to details.md", notice)
                self.assertIn("not a failure", notice)

    def test_stale_overwrite_shows_the_removed_heading(self):
        from agent_review_hook import net_deletion_details

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root, {"runbook.md": PROCEDURE, "other.md": "unrelated\n"})
            (root / "runbook.md").write_text("See the wiki.\n", encoding="utf-8")
            (root / "other.md").write_text("unrelated\nStep 3: something else entirely\n", encoding="utf-8")

            structure = _structure_for(root)

        finding = structure["net_deletions"][0]
        self.assertEqual("removed", finding["classification"])
        self.assertIn("# Deploy procedure", finding["sample_lines"])
        notice = "\n".join(net_deletion_details(structure))
        self.assertIn("runbook.md: net -99, content removed (not found elsewhere in this diff)", notice)
        self.assertIn("removed: # Deploy procedure", notice)
        self.assertEqual([], structure["failures"])

    def test_partial_move_keeps_unmatched_recovery_steps_visible(self):
        from agent_review_hook import net_deletion_details

        body = "".join(f"Recovery step {i}: restore checkpoint {i}\n" for i in range(100))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root, {"guide.md": body})
            (root / "guide.md").write_text("# Short guide\n", encoding="utf-8")
            (root / "details.md").write_text("".join(body.splitlines(keepends=True)[:80]))
            structure = _structure_for(root)

        finding = structure["net_deletions"][0]
        self.assertEqual("removed", finding["classification"])
        self.assertEqual(20, finding["unmatched_lines"])
        notice = "\n".join(net_deletion_details(structure))
        self.assertIn("20 unmatched lines", notice)
        self.assertIn("Recovery step 80", notice)

    def test_one_new_copy_does_not_account_for_repeated_removed_lines(self):
        body = "Execute the production rollback command\n" * 100
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root, {"guide.md": body})
            (root / "guide.md").write_text("# Short guide\n", encoding="utf-8")
            (root / "details.md").write_text("Execute the production rollback command\n")
            structure = _structure_for(root)

        finding = structure["net_deletions"][0]
        self.assertEqual("removed", finding["classification"])
        self.assertEqual(99, finding["unmatched_lines"])

    def test_truncated_diff_is_unavailable_instead_of_claiming_move(self):
        from unittest.mock import patch
        from agent_review_hook import net_deletion_details
        import agent_review_removals as removals

        body = "".join(f"Recovery step {i}: restore checkpoint {i}\n" for i in range(100))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root, {"guide.md": body})
            (root / "guide.md").write_text("# Short guide\n", encoding="utf-8")
            (root / "details.md").write_text(body)
            with patch.object(removals, "PER_FILE_BYTE_LIMIT", 200):
                structure = _structure_for(root)

        self.assertEqual("unavailable", structure["net_deletions"][0]["classification"])
        self.assertIn("review the diff", "\n".join(net_deletion_details(structure)))

    def test_samples_fall_back_to_the_first_removed_lines(self):
        from agent_review_removals import removal_samples

        lines = ["", "plain one", "plain two", "plain three", "plain four"]
        self.assertEqual(["plain one", "plain two", "plain three"], removal_samples(lines))
        self.assertEqual("[sensitive-looking content omitted]", removal_samples(["x" * 300])[0])

    def test_removed_value_samples_are_redacted_before_output_and_recording(self):
        from agent_review_removals import removal_samples

        samples = removal_samples([
            "API_TOKEN=dummy_value_for_test_only",
            "# Deploy procedure",
            "Step 1: restore checkpoint",
        ])
        self.assertEqual(["# Deploy procedure"], samples)
        fallback = removal_samples(["API_TOKEN=dummy_value_for_test_only"])
        self.assertEqual(["[sensitive-looking content omitted]"], fallback)
        self.assertNotIn("dummy_value_for_test_only", " ".join(fallback))

    def test_ordinary_edits_run_no_extra_diff_and_have_no_notice(self):
        from agent_review_hook import net_deletion_details

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root, {"guide.md": PROCEDURE})
            (root / "guide.md").write_text(PROCEDURE.replace("Step 4:", "Step four:"), encoding="utf-8")
            calls: list = []

            structure = _structure_for(root, calls)

        self.assertEqual([], structure["net_deletions"])
        self.assertEqual([], net_deletion_details(structure))
        self.assertFalse(any("-U0" in command for command in calls))


class NoticeBoundsTests(unittest.TestCase):
    def test_untracked_symlink_is_not_read_as_a_moved_destination(self):
        import agent_review_removals as removals

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.md"
            outside.write_text("private local reference\n")
            project = root / "project"
            project.mkdir()
            (project / "details.md").symlink_to(outside)
            budget = removals._Budget()
            added = {}
            removals._add_untracked_lines(
                added, project, {"details.md": {"untracked": True}}, budget
            )
        self.assertTrue(budget.truncated)
        self.assertEqual({}, added)

    def test_notice_is_capped_and_points_at_the_machine_report(self):
        from agent_review_removals import NOTICE_BYTE_LIMIT, removal_notice

        findings = [
            {"path": f"docs/long/path/file-{i}.md", "additions": 0, "deletions": 90, "net": 90,
             "classification": "removed", "sample_lines": ["# Heading " + "x" * 80] * 5}
            for i in range(40)
        ]
        notice = removal_notice(findings)
        self.assertLessEqual(sum(len(line) for line in notice), NOTICE_BYTE_LIMIT + 120)
        self.assertIn("more; all paths in structure_review.net_deletions", notice[-1])

    def test_diff_reading_stops_at_the_byte_budget(self):
        from unittest.mock import patch

        import agent_review_removals as removals

        diff = "diff --git a/big.md b/big.md\n--- a/big.md\n+++ b/big.md\n@@ -1,50 +0,0 @@\n"
        diff += "".join(f"-line number {i}\n" for i in range(50))
        with patch.object(removals, "PER_FILE_BYTE_LIMIT", 100):
            removed, _added = removals.parse_diff_lines(diff, removals._Budget())
        self.assertLess(len(removed["big.md"]), 50)
        self.assertGreater(len(removed["big.md"]), 0)

    def test_failed_diff_keeps_counts_without_a_classification_claim(self):
        from agent_review_removals import classify_net_deletions, removal_notice

        findings = [{"path": "guide.md", "additions": 1, "deletions": 100, "net": 99}]
        classify_net_deletions(
            findings, project=Path("."), run_command=lambda *_: {"returncode": 128, "stdout": ""},
            review_paths=None, review_commits=None, path_metadata={},
        )
        self.assertEqual("unavailable", findings[0]["classification"])
        self.assertIn("guide.md: net -99 (-100 +1)", "\n".join(removal_notice(findings)))


if __name__ == "__main__":
    unittest.main()
