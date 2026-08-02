"""Behavioural tests for the dispatch-CLI isolation-derivation helpers.

These exercise ``workflow.py dispatch`` end to end through a subprocess so the
CLI's exit codes and stderr messages -- the contract callers actually depend on
-- are the thing under test, rather than an in-process helper return value. They
mirror ``scripts/workflow_dispatch_cli.py`` and were split out of
``test_workflow_dispatch.py`` to keep both files within the module size budget.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_worktree_identity import new_worktree_path
from agent_route_state import request_fingerprint


_RUNTIME_SESSION_ID = "workflow-dispatch-cli-session"


def _worker(worker_id: str, scope: list[str], **overrides: object) -> dict[str, object]:
    """Build a structurally complete worker so only the field under test varies.

    Dispatch now validates the delegation plan structurally before it drives an
    isolation decision, so a worker must carry every required field or the plan
    is rejected for reasons unrelated to the isolation behaviour being tested.
    """

    worker: dict[str, object] = {
        "id": worker_id,
        "role": f"{worker_id} role",
        "owned_scope": scope,
        "forbidden_scope": ["docs/*.md"],
        "contract": f"{worker_id} contract",
        "acceptance": [f"{worker_id} acceptance"],
        "verification": ["python3 -m unittest discover tests"],
    }
    worker.update(overrides)
    return worker


class _IsolationDerivationTestCase(unittest.TestCase):
    """Wire a plan's per-worker isolation into dispatch (Fix 1)."""

    _REQUEST = "기획변경 때 문서 정리가 누락되는 걸 막아줘"

    def _write_plan(self, project: Path, workers: list[dict[str, object]]) -> None:
        plan = {
            "schema_version": 1,
            "mode": "parallel",
            "workers": workers,
            "integration_review": {
                "owner": "lead agent",
                "contract_drift_check": "compare against route gate policy",
                "final_verification": ["python3 -m unittest discover tests"],
            },
        }
        tao_dir = project / ".tao"
        tao_dir.mkdir(parents=True, exist_ok=True)
        (tao_dir / "agent-delegation-plan.json").write_text(
            json.dumps(plan), encoding="utf-8"
        )

    def _dispatch(self, project: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        envelope = {
            "schema_version": 1,
            "request_fingerprint": request_fingerprint({"request": self._REQUEST}),
            "runtime_session_id": _RUNTIME_SESSION_ID,
            "mode": "work",
            "intent": "dispatch",
            "target_summary": "the workflow dispatch test target",
            "requested_effects": ["local_write"],
            "ambiguity": "resolved",
        }
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "workflow.py"),
                "dispatch",
                "feature",
                "--request",
                self._REQUEST,
                "--project",
                str(project),
                "--format",
                "json",
                "--intent-envelope",
                json.dumps(envelope),
                "--runtime-session-id",
                _RUNTIME_SESSION_ID,
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    def test_declared_worker_dispatches_isolated_without_require_flag(self) -> None:
        # This is the regression the review reproduced: a plan-declared isolated
        # worker used to dispatch with working_dir_kind=workspace and
        # worktree_path=None because dispatch never read the plan.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [
                    _worker("impl-a", ["scripts/shared.py"], isolation="worktree"),
                    _worker("impl-b", ["scripts/shared.py"], isolation="worktree"),
                ],
            )
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual("worktree", manifest["capability_profile"]["working_dir_kind"])
        self.assertIsNotNone(manifest["worktree_path"])
        self.assertTrue(manifest["isolation_required"])

    def test_shared_worker_stays_on_workspace_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [_worker("impl-a", ["scripts/foo.py"])],
            )
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual("workspace", manifest["capability_profile"]["working_dir_kind"])
        self.assertIsNone(manifest["worktree_path"])
        self.assertFalse(manifest["isolation_required"])

    def test_require_isolation_flag_still_forces_isolation_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            completed = self._dispatch(project, "--require-isolation")

        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual("worktree", manifest["capability_profile"]["working_dir_kind"])
        self.assertIsNotNone(manifest["worktree_path"])

    def test_declared_worker_is_not_downgraded_by_omitting_flag(self) -> None:
        # A worker the plan declares isolated is isolated regardless of the flag.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [_worker("impl-a", ["scripts/shared.py"], isolation="worktree")],
            )
            with_flag = self._dispatch(project, "--worker-id", "impl-a", "--require-isolation")
            without_flag = self._dispatch(project, "--worker-id", "impl-a")

        for completed in (with_flag, without_flag):
            self.assertEqual(0, completed.returncode, completed.stderr)
            manifest = json.loads(completed.stdout)
            self.assertEqual("worktree", manifest["capability_profile"]["working_dir_kind"])

    def test_unknown_worker_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [_worker("impl-a", ["scripts/foo.py"], isolation="worktree")],
            )
            completed = self._dispatch(project, "--worker-id", "typo")

        self.assertEqual(2, completed.returncode)
        self.assertIn("typo", completed.stderr)

    def test_active_plan_without_worker_id_fails_closed(self) -> None:
        # Finding 1 (a): an ACTIVE plan (workers declared) dispatched with no
        # --worker-id used to fall through to inline/workspace execution because
        # the plan was never read. It must now fail closed so the plan's promises
        # cannot be silently bypassed.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [
                    _worker("impl-a", ["scripts/foo.py"]),
                    _worker("impl-b", ["scripts/bar.py"]),
                ],
            )
            completed = self._dispatch(project)

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("--worker-id", completed.stderr)

    def test_structurally_invalid_plan_with_worker_id_raises(self) -> None:
        # Finding 1 (b): a structurally INVALID plan (two non-isolated workers
        # with overlapping owned_scope, which validation rejects) used to drive
        # dispatch anyway because worker isolation was resolved without ever
        # running validate_delegation_plan_structure. It must now be rejected and
        # the validation failures surfaced.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [
                    _worker("impl-a", ["scripts/shared.py"]),
                    _worker("impl-b", ["scripts/shared.py"]),
                ],
            )
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("structurally invalid", completed.stderr)
        self.assertIn("overlapping owned_scope", completed.stderr)

    def test_no_plan_file_honors_only_the_flag(self) -> None:
        # Finding 1 (c): with no plan file and no --worker-id, behaviour is
        # unchanged flag-only single-worker dispatch -- isolated with the flag,
        # workspace without it. A stray plan must never be required here.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            with_flag = self._dispatch(project, "--require-isolation")
            without_flag = self._dispatch(project)

        self.assertEqual(0, with_flag.returncode, with_flag.stderr)
        self.assertEqual(
            "worktree",
            json.loads(with_flag.stdout)["capability_profile"]["working_dir_kind"],
        )
        self.assertEqual(0, without_flag.returncode, without_flag.stderr)
        self.assertEqual(
            "workspace",
            json.loads(without_flag.stdout)["capability_profile"]["working_dir_kind"],
        )


class MalformedPlanFailClosedTests(_IsolationDerivationTestCase):
    """A plan *file* that exists is delegation intent and must fail closed.

    Regression for the defect where anything that was not a non-empty ``workers``
    list -- broken JSON, ``"workers": []``, a plan missing the ``workers`` key,
    or an explicit ``--delegation-plan`` path that does not exist -- silently
    degraded to flag-only inline/workspace dispatch (exit 0) instead of being
    rejected. Each case below previously returned exit 0 / workspace and must now
    exit 2, while a genuinely absent plan and a valid plan stay unchanged.
    """

    def _write_raw_plan(self, project: Path, content: str) -> None:
        """Write arbitrary bytes to the default plan path (bypasses schema helper)."""

        tao_dir = project / ".tao"
        tao_dir.mkdir(parents=True, exist_ok=True)
        (tao_dir / "agent-delegation-plan.json").write_text(content, encoding="utf-8")

    def test_broken_json_plan_without_worker_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_raw_plan(project, "{ this is not json")
            completed = self._dispatch(project)

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("not valid JSON", completed.stderr)

    def test_broken_json_plan_with_worker_id_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_raw_plan(project, "{ this is not json")
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("not valid JSON", completed.stderr)

    def test_empty_workers_list_without_worker_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_raw_plan(
                project,
                json.dumps(
                    {
                        "schema_version": 1,
                        "mode": "parallel",
                        "workers": [],
                        "integration_review": {
                            "owner": "lead agent",
                            "contract_drift_check": "compare against route gate policy",
                            "final_verification": ["python3 -m unittest discover tests"],
                        },
                    }
                ),
            )
            completed = self._dispatch(project)

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("at least one worker", completed.stderr)

    def test_plan_missing_workers_key_without_worker_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_raw_plan(
                project,
                json.dumps(
                    {
                        "schema_version": 1,
                        "mode": "parallel",
                        "integration_review": {
                            "owner": "lead agent",
                            "contract_drift_check": "compare against route gate policy",
                            "final_verification": ["python3 -m unittest discover tests"],
                        },
                    }
                ),
            )
            completed = self._dispatch(project)

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("at least one worker", completed.stderr)

    def test_explicit_missing_delegation_plan_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            missing = project / "nowhere" / "does-not-exist.json"
            completed = self._dispatch(project, "--delegation-plan", str(missing))

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("not found", completed.stderr)
        self.assertIn("does-not-exist.json", completed.stderr)

    def test_absent_default_plan_without_worker_id_stays_flag_only(self) -> None:
        # Guard against over-tightening: a genuinely absent plan is the no-plan
        # state (exit 0 / workspace without the flag, worktree with it), not an
        # error.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            without_flag = self._dispatch(project)
            with_flag = self._dispatch(project, "--require-isolation")

        self.assertEqual(0, without_flag.returncode, without_flag.stderr)
        self.assertEqual(
            "workspace",
            json.loads(without_flag.stdout)["capability_profile"]["working_dir_kind"],
        )
        self.assertEqual(0, with_flag.returncode, with_flag.stderr)
        self.assertEqual(
            "worktree",
            json.loads(with_flag.stdout)["capability_profile"]["working_dir_kind"],
        )

    def test_explicit_directory_delegation_plan_fails_closed_without_traceback(self) -> None:
        # Regression: an explicit --delegation-plan pointing at an existing
        # directory used to raise IsADirectoryError out of read_text (only
        # json.JSONDecodeError was caught), which workflow.py's `except
        # ValueError` missed -> raw traceback, exit 1. It must now flow through
        # the invalid_json marker into structural validation and exit 2 cleanly.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            plan_dir = project / "plan-as-directory"
            plan_dir.mkdir(parents=True, exist_ok=True)
            completed = self._dispatch(project, "--delegation-plan", str(plan_dir))

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("not valid JSON", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_default_directory_delegation_plan_fails_closed_without_traceback(self) -> None:
        # Same defect on the default path: a .tao/agent-delegation-plan.json that
        # is a directory used to crash read_delegation_plan with a raw OSError.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            plan_path = project / ".tao" / "agent-delegation-plan.json"
            plan_path.mkdir(parents=True, exist_ok=True)
            completed = self._dispatch(project)

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("not valid JSON", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_noncanonical_owned_scope_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [
                    _worker("impl-a", ["shared.py"]),
                    _worker("impl-b", ["scripts/../shared.py"]),
                ],
            )
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn("normalized repo-relative POSIX path or glob", completed.stderr)

    def test_valid_plan_with_declared_worker_still_isolates(self) -> None:
        # Guard against over-tightening: the fix must not break the happy path.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._write_plan(
                project,
                [_worker("impl-a", ["scripts/shared.py"], isolation="worktree")],
            )
            completed = self._dispatch(project, "--worker-id", "impl-a")

        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual("worktree", manifest["capability_profile"]["working_dir_kind"])
        self.assertTrue(manifest["isolation_required"])


class DispatchFinalizeCliTests(unittest.TestCase):
    def test_cli_preserves_unintegrated_result_then_cleans_after_lead_integration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
            (project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            for args in (
                ("init", "-q"),
                ("config", "user.email", "tests@example.invalid"),
                ("config", "user.name", "Tao Agent OS Tests"),
                ("add", "-A"),
                ("commit", "-qm", "initial"),
            ):
                subprocess.run(
                    ["git", *args],
                    cwd=project,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            baseline = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            worktree = new_worktree_path(project)
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            (worktree / "worker-only.txt").write_text("integrate me\n", encoding="utf-8")
            command = [
                sys.executable,
                str(ROOT / "scripts" / "workflow.py"),
                "dispatch-finalize",
                "--project",
                str(project),
                "--worktree",
                str(worktree),
                "--format",
                "json",
            ]

            refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(2, refused.returncode)
            self.assertIn("not integrated", refused.stderr)
            self.assertTrue((worktree / "worker-only.txt").exists())

            (project / "worker-only.txt").write_text("integrate me\n", encoding="utf-8")
            finalized = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

            self.assertEqual(0, finalized.returncode, finalized.stderr)
            self.assertEqual("finalized", json.loads(finalized.stdout)["status"])
            self.assertFalse(worktree.exists())
            self.assertEqual(
                baseline,
                subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    cwd=project,
                    check=True,
                    stdout=subprocess.PIPE,
                ).stdout,
            )
            self.assertFalse((project / ".tao" / "worktrees").exists())


if __name__ == "__main__":
    unittest.main()
