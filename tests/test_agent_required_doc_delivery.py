"""A run's unread required docs reach the model once, at its first file edit."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_required_doc_delivery import MARKER, delivery_text, edited_paths

STARTED = "2026-10-02T03:00:00+00:00"
CORE = "platforms/android/skills/sample/SKILL.md"
OTHER = "common/skills/testing/references/final-check.md"
BIG = "common/skills/big/references/current-guidance.md"


class DeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        self.rules = base / "rules"
        self.project = base / "project"
        for doc, body in ((CORE, "## Must\n\n- Keep state immutable."),
                          (OTHER, "## Final\n\n- Run the tests."),
                          (BIG, "x" * 9000)):
            (self.rules / doc).parent.mkdir(parents=True, exist_ok=True)
            (self.rules / doc).write_text(f"---\nkeyflow_id: k\n---\n{body}\n", encoding="utf-8")
        run = self.project / ".tao" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        (self.project / ".tao" / "run-registry.json").write_text("{}", encoding="utf-8")
        self.evidence = run / "preflight.json"
        self.transcript = base / "transcript.jsonl"
        self._preflight([CORE, OTHER])
        self._transcript()

    def _preflight(self, docs: list[str]) -> None:
        self.evidence.write_text(json.dumps({
            "project": str(self.project), "rules": str(self.rules), "timestamp": STARTED,
            "route": {"required_docs": docs},
        }), encoding="utf-8")

    def _transcript(self, *calls, rows: list[dict] | None = None) -> None:
        """Claude Read calls as (stamp, doc[, output, is_error]); output defaults to the doc."""

        rows = list(rows or [])
        for index, (stamp, doc, *rest) in enumerate(calls):
            output = rest[0] if rest else (self.rules / doc).read_text(encoding="utf-8")
            rows.append({"type": "assistant", "timestamp": stamp, "message": {"content": [
                {"type": "tool_use", "id": f"t{index}", "name": "Read",
                 "input": {"file_path": f"{self.rules}/{doc}"}}]}})
            rows.append({"type": "user", "timestamp": stamp, "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{index}", "content": output,
                 "is_error": bool(rest[1]) if len(rest) > 1 else False}]}})
        self.transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def _deliver(self, evidence: Path | None = None) -> str:
        payload = {"tool_name": "Edit", "transcript_path": str(self.transcript),
                   "tool_input": {"file_path": str(self.project / "src" / "Screen.kt")}}
        found = self.evidence if evidence is None else evidence
        return delivery_text(payload, lambda project: found if project == self.project else None)

    def _count_document_reads(self):
        counts = {CORE: 0, OTHER: 0}
        original = Path.read_text

        def read(path, *args, **kwargs):
            for doc in counts:
                if path == self.rules / doc:
                    counts[doc] += 1
            return original(path, *args, **kwargs)

        return counts, patch.object(Path, "read_text", read)

    def test_unread_docs_are_opened_once_and_the_marker_skips_future_reads(self) -> None:
        counts, reads = self._count_document_reads()
        with reads:
            first = self._deliver()
        self.assertIn("Keep state immutable.", first)
        self.assertIn("Run the tests.", first)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)
        counts, reads = self._count_document_reads()
        with reads:
            self.assertEqual("", self._deliver())
        self.assertEqual({CORE: 0, OTHER: 0}, counts)

    def test_proven_reuse_does_not_open_document_content(self) -> None:
        counts, reads = self._count_document_reads()
        with reads, patch("agent_required_doc_delivery.required_doc_reuse",
                          return_value={"reused": [CORE, OTHER], "unread": []}):
            self.assertEqual("", self._deliver())
        self.assertEqual({CORE: 0, OTHER: 0}, counts)

    def test_mixed_reuse_and_fresh_delivery_opens_only_the_fresh_doc_once(self) -> None:
        counts, reads = self._count_document_reads()
        with reads, patch("agent_required_doc_delivery.required_doc_reuse",
                          return_value={"reused": [CORE], "unread": [OTHER]}):
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 0, OTHER: 1}, counts)

    def test_transcript_comparison_and_rendering_share_the_document_read(self) -> None:
        self._transcript((STARTED, CORE))
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_missing_transcript_still_opens_each_delivered_doc_once(self) -> None:
        self.transcript.unlink()
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_a_missing_doc_is_attempted_once_and_other_docs_are_delivered(self) -> None:
        (self.rules / CORE).unlink()
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_unread_docs_are_delivered_once(self) -> None:
        first = self._deliver()
        self.assertIn(f"=== {CORE} ===", first)
        self.assertIn("Keep state immutable.", first)
        self.assertIn("Run the tests.", first)
        self.assertNotIn("keyflow_id", first)
        self.assertEqual("", self._deliver())
        self.assertTrue((self.evidence.parent / MARKER).exists())

    def test_a_doc_read_before_the_run_started_still_counts(self) -> None:
        self._transcript(("2026-10-02T03:05:00.000Z", CORE), ("2026-10-02T02:00:00.000Z", OTHER))
        # Both readings are still in context, whichever side of `start` they fell on.
        self.assertEqual("", self._deliver())

    def test_a_compaction_drops_earlier_readings(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE), ("2026-10-02T02:00:00.000Z", OTHER))
        rows = [json.loads(line) for line in self.transcript.read_text(encoding="utf-8").splitlines()]
        rows.insert(2, {"type": "system", "subtype": "compact_boundary"})
        self.transcript.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
                                   encoding="utf-8")
        text = self._deliver()
        self.assertIn(f"=== {CORE} ===", text)
        self.assertNotIn(f"=== {OTHER} ===", text)

    def test_compaction_is_detected_independently_of_json_spacing(self) -> None:
        for boundary in ({"type": "system", "subtype": "compact_boundary"},
                         {"type": "compacted", "payload": {"message": "summary"}}):
            for separators in (None, (",", ":")):
                with self.subTest(boundary=boundary["type"], separators=separators):
                    (self.evidence.parent / MARKER).unlink(missing_ok=True)
                    self._transcript((STARTED, CORE), (STARTED, OTHER))
                    rows = [json.loads(line) for line in self.transcript.read_text().splitlines()]
                    rows.insert(2, boundary)
                    self.transcript.write_text("\n".join(json.dumps(row, separators=separators)
                                                        for row in rows) + "\n")
                    text = self._deliver()
                    self.assertIn(f"=== {CORE} ===", text)
                    self.assertNotIn(f"=== {OTHER} ===", text)

    def test_a_doc_changed_after_its_reading_is_delivered(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE))
        (self.rules / CORE).write_text("## Must\n\n- Keep state immutable.\n- A newer rule.\n", encoding="utf-8")
        self.assertIn("A newer rule.", self._deliver())

    def test_deleting_or_reordering_rules_invalidates_an_old_read(self) -> None:
        body = "## Rules\n- First rule.\n- Removed rule.\n- Last rule.\n"
        for current in ("## Rules\n- First rule.\n- Last rule.\n",
                        "## Rules\n- Last rule.\n- Removed rule.\n- First rule.\n"):
            with self.subTest(current=current):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                (self.rules / CORE).write_text(body)
                self._transcript((STARTED, CORE))
                (self.rules / CORE).write_text(current)
                self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_complete_numbered_partial_reads_are_reused(self) -> None:
        body = (self.rules / CORE).read_text().splitlines(keepends=True)
        for numbered in (False, True):
            with self.subTest(numbered=numbered):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                lines = [f"{index + 1}\t{line}" if numbered else line
                         for index, line in enumerate(body)]
                self._transcript((STARTED, CORE, "".join(lines[:3])),
                                 (STARTED, CORE, "".join(lines[3:])))
                self.assertNotIn(f"=== {CORE} ===", self._deliver())

    def test_a_compaction_resets_partial_read_coverage(self) -> None:
        body = (self.rules / CORE).read_text().splitlines(keepends=True)
        self._transcript((STARTED, CORE, "".join(body[:3])),
                         (STARTED, CORE, "".join(body[3:])))
        rows = [json.loads(line) for line in self.transcript.read_text().splitlines()]
        rows.insert(2, {"type": "compacted"})
        self.transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_partial_read_does_not_count(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "1\t---\n2\tkeyflow_id: k\n3\t---\n4\t## Must"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_searches_failed_and_partial_reads_do_not_count(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "Found 1 file"),
                         ("2026-10-02T02:00:00.000Z", OTHER, "File does not exist.", True))
        text = self._deliver()
        self.assertIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_a_codex_command_read_counts(self) -> None:
        body = (self.rules / CORE).read_text(encoding="utf-8")
        self._transcript(rows=[{"timestamp": "2026-10-02T02:00:00.000Z", "type": "event_msg", "payload": {
            "type": "item_completed", "item": {"type": "CommandExecution", "id": "e1", "status": "completed",
                                               "command": ["/bin/zsh", "-lc", f"cat {self.rules}/{CORE}"],
                                               "stdout": body}}}])
        text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_structured_codex_outputs_reuse_complete_reads(self) -> None:
        body = (self.rules / CORE).read_text() + '- Use "settings".\n'
        (self.rules / CORE).write_text(body)
        for kind in ("function_call", "custom_tool_call"):
            for serialized in (False, True):
                with self.subTest(kind=kind, serialized=serialized):
                    (self.evidence.parent / MARKER).unlink(missing_ok=True)
                    output = {"output": body, "exit_code": 0}
                    self._transcript(rows=[
                        {"type": "response_item", "payload": {
                            "type": kind, "call_id": "r1", "name": "exec_command",
                            "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
                        {"type": "response_item", "payload": {
                            "type": kind + "_output", "call_id": "r1",
                            "output": json.dumps(output) if serialized else output}},
                    ])
                    self.assertNotIn(f"=== {CORE} ===", self._deliver())

    def test_a_failed_codex_read_cannot_supply_partial_coverage(self) -> None:
        body = (self.rules / CORE).read_text()
        self._transcript(rows=[
            {"type": "response_item", "payload": {
                "type": "function_call", "call_id": "r1",
                "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
            {"type": "response_item", "payload": {
                "type": "function_call_output", "call_id": "r1",
                "output": {"output": body, "exit_code": 1}}},
        ])
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def _orchestrated_read(self, output: str) -> str:
        (self.evidence.parent / MARKER).unlink(missing_ok=True)
        self._transcript(rows=[
            {"type": "response_item", "payload": {
                "type": "custom_tool_call", "call_id": "r1", "name": "functions.exec",
                "input": f'const r = await tools.exec_command({{cmd:"cat {self.rules}/{CORE} {self.rules}/{OTHER}"}}); text(r);'}},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "r1", "output": output},
             "timestamp": "2099-01-01T00:00:00Z"},
        ])
        return self._deliver()

    def test_orchestration_json_items_preserve_complete_reads(self) -> None:
        items = [json.dumps({"i": i, "result": {"status": "fulfilled", "value": {
            "output": (self.rules / doc).read_text(), "exit_code": 0}}})
                 for i, doc in enumerate((CORE, OTHER))]
        for output in ("".join(items), "\n".join(items),
                       "Script completed\nWall time 0.3 seconds\nOutput:\n" + "".join(items)):
            with self.subTest(output=output):
                self.assertEqual("", self._orchestrated_read(output))

    def test_orchestration_failed_and_incomplete_results_stay_unread(self) -> None:
        first = json.dumps({"output": (self.rules / CORE).read_text(), "exit_code": 0})
        second = {"output": (self.rules / OTHER).read_text(), "exit_code": 0}
        for output in (first + json.dumps(second)[:-1], first + " trailing noise",
                       "Script running with cell ID 1\nOutput:\n" + first + json.dumps(second),
                       "Script completed\nOutput:\n" + first + json.dumps(second),
                       first + json.dumps({**second, "exit_code": 1})):
            with self.subTest(output=output):
                self.assertIn(f"=== {OTHER} ===", self._orchestrated_read(output))

        raw_pending = "Script running with cell ID 1\nOutput:\n" + (self.rules / OTHER).read_text()
        self.assertIn(f"=== {OTHER} ===", self._orchestrated_read(raw_pending))

    def test_orchestration_does_not_credit_a_rejected_nested_result(self) -> None:
        output = json.dumps({"result": {"status": "rejected", "value": {
            "output": (self.rules / CORE).read_text(), "exit_code": 0}}})
        self.assertIn(f"=== {CORE} ===", self._orchestrated_read(output))

    def test_orchestration_completed_sibling_does_not_credit_pending_command(self) -> None:
        first = json.dumps({"output": (self.rules / CORE).read_text(), "exit_code": 0})
        body = (self.rules / OTHER).read_text()
        for pending in ({"output": body, "session_id": 42},
                        {"output": body, "session_id": 42, "exit_code": None},
                        *({"output": body, "status": status}
                          for status in ("pending", "running", "in_progress"))):
            with self.subTest(pending=pending):
                output = first + json.dumps({"result": {"status": "fulfilled", "value": pending}})
                delivered = self._orchestrated_read(output)
                self.assertNotIn(f"=== {CORE} ===", delivered)
                self.assertIn(f"=== {OTHER} ===", delivered)

        completed = first + json.dumps({"output": body, "session_id": 42, "exit_code": 0})
        self.assertEqual("", self._orchestrated_read(completed))

    def test_codex_wrappers_preserve_text_and_failed_commands_stay_unread(self) -> None:
        body = (self.rules / CORE).read_text()
        for output, read in (
            ({"result": {"status": "fulfilled", "value": {"output": body, "exit_code": 0}}}, True),
            ({"content": [{"type": "text", "text": json.dumps({"output": body})}]}, True),
            (f"Chunk ID: c1\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n{body}", True),
            (f"Chunk ID: c1\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\n{body}", False),
        ):
            with self.subTest(output=output):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                self._transcript(rows=[
                    {"type": "response_item", "payload": {
                        "type": "function_call", "call_id": "r1",
                        "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
                    {"type": "response_item", "payload": {
                        "type": "function_call_output", "call_id": "r1", "output": output}},
                ])
                self.assertEqual(not read, f"=== {CORE} ===" in self._deliver())

    def test_repeated_lines_need_unambiguous_partial_read_evidence(self) -> None:
        (self.rules / CORE).write_text("Repeated rule.\nUnique rule.\nRepeated rule.\n")
        self._transcript((STARTED, CORE, "Repeated rule.\n"),
                         (STARTED, CORE, "Unique rule.\n"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_batched_read_reuses_each_complete_doc_in_command_order(self) -> None:
        body = (self.rules / OTHER).read_text() + (self.rules / CORE).read_text()
        self._transcript(rows=[{"type": "event_msg", "payload": {
            "item": {"type": "CommandExecution", "id": "r1", "status": "completed",
                     "exit_code": 0, "command": f"cat {self.rules}/{OTHER} {self.rules}/{CORE}",
                     "stdout": body}}}])
        self.assertEqual("", self._deliver())

    def test_a_doc_inside_a_compound_read_counts(self) -> None:
        body = (self.rules / CORE).read_text()
        self._transcript(("2099-01-01T00:00:00.000Z", CORE, f"## Other file\n- unrelated\n{body}trailing output\n"))
        text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_a_compound_read_of_a_since_changed_doc_does_not_count(self) -> None:
        """An old version whose trailing rule was deleted still holds the new text unbroken."""

        (self.rules / CORE).write_text("## Rules\n- First rule.\n- Removed rule.\n")
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "noise\n## Rules\n- First rule.\n- Removed rule.\n"))
        (self.rules / CORE).write_text("## Rules\n- First rule.\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_line_inserted_inside_the_doc_breaks_a_compound_read(self) -> None:
        self._transcript(("2099-01-01T00:00:00.000Z", CORE,
                          "noise\n---\nkeyflow_id: k\n---\n## Must\n- An old rule.\n- Keep state immutable.\n"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_everything_read_delivers_nothing_but_still_marks_the_run(self) -> None:
        self._transcript(("2026-10-02T03:05:00.000Z", CORE), ("2026-10-02T03:06:00.000Z", OTHER))
        self.assertEqual("", self._deliver())
        self.assertTrue((self.evidence.parent / MARKER).exists())

    def test_a_doc_over_the_inline_cap_is_named_not_inlined(self) -> None:
        self._preflight([BIG, CORE])
        text = self._deliver()
        self.assertIn(f"{BIG} (", text)
        self.assertNotIn("x" * 100, text)
        self.assertIn(f"=== {CORE} ===", text)

    def test_no_session_run_or_broken_evidence_delivers_nothing(self) -> None:
        self.assertEqual("", self._deliver(evidence=Path("/nonexistent/preflight.json")))
        self.evidence.write_text("not json", encoding="utf-8")
        self.assertEqual("", self._deliver())

    def test_codex_apply_patch_names_its_files(self) -> None:
        payload = {"cwd": str(self.project), "tool_input": {
            "command": "*** Begin Patch\n*** Update File: src/Screen.kt\n@@\n-a\n+b\n*** End Patch"}}
        self.assertIn(self.project / "src" / "Screen.kt", edited_paths(payload))


class GateCarriesTheDeliveryTests(unittest.TestCase):
    def test_the_context_rides_on_the_verdict_without_changing_it(self) -> None:
        import io
        from contextlib import redirect_stdout

        import claude_pretool_gate as gate

        for runtime in ("claude", "codex"):
            with self.subTest(runtime=runtime), patch.dict(os.environ, {"TAO_PRETOOL_RUNTIME": runtime}):
                gate._PENDING_CONTEXT.append("delivered docs")
                output = io.StringIO()
                with redirect_stdout(output):
                    gate.allow()
                hook = json.loads(output.getvalue())["hookSpecificOutput"]
                self.assertEqual("delivered docs", hook["additionalContext"])
                self.assertNotIn("permissionDecision", hook)
                self.assertNotIn("systemMessage", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
