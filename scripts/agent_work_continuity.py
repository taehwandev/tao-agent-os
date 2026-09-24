"""Link action runs to one work identity and carry valid local evidence.

Owner: start-time work continuation. Imports: registered local evidence readers
and the ordinary gate writer. Forbidden: authority copying, Git/external writes,
request classification. Callers/tests: agent-hook, test_agent_work_continuity.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_gate_evidence import gate_evidence_path_for_preflight, resync_gate_evidence_ledger
from agent_gate_reuse import GateEvidenceReuse
from agent_hook_runtime import write_json
from agent_runtime_session import runtime_session, same_runtime_session


class WorkContinuity:
    """The runtime declares the relationship; this owner checks its provenance."""

    def __init__(self, args: Any):
        self.args = args
        self.source_id = getattr(args, "continue_from", "")
        self.reason = getattr(args, "reuse_inputs", "")
        self.prior: dict[str, Any] = {}
        self.source: Path | None = None
        if not self.source_id:
            if self.reason:
                raise ValueError("--reuse-inputs requires --continue-from")
            return
        if not re.fullmatch(r"[0-9a-f]{32}", self.source_id):
            raise ValueError("--continue-from must name a registered run id")
        self.source = args.project.resolve() / ".tao" / "runs" / self.source_id / "preflight.json"
        if self.source.resolve() != self.source:
            raise ValueError("continuation source escapes its run directory")
        self.prior = self._read(self.source)
        registry = self._read(args.project / ".tao" / "run-registry.json")
        records = [run for run in registry.get("runs", []) if run.get("run_id") == self.source_id]
        if len(records) != 1 or records[0].get("state") not in {"completed", "running", "blocked", "interrupted"}:
            raise ValueError("continuation requires one retained, non-cancelled work record")
        # A resumed source records its resume generation beside the session;
        # it is still this session's work, so compare the session, not the dict.
        session = runtime_session()
        if (not same_runtime_session(
                    self.prior.get("runtime_session"), session,
                    resume_generation=int(records[0].get("resume_generation") or 0))
                or self.prior.get("project") != str(args.project.resolve())
                or self.prior.get("rules") != str(args.rules.resolve())
                or self.prior.get("agent_run_id") != self.source_id
                or records[0].get("evidence_name", "preflight.json") != "preflight.json"):
            raise ValueError("continuation project, rules, session or registered source differs")
        if getattr(args, "evidence", None) and args.evidence.resolve() == self.source:
            raise ValueError("continuation keeps source evidence immutable; omit --evidence")

    def apply(self, evidence: Path, *, retained_work: dict[str, Any] | None = None) -> list[str]:
        """Run after current action admission; old permissions are never imported."""
        from agent_hook_gate_records import _gate_progress, record_hook_gate_batch

        if not self.source_id and not re.fullmatch(r"[0-9a-f]{32}", evidence.parent.name):
            return []  # Compatibility evidence has no registered work identity.
        current = self._read(evidence)
        identity = (self.prior.get("work") or {}) if self.source_id else (retained_work or {})
        work_id = identity.get("id", self.source_id) or evidence.parent.name
        if not re.fullmatch(r"[0-9a-f]{32}", work_id):
            raise ValueError("invalid retained work identity")
        if self.source is not None and self._read(self.source) != self.prior:
            raise ValueError("continuation source changed during admission")
        previous_action = self.source_id or identity.get("previous_action", "")
        current["work"] = {"schema_version": 1, "id": work_id, "previous_action": previous_action}
        write_json(evidence, current)
        resync_gate_evidence_ledger(evidence, current)
        details = [f"work id: {work_id}"]
        if not self.source_id:
            return details
        details.append(f"continued action: {self.source_id}; current authority checked independently")
        if not self.reason.strip():
            return details + ["Local evidence retained as history; external inputs not attested, no gates carried."]
        reuse = GateEvidenceReuse(current)
        records = []
        for gate in current.get("route", {}).get("gates", []):
            if not reuse.supports(gate):
                continue  # Current authority/external/review gates never carry.
            try:
                source_id = _nearest_record(self.args.project, self.source_id, work_id, gate)
                records.extend(reuse.prepare([{"gate": gate, "reuse_from": source_id,
                                               "reuse_reason": self.reason}]))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                # Fixed categories never echo paths or arbitrary exception text.
                reason = "unreadable evidence" if isinstance(error, OSError) else "missing, stale or incompatible evidence"
                details.append(f"Local gate not carried: {gate}; {reason}; revalidate this gate.")
        if records:
            # Ordinary validation and atomic batch write still own the gate contract.
            record_hook_gate_batch(self.args, records)
        details.append(f"Carried local gates: {[record['gate'] for record in records]}")
        details.append(f"Remaining route gates: {_gate_progress(self.args)['remaining_gates']}")
        return details

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("oversized continuation evidence")
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("invalid continuation evidence")
        return result


def _nearest_record(project: Path, source_id: str, work_id: str, gate: str) -> str:
    """A missing gate can cross action boundaries; a failed/stale gate cannot."""
    seen = set()
    while source_id and len(seen) < 100:
        if source_id in seen or not re.fullmatch(r"[0-9a-f]{32}", source_id):
            raise ValueError("invalid work history")
        seen.add(source_id)
        path = project / ".tao" / "runs" / source_id / "preflight.json"
        if path.resolve() != path:
            raise ValueError("work history escapes its run directory")
        source = WorkContinuity._read(path)
        work = source.get("work") or {"id": source_id}
        if work.get("id") != work_id:
            raise ValueError("work identity changed in history")
        ledger_path = gate_evidence_path_for_preflight(path)
        if ledger_path.resolve() != ledger_path:
            raise ValueError("work ledger escapes its run directory")
        if not ledger_path.exists() and gate in (source.get("route") or {}).get("gates", []):
            raise ValueError("required action ledger is missing")
        ledger = WorkContinuity._read(ledger_path) if ledger_path.exists() else {}
        if any(entry.get("gate") == gate for entry in ledger.get("entries", [])):
            return source_id  # GateEvidenceReuse validates this exact latest record.
        source_id = work.get("previous_action", "")
    raise ValueError("no recorded evidence for this work")
