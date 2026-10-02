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

    def test_a_doc_changed_after_its_reading_is_delivered(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE))
        (self.rules / CORE).write_text("## Must\n\n- Keep state immutable.\n- A newer rule.\n", encoding="utf-8")
        self.assertIn("A newer rule.", self._deliver())

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
