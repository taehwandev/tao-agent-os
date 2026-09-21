"""Validate references to prior local gate evidence without granting authority."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import git_state
from agent_gate_evidence import gate_evidence_path_for_preflight, merge_gate_evidence_from_ledger


_LOCAL_GATES = frozenset({"source docs", "documentation", "documentation impact", "tests", "package", "smoke"})


class GateEvidenceReuse:
    """Owner: gate reference validation; no authorization or external operations.

    Imports: local ledger and Git snapshot readers. Caller: gate hook writer.
    Verification: test_agent_gate_reuse, including stale and foreign references.
    """

    def __init__(self, preflight: dict[str, Any]):
        self.preflight = preflight
        self.project = Path(preflight.get("project") or ".").resolve()
        self.rules = Path(preflight.get("rules") or ".").resolve()
        self.snapshot: dict[str, Any] | None = None

    def prepare(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for record in records:
            if "reuse_from" in record:
                record = self._resolve(record)
            record = dict(record)
            # Callers cannot supply a trusted snapshot through the CLI.
            record.pop("reuse_snapshot", None)
            if record.get("gate") in _LOCAL_GATES and record.get("status", "SUCCESS") == "SUCCESS":
                snapshot = self._snapshot()
                if snapshot is not None:
                    record["reuse_snapshot"] = snapshot
            result.append(record)
        return result

    def _snapshot(self) -> dict[str, Any] | None:
        if self.snapshot is not None:
            return self.snapshot
        session = self.preflight.get("runtime_session") or {}
        if (not self.preflight.get("project") or not self.preflight.get("rules")
                or not session.get("runtime") or not session.get("session_id")):
            return None
        try:
            states = {}
            for name, root in (("project", self.project), ("rules", self.rules)):
                state = git_state(root)
                states[name] = {key: state[key] for key in ("head", "worktree_fingerprint")}
            self.snapshot = {"schema_version": 1, "project": str(self.project),
                             "rules": str(self.rules), "session": session, "states": states}
        except (OSError, RuntimeError, ValueError, KeyError):
            return None
        return self.snapshot

    def _resolve(self, record: dict[str, Any]) -> dict[str, Any]:
        gate = record.get("gate")
        if gate not in _LOCAL_GATES or gate not in (self.preflight.get("route") or {}).get("gates", []):
            raise ValueError(f"gate reuse is not allowed for {gate}; record current authority/external/review evidence normally")
        if set(record) - {"gate", "reuse_from", "reuse_reason"}:
            raise ValueError("gate reuse cannot override source status, evidence, or fields")
        reason = record.get("reuse_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("gate reuse requires reuse_reason confirming matching scope, artifacts, toolchain and external inputs")
        run_id = record.get("reuse_from")
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("reuse_from must be one registered source run id in this project")
        path = self.project / ".tao" / "runs" / run_id / "preflight.json"
        if path.resolve() != path or path.parent.is_symlink():
            raise ValueError("gate reuse source must stay in its registered run directory")
        registry = _read(self.project / ".tao" / "run-registry.json")
        if not any(isinstance(run, dict) and run.get("run_id") == run_id
                   and run.get("evidence_name", "preflight.json") == "preflight.json"
                   for run in registry.get("runs", [])):
            raise ValueError("gate reuse source run is not registered")
        prior = _read(path)
        if (prior.get("project") != str(self.project) or prior.get("rules") != str(self.rules)
                or prior.get("runtime_session") != self.preflight.get("runtime_session")
                or prior.get("agent_run_id") != run_id):
            raise ValueError("gate reuse source project, rules, run or session differs")
        ledger_path = gate_evidence_path_for_preflight(path)
        if ledger_path.resolve() != ledger_path:
            raise ValueError("gate reuse ledger must stay in its registered run directory")
        ledger = _read(ledger_path)
        merged, diagnostics = merge_gate_evidence_from_ledger(route=prior.get("route") or {}, evidence_path=path)
        if gate not in merged or diagnostics.get("warnings"):
            raise ValueError(f"gate reuse has no valid latest SUCCESS for {gate}")
        if _read(ledger_path) != ledger or _read(path) != prior:
            raise ValueError("gate reuse source changed during validation")
        entry = next((item for item in reversed(ledger.get("entries", []))
                      if isinstance(item, dict) and item.get("gate") == gate), {})
        if entry.get("status") != "SUCCESS":
            raise ValueError(f"gate reuse has no valid latest SUCCESS for {gate}")
        current = self._snapshot()
        if current is None or entry.get("reuse_snapshot") != current:
            raise ValueError("gate reuse inputs changed or original snapshot is unavailable; revalidate only affected evidence")
        if gate == "source docs" and (prior.get("route") or {}).get("required_docs") != (self.preflight.get("route") or {}).get("required_docs"):
            raise ValueError("gate reuse required-document manifest changed")
        # Keep the accepted narrative verbatim. Internal capsule/doc receipts
        # must be regenerated by the current writer, never copied as authority.
        fields = {key: value for key, value in entry.get("fields", {}).items()
                  if key not in {"execution_capsule_binding", "artifact_receipt_version",
                                 "baseline_sha256", "final_sha256", "final_size_bytes"}}
        return {"gate": gate, "status": "SUCCESS", "source": "reuse",
                "evidence": entry.get("evidence", ""), "fields": fields,
                "reuse_provenance": {"run_id": run_id, "created_at": entry.get("created_at"),
                                     "reason": reason}}


def _read(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("oversized gate reuse evidence")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid gate reuse evidence")
    return value
