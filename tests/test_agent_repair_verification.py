from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_hook_runtime import repair_context_failures
from agent_repair_ledger import record_failure_checkpoints
from agent_repair_verification import create_repair_receipt, validate_repair_receipt
from agent_verification_command import verification_workdir


def _init_repo(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=str(project), check=True
    )


class AgentRepairVerificationTests(unittest.TestCase):
    """Structural repair receipts, not parsed prose, gate a repair-cycle resume."""

    def _prepared_repair(self, project: Path) -> tuple[Path, dict]:
        _init_repo(project)
        evidence_path = project / ".tao" / "preflight.json"
        evidence_path.parent.mkdir(parents=True)
        preflight = {"route": {"command": "bugfix", "gates": ["tests", "handoff"]}}
        evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
        record_failure_checkpoints(
            evidence_path=evidence_path,
            preflight=preflight,
            checkpoints=["tests"],
            signature="sig-a",
            checkpoint_signatures={"tests": "sig-a"},
        )
        return evidence_path, preflight

    def test_receipt_requires_target_to_be_actually_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "target.py"], cwd=str(project), check=True)
            subprocess.run(["git", "commit", "-q", "-m", "add target"], cwd=str(project), check=True)

            # Committed and unchanged since: a receipt cannot certify a repair
            # that never touched the target.
            unchanged = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertFalse(unchanged["created"])
            self.assertEqual("target_not_changed", unchanged["reason"])

            target.write_text("x = 2\n", encoding="utf-8")
            changed = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(changed["created"])
            self.assertEqual("SUCCESS", changed["status"])

    def test_unittest_verification_runs_from_target_owner_root(self) -> None:
        project = Path("/tmp/project")
        rules = Path("/tmp/rules")

        self.assertEqual(
            project,
            verification_workdir(
                verification_kind="unittest",
                target_root=project,
                rules=rules,
            ),
        )
        self.assertEqual(
            rules,
            verification_workdir(
                verification_kind="unittest",
                target_root=rules,
                rules=rules,
            ),
        )
        self.assertEqual(
            rules,
            verification_workdir(
                verification_kind="py_compile",
                target_root=project,
                rules=rules,
            ),
        )

    def test_receipt_accepts_changed_rules_target_ignored_by_parent_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            _init_repo(project)
            (project / ".gitignore").write_text(".agents/\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=str(project), check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "ignore local runtime"],
                cwd=str(project),
                check=True,
            )

            rules = project / ".agents" / "local" / "runtime"
            rules.mkdir(parents=True)
            target = rules / "repair.py"
            original = "x = 1\n"
            target.write_text(original, encoding="utf-8")
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {"command": "bugfix", "gates": ["tests", "handoff"]},
                "execution_snapshot": {
                    "required_docs": [
                        {
                            "path": "repair.py",
                            "sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                        }
                    ]
                },
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            target.write_text("x = 2\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=rules,
                evidence_path=evidence_path,
                preflight=preflight,
                target="repair.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )

            self.assertTrue(receipt["created"])
            self.assertEqual("SUCCESS", receipt["status"])
            self.assertEqual(
                [],
                validate_repair_receipt(
                    project=project,
                    rules=rules,
                    evidence_path=evidence_path,
                    preflight=preflight,
                    target="repair.py",
                    checkpoint="tests",
                    receipt_path=Path(receipt["receipt_path"]),
                ),
            )

    def test_receipt_accepts_non_git_target_changed_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            started_at = datetime.now(timezone.utc)
            preflight = {
                "project": str(project),
                "timestamp": started_at.isoformat(),
                "git_status": {"returncode": 128, "review_only": True},
                "route": {"command": "bugfix", "gates": ["tests", "handoff"]},
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            target = project / "target.py"
            target.write_text("x = 2\n", encoding="utf-8")
            modified_at = started_at + timedelta(seconds=1)
            os.utime(target, (modified_at.timestamp(), modified_at.timestamp()))

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )

            self.assertTrue(receipt["created"])
            self.assertEqual("SUCCESS", receipt["status"])

    def test_receipt_accepts_non_git_rules_target_changed_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            rules = root / "rules"
            project.mkdir()
            rules.mkdir()
            _init_repo(project)
            evidence_path = project / ".tao" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            started_at = datetime.now(timezone.utc)
            preflight = {
                "project": str(project),
                "timestamp": started_at.isoformat(),
                "route": {"command": "bugfix", "gates": ["tests", "handoff"]},
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            record_failure_checkpoints(
                evidence_path=evidence_path,
                preflight=preflight,
                checkpoints=["tests"],
                signature="sig-a",
                checkpoint_signatures={"tests": "sig-a"},
            )
            target = rules / "repair.py"
            target.write_text("x = 2\n", encoding="utf-8")
            modified_at = started_at + timedelta(seconds=1)
            os.utime(target, (modified_at.timestamp(), modified_at.timestamp()))

            receipt = create_repair_receipt(
                project=project,
                rules=rules,
                evidence_path=evidence_path,
                preflight=preflight,
                target="repair.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )

            self.assertTrue(receipt["created"])
            self.assertEqual("SUCCESS", receipt["status"])

    def test_valid_receipt_unlocks_repair_cycle_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])

            failures = repair_context_failures(
                "target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertEqual([], failures)

            # The bounded-attempt ledger, not the receipt file, is what
            # prevents replay: the same valid receipt cannot consume a
            # second repair attempt for the same checkpoint.
            replay_failures = repair_context_failures(
                "target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertTrue(replay_failures)
            self.assertTrue(any("repair cycle limit" in f for f in replay_failures))

    def test_failed_verification_receipt_cannot_unlock_repair_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            target = project / "target.py"
            target.write_text("this is not valid python syntax (((\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])
            self.assertEqual("FAIL", receipt["status"])

            failures = repair_context_failures(
                "target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertTrue(failures)

    def test_tampered_receipt_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            receipt_path = Path(receipt["receipt_path"])
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            # Claim the receipt actually covers a different checkpoint than
            # the one it was really generated for -- the receipt_id hash was
            # computed over the original fields, so this must be detected.
            payload["checkpoint"] = "handoff"
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")

            failures = validate_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                receipt_path=receipt_path,
            )
            self.assertTrue(failures)
            self.assertTrue(
                any(
                    "does not match" in failure or "invalid or has been modified" in failure
                    for failure in failures
                )
            )

    def test_receipt_path_outside_tao_dir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            outside_receipt = project / "outside-receipt.json"
            outside_receipt.write_text("{}", encoding="utf-8")

            failures = validate_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                receipt_path=outside_receipt,
            )
            self.assertTrue(
                any("structural repair receipt" in failure for failure in failures)
            )

    def test_receipt_bound_to_stale_target_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path, preflight = self._prepared_repair(project)
            target = project / "target.py"
            target.write_text("x = 1\n", encoding="utf-8")

            receipt = create_repair_receipt(
                project=project,
                rules=ROOT,
                evidence_path=evidence_path,
                preflight=preflight,
                target="target.py",
                checkpoint="tests",
                verification_kind="py_compile",
            )
            self.assertTrue(receipt["created"])

            # The target changed again after the receipt was generated; the
            # stale receipt's target_sha256 no longer matches live state.
            target.write_text("x = 3\n", encoding="utf-8")

            failures = repair_context_failures(
                "target.py",
                receipt["receipt_path"],
                "tests",
                route=preflight["route"],
                evidence_path=evidence_path,
                preflight=preflight,
                project=project,
                rules=ROOT,
            )
            self.assertTrue(failures)
            self.assertTrue(any("target_sha256" in f for f in failures))


if __name__ == "__main__":
    unittest.main()
