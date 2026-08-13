from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_hook_gate_records import preflight_evidence_path
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import register_run, registry_path
import agent_run_registry
import agent_runtime_session
from agent_runtime_session import (
    bind_resumed_runtime_session,
    is_run_local_continuation_evidence,
    resolve_runtime_evidence,
)

ROUTE = {"command": "task", "gates": ["finish"], "required_docs": []}
INTAKE = {"request": "runtime fixture request", "request_classified": False}


@contextmanager
def unreadable_directory(test: unittest.TestCase, path: Path):
    """Make one directory refuse enumeration for the body of the test."""

    os.chmod(path, 0o000)
    try:
        try:
            os.listdir(path)
        except OSError:
            pass
        else:
            test.skipTest("this filesystem still enumerates a 0o000 directory")
        yield
    finally:
        os.chmod(path, 0o755)


class RuntimeFixture:
    def __init__(self, directory: str, *, session_id: str = "old-session") -> None:
        self.project = Path(directory) / "project"
        self.rules = Path(directory) / "rules"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        self.rules.mkdir()
        self.run_id = uuid.uuid4().hex
        self.evidence = (
            self.project / ".tao" / "runs" / self.run_id / "preflight.json"
        )
        self.evidence.parent.mkdir(parents=True)
        run = register_run(self.project, self.evidence, ROUTE, INTAKE)
        if run["run_id"] != self.run_id:
            raise AssertionError("fixture run id was not adopted")
        self.preflight = {
            "project": str(self.project),
            "rules": str(self.rules),
            "route": ROUTE,
            "request_intake": INTAKE,
            "runtime_session": {"runtime": "claude", "session_id": session_id},
            "execution_snapshot": {
                "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                "route_fingerprint": route_fingerprint(ROUTE),
                "request_fingerprint": request_fingerprint(INTAKE),
                "required_docs": [],
            },
        }
        self.evidence.write_text(json.dumps(self.preflight), encoding="utf-8")
        write_continuation_checkpoint(
            project=self.project,
            rules=self.rules,
            run_id=self.run_id,
            kind="initial",
            binding_path=self.evidence,
            work={"objective": "resume safe work"},
        )

    def packet(self) -> dict:
        return read_continuation_packet(
            self.project, continuation_path(self.project, self.run_id)
        )["packet"]

    def set_generation(self, generation: int) -> None:
        path = registry_path(self.project)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for run in payload["runs"]:
            if run["run_id"] == self.run_id:
                run["resume_generation"] = generation
        path.write_text(json.dumps(payload), encoding="utf-8")


class RuntimeEvidenceTests(unittest.TestCase):
    def test_runtime_session_detects_codex_thread(self) -> None:
        with patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "codex-session"},
            clear=True,
        ):
            self.assertEqual(
                {"runtime": "codex", "session_id": "codex-session"},
                agent_runtime_session.runtime_session(),
            )

    def test_run_local_continuation_eligibility_rejects_custom_and_spoofed_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            custom = fixture.project / ".tao" / "preflight-hotfix.json"
            custom.write_text("{}", encoding="utf-8")
            spoofed = (
                fixture.project
                / ".tao"
                / "runs"
                / "not-an-opaque-run"
                / "preflight.json"
            )
            spoofed.parent.mkdir(parents=True)
            spoofed.write_text("{}", encoding="utf-8")

            self.assertTrue(
                is_run_local_continuation_evidence(
                    fixture.project, fixture.evidence
                )
            )
            self.assertFalse(
                is_run_local_continuation_evidence(fixture.project, custom)
            )
            self.assertFalse(
                is_run_local_continuation_evidence(fixture.project, spoofed)
            )

    def test_exact_session_resolves_project_local_custom_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            evidence = project / ".tao" / "preflight-hotfix.json"
            evidence.parent.mkdir()
            register_run(project, evidence, ROUTE, INTAKE)
            evidence.write_text(
                json.dumps(
                    {
                        "runtime_session": {
                            "runtime": "claude",
                            "session_id": "custom-session",
                        }
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_runtime_evidence(
                project,
                {"runtime": "claude", "session_id": "custom-session"},
            )

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(evidence.resolve(), resolved.resolve())
            self.assertIsNone(
                resolve_runtime_evidence(
                    project,
                    {"runtime": "claude", "session_id": "other-session"},
                )
            )

            registry = registry_path(project)
            state = json.loads(registry.read_text(encoding="utf-8"))
            state["runs"][0]["resume_generation"] = 1
            registry.write_text(json.dumps(state), encoding="utf-8")
            self.assertIsNone(
                resolve_runtime_evidence(
                    project,
                    {"runtime": "claude", "session_id": "custom-session"},
                )
            )

    def test_nested_project_local_candidate_uses_exact_registry_evidence_key(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            registered = project / ".tao" / "nested" / "preflight-hotfix.json"
            registered.parent.mkdir(parents=True)
            register_run(project, registered, ROUTE, INTAKE)
            payload = {
                "runtime_session": {
                    "runtime": "claude",
                    "session_id": "custom-session",
                }
            }
            registered.write_text(json.dumps(payload), encoding="utf-8")
            forged = project / ".tao" / registered.name
            forged.write_text(json.dumps(payload), encoding="utf-8")

            resolved = resolve_runtime_evidence(
                project,
                {"runtime": "claude", "session_id": "custom-session"},
            )

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(registered.resolve(), resolved.resolve())

    def test_multiple_exact_custom_session_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            payload = {
                "runtime_session": {
                    "runtime": "claude",
                    "session_id": "ambiguous-session",
                }
            }
            for name in ("preflight-one.json", "preflight-two.json"):
                evidence = project / ".tao" / name
                evidence.parent.mkdir(exist_ok=True)
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(json.dumps(payload), encoding="utf-8")

            self.assertIsNone(
                resolve_runtime_evidence(
                    project,
                    {"runtime": "claude", "session_id": "ambiguous-session"},
                )
            )

    def test_unreadable_unrelated_state_skips_only_that_subtree(self) -> None:
        # Given a session whose only active binding is readable, when unrelated
        # concurrent-run state under `.tao` cannot be enumerated, the session
        # still resolves its own evidence instead of losing every edit to state
        # the decision never depended on.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {"runtime": "claude", "session_id": "walk-session"}
            evidence = project / ".tao" / "preflight-parent.json"
            evidence.parent.mkdir()
            register_run(project, evidence, ROUTE, INTAKE)
            evidence.write_text(
                json.dumps({"runtime_session": session}), encoding="utf-8"
            )
            unrelated = project / ".tao" / "worktrees" / "stale"
            unrelated.mkdir(parents=True)

            with unreadable_directory(self, unrelated):
                self.assertEqual(
                    evidence.resolve(),
                    resolve_runtime_evidence(project, session),
                )

    def test_unreadable_state_hiding_a_second_binding_fails_closed(self) -> None:
        # Negative control for the case above: when the subtree the scan had to
        # skip is the one holding a second active binding for the same session,
        # the single-match rule must still refuse rather than resolve the one
        # claim that happened to stay visible.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {"runtime": "claude", "session_id": "walk-session"}
            payload = json.dumps({"runtime_session": session})
            visible = project / ".tao" / "preflight-one.json"
            visible.parent.mkdir()
            hidden_root = project / ".tao" / "hidden"
            hidden_root.mkdir()
            hidden = hidden_root / "preflight-two.json"
            for evidence in (visible, hidden):
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(payload, encoding="utf-8")

            with unreadable_directory(self, hidden_root):
                self.assertIsNone(resolve_runtime_evidence(project, session))

    def test_active_worker_claim_does_not_deny_the_parent_on_an_incomplete_scan(
        self,
    ) -> None:
        # Worker evidence is out of the parent's candidate scope but its
        # registry claim still exists. If it were simply dropped, no scan could
        # ever account for that key, so every unreadable subtree would deny an
        # otherwise healthy parent session.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {"runtime": "claude", "session_id": "walk-session"}
            payload = json.dumps({"runtime_session": session})
            parent = project / ".tao" / "preflight-parent.json"
            worker = (
                project / ".tao" / "workers" / "0123456789abcdef" / "preflight.json"
            )
            for evidence in (parent, worker):
                evidence.parent.mkdir(parents=True, exist_ok=True)
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(payload, encoding="utf-8")
            unrelated = project / ".tao" / "worktrees" / "stale"
            unrelated.mkdir(parents=True)

            with patch.dict(os.environ, {}, clear=True):
                with unreadable_directory(self, unrelated):
                    self.assertEqual(
                        parent.resolve(),
                        resolve_runtime_evidence(project, session),
                    )

    def test_unreadable_worker_root_does_not_deny_the_parent(self) -> None:
        # The worker root is enumerated only to account for a worker's registry
        # claim; no file under it can ever become a parent candidate. An error
        # reading it therefore says nothing about the parent's decision and
        # must not make the scan count as incomplete.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {"runtime": "claude", "session_id": "walk-session"}
            payload = json.dumps({"runtime_session": session})
            parent = project / ".tao" / "preflight-parent.json"
            worker = (
                project / ".tao" / "workers" / "0123456789abcdef" / "preflight.json"
            )
            for evidence in (parent, worker):
                evidence.parent.mkdir(parents=True, exist_ok=True)
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(payload, encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with unreadable_directory(self, project / ".tao" / "workers"):
                    self.assertEqual(
                        parent.resolve(),
                        resolve_runtime_evidence(project, session),
                    )

    def test_parent_and_isolated_worker_resolve_inside_their_own_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {
                "runtime": "claude",
                "session_id": "shared-session",
            }
            parent = project / ".tao" / "custom" / "preflight-parent.json"
            worker = (
                project
                / ".tao"
                / "workers"
                / "0123456789abcdef"
                / "preflight.json"
            )
            for evidence in (parent, worker):
                evidence.parent.mkdir(parents=True, exist_ok=True)
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(
                    json.dumps({"runtime_session": session}),
                    encoding="utf-8",
                )

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    parent.resolve(),
                    resolve_runtime_evidence(project, session),
                )
            with patch.dict(
                os.environ,
                {"TAO_WORKER_EVIDENCE": str(worker)},
                clear=True,
            ):
                self.assertEqual(
                    worker.resolve(),
                    resolve_runtime_evidence(project, session),
                )

    def test_invalid_or_foreign_worker_hint_fails_without_parent_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            session = {
                "runtime": "claude",
                "session_id": "shared-session",
            }
            parent = project / ".tao" / "preflight-parent.json"
            parent.parent.mkdir()
            register_run(project, parent, ROUTE, INTAKE)
            parent.write_text(
                json.dumps({"runtime_session": session}),
                encoding="utf-8",
            )
            invalid_hints = (
                project / ".tao" / "workers" / "too" / "deep" / "preflight.json",
                root / "foreign" / ".tao" / "workers" / "one" / "preflight.json",
            )

            for hint in invalid_hints:
                with self.subTest(hint=hint):
                    with patch.dict(
                        os.environ,
                        {"TAO_WORKER_EVIDENCE": str(hint)},
                        clear=True,
                    ):
                        self.assertIsNone(
                            resolve_runtime_evidence(project, session)
                        )

    def test_candidate_and_registry_enumeration_are_bounded_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            session = {
                "runtime": "claude",
                "session_id": "shared-session",
            }
            for index in range(3):
                evidence = (
                    project
                    / ".tao"
                    / f"nested-{index}"
                    / f"preflight-{index}.json"
                )
                evidence.parent.mkdir(parents=True)
                register_run(project, evidence, ROUTE, INTAKE)
                evidence.write_text(
                    json.dumps({"runtime_session": session}),
                    encoding="utf-8",
                )

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    agent_runtime_session,
                    "active_run_bindings",
                    wraps=agent_runtime_session.active_run_bindings,
                ) as bindings:
                    with patch.object(
                        agent_runtime_session,
                        "_runtime_evidence_candidates",
                        wraps=agent_runtime_session._runtime_evidence_candidates,
                    ) as candidates:
                        self.assertIsNone(
                            resolve_runtime_evidence(project, session)
                        )

            bindings.assert_called_once_with(project.resolve())
            candidates.assert_called_once()

    def test_exact_session_resolves_only_its_run_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)

            resolved = resolve_runtime_evidence(
                fixture.project,
                {"runtime": "claude", "session_id": "old-session"},
            )

            self.assertEqual(fixture.evidence.resolve(), resolved.resolve())
            self.assertIsNone(
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "other-session"},
                )
            )

    def test_resume_binding_replaces_the_session_and_refreshes_packet_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()["binding"]["file_sha256"]
            fixture.set_generation(1)

            bind_resumed_runtime_session(
                project=fixture.project,
                evidence_path=fixture.evidence,
                run_id=fixture.run_id,
                resume_generation=1,
                runtime="claude",
                session_id="new-session",
            )

            self.assertIsNone(
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "old-session"},
                )
            )
            self.assertEqual(
                fixture.evidence.resolve(),
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "new-session"},
                ).resolve(),
            )
            self.assertNotEqual(before, fixture.packet()["binding"]["file_sha256"])

    def test_start_without_explicit_evidence_allocates_one_stable_run_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            args = Namespace(project=project, evidence=None, hook="start")
            with patch.dict(
                "os.environ", {"CLAUDE_CODE_SESSION_ID": "session-1"}, clear=True
            ):
                first = preflight_evidence_path(args)
                second = preflight_evidence_path(args)

            self.assertEqual(first, second)
            self.assertEqual("preflight.json", first.name)
            self.assertEqual(project / ".tao" / "runs", first.parent.parent)
            self.assertEqual(32, len(first.parent.name))

    def test_generic_start_without_explicit_evidence_is_run_local(self) -> None:
        """A runtime without a session id still gets an isolated gate ledger."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            args = Namespace(project=project, evidence=None, hook="start")
            with patch.dict("os.environ", {}, clear=True):
                first = preflight_evidence_path(args)
                second = preflight_evidence_path(args)

            self.assertEqual(first, second)
            self.assertEqual("preflight.json", first.name)
            self.assertEqual(project / ".tao" / "runs", first.parent.parent)
            self.assertEqual(32, len(first.parent.name))


class SupersededSessionRunTests(unittest.TestCase):
    """A session that leaks runs must not deny its own next edit."""

    @staticmethod
    def _extra_run(fixture: RuntimeFixture, *, session_id: str) -> str:
        run_id = uuid.uuid4().hex
        evidence = fixture.project / ".tao" / "runs" / run_id / "preflight.json"
        evidence.parent.mkdir(parents=True)
        register_run(fixture.project, evidence, ROUTE, INTAKE)
        preflight = dict(fixture.preflight)
        preflight["runtime_session"] = {
            "runtime": "claude",
            "session_id": session_id,
        }
        evidence.write_text(json.dumps(preflight), encoding="utf-8")
        return run_id

    @staticmethod
    def _states(project: Path) -> dict[str, str]:
        payload = json.loads(registry_path(project).read_text(encoding="utf-8"))
        return {run["run_id"]: run["state"] for run in payload["runs"]}

    def test_second_run_in_one_session_denies_the_edit_gate_until_settled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory, session_id="claude-session")
            kept = self._extra_run(fixture, session_id="claude-session")
            session = {"runtime": "claude", "session_id": "claude-session"}

            # Two matching claims are the reported bug: the single-match rule
            # cannot tell which one owns an edit, so it denies every edit.
            self.assertIsNone(resolve_runtime_evidence(fixture.project, session))

            with patch.dict(
                os.environ, {"CLAUDE_CODE_SESSION_ID": "claude-session"}, clear=True
            ):
                settled = agent_runtime_session.settle_superseded_session_runs(
                    fixture.project, keep_run_id=kept
                )

            self.assertEqual([fixture.run_id], settled)
            self.assertEqual("cancelled", self._states(fixture.project)[fixture.run_id])
            self.assertEqual(
                (
                    fixture.project / ".tao" / "runs" / kept / "preflight.json"
                ).resolve(),
                resolve_runtime_evidence(fixture.project, session),
            )

    def test_another_runtime_session_keeps_its_active_run(self) -> None:
        """Settling is session-scoped; a concurrent runtime must survive it."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory, session_id="codex-session")
            kept = self._extra_run(fixture, session_id="claude-session")

            with patch.dict(
                os.environ, {"CLAUDE_CODE_SESSION_ID": "claude-session"}, clear=True
            ):
                settled = agent_runtime_session.settle_superseded_session_runs(
                    fixture.project, keep_run_id=kept
                )

            self.assertEqual([], settled)
            self.assertEqual("running", self._states(fixture.project)[fixture.run_id])

    def test_run_completed_after_selection_is_not_overwritten_or_reported(self) -> None:
        """A concurrent finish wins over the later supersession attempt."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory, session_id="claude-session")
            kept = self._extra_run(fixture, session_id="claude-session")
            real_cancel = agent_run_registry.cancel_active_run_if_current

            def complete_then_try_cancel(
                project: Path,
                evidence: Path,
                *,
                run_id: str,
                expected_resume_generation: int,
                expected_started_at: str,
            ) -> dict | None:
                agent_run_registry.transition_run(
                    project, evidence, "completed", run_id=run_id
                )
                return real_cancel(
                    project,
                    evidence,
                    run_id=run_id,
                    expected_resume_generation=expected_resume_generation,
                    expected_started_at=expected_started_at,
                )

            with (
                patch.dict(
                    os.environ,
                    {"CLAUDE_CODE_SESSION_ID": "claude-session"},
                    clear=True,
                ),
                patch.object(
                    agent_runtime_session,
                    "cancel_active_run_if_current",
                    side_effect=complete_then_try_cancel,
                ),
            ):
                settled = agent_runtime_session.settle_superseded_session_runs(
                    fixture.project, keep_run_id=kept
                )

            self.assertEqual([], settled)
            self.assertEqual("completed", self._states(fixture.project)[fixture.run_id])

    def test_worker_start_settles_nothing(self) -> None:
        """A worker's claim runs alongside its parent's, so neither cancels it."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory, session_id="claude-session")
            kept = self._extra_run(fixture, session_id="claude-session")

            with patch.dict(
                os.environ,
                {
                    "CLAUDE_CODE_SESSION_ID": "claude-session",
                    "TAO_WORKER_EVIDENCE": str(fixture.evidence),
                },
                clear=True,
            ):
                settled = agent_runtime_session.settle_superseded_session_runs(
                    fixture.project, keep_run_id=kept
                )

            self.assertEqual([], settled)
            self.assertEqual("running", self._states(fixture.project)[fixture.run_id])

    def test_no_runtime_session_settles_nothing(self) -> None:
        """Without a session id there is no claim this start supersedes."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory, session_id="claude-session")
            kept = self._extra_run(fixture, session_id="claude-session")

            with patch.dict(os.environ, {}, clear=True):
                settled = agent_runtime_session.settle_superseded_session_runs(
                    fixture.project, keep_run_id=kept
                )

            self.assertEqual([], settled)
            self.assertEqual("running", self._states(fixture.project)[fixture.run_id])


if __name__ == "__main__":
    unittest.main()
