import json
import unittest
from unittest.mock import patch

from tests import test_agent_gate_reuse as fixture
from tests import test_agent_hook_start_run_binding as start_fixture
from agent_hook_gate_records import reset_and_record_preflight_gate


class WorkContinuityStartTests(unittest.TestCase):
    setUp = fixture.GateEvidenceReuseTests.setUp
    git = staticmethod(fixture.GateEvidenceReuseTests.git)
    make_run = fixture.GateEvidenceReuseTests.make_run
    record_source = fixture.GateEvidenceReuseTests.record_source

    def invoke(self, admitted):
        self.record_source()
        args = start_fixture.start_args(self.project, "메인에 반영해")
        args.rules = self.rules
        args.evidence = self.target.evidence
        args.continue_from = self.source_id
        args.reuse_inputs = "Matching local inputs and target; independent current authority"
        args.hook = "start"
        current = json.loads(self.target.evidence.read_text())
        source_bytes = self.source.evidence.read_bytes()
        hook = start_fixture.agent_hook
        events = []

        def preflight(*unused):
            events.append("current admission")
            if admitted:
                self.target.evidence.write_text(json.dumps(current))
                reset_and_record_preflight_gate(self.target.evidence, current)
            return {"returncode": 0 if admitted else 1, "stdout": "", "stderr": "denied" if not admitted else ""}

        def promote(*unused):
            events.append("promotion")
            from agent_hook_gate_records import _gate_progress
            self.assertNotIn("tests", _gate_progress(args)["remaining_gates"])
            return True

        with (
            patch("agent_work_continuity.runtime_session", return_value=current["runtime_session"]),
            patch.object(hook, "task_affinity_denial", return_value=None),
            patch.object(hook, "claim_run", return_value={"conflict": False, "run": {"run_id": self.target_id}}),
            patch.object(hook, "_preflight_arguments", return_value=[]),
            patch.object(hook, "run_script_main", side_effect=preflight),
            patch.object(hook, "_hook_summary_from_preflight", return_value=[]),
            patch.object(hook, "_start_capsule_detail", return_value=""),
            patch.object(hook, "_refresh_started_context", return_value=True),
            patch.object(hook, "_bind_read_only_execution_state", return_value=True),
            patch.object(hook, "_register_started_run", side_effect=promote),
            patch.object(hook, "start_checkpoint", return_value=("initial", {})),
            patch.object(hook, "record_lifecycle_checkpoint", return_value=""),
            patch.object(hook, "work_checkpoint_advice", return_value=[]),
            patch.object(hook, "_release_claimed_run", return_value=""),
            patch.object(hook, "finish_with_result", side_effect=lambda name, ok, *a, **kw: 0 if ok else 1),
        ):
            result = hook.start_hook(args)
        self.assertEqual(source_bytes, self.source.evidence.read_bytes())
        return result, events

    def test_start_carries_evidence_only_after_current_action_admission(self):
        result, events = self.invoke(True)
        self.assertEqual(0, result)
        self.assertEqual(["current admission", "promotion"], events)
        payload = json.loads(self.target.evidence.read_text())
        self.assertEqual(self.source_id, payload["work"]["id"])

    def test_rejected_action_does_not_promote_or_inherit(self):
        result, events = self.invoke(False)
        self.assertEqual(1, result)
        self.assertEqual(["current admission"], events)
        self.assertNotIn("work", json.loads(self.target.evidence.read_text()))
