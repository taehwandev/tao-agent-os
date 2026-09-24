"""Parallel agents that share one runtime session id keep their own runs.

Claude Code subagents inherit the parent's session id, and each usually works
in its own linked worktree nested under the parent checkout's ``.tao``. These
tests interleave start (supersession), gate/edit-admission lookups and Stop
boundaries across those checkouts and assert that each run stays addressable
by its own project path.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_continuation_claim import stopped_session_matches
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_interruption import record_turn_boundary
from agent_run_registry import register_run, registry_path
from agent_runtime_session import (
    resolve_runtime_evidence,
    same_runtime_session,
    settle_superseded_session_runs,
)
from test_agent_runtime_session import unreadable_directory

SESSION = {"runtime": "claude", "session_id": "shared-parent-session"}
ROUTE = {"command": "task", "gates": ["verify"], "required_docs": [], "lifecycle_version": 2}
INTAKE = {"request": "parallel worker fixture", "request_classified": False}


def start_run(project: Path, session: dict[str, str] = SESSION) -> Path:
    """Register one run-local run the way `start` does and stamp its session."""

    evidence = project / ".tao" / "runs" / uuid.uuid4().hex / "preflight.json"
    evidence.parent.mkdir(parents=True)
    register_run(project, evidence, ROUTE, INTAKE)
    evidence.write_text(
        json.dumps(
            {
                "project": str(project.resolve()),
                "rules": str(project.resolve()),
                "route": ROUTE,
                "request_intake": INTAKE,
                "runtime_session": dict(session),
                "execution_snapshot": {
                    "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                    "route_fingerprint": route_fingerprint(ROUTE),
                    "request_fingerprint": request_fingerprint(INTAKE),
                    "required_docs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return evidence.resolve()


def states(project: Path) -> dict[str, str]:
    runs = json.loads(registry_path(project).read_text(encoding="utf-8"))["runs"]
    return {run["run_id"]: run["state"] for run in runs}


def run_id(evidence: Path) -> str:
    return evidence.parent.name


class ParallelSessionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.main = Path(self._directory.name) / "repo"
        self.main.mkdir()
        (self.main / ".git").mkdir()
        (self.main / "AGENTS.md").write_text("uses tao\n", encoding="utf-8")
        self.worktrees = {}
        for name in ("worker-a", "worker-b"):
            checkout = self.main / ".tao" / "worktrees" / name
            checkout.mkdir(parents=True)
            # A linked worktree marks its root with a `.git` file.
            (checkout / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            (checkout / "AGENTS.md").write_text("uses tao\n", encoding="utf-8")
            self.worktrees[name] = checkout

    def test_each_worktree_resolves_its_own_run_for_the_shared_session(self) -> None:
        a = start_run(self.worktrees["worker-a"])
        b = start_run(self.worktrees["worker-b"])
        parent = start_run(self.main)

        self.assertEqual(a, resolve_runtime_evidence(self.worktrees["worker-a"], SESSION))
        self.assertEqual(b, resolve_runtime_evidence(self.worktrees["worker-b"], SESSION))
        self.assertEqual(parent, resolve_runtime_evidence(self.main, SESSION))

    def test_start_in_one_worktree_never_supersedes_another_worktree(self) -> None:
        a_first = start_run(self.worktrees["worker-a"])
        b = start_run(self.worktrees["worker-b"])
        parent = start_run(self.main)
        a_second = start_run(self.worktrees["worker-a"])

        env = {"CLAUDE_CODE_SESSION_ID": SESSION["session_id"]}
        with patch.dict(os.environ, env, clear=True):
            settled = settle_superseded_session_runs(
                self.worktrees["worker-a"], keep_run_id=run_id(a_second)
            )

        self.assertEqual([run_id(a_first)], settled)
        self.assertEqual("running", states(self.worktrees["worker-b"])[run_id(b)])
        self.assertEqual("running", states(self.main)[run_id(parent)])
        self.assertEqual(a_second, resolve_runtime_evidence(self.worktrees["worker-a"], SESSION))
        self.assertEqual(b, resolve_runtime_evidence(self.worktrees["worker-b"], SESSION))

    def test_stop_in_one_checkout_leaves_other_worktree_runs_active(self) -> None:
        a = start_run(self.worktrees["worker-a"])
        b = start_run(self.worktrees["worker-b"])
        parent = start_run(self.main)

        # Interleave: worker A's gate lookup, the parent's Stop, worker B's
        # edit admission, worker A's Stop, then both lookups again.
        self.assertEqual(a, resolve_runtime_evidence(self.worktrees["worker-a"], SESSION))
        self.assertTrue(record_turn_boundary(self.main, "claude", SESSION["session_id"]))
        self.assertEqual("interrupted", states(self.main)[run_id(parent)])
        self.assertEqual(b, resolve_runtime_evidence(self.worktrees["worker-b"], SESSION))
        self.assertTrue(
            record_turn_boundary(self.worktrees["worker-a"], "claude", SESSION["session_id"])
        )

        self.assertEqual("interrupted", states(self.worktrees["worker-a"])[run_id(a)])
        self.assertEqual("running", states(self.worktrees["worker-b"])[run_id(b)])
        self.assertEqual(b, resolve_runtime_evidence(self.worktrees["worker-b"], SESSION))

    def test_same_checkout_stop_leaves_the_isolated_worker_run_active(self) -> None:
        parent = start_run(self.main)
        worker = self.main / ".tao" / "workers" / "0123456789abcdef" / "preflight.json"
        worker.parent.mkdir(parents=True)
        register_run(self.main, worker, ROUTE, INTAKE)
        worker.write_text(
            json.dumps({"project": str(self.main.resolve()), "route": ROUTE,
                        "runtime_session": dict(SESSION)}),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(record_turn_boundary(self.main, "claude", SESSION["session_id"]))
        self.assertEqual("interrupted", states(self.main)[run_id(parent)])
        with patch.dict(os.environ, {"TAO_WORKER_EVIDENCE": str(worker)}, clear=True):
            self.assertEqual(worker.resolve(), resolve_runtime_evidence(self.main, SESSION))

    def test_worker_checkout_churn_does_not_drop_the_parent_binding(self) -> None:
        # The parent checkout's `.tao` holds every linked worktree, so its scan
        # walked their whole source trees. A directory a parallel worker
        # creates or removes mid-walk (unreadable here, deterministically) made
        # the scan incomplete, and any active binding the scan could not
        # account for then denied the parent's own edit admission.
        parent = start_run(self.main)
        orphan = self.main / ".tao" / "runs" / uuid.uuid4().hex / "preflight.json"
        orphan.parent.mkdir(parents=True)
        register_run(self.main, orphan, ROUTE, INTAKE)  # evidence never written
        churn = self.worktrees["worker-a"] / "build" / "tmp"
        churn.mkdir(parents=True)

        with unreadable_directory(self, churn):
            self.assertEqual(parent, resolve_runtime_evidence(self.main, SESSION))

    def test_nested_checkout_evidence_is_never_a_parent_candidate(self) -> None:
        start_run(self.worktrees["worker-a"])
        parent = start_run(self.main)
        import agent_runtime_session

        scanned = agent_runtime_session._runtime_evidence_candidates(
            self.main.resolve(), {"preflight.json"}
        )
        self.assertEqual((parent,), scanned[0])
        self.assertTrue(scanned[2])
        self.assertEqual(parent, resolve_runtime_evidence(self.main, SESSION))

    def test_resumed_binding_is_still_the_same_session(self) -> None:
        resumed = dict(SESSION, resume_generation=1)
        self.assertTrue(same_runtime_session(resumed, SESSION))
        self.assertTrue(same_runtime_session(resumed, SESSION, resume_generation=1))
        self.assertFalse(same_runtime_session(resumed, SESSION, resume_generation=2))
        self.assertFalse(same_runtime_session(SESSION, dict(SESSION, session_id="other")))
        self.assertFalse(same_runtime_session(SESSION, {"runtime": "claude"}))
        binding = {"runtime_session": resumed, "route": ROUTE}
        run = {"state": "interrupted", "resume_generation": 1}
        with patch("agent_continuation_claim.runtime_session", return_value=dict(SESSION)):
            self.assertTrue(stopped_session_matches(run, binding))
            self.assertFalse(stopped_session_matches(dict(run, resume_generation=2), binding))


if __name__ == "__main__":
    unittest.main()
