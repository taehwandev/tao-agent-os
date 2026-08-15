from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_run_registry import register_run, registered_run, transition_run
from agent_transfer_cancel import CANCEL_RECEIPT_NAME, cancel_transferred_run


class TransferredRunCancellationTests(unittest.TestCase):
    def test_completed_same_request_linked_worktree_cancels_clean_source(self) -> None:
        with self.fixture() as fixture:
            code, output = fixture.cancel()

            self.assertEqual(0, code, output)

            source = registered_run(
                fixture.source,
                fixture.source_evidence,
                run_id=fixture.source_run_id,
            )
            replacement = registered_run(
                fixture.replacement,
                fixture.replacement_evidence,
                run_id=fixture.replacement_run_id,
            )
            receipt = json.loads(
                (fixture.source_evidence.parent / CANCEL_RECEIPT_NAME).read_text(
                    encoding="utf-8"
                )
            )

        self.assertIn("SUCCESS cancel", output)
        self.assertEqual("cancelled", source["state"])
        self.assertEqual("completed", replacement["state"])
        self.assertEqual(
            {
                "created_at",
                "reason",
                "replacement_run_id",
                "request_fingerprint",
                "schema_version",
                "source_run_id",
                "status",
            },
            set(receipt),
        )

    def test_dirty_source_fails_without_settling_either_run(self) -> None:
        with self.fixture() as fixture:
            (fixture.source / "untracked.txt").write_text("owned work\n", encoding="utf-8")
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)
            replacement = registered_run(
                fixture.replacement, fixture.replacement_evidence
            )

        self.assertEqual(1, code)
        self.assertIn("source checkout has tracked or untracked changes", output)
        self.assertEqual("running", source["state"])
        self.assertEqual("completed", replacement["state"])

    def test_incomplete_replacement_fails_without_cancelling_source(self) -> None:
        with self.fixture(complete_replacement=False) as fixture:
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("replacement run has not completed successfully", output)
        self.assertEqual("running", source["state"])

    def test_different_request_fails_without_cancelling_source(self) -> None:
        with self.fixture(replacement_request="different request") as fixture:
            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("source and replacement requests do not match", output)
        self.assertEqual("running", source["state"])

    def test_unrelated_repository_fails_without_cancelling_source(self) -> None:
        with self.fixture() as fixture:
            unrelated = fixture.root / "unrelated"
            unrelated.mkdir()
            fixture.git("init", str(unrelated), cwd=fixture.root)
            (unrelated / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            fixture.git("config", "user.email", "test@example.com", cwd=unrelated)
            fixture.git("config", "user.name", "Test User", cwd=unrelated)
            fixture.git("add", ".gitignore", cwd=unrelated)
            fixture.git("commit", "-m", "base", cwd=unrelated)
            fixture.replacement_project_in_preflight(unrelated)

            code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("replacement project must be a linked Git worktree", output)
        self.assertIn("source and replacement must share one Git common directory", output)
        self.assertEqual("running", source["state"])

    def test_transition_race_removes_uncommitted_receipt(self) -> None:
        with self.fixture() as fixture:
            receipt_path = fixture.source_evidence.parent / CANCEL_RECEIPT_NAME
            with patch("agent_transfer_cancel.cancel_run", return_value=None):
                code, output = fixture.cancel()
            source = registered_run(fixture.source, fixture.source_evidence)

        self.assertEqual(1, code)
        self.assertIn("source run changed before the cancellation transition", output)
        self.assertFalse(receipt_path.exists())
        self.assertEqual("running", source["state"])

    @staticmethod
    def fixture(
        *,
        complete_replacement: bool = True,
        replacement_request: str = "same request",
    ) -> "TransferFixture":
        return TransferFixture(complete_replacement, replacement_request)


class TransferFixture:
    def __init__(self, complete_replacement: bool, replacement_request: str):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.source = self.root / "source"
        self.replacement = self.root / "replacement"
        self.rules = self.root / "rules"
        self.source.mkdir()
        self.rules.mkdir()
        self.git("init", str(self.source), cwd=self.root)
        self.git("config", "user.email", "test@example.com", cwd=self.source)
        self.git("config", "user.name", "Test User", cwd=self.source)
        (self.source / "tracked.txt").write_text("base\n", encoding="utf-8")
        (self.source / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        self.git("add", "tracked.txt", ".gitignore", cwd=self.source)
        self.git("commit", "-m", "base", cwd=self.source)
        self.git(
            "worktree",
            "add",
            "-b",
            "transfer-test",
            str(self.replacement),
            "HEAD",
            cwd=self.source,
        )

        session = {"runtime": "codex", "session_id": "runtime-session-01"}
        route = {"command": "bugfix", "gates": []}
        source_intake = {"request": "same request", "request_classified": False}
        replacement_intake = {
            "request": replacement_request,
            "request_classified": False,
        }
        self.source_evidence = self.evidence(self.source)
        self.replacement_evidence = self.evidence(self.replacement)
        source_run = register_run(
            self.source, self.source_evidence, route, source_intake
        )
        replacement_run = register_run(
            self.replacement,
            self.replacement_evidence,
            route,
            replacement_intake,
        )
        self.source_run_id = str(source_run["run_id"])
        self.replacement_run_id = str(replacement_run["run_id"])
        self.write_preflight(
            self.source_evidence,
            self.source,
            source_intake,
            session,
            self.source_run_id,
        )
        self.write_preflight(
            self.replacement_evidence,
            self.replacement,
            replacement_intake,
            session,
            self.replacement_run_id,
        )
        if complete_replacement:
            transition_run(
                self.replacement,
                self.replacement_evidence,
                "completed",
                run_id=self.replacement_run_id,
            )

    def __enter__(self) -> "TransferFixture":
        return self

    def __exit__(self, *_args: object) -> None:
        self._temporary.cleanup()

    def cancel(self) -> tuple[int, str]:
        args = Namespace(
            project=self.source,
            rules=self.rules,
            evidence=self.source_evidence,
            replacement_evidence=self.replacement_evidence,
            output=None,
            repair_cycle=0,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            code = cancel_transferred_run(args)
        return code, output.getvalue()

    @staticmethod
    def evidence(project: Path) -> Path:
        path = project / ".tao" / "runs" / ("a" * 32) / "preflight.json"
        path.parent.mkdir(parents=True)
        return path

    def write_preflight(
        self,
        path: Path,
        project: Path,
        intake: dict,
        session: dict,
        run_id: str,
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "agent_run_id": run_id,
                    "project": str(project),
                    "rules": str(self.rules),
                    "request_intake": intake,
                    "runtime_session": session,
                    "route": {"command": "bugfix", "gates": []},
                }
            ),
            encoding="utf-8",
        )

    def replacement_project_in_preflight(self, project: Path) -> None:
        payload = json.loads(self.replacement_evidence.read_text(encoding="utf-8"))
        payload["project"] = str(project)
        self.replacement_evidence.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def git(*arguments: str, cwd: Path) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
