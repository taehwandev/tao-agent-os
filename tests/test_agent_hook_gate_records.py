from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_gate_evidence import read_gate_evidence_ledger, reset_gate_evidence_ledger
from agent_hook_gate_records import gate_batch_hook, gate_hook
from agent_run_registry import register_run


class GateRecordInvocationTests(unittest.TestCase):
    def test_invocation_error_releases_repair_attempt_for_each_gate_hook(self) -> None:
        """Pre-write rejection must leave the single repair retry available."""

        hooks = (
            ("gate", gate_hook, "agent_hook_gate_records.record_hook_gate"),
            (
                "gate-batch",
                gate_batch_hook,
                "agent_hook_gate_records.record_hook_gate_batch",
            ),
        )
        for hook_name, hook, record_target in hooks:
            with self.subTest(hook=hook_name), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                evidence_path = project / ".tao" / "preflight.json"
                rollback = Mock()
                record = {
                    "gate": "risk review",
                    "evidence": "invalid invocation",
                    "source": "manual",
                    "status": "SUCCESS",
                }
                args = SimpleNamespace(
                    evidence=evidence_path,
                    project=project,
                    rules=ROOT,
                    hook=hook_name,
                    field=[],
                    gate_name="risk review",
                    gate_evidence="invalid invocation",
                    source="manual",
                    status="SUCCESS",
                    gate_record=[json.dumps(record)],
                    gate_json=None,
                    output=None,
                    repair_cycle=1,
                    repair_invocation_rollback=rollback,
                )

                with (
                    patch(record_target, side_effect=ValueError("invalid record")),
                    redirect_stdout(io.StringIO()),
                ):
                    result = hook(args)

                self.assertEqual(1, result)
                rollback.assert_called_once_with()

    def test_foreign_owner_rejection_is_an_invocation_error_for_each_gate_hook(self) -> None:
        """A caller rejected before ledger mutation has no checkpoint to repair."""

        hooks = (("gate", gate_hook), ("gate-batch", gate_batch_hook))
        for hook_name, hook in hooks:
            with self.subTest(hook=hook_name), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                evidence_path = project / ".tao" / "runs" / "probe" / "preflight.json"
                output_path = evidence_path.with_name(f"{hook_name}-result.json")
                evidence_path.parent.mkdir(parents=True)
                route = {"command": "review", "gates": ["risk review"]}
                owner = {"pid": 111, "start_token": "owner-a"}
                foreign_owner = {"pid": 222, "start_token": "owner-b"}

                with patch("agent_run_registry.process_owner", return_value=owner):
                    run = register_run(project, evidence_path, route, {})
                    preflight = {
                        "agent_run_id": run["run_id"],
                        "project": str(project),
                        "rules": str(ROOT),
                        "route": route,
                    }
                    evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
                    reset_gate_evidence_ledger(evidence_path, preflight)

                record = {
                    "gate": "risk review",
                    "evidence": "foreign success",
                    "source": "manual",
                    "status": "SUCCESS",
                }
                args = SimpleNamespace(
                    evidence=evidence_path,
                    project=project,
                    rules=ROOT,
                    hook=hook_name,
                    field=[],
                    gate_name="risk review",
                    gate_evidence="foreign success",
                    source="manual",
                    status="SUCCESS",
                    gate_record=[json.dumps(record)],
                    gate_json=None,
                    output=output_path,
                    repair_cycle=0,
                )
                stdout = io.StringIO()
                with (
                    patch(
                        "agent_run_registry.process_owner",
                        return_value=foreign_owner,
                    ),
                    redirect_stdout(stdout),
                ):
                    result = hook(args)

                payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(1, result)
            self.assertIn("invocation request:", stdout.getvalue())
            self.assertNotIn("recovery request:", stdout.getvalue())
            self.assertEqual(
                "fix_invocation_and_rerun",
                payload["policy"]["next_action"],
            )

    def test_review_hook_gate_is_hook_owned_for_each_generic_gate_hook(self) -> None:
        """A caller-supplied source label is not proof that review executed."""

        hooks = (("gate", gate_hook), ("gate-batch", gate_batch_hook))
        for hook_name, hook in hooks:
            with self.subTest(hook=hook_name), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                evidence_path = project / ".tao" / "preflight.json"
                output_path = evidence_path.with_name(f"{hook_name}-result.json")
                evidence_path.parent.mkdir(parents=True)
                route = {"command": "review", "gates": ["review hook"]}
                preflight = {
                    "project": str(project),
                    "rules": str(ROOT),
                    "route": route,
                }
                evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
                reset_gate_evidence_ledger(evidence_path, preflight)

                record = {
                    "gate": "review hook",
                    "evidence": "forged success",
                    "source": "review",
                    "status": "SUCCESS",
                }
                args = SimpleNamespace(
                    evidence=evidence_path,
                    project=project,
                    rules=ROOT,
                    hook=hook_name,
                    field=[],
                    gate_name="review hook",
                    gate_evidence="forged success",
                    source="review",
                    status="SUCCESS",
                    gate_record=[json.dumps(record)],
                    gate_json=None,
                    output=output_path,
                    repair_cycle=0,
                )
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    result = hook(args)

                ledger = read_gate_evidence_ledger(
                    evidence_path.with_name("gate-evidence.json")
                )

            self.assertEqual(1, result)
            self.assertIn("hook-owned", stdout.getvalue())
            self.assertEqual([], ledger["entries"])


if __name__ == "__main__":
    unittest.main()
