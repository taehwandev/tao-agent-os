from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from test_agent_continuation_checkpoint import initialize_git
from agent_execution_capsule import refresh_execution_capsule
from agent_gate_evidence import record_gate_evidence
from agent_mailbox_delivery import SessionDelivery
from agent_mailbox_store import MailboxStore
from agent_mailbox_task import TaskContinuation, continuation_reason
from agent_run_registry import register_run, transition_run, registry_path, evidence_binding_key
import agent_mailbox_hook as hook
import codex_stop_gate
import claude_stop_gate


class MailboxTaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project, self.rules = self.root / "project", self.root / "rules"
        self.project.mkdir()
        self.rules.mkdir()
        (self.project / "AGENTS.md").write_text("uses tao\n")
        (self.rules / "guide.md").write_text("guidance\n")
        initialize_git(self.project)
        initialize_git(self.rules)
        environment = patch.dict(os.environ, {"TAO_STATE_HOME": str(self.root / "state"),
                                 "CODEX_THREAD_ID": "task-session", "CLAUDE_CODE_SESSION_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.identity = {"runtime": "codex", "session_id": "task-session"}
        self.route = {"command": "task", "gates": ["request intake"], "required_docs": [], "lifecycle_version": 2,
                      "request_classification": {"intent_envelope": {"schema_valid": True,
                      "envelope_present": True, "failures": [], "effective_effect": "local_write"}}}
        self.intake = {"request": "implement this bounded local task", "request_classified": False}
        self.run = register_run(self.project, self.project / ".tao/preflight.json", self.route, self.intake)
        self.evidence = self.project / ".tao/runs" / self.run["run_id"] / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        registry = json.loads(registry_path(self.project).read_text())
        registry["runs"][0]["evidence_key"] = evidence_binding_key(self.project, self.evidence)
        registry_path(self.project).write_text(json.dumps(registry))
        self.preflight = {"project": str(self.project), "rules": str(self.rules), "route": self.route,
                          "request_intake": self.intake, "runtime_session": self.identity}
        self.refresh()
        self.store = MailboxStore(self.project, evidence_path=self.evidence)
        self.tasks = TaskContinuation(self.project, self.identity)
        self.payload = {"cwd": str(self.project), "session_id": "task-session"}

    def refresh(self):
        self.evidence.write_text(json.dumps(self.preflight))
        record_gate_evidence(evidence_path=self.evidence, preflight=self.preflight,
                             gate="request intake", status="SUCCESS", evidence="explicit scoped test authorization")
        refresh_execution_capsule(self.project, self.rules, self.evidence, self.route)

    def send(self, kind="task", body="Finish the already approved local subtask."):
        return self.store.enqueue(sender="codex", recipient="codex", kind=kind, body=body, ttl_seconds=600)

    def arm(self):
        packet = self.send()
        self.tasks.authorize(self.evidence, packet["message_id"])
        return packet

    def test_default_off_and_reference_task_kind_never_supplies_authority(self):
        self.send()
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        self.assertFalse(self.tasks.root.exists())
        from agent_mailbox_reference import ReferenceMailboxStore
        packet = ReferenceMailboxStore(self.project).enqueue(sender="claude", recipient="codex",
                    kind="task", body="Unbound request", ttl_seconds=600)
        with self.assertRaisesRegex(ValueError, "missing"):
            self.tasks.authorize(self.evidence, packet["message_id"])

    def test_one_registered_task_once_and_delivery_ack_is_not_completion(self):
        packet = self.arm()
        delivery = SessionDelivery(self.project, "codex", "task-session")
        delivery.claim()
        delivery.mark_delivered([packet["message_id"]])
        delivery.acknowledge()
        self.assertEqual(0, self.store.status("codex")["pending"])
        reason = continuation_reason(self.payload, "codex")
        self.assertIn(packet["body"], reason)
        self.assertIn("no new authority", reason)
        self.assertEqual("continued", json.loads(self.tasks.path(packet["message_id"]).read_text())["status"])
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        self.tasks.complete(packet["message_id"])
        self.assertEqual("completed", json.loads(self.tasks.path(packet["message_id"]).read_text())["status"])

    def test_read_only_and_read_floor_routes_cannot_register(self):
        packet = self.send()
        for update in ({"execution_mode": {"read_only": True}}, {"route": {**self.route, "command": "analysis"}}):
            with self.subTest(update=update):
                with patch.dict(self.preflight, update):
                    self.refresh()
                    with self.assertRaisesRegex(ValueError, "writable scope"):
                        self.tasks.authorize(self.evidence, packet["message_id"])

    def test_invalid_capsule_and_workspace_drift_never_continue(self):
        self.arm()
        (self.project / "AGENTS.md").write_text("changed rules\n")
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        self.assertFalse(self.tasks.budget.exists())

    def test_foreign_session_cannot_register_continue_or_complete(self):
        packet = self.arm()
        foreign = TaskContinuation(self.project, {"runtime": "codex", "session_id": "other"})
        with self.assertRaises(ValueError):
            foreign.authorize(self.evidence, packet["message_id"])
        self.assertIsNone(continuation_reason({**self.payload, "session_id": "other"}, "codex"))
        with self.assertRaises(ValueError):
            foreign.complete(packet["message_id"])

    def test_opinion_and_review_messages_cannot_register(self):
        for kind in ("opinion", "review"):
            packet = self.send(kind=kind)
            with self.assertRaisesRegex(ValueError, "task"):
                self.tasks.authorize(self.evidence, packet["message_id"])

    def test_operator_question_user_stop_and_repeated_stop_do_not_continue(self):
        self.arm()
        for extra in ({"stop_hook_active": True}, {"user_interrupted": True}, {"interrupted": True},
                      {"approval_pending": True}, {"waiting_for_approval": True}, {"stop_reason": "user_stop"},
                      {"stop_reason": "unknown_reason"}):
            with self.subTest(extra=extra):
                self.assertIsNone(continuation_reason({**self.payload, **extra}, "codex"))
        requests = self.root / "state/codex-operator-review"
        requests.mkdir(parents=True)
        (requests / "pending.json").write_text(json.dumps({"session_id": "task-session", "status": "pending",
                                                          "expires_at": datetime.now(timezone.utc).timestamp() + 600}))
        self.assertIsNone(continuation_reason(self.payload, "codex"))

    def test_pause_and_next_prompt_cancel_unused_turn_permission(self):
        packet = self.arm()
        self.tasks.pause()
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        self.tasks.authorize(self.evidence, packet["message_id"])
        with redirect_stdout(io.StringIO()):
            hook.deliver(self.payload, "codex")
        self.assertIsNone(continuation_reason(self.payload, "codex"))

    def test_completed_run_or_expired_task_never_wakes(self):
        packet = self.arm()
        record = json.loads(self.tasks.path(packet["message_id"]).read_text())
        record["packet"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        record["packet"]["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        self.tasks.path(packet["message_id"]).write_text(json.dumps(record))
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        transition_run(self.project, self.evidence, "completed")
        self.assertIsNone(continuation_reason(self.payload, "codex"))

    def test_competing_stops_continue_only_one_task_total(self):
        self.arm()
        self.arm()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: continuation_reason(self.payload, "codex"), range(2)))
        self.assertEqual(1, sum(reason is not None for reason in results))

    def test_changed_source_request_is_outside_the_registered_scope(self):
        packet = self.arm()
        self.intake["request"] = "publish an unrelated service"
        self.refresh()
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        with self.assertRaises(ValueError):
            self.tasks.authorize(self.evidence, packet["message_id"])

    def test_stop_adapters_emit_one_block_for_the_registered_task(self):
        self.arm()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, codex_stop_gate.decide(self.payload))
        self.assertEqual("block", json.loads(output.getvalue())["decision"])
        self.assertIn("explicitly enrolled task", json.loads(output.getvalue())["reason"])
        with patch("agent_mailbox_task.continuation_reason", return_value="authorized mailbox task"), \
                redirect_stdout(output := io.StringIO()):
            self.assertEqual(0, claude_stop_gate.decide(self.payload))
        self.assertEqual({"decision": "block", "reason": "authorized mailbox task"}, json.loads(output.getvalue()))

    def test_claude_bound_task_uses_the_same_real_validation(self):
        self.identity["runtime"] = "claude"
        self.refresh()
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "task-session", "CODEX_THREAD_ID": ""}):
            tasks = TaskContinuation(self.project, self.identity)
            packet = self.store.enqueue(sender="claude", recipient="claude", kind="task",
                                        body="Finish the approved local task.", ttl_seconds=600)
            tasks.authorize(self.evidence, packet["message_id"])
            with redirect_stdout(output := io.StringIO()):
                claude_stop_gate.decide(self.payload)
            self.assertEqual("block", json.loads(output.getvalue())["decision"])
            self.assertIn(packet["message_id"], json.loads(output.getvalue())["reason"])
            self.assertIsNone(continuation_reason({**self.payload, "stop_hook_active": True}, "claude"))

    def test_cli_records_only_bound_decisions_and_rejects_missing_identity(self):
        packet = self.send()
        args = ["mailbox-hook", "authorize-task", "--runtime", "codex", "--project", str(self.project),
                "--evidence", str(self.evidence), "--message-id", packet["message_id"]]
        with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(0, hook.main())
        with patch.object(sys, "argv", ["mailbox-hook", "pause-tasks", "--runtime", "codex", "--project", str(self.project)]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(0, hook.main())
        self.assertIsNone(continuation_reason(self.payload, "codex"))
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "", "CLAUDE_CODE_SESSION_ID": ""}), \
                patch.object(sys, "argv", args), patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                hook.main()

    def test_optional_queue_failure_does_not_suppress_prompt_mailbox(self):
        packet = self.send()
        with patch.object(TaskContinuation, "new_prompt", side_effect=OSError("unavailable")), \
                redirect_stdout(output := io.StringIO()):
            hook.deliver(self.payload, "codex")
        self.assertIn(packet["message_id"], output.getvalue())

    def test_lease_on_another_session_and_unresolved_checkpoint_prevent_work(self):
        packet = self.send()
        SessionDelivery(self.project, "codex", "other").claim()
        with self.assertRaisesRegex(ValueError, "leased"):
            self.tasks.authorize(self.evidence, packet["message_id"])
        # A valid enrollment still yields to a recorded blocker/mutation.
        packet = self.arm()
        with patch("agent_continuation_store.read_continuation_packet", return_value={"packet": {"phase": "blocked"}}):
            self.assertIsNone(continuation_reason(self.payload, "codex"))


if __name__ == "__main__":
    unittest.main()
