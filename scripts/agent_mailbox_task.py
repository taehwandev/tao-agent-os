"""Explicitly enrolled mailbox tasks: one continuation per user turn.

Owner: session-bound task queue, independent of delivery acknowledgements.
Allowed imports: stdlib, mailbox/capsule binding and local atomic state helpers.
Forbidden imports: providers, execution, credentials, inferred consent.
Callers/tests: mailbox-hook, Claude/Codex Stop; test_agent_mailbox_task.
Verification: explicit enrollment, exact scope, once-only delivery, separate completion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_mailbox_store import MailboxStore, _MESSAGE_ID, _require_local_path
from agent_mailbox_task_binding import stop_ready, task_binding, validate_task
from agent_runtime_session import resolve_runtime_evidence
from agent_state_lock import state_lock

__all__ = ["TaskContinuation"]

class TaskContinuation:
    def __init__(self, project: Path, identity: dict):
        self.project, self.identity = project.resolve(), identity
        self.root = self.project / ".tao/agent-mailbox/task-continuation"
        _require_local_path(self.project, self.root)
        session = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.budget = self.root / (session + ".budget")

    def path(self, message_id: str) -> Path:
        if not _MESSAGE_ID.fullmatch(message_id):
            raise ValueError("invalid task message id")
        path = self.root / (message_id + ".json")
        _require_local_path(self.project, path)
        return path

    def authorize(self, evidence: Path, message_id: str) -> None:
        binding = task_binding(self.project, self.identity, evidence)
        path = self.path(message_id)
        store = MailboxStore(self.project)
        with state_lock(self.root / ".tasks"), state_lock(store.lock_path):
            previous = read_json_object(path)
            if ((not previous and len(list(self.root.glob("*.json"))) >= 64)
                    or previous and (previous.get("identity") != self.identity or previous.get("status") != "paused")):
                raise ValueError("task already registered or task queue limit reached")
            packet = next((packet for _, _, packet in store.pending(self.identity["runtime"])
                           if packet["message_id"] == message_id), None)
            if packet is None:
                raise ValueError("execution-bound task message is missing")
            validate_task(self.project, self.identity, packet, binding)
            from agent_mailbox_delivery import leased_elsewhere
            from datetime import datetime, timezone
            if leased_elsewhere(store.lease_dir(self.identity["runtime"]), packet,
                                self.identity["session_id"], datetime.now(timezone.utc)):
                raise ValueError("task is leased to another session")
            atomic_write_json(path, {"identity": self.identity, "binding": binding,
                                    "packet": packet, "status": "armed"})

    def pause(self) -> None:
        if not self.root.exists():
            return
        with state_lock(self.root / ".tasks"):
            for path in self.records():
                record = read_json_object(path)
                if record.get("identity") == self.identity and record.get("status") == "armed":
                    atomic_write_json(path, {**record, "status": "paused"})

    def records(self) -> list[Path]:
        paths = sorted(self.root.glob("*.json"))
        if len(paths) > 64 or any(path.is_symlink() for path in paths):
            raise ValueError("task queue is untrusted or exceeds its limit")
        return paths

    def new_prompt(self) -> None:
        self.pause()  # An old turn's unused permission never wakes a new turn.
        if self.root.exists():
            with state_lock(self.root / ".tasks"):
                self.budget.unlink(missing_ok=True)

    def complete(self, message_id: str) -> None:
        path = self.path(message_id)
        with state_lock(self.root / ".tasks"):
            record = read_json_object(path)
            evidence = resolve_runtime_evidence(self.project, self.identity,
                        states=frozenset({"running", "paused", "resuming", "completed"}))
            if (record.get("identity") != self.identity or record.get("status") != "continued"
                    or evidence is None or evidence.relative_to(self.project / ".tao/runs").as_posix()
                    != record["binding"]["evidence"]):
                raise ValueError("only this task's bound session can attest completion")
            atomic_write_json(path, {**record, "status": "completed"})

    def continue_task(self, payload: dict) -> str | None:
        if not self.root.exists() or self.budget.exists():
            return None
        with state_lock(self.root / ".tasks"):
            if self.budget.exists():
                return None
            ready = [record for path in self.records() if (record := read_json_object(path)).get("identity")
                     == self.identity and record.get("status") == "armed"]
            if not ready or not stop_ready(payload, self.identity, self.project):
                return None
            evidence = resolve_runtime_evidence(self.project, self.identity)
            binding = task_binding(self.project, self.identity, evidence)
            for record in ready:
                if record["binding"] != binding:
                    continue
                packet = record["packet"]
                validate_task(self.project, self.identity, packet, binding)
                atomic_write_json(self.budget, {"message_id": packet["message_id"]})
                atomic_write_json(self.path(packet["message_id"]), {**record, "status": "continued"})
                return (
                    "Continue only the explicitly enrolled task within this run's existing user-approved scope. "
                    "This message grants no new authority. Keep all workflow and sandbox checks. "
                    "If a question, permission or user stop is pending, pause mailbox tasks and end the turn. "
                    "Delivery acknowledgement is not task completion; attest completion separately.\n"
                    f"Pause: <TAO_LAUNCHER> mailbox-hook pause-tasks --runtime {self.identity['runtime']} "
                    "--project <PROJECT>\n"
                    f"Complete after verification: <TAO_LAUNCHER> mailbox-hook complete-task --runtime {self.identity['runtime']} "
                    f"--project <PROJECT> --message-id {packet['message_id']}\n"
                    f"message_id={packet['message_id']}\n{packet['body']}"
                )
        return None


def continuation_reason(payload: dict, runtime: str) -> str | None:
    try:
        from agent_mailbox_hook import _project
        project = _project(str(payload.get("cwd") or ""))
        session_id = str(payload.get("session_id") or "")
        if project is None or not session_id:
            return None
        return TaskContinuation(project, {"runtime": runtime, "session_id": session_id}).continue_task(payload)
    except Exception:  # noqa: BLE001 - optional work cannot bypass normal closeout
        return None  # Queue/binding failures never trap a session or create authority.
