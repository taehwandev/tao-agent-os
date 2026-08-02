from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_repair_ledger import (
    CONFLICT,
    NOT_APPLICABLE,
    REBOUND,
    capture_failure_checkpoint_binding,
    checkpoint_has_recorded_failure,
    rebind_failure_checkpoints_after_required_doc_refresh,
    record_failure_checkpoints,
    repair_checkpoint_path_for_preflight,
)


class AgentRepairLedgerTests(unittest.TestCase):
    def test_required_doc_refresh_rebinds_same_request_failure_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            route = {"command": "review", "gates": ["review hook"]}
            intake = {"request": "verify the current repair", "request_classified": False}
            preflight = {"route": route, "request_intake": intake, "agent_run_id": "old"}
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["review"],
                signature="same-failure",
            )
            binding = capture_failure_checkpoint_binding(evidence_path)

            refreshed = {**preflight, "agent_run_id": "new"}
            evidence_path.write_text(json.dumps(refreshed), encoding="utf-8")
            self.assertEqual(
                REBOUND,
                rebind_failure_checkpoints_after_required_doc_refresh(
                    evidence_path=evidence_path,
                    preflight=refreshed,
                    prior_binding=binding,
                    required_doc_drift=True,
                ),
            )
            self.assertTrue(
                checkpoint_has_recorded_failure(
                    route=route, evidence_path=evidence_path, checkpoint="review"
                )
            )

    def test_required_doc_refresh_never_rebinds_another_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            route = {"command": "review", "gates": ["review hook"]}
            preflight = {
                "route": route,
                "request_intake": {"request": "first request"},
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["review"],
                signature="first-failure",
            )
            binding = capture_failure_checkpoint_binding(evidence_path)

            refreshed = {
                "route": route,
                "request_intake": {"request": "different request"},
            }
            evidence_path.write_text(json.dumps(refreshed), encoding="utf-8")
            self.assertEqual(
                NOT_APPLICABLE,
                rebind_failure_checkpoints_after_required_doc_refresh(
                    evidence_path=evidence_path,
                    preflight=refreshed,
                    prior_binding=binding,
                    required_doc_drift=True,
                ),
            )
            self.assertFalse(
                checkpoint_has_recorded_failure(
                    route=route, evidence_path=evidence_path, checkpoint="review"
                )
            )

    def test_unchanged_context_never_rebinds_a_stale_preflight_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {
                "route": {"command": "review", "gates": ["review hook"]},
                "request_intake": {"request": "same request"},
                "agent_run_id": "old",
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["review"],
                signature="failure",
            )
            binding = capture_failure_checkpoint_binding(evidence_path)
            refreshed = {**preflight, "agent_run_id": "new"}
            evidence_path.write_text(json.dumps(refreshed), encoding="utf-8")

            self.assertEqual(
                NOT_APPLICABLE,
                rebind_failure_checkpoints_after_required_doc_refresh(
                    evidence_path=evidence_path,
                    preflight=refreshed,
                    prior_binding=binding,
                    required_doc_drift=False,
                ),
            )

    def test_required_doc_refresh_fails_closed_when_ledger_changes_mid_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "preflight.json"
            preflight = {
                "route": {"command": "review", "gates": ["review hook"]},
                "request_intake": {"request": "same request"},
                "agent_run_id": "old",
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["review"],
                signature="failure",
            )
            binding = capture_failure_checkpoint_binding(evidence_path)
            ledger_path = repair_checkpoint_path_for_preflight(evidence_path)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["failure_signature"] = "concurrent-change"
            ledger["preflight_evidence_sha256"] = "0" * 64
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            refreshed = {**preflight, "agent_run_id": "new"}
            evidence_path.write_text(json.dumps(refreshed), encoding="utf-8")

            self.assertEqual(
                CONFLICT,
                rebind_failure_checkpoints_after_required_doc_refresh(
                    evidence_path=evidence_path,
                    preflight=refreshed,
                    prior_binding=binding,
                    required_doc_drift=True,
                ),
            )


if __name__ == "__main__":
    unittest.main()
