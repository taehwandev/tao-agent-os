from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_outbound import (
    CONTINUATION_STORAGE_CLASS,
    OUTBOUND_BOUNDARIES,
    assert_no_continuation_outbound,
)
from agent_execution_capsule import _write_execution_capsule
from agent_execution_capsule_state import atomic_write_json
from agent_hook_runtime import write_json as write_diagnostic_json
from agent_ipc import emit_event
from agent_lesson_store import upsert_retrospective_candidate


RUN_ID = "a" * 32
PACKET_PATH = f".tao/runs/{RUN_ID}/continuation.json"


class AgentContinuationOutboundTests(unittest.TestCase):
    def test_every_outbound_class_rejects_schema_marker_and_packet_path(self) -> None:
        for boundary in sorted(OUTBOUND_BOUNDARIES):
            for value in (
                {"storage_class": CONTINUATION_STORAGE_CLASS},
                {"path": PACKET_PATH},
                {"path": f"/workspace/{PACKET_PATH}"},
                {"path": PACKET_PATH.replace("/", "\\")},
            ):
                with self.subTest(boundary=boundary, value_type=next(iter(value))):
                    with self.assertRaises(ValueError):
                        assert_no_continuation_outbound(value, boundary=boundary)

    def test_safe_content_passes_and_unknown_boundary_fails_closed(self) -> None:
        safe = {"schema_version": 1, "run_id": "opaque-run", "state": "ready"}
        for boundary in sorted(OUTBOUND_BOUNDARIES):
            assert_no_continuation_outbound(safe, boundary=boundary)
        with self.assertRaisesRegex(ValueError, "unknown continuation outbound boundary"):
            assert_no_continuation_outbound(safe, boundary="network")

    def test_failure_does_not_echo_rejected_value(self) -> None:
        rejected = f"/private/example/{PACKET_PATH}"
        with self.assertRaises(ValueError) as raised:
            assert_no_continuation_outbound(rejected, boundary="export")
        self.assertNotIn(rejected, str(raised.exception))

    def test_generic_artifact_writer_rejects_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifact.json"
            with self.assertRaises(ValueError):
                atomic_write_json(
                    output,
                    {"storage_class": CONTINUATION_STORAGE_CLASS},
                )
            self.assertFalse(output.exists())

    def test_generic_artifact_writer_rejects_the_canonical_packet_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / PACKET_PATH
            with self.assertRaises(ValueError):
                atomic_write_json(output, {"schema_version": 1})
            self.assertFalse(output.parent.exists())

    def test_execution_capsule_writer_rejects_continuation_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "execution-capsule.json"
            with self.assertRaises(ValueError):
                _write_execution_capsule(output, {"packet_path": PACKET_PATH})
            self.assertFalse(output.exists())

    def test_ipc_and_telemetry_reject_before_event_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaises(ValueError):
                emit_event(
                    project,
                    "run.started",
                    run_id=CONTINUATION_STORAGE_CLASS,
                    state="running",
                )
            self.assertFalse((project / ".tao" / "events.json").exists())

    def test_global_lesson_rejects_before_candidate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = upsert_retrospective_candidate(
                root,
                {
                    "lesson_id": "continuation-boundary-test",
                    "storage_class": CONTINUATION_STORAGE_CLASS,
                },
            )
            self.assertEqual("write_failed", result["reason"])
            self.assertFalse((root / "lessons").exists())

    def test_diagnostic_rejects_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagnostic.json"
            with self.assertRaises(ValueError):
                write_diagnostic_json(output, {"packet": PACKET_PATH})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
