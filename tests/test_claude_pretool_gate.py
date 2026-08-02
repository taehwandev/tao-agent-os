from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_GATE_SPEC = importlib.util.spec_from_file_location(
    "claude_pretool_gate_under_test", ROOT / "scripts" / "claude_pretool_gate.py"
)
assert _GATE_SPEC and _GATE_SPEC.loader
gate = importlib.util.module_from_spec(_GATE_SPEC)
_GATE_SPEC.loader.exec_module(gate)

from support.claude_setup import (
    _PRETOOL_GATE_ALIAS,
    _PRETOOL_GATE_MATCHER,
    _merge_claude_pre_tool_gate,
)
from support.setup_config_files import read_json
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import register_run
from agent_runtime_session import resolve_runtime_evidence


def _decide(payload: dict) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = gate.decide(payload)
    return code, buffer.getvalue()


def _reason(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def _opt_in_project(base: Path) -> Path:
    project = base / "proj"
    (project / ".tao").mkdir(parents=True)
    (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
    return project


def _write_preflight(project: Path, session_id: str | None = None) -> None:
    """Write preflight evidence the way `start` does, stamped with its session."""
    if session_id is None:
        (project / ".tao" / "preflight.json").write_text("{}", encoding="utf-8")
        return
    session = {"runtime": "claude", "session_id": session_id}
    if resolve_runtime_evidence(project, session) is not None:
        return
    route = {"command": "task", "gates": ["finish"], "required_docs": []}
    intake = {"request": "test request", "request_classified": False}
    run_id = uuid.uuid4().hex
    evidence = project / ".tao" / "runs" / run_id / "preflight.json"
    evidence.parent.mkdir(parents=True)
    registered = register_run(project, evidence, route, intake)
    assert registered["run_id"] == run_id
    payload = {
        "project": str(project),
        "rules": str(project),
        "route": route,
        "request_intake": intake,
        "runtime_session": session,
        "execution_snapshot": {
            "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
            "route_fingerprint": route_fingerprint(route),
            "request_fingerprint": request_fingerprint(intake),
            "required_docs": [],
        },
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    write_continuation_checkpoint(
        project=project,
        rules=project,
        run_id=run_id,
        kind="initial",
        binding_path=evidence,
        work={"objective": "task workflow"},
    )


def _write_custom_preflight(
    project: Path,
    session_id: str,
    relative_path: str = "preflight-hotfix.json",
) -> Path:
    """Write an explicit project-local evidence path accepted by ``start``."""
    session = {"runtime": "claude", "session_id": session_id}
    route = {"command": "task", "gates": ["finish"], "required_docs": []}
    intake = {"request": "test request", "request_classified": False}
    evidence = project / ".tao" / relative_path
    evidence.parent.mkdir(parents=True, exist_ok=True)
    register_run(project, evidence, route, intake)
    evidence.write_text(
        json.dumps(
            {
                "project": str(project),
                "rules": str(project),
                "route": route,
                "request_intake": intake,
                "runtime_session": session,
                "execution_snapshot": {
                    "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                    "route_fingerprint": route_fingerprint(route),
                    "request_fingerprint": request_fingerprint(intake),
                    "required_docs": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return evidence


def _age_preflight(
    project: Path, seconds: float, session_id: str | None = None
) -> None:
    preflight = (
        resolve_runtime_evidence(
            project, {"runtime": "claude", "session_id": session_id}
        )
        if session_id
        else None
    )
    candidates = list((project / ".tao").glob("runs/*/preflight.json"))
    preflight = preflight or (
        candidates[-1] if candidates else project / ".tao" / "preflight.json"
    )
    stamp = time.time() - seconds
    os.utime(preflight, (stamp, stamp))


# Gate 2 (sprawl) tests only need gate 1 satisfied; `start` stamping this
# session into the preflight is exactly what that means.
_satisfy_workflow_entry = _write_preflight


class ClaudePreToolGateTests(unittest.TestCase):
    def test_non_edit_tool_is_allowed(self) -> None:
        code, out = _decide({"tool_name": "Bash", "cwd": "/tmp", "session_id": "s"})
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_edit_outside_tao_project_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _decide(
                {"tool_name": "Edit", "cwd": tmp, "session_id": "s"}
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_edit_without_preflight_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            code, out = _decide(
                {"tool_name": "Edit", "cwd": str(project), "session_id": "s"}
            )
        self.assertEqual(0, code)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertIn("start hook", decision["permissionDecisionReason"])

    def test_start_then_edit_is_allowed_and_stays_allowed(self) -> None:
        # Regression: an ordering-based gate denied this, the *correct*, flow
        # outright -- evidence written before the first edit attempt can never
        # be newer than it, so a compliant session was permanently blocked.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "s5")
            target = project / "note.md"
            payload = {
                "tool_name": "Write",
                "cwd": str(project),
                "session_id": "s5",
                "tool_input": {"file_path": str(target)},
            }

            for attempt in range(3):
                code, out = _decide(payload)
                target.write_text(f"attempt {attempt}\n", encoding="utf-8")
                post = gate.ClaudeContinuationAdapter.post_mutation(
                    {**payload, "hook_event_name": "PostToolUse"}
                )
                with self.subTest(attempt=attempt):
                    self.assertEqual(0, code)
                    self.assertEqual("", out)
                    self.assertIsNone(post)

    def test_project_local_custom_preflight_allows_its_exact_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_custom_preflight(project, "custom-session")

            with patch.object(
                gate.ClaudeContinuationAdapter,
                "pre_mutation",
                side_effect=AssertionError("custom evidence has no continuation packet"),
            ):
                code, out = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(project),
                        "session_id": "custom-session",
                        "tool_input": {"file_path": str(project / "note.md")},
                    }
                )

            self.assertEqual(0, code)
            self.assertEqual("", out)

    def test_nested_project_local_preflight_allows_its_exact_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_custom_preflight(
                project,
                "nested-session",
                "custom/preflight-hotfix.json",
            )

            with patch.object(
                gate.ClaudeContinuationAdapter,
                "pre_mutation",
                side_effect=AssertionError(
                    "nested custom evidence has no continuation packet"
                ),
            ):
                code, out = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(project),
                        "session_id": "nested-session",
                        "tool_input": {"file_path": str(project / "note.md")},
                    }
                )

            self.assertEqual(0, code)
            self.assertEqual("", out)

    def test_parent_and_isolated_worker_same_session_each_open_their_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            session_id = "shared-session"
            parent = _write_custom_preflight(
                project,
                session_id,
                "custom/preflight-parent.json",
            )
            worker = _write_custom_preflight(
                project,
                session_id,
                "workers/0123456789abcdef/preflight.json",
            )
            payload = {
                "tool_name": "Write",
                "cwd": str(project),
                "session_id": session_id,
                "tool_input": {"file_path": str(project / "note.md")},
            }

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    parent.resolve(),
                    gate.session_evidence(project, session_id),
                )
                code, out = _decide(payload)
                self.assertEqual((0, ""), (code, out))
            with patch.dict(
                os.environ,
                {"TAO_WORKER_EVIDENCE": str(worker)},
                clear=True,
            ):
                self.assertEqual(
                    worker.resolve(),
                    gate.session_evidence(project, session_id),
                )
                code, out = _decide(payload)
                self.assertEqual((0, ""), (code, out))

    def test_invalid_worker_hint_denies_without_reusing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            session_id = "shared-session"
            _write_custom_preflight(project, session_id)
            invalid = (
                project / ".tao" / "workers" / "too" / "deep" / "preflight.json"
            )

            with patch.dict(
                os.environ,
                {"TAO_WORKER_EVIDENCE": str(invalid)},
                clear=True,
            ):
                code, out = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(project),
                        "session_id": session_id,
                        "tool_input": {"file_path": str(project / "note.md")},
                    }
                )

            self.assertEqual(0, code)
            self.assertEqual(
                "deny",
                json.loads(out)["hookSpecificOutput"]["permissionDecision"],
            )

    def test_claim_disappearing_before_mutation_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            evidence = _write_custom_preflight(project, "custom-session")

            with patch.object(
                gate,
                "session_evidence",
                side_effect=(evidence, None, None),
            ):
                code, out = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(project),
                        "session_id": "custom-session",
                        "tool_input": {"file_path": str(project / "note.md")},
                    }
                )

            self.assertEqual(0, code)
            self.assertEqual(
                "deny",
                json.loads(out)["hookSpecificOutput"]["permissionDecision"],
            )

    def test_preflight_from_another_session_does_not_open_the_gate(self) -> None:
        # Regression: preflight.json is shared across runtimes and outlives a
        # session, so freshness alone used to unlock an unrelated session.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "other-session")

            code, out = _decide(
                {"tool_name": "Write", "cwd": str(project), "session_id": "sX"}
            )

            self.assertEqual(0, code)
            self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_preflight_without_a_recorded_session_is_denied(self) -> None:
        # Evidence from a runtime that records no session (or a pre-upgrade
        # file) proves nothing about the session now asking to edit.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)

            code, out = _decide(
                {"tool_name": "Write", "cwd": str(project), "session_id": "sX"}
            )

            self.assertEqual(0, code)
            self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_own_session_evidence_still_expires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "s7")
            _age_preflight(project, gate.DEFAULT_MAX_AGE_SECONDS + 60, "s7")

            code, out = _decide(
                {"tool_name": "Write", "cwd": str(project), "session_id": "s7"}
            )

            self.assertEqual(0, code)
            self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_payload_without_a_session_id_is_denied(self) -> None:
        # Falling back to freshness here would reopen the original bypass for
        # any payload that omits the session.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "s1")

            code, out = _decide({"tool_name": "Write", "cwd": str(project), "session_id": ""})

            self.assertEqual(0, code)
            self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_env_kill_switch_disables_the_gate(self) -> None:
        # Escape hatch for a Claude Code older than the release that put
        # CLAUDE_CODE_SESSION_ID in the Bash subprocess environment.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            with patch.dict("os.environ", {"TAO_CLAUDE_GATE": "0"}):
                code, out = _decide(
                    {"tool_name": "Write", "cwd": str(project), "session_id": "s1"}
                )

            self.assertEqual(0, code)
            self.assertEqual("", out)

    def test_edit_is_gated_by_the_project_that_owns_the_file(self) -> None:
        # Regression: the gate resolved the project from cwd, so a session
        # sitting in one project could edit another project's files on the first
        # project's start. Observed live on a writing workspace.
        with tempfile.TemporaryDirectory() as tmp:
            here = _opt_in_project(Path(tmp) / "here")
            there = _opt_in_project(Path(tmp) / "there")
            _write_preflight(here, "s1")  # start ran here, not there

            code, out = _decide({
                "tool_name": "Write",
                "cwd": str(here),
                "session_id": "s1",
                "tool_input": {"file_path": str(there / "draft.md")},
            })

            self.assertEqual(0, code)
            self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_denied_gate_never_fabricates_a_continuation_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            _decide({"tool_name": "Write", "cwd": str(project), "session_id": "sX"})

            self.assertEqual(
                [], list((project / ".tao").glob("runs/*/continuation.json"))
            )

    def test_deny_reason_names_the_actual_cause(self) -> None:
        # Each cause has a different fix. Reporting "no fresh evidence" for a
        # preflight that is present and fresh sends the reader hunting for a
        # missing file instead of rerunning start.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            payload = {"tool_name": "Write", "cwd": str(project), "session_id": "s1"}

            _, missing = _decide(payload)
            self.assertIn("No exact registered preflight evidence", _reason(missing))

            _write_preflight(project)
            _, unstamped = _decide(payload)
            self.assertIn("default-path evidence", _reason(unstamped))

            _write_preflight(project, "another-session")
            _, foreign = _decide(payload)
            self.assertIn("another session is not reusable", _reason(foreign))

            _write_preflight(project, "s1")
            _age_preflight(project, gate.DEFAULT_MAX_AGE_SECONDS + 60, "s1")
            _, stale = _decide(payload)
            self.assertIn("older than the freshness window", _reason(stale))

    def test_deny_reason_uses_resolved_absolute_launcher_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))

            _, out = _decide(
                {"tool_name": "Edit", "cwd": str(project), "session_id": "s"}
            )

            reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn(str(gate.stable_launcher_path()), reason)
            self.assertNotIn("~/.tao", reason)

    def test_malformed_stdin_fails_open(self) -> None:
        with patch_stdin("not json{{"):
            code = gate.main()
        self.assertEqual(0, code)

    def test_nested_cwd_resolves_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            nested = project / "a" / "b"
            nested.mkdir(parents=True)
            code, out = _decide(
                {"tool_name": "Edit", "cwd": str(nested), "session_id": "s"}
            )
        self.assertEqual(0, code)
        self.assertEqual("deny", json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def _write_new_source(self, project: Path, session: str, relative: str) -> tuple[int, str]:
        # Gate 2 (sprawl) is what these tests exercise; put the session past
        # gate 1 explicitly rather than depending on preflight timing.
        _satisfy_workflow_entry(project, session)
        payload = {
            "tool_name": "Write",
            "cwd": str(project),
            "session_id": session,
            "tool_input": {"file_path": relative},
        }
        code, output = _decide(payload)
        if not output:
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"{relative}\n", encoding="utf-8")
            post = gate.ClaudeContinuationAdapter.post_mutation(
                {**payload, "hook_event_name": "PostToolUse"}
            )
            if post:
                raise AssertionError(post)
        return code, output

    def test_new_source_files_up_to_budget_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)
            for index in range(5):
                code, out = self._write_new_source(project, "sp", f"src/file{index}.py")
                self.assertEqual(0, code)
                self.assertEqual("", out, f"file{index} should be allowed")

    def test_new_source_file_past_budget_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)
            for index in range(5):
                self._write_new_source(project, "sp", f"src/file{index}.py")
            code, out = self._write_new_source(project, "sp", "src/file5.py")
        self.assertEqual(0, code)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertIn("proportionality gate", decision["permissionDecisionReason"])

    def test_ack_file_unlocks_further_new_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)
            for index in range(5):
                self._write_new_source(project, "sp", f"src/file{index}.py")
            ack = project / ".tao" / "claude-pretool-gate" / "sp.sprawl-ack"
            ack.parent.mkdir(parents=True, exist_ok=True)
            ack.write_text("each file owns a distinct platform adapter\n", encoding="utf-8")
            code, out = self._write_new_source(project, "sp", "src/file5.py")
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_non_source_new_files_are_never_counted(self) -> None:
        # Doc/content sprawl (e.g. a writing workspace) must not be blocked.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)
            for index in range(12):
                code, out = self._write_new_source(project, "sp", f"drafts/post{index}.md")
                self.assertEqual("", out, f"markdown draft {index} must be allowed")

    def test_overwriting_existing_source_file_is_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project)
            existing = project / "src" / "existing.py"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("value = 1\n", encoding="utf-8")
            # Fill the budget with new files, then overwrite the existing one.
            for index in range(5):
                self._write_new_source(project, "sp", f"src/new{index}.py")
            code, out = self._write_new_source(project, "sp", "src/existing.py")
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_new_file_budget_can_be_disabled_with_zero(self) -> None:
        import os as _os

        previous = _os.environ.get("TAO_CLAUDE_GATE_NEW_FILE_BUDGET")
        _os.environ["TAO_CLAUDE_GATE_NEW_FILE_BUDGET"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                project = _opt_in_project(Path(tmp))
                _write_preflight(project)
                for index in range(20):
                    code, out = self._write_new_source(project, "sp", f"src/file{index}.py")
                    self.assertEqual("", out)
        finally:
            if previous is None:
                _os.environ.pop("TAO_CLAUDE_GATE_NEW_FILE_BUDGET", None)
            else:
                _os.environ["TAO_CLAUDE_GATE_NEW_FILE_BUDGET"] = previous


class ClaudePreToolGateSetupTests(unittest.TestCase):
    def test_merge_installs_pre_tool_use_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            command = f"TAO_HOOK_SOFT_FAIL=1 launcher {_PRETOOL_GATE_ALIAS}"
            status = _merge_claude_pre_tool_gate(target, command, dry_run=False)
            self.assertEqual("installed", status)
            config = read_json(target)
            groups = config["hooks"]["PreToolUse"]
            group = next(g for g in groups if g.get("matcher") == _PRETOOL_GATE_MATCHER)
            self.assertEqual(command, group["hooks"][0]["command"])

    def test_merge_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            command = f"TAO_HOOK_SOFT_FAIL=1 launcher {_PRETOOL_GATE_ALIAS}"
            _merge_claude_pre_tool_gate(target, command, dry_run=False)
            status = _merge_claude_pre_tool_gate(target, command, dry_run=False)
            self.assertEqual("ok", status)
            config = read_json(target)
            matching = [
                g
                for g in config["hooks"]["PreToolUse"]
                if g.get("matcher") == _PRETOOL_GATE_MATCHER
            ]
            self.assertEqual(1, len(matching))


class patch_stdin:
    def __init__(self, text: str) -> None:
        self.text = text
        self._old = None

    def __enter__(self) -> None:
        self._old = sys.stdin
        sys.stdin = io.StringIO(self.text)

    def __exit__(self, *exc: object) -> None:
        sys.stdin = self._old


if __name__ == "__main__":
    unittest.main()
