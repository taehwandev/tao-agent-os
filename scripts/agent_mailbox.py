"""Validate and exchange local cross-runtime handoffs without invoking a model."""

from __future__ import annotations

import json
from pathlib import Path

from agent_execution_capsule import (
    capsule_path_for_evidence,
    read_execution_capsule,
    validate_execution_capsule,
)
from agent_mailbox_store import MailboxStore
from agent_mailbox_reference import ReferenceMailboxStore
from agent_runtime_session import runtime_session


class AgentMailbox:
    """Exchange references, or explicitly bind a handoff to execution evidence."""

    def __init__(self, project: Path, rules: Path) -> None:
        self.project = project.expanduser().resolve()
        self.rules = rules.expanduser().resolve()

    def send(
        self,
        *,
        recipient: str,
        kind: str,
        body: str,
        ttl_seconds: int = 24 * 60 * 60,
        evidence_path: Path | None = None,
        sender: str = "",
    ) -> dict[str, object]:
        if evidence_path is not None:
            evidence = evidence_path.expanduser().resolve()
            self._validate_source(evidence)
            store = MailboxStore(self.project, evidence_path=evidence)
        else:
            store = ReferenceMailboxStore(self.project)
        selected_sender = sender or str(runtime_session().get("runtime") or "")
        if not selected_sender:
            raise RuntimeError("mailbox sender runtime is unavailable")
        return store.enqueue(
            sender=selected_sender,
            recipient=recipient,
            kind=kind,
            body=body,
            ttl_seconds=ttl_seconds,
        )

    def receive(self, runtime: str, *, limit: int = 8) -> list[dict[str, object]]:
        packets = MailboxStore(self.project).consume(runtime, limit=limit)
        if len(packets) < limit:
            packets.extend(ReferenceMailboxStore(self.project).consume(runtime, limit=limit - len(packets)))
        return packets

    def status(self, runtime: str) -> dict[str, int | str]:
        result = MailboxStore(self.project).status(runtime)
        reference = ReferenceMailboxStore(self.project).status(runtime)
        for key in ("pending", "expired", "acked", "rejected"):
            result[key] += reference[key]
        return result

    def _validate_source(self, evidence: Path) -> None:
        if not self.project.is_dir():
            raise ValueError(f"project directory does not exist: {self.project}")
        if not all((self.rules / marker).exists() for marker in ("AGENTS.md", "index.md", "scripts/workflow.py")):
            raise ValueError(f"rules root is not a usable Tao Agent OS root: {self.rules}")
        if not evidence.is_file():
            raise ValueError("preflight evidence does not exist")
        try:
            preflight = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("preflight evidence is missing or malformed") from error
        route = preflight.get("route") if isinstance(preflight, dict) else None
        if not isinstance(route, dict):
            raise ValueError("preflight evidence does not contain a route manifest")
        capsule_path = capsule_path_for_evidence(evidence)
        failures = validate_execution_capsule(
            read_execution_capsule(capsule_path),
            project=self.project,
            rules=self.rules,
            evidence_path=evidence,
            route=route,
        )
        if failures:
            detail = "; ".join(str(reason) for reason in failures[:3])
            raise RuntimeError(
                f"execution capsule is not ready; run parent handoff before sending ({detail})"
            )
