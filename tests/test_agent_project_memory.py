"""Captured project memory is recalled at once, and corrected by replace, retire and expiry."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_project_memory import (  # noqa: E402
    _capture as capture,
    _digest,
    _main as main,
    _recall as recall,
    _retire as retire,
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
                  scope: str = "task", **extra: str) -> dict:
        return capture(self.project, body=body, source="design note",
                       scope=scope, review_on=self.review_on, **extra)

    def _path(self, record: dict) -> Path:
        return next((self.project / "state-home/project-memory").glob(f'*/{record["id"]}.json'))

    def test_capture_is_recalled_without_approval(self) -> None:
        record = self.candidate()
        self.assertEqual("active", record["status"])
        self.assertEqual([record["id"]], [item["id"] for item in recall(self.project, "task")])
        self.assertEqual([], recall(self.project, "review"))
        header = recall_lines(self.project, "task")[0]
        self.assertIn("agent-written reference", header)
        self.assertIn("current request, repo rules and source evidence prevail", header)

    def test_expired_and_retired_records_are_not_recalled(self) -> None:
        record = self.candidate()
        self.assertEqual([], recall(self.project, "task", today=date.fromisoformat(self.review_on)))
        retire(self.project, record["id"])
        self.assertEqual([], recall(self.project, "task"))

    def test_replace_retires_the_old_record(self) -> None:
        old = self.candidate("Old advice")
        new = self.candidate("Corrected advice", replaces=old["id"])
        self.assertEqual(old["id"], new["replaces"])
        self.assertEqual([new["id"]], [item["id"] for item in recall(self.project, "task")])
        stored = json.loads(self._path(old).read_text(encoding="utf-8"))
        self.assertEqual(("retired", new["id"]), (stored["status"], stored["replaced_by"]))

    def test_replacement_hides_the_old_record_even_before_its_retire_lands(self) -> None:
        old = self.candidate("Old advice")
        with mock.patch("agent_project_memory._retire"):
            new = self.candidate("Corrected advice", replaces=old["id"])
        self.assertEqual([new["id"]], [item["id"] for item in recall(self.project, "task")])

    def test_replacing_an_unknown_record_writes_nothing(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing or invalid"):
            self.candidate(replaces="0123456789abcdef")
        self.assertEqual([], recall(self.project, "task"))

    def test_records_from_the_former_review_step_stay_recallable(self) -> None:
        record = self.candidate()
        path = self._path(record)
        for status in ("pending", "approved"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["status"] = status
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(status=status):
                self.assertEqual([record["id"]], [item["id"] for item in recall(self.project, "task")])

    def test_approve_is_a_no_op_alias(self) -> None:
        record = self.candidate()
        before = self._path(record).read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(["--project", str(self.project), "approve", record["id"],
                                      "--digest", record["digest"]]))
        self.assertEqual(before, self._path(record).read_bytes())

    def test_changed_content_fails_closed(self) -> None:
        record = self.candidate()
        path = self._path(record)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["body"] = "Changed on disk"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual([], recall(self.project, "task"))
        payload["digest"] = _digest(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(1, len(recall(self.project, "task")))

    def test_recall_is_bounded_and_project_local(self) -> None:
        for number in range(5):
            self.candidate(f"Guidance {number}", scope="all")
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

    def test_linked_worktrees_recall_the_same_record(self) -> None:
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
        record = capture(repo, body="Shared across worktrees", source="note",
                         scope="task", review_on=self.review_on)
        self.assertEqual([record["id"]], [item["id"] for item in recall(sibling, "task")])


if __name__ == "__main__":
    unittest.main()
