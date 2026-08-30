from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_gate_evidence import record_gate_evidence
from agent_route_state import request_fingerprint
from agent_worker_evidence import create_worker_reservation, claim_worker_reservation, worker_reservation_matches
from workflow_dispatch import build_dispatch_manifest, execute_dispatch_manifest
from support.permission_entries import (
    STALE_PERMISSION_ENTRYPOINTS,
    agy_legacy_permission_entries,
    agy_permission_entries,
    claude_legacy_permission_entries,
    claude_permission_entries,
    codex_prefix_rule_entries,
)
from support.setup_config_files import merge_permissions_allow
from support.stable_launcher import ensure_stable_launcher, stable_launcher_path


class RemovedEntrypointMigrationTests(unittest.TestCase):
    def test_removed_entrypoints_are_cleanup_only_permissions(self) -> None:
        scripts = ROOT / "scripts"
        desired = [
            *agy_permission_entries(scripts, spill_available=False),
            *claude_permission_entries(scripts, spill_available=False),
            *codex_prefix_rule_entries(scripts),
        ]
        cleanup = [
            *agy_legacy_permission_entries(scripts),
            *claude_legacy_permission_entries(scripts),
        ]

        for name in STALE_PERMISSION_ENTRYPOINTS:
            self.assertFalse(any(name in entry for entry in desired), name)
            self.assertTrue(any(name in entry for entry in cleanup), name)

    def test_permission_merge_removes_both_removed_entrypoints(self) -> None:
        scripts = ROOT / "scripts"
        for runtime, cleanup in (
            ("antigravity", agy_legacy_permission_entries(scripts)),
            ("claude", claude_legacy_permission_entries(scripts)),
        ):
            with self.subTest(runtime=runtime):
                stale = [
                    next(entry for entry in cleanup if name in entry)
                    for name in STALE_PERMISSION_ENTRYPOINTS
                ]
                self.assertEqual(len(STALE_PERMISSION_ENTRYPOINTS), len(stale))
                with tempfile.TemporaryDirectory() as temp_dir:
                    target = Path(temp_dir) / "settings.json"
                    target.write_text(
                        json.dumps({"permissions": {"allow": [*stale, "command(custom-tool)"]}}),
                        encoding="utf-8",
                    )

                    status = merge_permissions_allow(
                        target,
                        [],
                        dry_run=False,
                        cleanup_entries=cleanup,
                    )

                    allow = json.loads(target.read_text(encoding="utf-8"))["permissions"]["allow"]
                self.assertEqual("installed", status)
                self.assertEqual(["command(custom-tool)"], allow)

    def test_claude_cleanup_removes_former_git_wildcards(self) -> None:
        scripts = ROOT / "scripts"
        cleanup = claude_legacy_permission_entries(scripts)
        stale = [
            "Bash(git -C * show *)",
            "Bash(git -C * branch -v*)",
            "Bash(git status *)",
        ]
        self.assertTrue(all(entry in cleanup for entry in stale))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "settings.json"
            target.write_text(
                json.dumps({"permissions": {"allow": [*stale, "Bash(custom-tool)"]}}),
                encoding="utf-8",
            )

            merge_permissions_allow(
                target,
                [],
                dry_run=False,
                cleanup_entries=cleanup,
            )
            allow = json.loads(target.read_text(encoding="utf-8"))["permissions"]["allow"]

        self.assertEqual(["Bash(custom-tool)"], allow)

    def test_document_receipt_entrypoints_are_physically_removed(self) -> None:
        for script in STALE_PERMISSION_ENTRYPOINTS:
            with self.subTest(script=script):
                self.assertFalse((ROOT / "scripts" / script).exists())

    def test_removed_route_docs_module_cannot_be_imported(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_route_docs import route_fingerprint",
            ],
            cwd=ROOT / "scripts",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("ModuleNotFoundError", result.stderr)

    def test_agent_hook_and_stable_launcher_do_not_expose_docs_read_alias(self) -> None:
        direct = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent-hook.py"),
                "docs-read",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(2, direct.returncode)
        self.assertIn("invalid choice", direct.stderr)

        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher_text = stable_launcher_path().read_text(encoding="utf-8")
        self.assertNotIn('"docs-read"', launcher_text)

    def test_invalid_handoff_reserves_isolated_worker_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence = project / ".tao" / "preflight.json"
            output = project / "handoff.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-hook.py"),
                    "handoff",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--evidence",
                    str(evidence),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            capsule = payload["execution_capsule"]
            worker_preflight = Path(capsule["fallback_worker_preflight_evidence"])
            worker_ledger = Path(capsule["fallback_worker_gate_ledger"])
            worker_root = project.resolve() / ".tao" / "workers"

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(capsule["reusable"])
            self.assertTrue(worker_preflight.is_relative_to(worker_root))
            self.assertTrue(worker_ledger.is_relative_to(worker_root))
            self.assertNotEqual(evidence, worker_preflight)
            self.assertNotEqual(project / ".tao" / "gate-evidence.json", worker_ledger)
            self.assertEqual("preflight.json", worker_preflight.name)
            self.assertEqual("gate-evidence.json", worker_ledger.name)
            self.assertRegex(capsule["fallback_worker_reservation_token"], r"^[0-9a-f]{32}$")
            self.assertTrue(worker_root.is_dir())
            self.assertTrue(worker_preflight.parent.is_dir())
            self.assertEqual(0o700, worker_preflight.parent.stat().st_mode & 0o777)
            self.assertIn(
                f"--worker-reservation-token {capsule['fallback_worker_reservation_token']}",
                result.stdout,
            )
            self.assertIn(f"--evidence {worker_preflight}", result.stdout)
            self.assertNotIn("--worker-evidence", result.stdout)
            self.assertIn("must never write the parent ledger", result.stdout)

    @staticmethod
    def _init_git_repo(project: Path) -> None:
        """A committed repo lets isolated dispatch add a real worktree at launch."""

        project.mkdir(parents=True, exist_ok=True)
        (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        for args in (
            ("init", "-q"),
            ("config", "user.email", "tests@example.invalid"),
            ("config", "user.name", "Tao Agent OS Tests"),
            ("add", "-A"),
            ("commit", "-qm", "initial"),
        ):
            subprocess.run(
                ["git", *args],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def test_handoff_reserved_worker_path_is_consumed_without_second_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._init_git_repo(project)
            evidence = project / ".tao" / "preflight.json"
            output = project / "handoff.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-hook.py"),
                    "handoff",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--evidence",
                    str(evidence),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            capsule = json.loads(output.read_text(encoding="utf-8"))["execution_capsule"]
            worker_evidence = Path(capsule["fallback_worker_preflight_evidence"])
            token = capsule["fallback_worker_reservation_token"]
            accepted_classification = {
                "request": "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                "clarity": "clear-scoped",
                "effort": "standard",
                "question_drill": False,
                "response_mode": "work",
                "recommended_route": "",
            }

            manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                project,
                isolation_required=True,
                worker_evidence_path=worker_evidence,
                worker_reservation_token=token,
                request_classification=accepted_classification,
            )
            second_manifest = build_dispatch_manifest(
                "feature",
                "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                project,
                isolation_required=True,
                worker_evidence_path=worker_evidence,
                worker_reservation_token=token,
                request_classification=accepted_classification,
            )
            # Isolated manifests can no longer be executed through an injected
            # runner (Fix B); drive the real launch path with only the codex
            # process mocked so the reservation-token flow is still exercised.
            real_run = subprocess.run

            def fake_run(command, *args, **kwargs):
                if command and command[0] == "git":
                    return real_run(command, *args, **kwargs)
                return SimpleNamespace(returncode=0)

            self.assertTrue(manifest["handoff_state"]["worker_evidence_reserved"])
            with patch(
                "workflow_dispatch_launch.subprocess.run", side_effect=fake_run
            ) as launch:
                self.assertEqual(0, execute_dispatch_manifest(manifest))
            self.assertIn(token, launch.call_args.args[0][-1])

            self.assertTrue(claim_worker_reservation(worker_evidence.parent, token))
            with self.assertRaisesRegex(ValueError, "does not match"):
                execute_dispatch_manifest(second_manifest)

            with self.assertRaisesRegex(ValueError, "reservation token does not match"):
                build_dispatch_manifest(
                    "feature",
                    "기획변경 때 문서 정리가 누락되는 걸 막아줘",
                    project,
                    isolation_required=True,
                    worker_evidence_path=worker_evidence,
                    worker_reservation_token="0" * 32,
                    request_classification=accepted_classification,
                )

    def test_invalid_handoff_rejects_symlinked_worker_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            outside = root / "outside"
            evidence_root = project / ".tao"
            evidence_root.mkdir(parents=True)
            outside.mkdir()
            (evidence_root / "workers").symlink_to(outside, target_is_directory=True)
            output = project / "handoff.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-hook.py"),
                    "handoff",
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--evidence",
                    str(evidence_root / "preflight.json"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            capsule = json.loads(output.read_text(encoding="utf-8"))["execution_capsule"]
            self.assertEqual(1, result.returncode)
            self.assertFalse(capsule["reusable"])
            self.assertIsNone(capsule["fallback_worker_preflight_evidence"])
            self.assertIsNone(capsule["fallback_worker_gate_ledger"])
            self.assertIn("unsafe fallback evidence boundary", result.stdout)

    def test_worker_preflight_rejects_replaced_reserved_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            worker_root = project / ".tao" / "workers"
            outside = root / "outside"
            worker_root.mkdir(parents=True)
            outside.mkdir()
            worker_dir = worker_root / "worker-id"
            worker_dir.symlink_to(outside, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "task",
                    "--request",
                    "bounded worker task",
                    "--evidence",
                    str(worker_dir / "preflight.json"),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("must not be a symlink", result.stderr)
            self.assertFalse((outside / "preflight.json").exists())

    def test_worker_preflight_requires_and_consumes_single_use_reservation_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            worker = project / ".tao" / "workers" / "worker-id"
            worker.mkdir(parents=True)
            evidence = worker / "preflight.json"
            without_token = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "review",
                    "--request",
                    "Review only the current bounded worker fixture diff.",
                    "--read-only",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(2, without_token.returncode)
            self.assertIn("requires a single-use", without_token.stderr)

            token = create_worker_reservation(worker)
            request = "Review only the current bounded worker fixture diff."
            session_id = "worker-reservation-session"
            envelope = {
                "schema_version": 1,
                "request_fingerprint": request_fingerprint({"request": request}),
                "runtime_session_id": session_id,
                "mode": "work",
                "intent": "review",
                "target_summary": "the bounded worker fixture diff",
                "requested_effects": ["read"],
                "ambiguity": "resolved",
            }
            with_token = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "review",
                    "--request",
                    request,
                    "--intent-envelope",
                    json.dumps(envelope),
                    "--runtime-session-id",
                    session_id,
                    "--read-only",
                    "--evidence",
                    str(evidence),
                    "--worker-reservation-token",
                    token,
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(2, with_token.returncode, with_token.stderr)
            self.assertFalse(worker_reservation_matches(worker, token))

    def test_worker_route_rejection_keeps_reservation_for_corrected_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            worker = project / ".tao" / "workers" / "worker-id"
            worker.mkdir(parents=True)
            evidence = worker / "preflight.json"
            token = create_worker_reservation(worker)

            rejected = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "review",
                    "--request",
                    "Implement permission architecture",
                    "--read-only",
                    "--evidence",
                    str(evidence),
                    "--worker-reservation-token",
                    token,
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("intent envelope", rejected.stderr)
            self.assertTrue(worker_reservation_matches(worker, token))

            request = "Review only the current diff for notification permission correctness."
            session_id = "worker-retry-session"
            envelope = {
                "schema_version": 1,
                "request_fingerprint": request_fingerprint({"request": request}),
                "runtime_session_id": session_id,
                "mode": "work",
                "intent": "review",
                "target_summary": "the notification permission diff",
                "requested_effects": ["read"],
                "ambiguity": "resolved",
            }
            accepted = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-preflight.py"),
                    "--project",
                    str(project),
                    "--rules",
                    str(ROOT),
                    "--command",
                    "review",
                    "--request",
                    request,
                    "--intent-envelope",
                    json.dumps(envelope),
                    "--runtime-session-id",
                    session_id,
                    "--read-only",
                    "--evidence",
                    str(evidence),
                    "--worker-reservation-token",
                    token,
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertIn("Route: review", accepted.stdout)
            self.assertFalse(worker_reservation_matches(worker, token))

    def test_worker_gate_ledger_rejects_replaced_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            worker_root = project / ".tao" / "workers"
            outside = root / "outside"
            worker_root.mkdir(parents=True)
            outside.mkdir()
            worker_dir = worker_root / "worker-id"
            worker_dir.symlink_to(outside, target_is_directory=True)
            evidence_path = worker_dir / "preflight.json"
            preflight = {
                "route": {
                    "command": "task",
                    "required_docs": [],
                    "gates": ["verify"],
                }
            }
            (outside / "preflight.json").write_text(
                json.dumps(preflight), encoding="utf-8"
            )

            with self.assertRaises(OSError):
                record_gate_evidence(
                    evidence_path=evidence_path,
                    preflight=preflight,
                    gate="verify",
                    evidence="worker verification passed",
                )

            self.assertFalse((outside / "gate-evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
