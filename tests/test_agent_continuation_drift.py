from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_continuation_drift import (
    capture_drift_state,
    required_docs_digest,
    verify_drift,
)
from agent_execution_capsule_state import doc_hash_record
from test_agent_continuation_packet import packet

RUN_ID = "0123456789abcdef" * 2
GUIDANCE = "guidance.md"


def workspace(directory: str) -> tuple[Path, Path]:
    """Build a project and a separate rules root outside Git.

    Keeping them separate is what makes a rules-only change distinguishable
    from a project-only change; a shared checkout reports one state for both.
    """

    project = Path(directory) / "project"
    rules = Path(directory) / "rules"
    (project / "src").mkdir(parents=True)
    rules.mkdir()
    (project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (rules / GUIDANCE).write_text("# guidance\n", encoding="utf-8")
    return project, rules


def doc_records(rules: Path) -> list[dict]:
    return [doc_hash_record(GUIDANCE, rules / GUIDANCE)]


def bound_packet(project: Path, rules: Path, records: list | None = None, **overrides) -> dict:
    if records is None:
        records = doc_records(rules)
    payload = packet(run_id=RUN_ID, drift=capture_drift_state(project, rules, required_docs_digest(records)))
    payload.update(overrides)
    return payload


def git_workspace(directory: str) -> Path:
    project = Path(directory)
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    (project / "module.py").write_text("value = 1\n", encoding="utf-8")
    run = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run([*run, "add", "-A"], cwd=project, check=True)
    subprocess.run([*run, "commit", "-qm", "first"], cwd=project, check=True)
    return project


class CleanStateTests(unittest.TestCase):
    def test_an_untouched_workspace_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            result = verify_drift(project, rules, bound_packet(project, rules), required_doc_records=doc_records(rules))

            self.assertEqual("clean", result["status"])
            self.assertEqual([], result["changed_signals"])

    def test_negative_control_identical_bytes_rewritten_are_not_drift(self) -> None:
        """The control: identity is content, never cache metadata.

        Treating a rewrite with the same bytes as drift would make ordinary
        editor behaviour look like tampering and would refuse every resume
        after a formatter no-op.
        """

        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)
            source = project / "src" / "module.py"
            content = source.read_text(encoding="utf-8")
            source.unlink()
            source.write_text(content, encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=doc_records(rules))

            self.assertEqual("clean", result["status"])


class WorktreeDriftTests(unittest.TestCase):
    def test_changed_project_bytes_refuse_the_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)
            (project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=doc_records(rules))

            self.assertEqual("drift_refused", result["status"])
            self.assertEqual("reconcile_required", result["phase"])
            self.assertIn("project_worktree", result["changed_signals"])

    def test_a_new_untracked_file_is_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)
            (project / "src" / "added.py").write_text("new\n", encoding="utf-8")

            self.assertEqual(
                "drift_refused",
                verify_drift(project, rules, payload, required_doc_records=doc_records(rules))["status"],
            )

    def test_a_deleted_file_is_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)
            (project / "src" / "module.py").unlink()

            self.assertEqual(
                "drift_refused",
                verify_drift(project, rules, payload, required_doc_records=doc_records(rules))["status"],
            )

    def test_changed_rules_bytes_are_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)
            (rules / "other.md").write_text("unrelated\n", encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=doc_records(rules))

            self.assertIn("rules_worktree", result["changed_signals"])
            self.assertNotIn("project_worktree", result["changed_signals"])


class HeadDriftTests(unittest.TestCase):
    def test_a_moved_head_refuses_the_resume_on_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = git_workspace(directory)
            payload = bound_packet(project, project, records=[])
            run = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            (project / "module.py").write_text("value = 2\n", encoding="utf-8")
            subprocess.run([*run, "commit", "-qam", "second"], cwd=project, check=True)

            result = verify_drift(project, project, payload, required_doc_records=[])

            self.assertEqual("drift_refused", result["status"])
            self.assertIn("head", result["changed_signals"])


class RequiredDocDriftTests(unittest.TestCase):
    def test_a_changed_required_doc_names_its_repo_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            recorded = doc_records(rules)
            payload = bound_packet(project, rules, records=recorded)
            (rules / GUIDANCE).write_text("# guidance, revised\n", encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=recorded)

            self.assertIn("required_docs", result["changed_signals"])
            self.assertEqual([GUIDANCE], result["affected_paths"])

    def test_there_is_no_empty_scope_exception(self) -> None:
        """A packet with no changed files still holds decisions made under the
        old guidance, so changed required docs refuse it just the same."""

        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            recorded = doc_records(rules)
            payload = bound_packet(project, rules, records=recorded)
            payload["work"]["changed_scope"] = []
            payload["work"]["verification"] = []
            (rules / GUIDANCE).write_text("# guidance, revised\n", encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=recorded)

            self.assertEqual("drift_refused", result["status"])
            self.assertEqual(["required_docs", "rules_worktree"], sorted(result["changed_signals"]))

    def test_a_required_doc_snapshot_from_another_run_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = bound_packet(project, rules)

            result = verify_drift(project, rules, payload, required_doc_records=[])

            self.assertIn("required_docs", result["changed_signals"])

    def test_the_digest_covers_order_and_content(self) -> None:
        first = {"path": "a.md", "size_bytes": 1, "sha256": "a" * 64}
        second = {"path": "b.md", "size_bytes": 2, "sha256": "b" * 64}
        self.assertNotEqual(required_docs_digest([first, second]), required_docs_digest([first]))
        self.assertEqual(required_docs_digest([first, second]), required_docs_digest([first, second]))


class PendingMutationTests(unittest.TestCase):
    def _pending(self, project: Path, rules: Path) -> dict:
        payload = bound_packet(project, rules)
        payload["checkpoint"]["mutation_pending"] = {
            "kind": "update",
            "paths": ["src/module.py"],
            "project": payload["drift"]["project"],
            "rules": payload["drift"]["rules"],
            "started_at": "2026-07-27T09:00:00+00:00",
        }
        return payload

    def test_untouched_bytes_leave_the_pending_record_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            result = verify_drift(
                project, rules, self._pending(project, rules), required_doc_records=doc_records(rules)
            )

            self.assertEqual("clean", result["status"])
            self.assertEqual("pending_clean", result["pending_state"])

    def test_changed_bytes_make_the_pending_record_reconcilable_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, rules = workspace(directory)
            payload = self._pending(project, rules)
            (project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            result = verify_drift(project, rules, payload, required_doc_records=doc_records(rules))

            self.assertEqual("drift_refused", result["status"])
            self.assertEqual("pending_changed", result["pending_state"])
            self.assertIn("pending_mutation", result["changed_signals"])


if __name__ == "__main__":
    unittest.main()
