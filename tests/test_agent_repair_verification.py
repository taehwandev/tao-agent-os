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
from agent_verification_command import run_verification_command, verification_workdir


def _init_repo(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=str(project), check=True
    )


class VerificationCacheIsolationTests(unittest.TestCase):
    """A check must fail for the file it names, never for a cache path.

    The default interpreter here is Xcode's Python, whose `sys.pycache_prefix`
    is an absolute path outside the project. `run_verification_command` passed
    the environment straight through, so where a sandbox denies that path,
    `py_compile` exits 1 with a PermissionError -- reporting a syntactically
    perfect file as a failed verification. `unittest` is unaffected: bytecode
    written at import time is best-effort, and only `py_compile` treats the
    write as the job.
    """

    def test_py_compile_passes_where_the_interpreter_cache_path_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sound.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            denied = Path(tmp) / "denied"
            denied.mkdir()
            denied.chmod(0o500)
            os.environ["PYTHONPYCACHEPREFIX"] = str(denied / "cache")
            self.addCleanup(os.environ.pop, "PYTHONPYCACHEPREFIX", None)
            try:
                result = run_verification_command(
                    [sys.executable, "-m", "py_compile", str(target)], Path(tmp)
                )
            finally:
                # Before the fixture unwinds, or it cannot remove the directory.
                denied.chmod(0o700)

        self.assertEqual(0, result["returncode"], result["stderr"])
        self.assertNotIn("PermissionError", result["stderr"])

    def test_a_denied_temp_location_does_not_raise_into_the_caller(self) -> None:
        """Isolating the cache must not become a new way to fail.

        Every caller reads result["returncode"]; none guards the call. Creating
        a cache directory gave this function a filesystem write of its own, so
        where the temp location is denied it raised instead of returning a
        captured failure -- trading a check that fails for a hook that stops.
        """

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sound.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            denied = Path(tmp) / "denied"
            denied.mkdir()
            denied.chmod(0o500)
            original = tempfile.tempdir
            tempfile.tempdir = str(denied)
            try:
                result = run_verification_command(
                    [sys.executable, "-m", "py_compile", str(target)], Path(tmp)
                )
            finally:
                tempfile.tempdir = original
                denied.chmod(0o700)

        self.assertEqual(0, result["returncode"], result["stderr"])

    def test_the_command_runs_once_when_the_cache_cannot_be_removed(self) -> None:
        """Falling back must not mean running the check again.

        The first fallback wrapped creation and cleanup in one try, so a
        cleanup failure re-entered the runner and executed the verification a
        second time. Written first against the happy path, which proved
        nothing: that shape also runs once when cleanup succeeds. The child
        therefore makes its own cache directory unremovable, and the ledger it
        appends to has to hold exactly one line.
        """

        with tempfile.TemporaryDirectory() as tmp:
            holder = Path(tmp) / "holder"
            holder.mkdir()
            ledger = Path(tmp) / "runs.txt"
            script = (
                "import os, pathlib;"
                f"pathlib.Path({str(ledger)!r}).open('a').write('run\\n');"
                # Removing the cache needs write on its parent; deny that.
                f"os.chmod({str(holder)!r}, 0o500)"
            )
            original = tempfile.tempdir
            tempfile.tempdir = str(holder)
            try:
                result = run_verification_command(
                    [sys.executable, "-c", script], Path(tmp)
                )
            finally:
                tempfile.tempdir = original
                holder.chmod(0o700)

            self.assertEqual(0, result["returncode"], result["stderr"])
            self.assertEqual(1, ledger.read_text(encoding="utf-8").count("run"))

    def test_a_real_syntax_error_still_fails(self) -> None:
        # The isolation must not swallow the failure the check exists to find.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "broken.py"
            target.write_text("def (\n", encoding="utf-8")
            result = run_verification_command(
                [sys.executable, "-m", "py_compile", str(target)], Path(tmp)
            )

        self.assertNotEqual(0, result["returncode"])


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
