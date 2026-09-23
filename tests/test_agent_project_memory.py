"""Project memory never reaches a later task without exact review and freshness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_project_memory import (  # noqa: E402
    _capture as capture,
    _decide as decide,
    _recall as recall,
    recall_lines,
)


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        state_home = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(self.project / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.review_on = (date.today() + timedelta(days=30)).isoformat()

    def candidate(self, body: str = "Use the checked contract before changing the adapter.",
                  scope: str = "task") -> dict:
        return capture(self.project, body=body, source="reviewed design note",
                       scope=scope, review_on=self.review_on)

    def test_only_exact_approved_current_scope_is_recalled(self) -> None:
        pending = self.candidate("Pending advice")
        approved = self.candidate("Approved advice")
        with self.assertRaisesRegex(ValueError, "current pending digest"):
            decide(self.project, approved["id"], decision="approve", digest=pending["digest"])
        self.assertEqual([], recall(self.project, "task"))

        decide(self.project, approved["id"], decision="approve", digest=approved["digest"])
        self.assertEqual([approved["id"]], [item["id"] for item in recall(self.project, "task")])
        self.assertEqual([], recall(self.project, "review"))
        self.assertIn("reviewed reference only", recall_lines(self.project, "task")[0])
        self.assertEqual([], recall(self.project, "task", today=date.fromisoformat(self.review_on)))

        decide(self.project, approved["id"], decision="retire")
        self.assertEqual([], recall(self.project, "task"))

    def test_changed_content_and_unreviewed_status_fail_closed(self) -> None:
        record = self.candidate()
        path = next((self.project / "state-home/project-memory").glob(f'*/{record["id"]}.json'))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "approved"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual([], recall(self.project, "task"))

        payload["approved_at"] = "2026-01-01T00:00:00+00:00"
        payload["body"] = "Changed after review"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual([], recall(self.project, "task"))

    def test_recall_is_bounded_and_project_local(self) -> None:
        for number in range(5):
            record = self.candidate(f"Guidance {number}", scope="all")
            decide(self.project, record["id"], decision="approve", digest=record["digest"])
        lines = recall_lines(self.project, "task")
        self.assertEqual(4, len(lines))
        self.assertTrue(all("Guidance" in line for line in lines[1:]))
        self.assertEqual([], recall(self.project / "another-project", "task"))

    def test_symlink_store_is_refused(self) -> None:
        outside = self.project / "outside"
        outside.mkdir()
        state = self.project / "state-home"
        state.mkdir()
        (state / "project-memory").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.candidate()

    def test_linked_worktrees_recall_the_same_approved_record(self) -> None:
        repo = self.project / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
        sibling = self.project / "sibling"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "sibling",
                        str(sibling)], check=True)
        record = capture(repo, body="Shared across worktrees", source="reviewed note",
                         scope="task", review_on=self.review_on)
        decide(repo, record["id"], decision="approve", digest=record["digest"])
        self.assertEqual([record["id"]], [item["id"] for item in recall(sibling, "task")])


if __name__ == "__main__":
    unittest.main()
