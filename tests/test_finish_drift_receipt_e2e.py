"""Required-doc drift recovery, driven through the real hook CLI.

Finish classifies a failure made only of required-doc drift as `doc_receipt`
and one that also carries a stale review attestation as
`doc_receipt_then_review`. Both recoveries stay in the same run: record the
documentation receipts finish names, rerun review when it is owed, and retry
finish. That only works if a failed finish leaves the run unsettled, so the
review hook and the gate ledger still bind to it. These tests run every step as
a separate process against a disposable project and a disposable copy of the
rules root, so the drifted document is real bytes on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _tao_test_support import ROOT, TemplateRepository, fake_vibeguard_environment
from test_work_continuity_lifecycle_e2e import git, hook

SESSION = "drift-receipt-e2e-session"
_MODULE_STATE: list = []


def _build_fixture(root: Path) -> None:
    rules = root / "rules"
    shutil.copytree(
        ROOT,
        rules,
        symlinks=True,
        # `.codegraph/` can hold a live socket; the fixture needs no index.
        ignore=shutil.ignore_patterns(".git", ".tao", "__pycache__", ".pytest_cache", ".codegraph"),
    )
    project = root / "project"
    project.mkdir()
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    (project / "README.md").write_text("Baseline readme.\n", encoding="utf-8")
    for checkout in (rules, project):
        git(checkout, "init", "-q")
        # A commit of the whole rules tree can trigger a detached auto-gc that
        # packs loose objects while a later test copies the template.
        git(checkout, "config", "gc.auto", "0")
        git(checkout, "config", "maintenance.auto", "false")
        git(checkout, "config", "user.email", "drift@example.invalid")
        git(checkout, "config", "user.name", "Drift")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-qm", "fixture")


_FIXTURE = TemplateRepository(_build_fixture, repositories=("rules", "project"))


def setUpModule() -> None:
    # Keep work cards out of the developer's ~/.tao and skip the real audit.
    directory = tempfile.TemporaryDirectory(prefix="tao-state-home-")
    state = mock.patch.dict(os.environ, {"TAO_STATE_HOME": directory.name})
    state.start()
    vibeguard = fake_vibeguard_environment()
    vibeguard.start()
    _MODULE_STATE.extend((state, directory, vibeguard))


def tearDownModule() -> None:
    state, directory, vibeguard = _MODULE_STATE
    vibeguard.stop()
    state.stop()
    directory.cleanup()
    _MODULE_STATE.clear()
    _FIXTURE.cleanup()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gate(gate: str, **fields: str) -> dict:
    return {"gate": gate, "status": "SUCCESS", "fields": fields}


class RequiredDocDriftReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        _FIXTURE.copy_to(self.root)
        self.rules = self.root / "rules"
        self.project = self.root / "project"

    def hook(self, *arguments: str) -> subprocess.CompletedProcess:
        return hook(self.project, self.rules, *arguments, session=SESSION)

    def ok(self, *arguments: str) -> subprocess.CompletedProcess:
        result = self.hook(*arguments)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result

    def finish(self, name: str) -> tuple[subprocess.CompletedProcess, dict]:
        output = self.root / f"{name}.json"
        result = self.hook("finish", "--output", str(output))
        return result, json.loads(output.read_text(encoding="utf-8"))

    def run_state(self) -> str:
        registry = json.loads((self.project / ".tao" / "run-registry.json").read_text())
        return registry["runs"][-1]["state"]

    def start_and_record_gates(self) -> list[str]:
        started = self.ok(
            "start", "--command", "docs", "--request", "README.md 의 설명을 고쳐줘",
            "--intent", "drift_receipt_scenario", "--target-summary", "the fixture readme",
            "--approved-effect", "git_write",
        )
        evidence = next((self.project / ".tao" / "runs").glob("*/preflight.json"))
        self.assertIn(str(evidence), started.stdout)
        docs = json.loads(evidence.read_text(encoding="utf-8"))["route"]["required_docs"]
        self.assertTrue(docs)
        (self.project / "README.md").write_text("Updated readme.\n", encoding="utf-8")
        recorded = self.ok("gate-batch", "--gate-record", json.dumps([
            _gate("source docs", required_docs=", ".join(docs),
                  source="read every required doc in the fixture rules root",
                  takeaway="change only the readme"),
            _gate("documentation impact", artifact="README.md", decision="updated",
                  reason="the readme is the requested artifact"),
            _gate("ambiguity check", blocker_status="none",
                  assumptions="the readme is the only target", decision="proceed"),
            _gate("alignment brief", shared_understanding="rewrite README.md",
                  possible_differences="none", assumptions="disposable fixture",
                  checkpoint="user_visible_before_edits"),
            _gate("agentic run state", state="acting", transition="planning to acting",
                  evidence="README.md rewritten", checkpoint="review", blockers="none"),
            _gate("cycle contract", cycle_type="docs", input_scope="README.md",
                  allowed_changes="README.md", forbidden_changes="everything else",
                  acceptance_criteria="readme updated", verification="review hook",
                  stop_condition="review passes", checkpoint="finish"),
            _gate("documentation", decision="updated", target="README.md",
                  reason="rewrote the readme"),
            _gate("retrospective check",
                  skills_checked="agent_operating_skill, documentation_update",
                  outcome="no_reusable_gap", observation="not_needed"),
        ]))
        self.assertIn("Remaining route gates: ['review hook']", recorded.stdout)
        return docs

    def review(self, note: str) -> None:
        reviewed = self.ok(
            "review", "--review-outcome", "pass",
            "--code-review-evidence", f"Reviewed the readme change; {note}",
            "--docs-freshness-evidence", "README.md is the updated documentation",
        )
        self.assertIn("SUCCESS review", reviewed.stdout)

    def drift(self, relative: str) -> tuple[Path, str]:
        document = self.rules / relative
        original = _sha256(document)
        document.write_text(document.read_text(encoding="utf-8") + "\nDrift line.\n",
                            encoding="utf-8")
        return document, original

    def assert_drift_failure(self, result, payload, relative: str, next_action: str) -> str:
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn("FAIL finish", result.stdout)
        self.assertIn(f"FAIL: execution capsule required doc size changed: {relative}",
                      result.stdout)
        self.assertIn(f"FAIL: execution capsule required doc hash changed: {relative}",
                      result.stdout)
        self.assertEqual(next_action, payload["policy"]["next_action"])
        self.assertEqual("bound_drift_receipt", payload["policy"]["recovery_required"])
        details = "\n".join(payload["details"])
        self.assertNotIn("do not run repair-verify", details)
        self.assertIn("required-doc drift recovery", details)
        # A failed finish leaves the run unsettled, so the same run can recover.
        self.assertEqual("failed", self.run_state())
        return details

    def record_receipt(self, details: str, relative: str, original: str, document: Path) -> None:
        match = re.search(
            rf"required-doc drift recovery for {re.escape(relative)}: "
            r"baseline_sha256=([0-9a-f]{64}) "
            r"final_sha256=([0-9a-f]{64}) final_size_bytes=(\d+)",
            details,
        )
        self.assertIsNotNone(match, details)
        baseline, final_sha256, final_size = match.group(1), match.group(2), match.group(3)
        # Finish hands over the snapshot baseline and the current bytes, so
        # the receipt is recorded from its output alone; check both are real.
        self.assertEqual(original, baseline)
        self.assertEqual(_sha256(document), final_sha256)
        self.assertEqual(document.stat().st_size, int(final_size))
        recorded = self.ok("gate-batch", "--gate-record", json.dumps([_gate(
            "documentation", decision="updated", target=relative,
            reason="this run appended the drift line to the required doc",
            artifact_receipt_version="1", baseline_sha256=baseline,
            final_sha256=final_sha256, final_size_bytes=final_size,
        )]))
        self.assertIn("recorded gate: documentation", recorded.stdout)

    def assert_finished(self) -> None:
        result, payload = self.finish("finish-retry")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("SUCCESS finish", result.stdout)
        self.assertEqual("continue", payload["policy"]["next_action"])
        self.assertEqual("completed", self.run_state())
        # The recovery reused the one run: no second start was needed.
        self.assertEqual(1, len(list((self.project / ".tao" / "runs").glob("*/preflight.json"))))

    def test_doc_drift_with_stale_review_recovers_in_the_same_run(self) -> None:
        relative = self.start_and_record_gates()[-1]
        self.review("before drift")
        document, original = self.drift(relative)
        (self.project / "README.md").write_text("Updated readme again.\n", encoding="utf-8")

        result, payload = self.finish("finish-drift")

        self.assertIn("FAIL: review hook attestation project worktree binding is stale",
                      result.stdout)
        details = self.assert_drift_failure(
            result, payload, relative, "record_drift_receipts_rerun_review_and_retry_finish"
        )
        self.assertIn("rerun the review hook in this same run", details)
        self.record_receipt(details, relative, original, document)
        self.review("after the documentation receipt")
        self.assert_finished()

    def test_doc_drift_before_review_needs_only_the_receipt(self) -> None:
        # The rules root is part of the review attestation, so a required doc
        # that drifts after review always stales it. The receipt-only recovery
        # is the case where another writer changed the doc before review.
        relative = self.start_and_record_gates()[-1]
        document, original = self.drift(relative)
        self.review("after another writer changed a required doc")

        result, payload = self.finish("finish-drift")

        self.assertNotIn("review hook attestation", result.stdout)
        details = self.assert_drift_failure(
            result, payload, relative, "record_drift_receipts_and_retry_finish"
        )
        self.assertNotIn("rerun the review hook", details)
        self.record_receipt(details, relative, original, document)
        self.assert_finished()


if __name__ == "__main__":
    unittest.main()
