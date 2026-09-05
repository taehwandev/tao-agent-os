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
from agent_hook_gate_records import _normalize_gate_record, gate_batch_hook, gate_hook
from agent_run_registry import register_run

# The join advice belongs to the array rejection alone. Asserting its absence
# elsewhere is what keeps it from drifting back onto every wrong-typed field.
ARRAY_HINT = 'pass "a.md, b.md" rather than ["a.md", "b.md"]'


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

    def test_permission_denial_is_an_invocation_error_for_each_gate_hook(self) -> None:
        """An environment denial before ledger mutation has no checkpoint to repair."""

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
                output_path = evidence_path.with_name(f"{hook_name}-result.json")
                evidence_path.parent.mkdir(parents=True)
                record = {
                    "gate": "risk review",
                    "evidence": "environment denied ledger write",
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
                    gate_evidence="environment denied ledger write",
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
                        record_target,
                        side_effect=PermissionError("sandbox denied state lock"),
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


class GateRecordFieldTypeTests(unittest.TestCase):
    def test_string_field_value_is_preserved_unchanged(self) -> None:
        """The documented shape must survive normalization untouched."""

        record = _normalize_gate_record(
            {
                "gate": "documentation",
                "fields": {"decision": "updated", "target": "docs/a.md"},
            }
        )

        self.assertEqual(
            {"decision": "updated", "target": "docs/a.md"},
            record["fields"],
        )

    def test_array_field_value_is_rejected_with_the_received_json_type(self) -> None:
        """A list used to become a Python repr and fail as a path-shape error."""

        with self.assertRaises(ValueError) as caught:
            _normalize_gate_record(
                {
                    "gate": "documentation",
                    "fields": {"decision": "updated", "target": ["docs/a.md"]},
                }
            )

        message = str(caught.exception)
        self.assertIn("gate record for documentation", message)
        self.assertIn("non-string field target", message)
        self.assertIn("received JSON array", message)
        self.assertIn(ARRAY_HINT, message)

    def test_boolean_field_value_is_rejected_instead_of_becoming_true(self) -> None:
        """`str(True)` produced "True", which no lowercase enum compare matches."""

        with self.assertRaises(ValueError) as caught:
            _normalize_gate_record(
                {"gate": "risk review", "fields": {"resolved": True}}
            )

        message = str(caught.exception)
        self.assertIn("gate record for risk review", message)
        self.assertIn("non-string field resolved", message)
        self.assertIn("received JSON boolean", message)
        self.assertNotIn("True", message)
        self.assertNotIn(ARRAY_HINT, message)

    def test_number_field_value_is_rejected_as_a_json_number(self) -> None:
        """One documented shape beats a second, silently stringified one."""

        with self.assertRaises(ValueError) as caught:
            _normalize_gate_record({"gate": "source docs", "fields": {"count": 2}})

        message = str(caught.exception)
        self.assertIn("received JSON number", message)
        self.assertNotIn(ARRAY_HINT, message)

    def test_object_field_value_is_rejected_as_a_json_object(self) -> None:
        """A nested object is the same wrong-type mistake as an array."""

        with self.assertRaises(ValueError) as caught:
            _normalize_gate_record(
                {"gate": "source docs", "fields": {"manifest": {"a": "b"}}}
            )

        message = str(caught.exception)
        self.assertIn("received JSON object", message)
        self.assertNotIn(ARRAY_HINT, message)

    def test_null_field_value_is_dropped_rather_than_stored_as_none(self) -> None:
        """Null must read as absent, the way canonical_gate_fields treats it."""

        record = _normalize_gate_record(
            {
                "gate": "documentation",
                "fields": {"decision": "updated", "target": None},
            }
        )

        self.assertEqual({"decision": "updated"}, record["fields"])

    def test_gate_json_file_path_rejects_a_non_string_field_value(self) -> None:
        """The file input must not bypass the validation --gate-record gets."""

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            gate_json = project / "records.json"
            gate_json.write_text(
                json.dumps(
                    [
                        {
                            "gate": "documentation",
                            "status": "SUCCESS",
                            "source": "manual",
                            "fields": {
                                "decision": "updated",
                                "target": ["docs/a.md"],
                                "reason": "updated the routed required doc",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                evidence=evidence_path,
                project=project,
                rules=ROOT,
                hook="gate-batch",
                field=[],
                gate_record=[],
                gate_json=gate_json,
                output=None,
                repair_cycle=0,
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = gate_batch_hook(args)

        self.assertEqual(1, result)
        self.assertIn("received JSON array", stdout.getvalue())
        self.assertNotIn("route-relative path", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
