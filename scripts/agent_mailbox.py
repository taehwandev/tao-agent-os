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
from agent_runtime_session import resolve_runtime_evidence, runtime_session


class AgentMailbox:
    """Bind sends to exact active work and expose project-local one-time receives."""

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
        evidence = self._evidence(evidence_path)
        self._validate_source(evidence)
        selected_sender = sender or str(runtime_session().get("runtime") or "")
        if not selected_sender:
            raise RuntimeError("mailbox sender runtime is unavailable")
        return MailboxStore(self.project, evidence_path=evidence).enqueue(
            sender=selected_sender,
            recipient=recipient,
            kind=kind,
            body=body,
            ttl_seconds=ttl_seconds,
        )

    def receive(self, runtime: str, *, limit: int = 8) -> list[dict[str, object]]:
        return MailboxStore(self.project).consume(runtime, limit=limit)

    def status(self, runtime: str) -> dict[str, int | str]:
        return MailboxStore(self.project).status(runtime)

    def _evidence(self, provided: Path | None) -> Path:
        if provided is not None:
            return provided.expanduser().resolve()
        resolved = resolve_runtime_evidence(self.project)
        if resolved is None:
            raise RuntimeError(
                "no exact active Tao work is bound to this runtime session; run the normal Tao start flow first"
            )
        return resolved.resolve()

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
