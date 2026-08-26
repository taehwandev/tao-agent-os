from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
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
    _EDIT_TOOL_MATCHER,
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
import claude_worktree_gate as worktree_gate


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


def _require_linked_worktree(project: Path, *, linked: bool = False) -> None:
    git_marker = project / ".git"
    if linked:
        git_marker.write_text("gitdir: ../common/worktrees/proj\n", encoding="utf-8")
    else:
        git_marker.mkdir()
    policy = project / gate.WORKTREE_POLICY_PATH
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "require_linked_worktree": True,
                "protected_branches": ["develop", "main"],
            }
        ),
        encoding="utf-8",
    )


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


# The gate stops a call by asking rather than refusing: a refusal is final in
# the runtime and left the operator unable to approve work in their own
# repository -- including the edit that would change this gate, and the setting
# that would turn it off. These tests assert that the call is stopped and why,
# which is the contract; the word is the runtime's way of asking.
STOP_DECISION = "ask"


class ClaudePreToolGateTests(unittest.TestCase):
    def test_bash_outside_tao_project_is_allowed(self) -> None:
        code, out = _decide({"tool_name": "Bash", "cwd": "/tmp", "session_id": "s"})
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_read_only_bash_in_required_main_checkout_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "s",
                    "tool_input": {"command": "git status -sb"},
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_print_only_sed_is_allowed_in_required_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "sed-read",
                    "tool_input": {"command": "sed -n '1,420p' AGENTS.md"},
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_sed_write_program_is_denied_in_required_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "sed-write",
                    "tool_input": {"command": "sed -n '1w output.txt' AGENTS.md"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_vibeguard_audit_is_allowed_but_fix_is_denied_in_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            read_code, read_out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "audit-read",
                    "tool_input": {"command": "vibeguard audit ."},
                }
            )
            write_code, write_out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "audit-fix",
                    "tool_input": {"command": "vibeguard audit . --fix"},
                }
            )
        self.assertEqual(0, read_code)
        self.assertEqual("", read_out)
        self.assertEqual(0, write_code)
        self.assertIn("worktree gate", _reason(write_out))

    def test_npx_vibeguard_audit_is_allowed_but_fix_is_denied_in_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            read_code, read_out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "npx-audit-read",
                    "tool_input": {
                        "command": "npx --yes @taehwandev/vibeguard@latest audit ."
                    },
                }
            )
            write_code, write_out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "npx-audit-fix",
                    "tool_input": {
                        "command": "npx --yes @taehwandev/vibeguard@latest audit . --fix"
                    },
                }
            )
        self.assertEqual(0, read_code)
        self.assertEqual("", read_out)
        self.assertEqual(0, write_code)
        self.assertIn("worktree gate", _reason(write_out))

    def test_worktree_bootstrap_bash_is_allowed_in_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "s",
                    "tool_input": {"command": "git worktree add ../task origin/develop"},
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_exact_runtime_launcher_start_is_denied_in_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"{gate.stable_launcher_path()} start --project {project}"
                    },
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_exact_runtime_launcher_start_is_allowed_in_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project, linked=True)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"{gate.stable_launcher_path()} start --project {project}"
                    },
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_start_targeting_the_linked_worktree_is_allowed_from_main_checkout(self) -> None:
        """The denial's own remedy must be runnable from where the session sits.

        A session launched in the protected main checkout is told to select the
        linked worktree and run start there, but the session cwd stayed in the
        governed roots, so the gate denied the exact relocation it demanded.
        The start hook claims only the project it names; its worktree policy is
        judged by that target, not by every checkout the session can see.
        """

        with tempfile.TemporaryDirectory() as tmp:
            main = _opt_in_project(Path(tmp))
            _require_linked_worktree(main)
            worktree = Path(tmp) / "wt"
            (worktree / ".tao").mkdir(parents=True)
            (worktree / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            (worktree / ".git").write_text("gitdir: ../proj/.git/worktrees/wt\n", encoding="utf-8")
            policy = worktree / gate.WORKTREE_POLICY_PATH
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text(
                (main / gate.WORKTREE_POLICY_PATH).read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            explicit_target = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(main),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"{gate.stable_launcher_path()} start --project {worktree}"
                    },
                }
            )
            cd_prefix = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(main),
                    "session_id": "s",
                    "tool_input": {
                        "command": (
                            f"cd {worktree} && {gate.stable_launcher_path()} start --project ."
                        )
                    },
                }
            )
            main_target_from_worktree = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(worktree),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"{gate.stable_launcher_path()} start --project {main}"
                    },
                }
            )

        self.assertEqual((0, ""), explicit_target)
        self.assertEqual((0, ""), cd_prefix)
        self.assertIn("worktree gate", _reason(main_target_from_worktree[1]))

    def test_runtime_cancel_remains_available_in_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "s",
                    "tool_input": {
                        "command": f"{gate.stable_launcher_path()} cancel --project {project}"
                    },
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_mutating_bash_is_denied_in_required_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "bash-main",
                    "tool_input": {"command": "python3 mutate.py"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_local_environment_can_bridge_policy_until_the_tracked_marker_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            (project / ".git").mkdir()
            with patch.dict(
                os.environ,
                {
                    gate.REQUIRE_LINKED_WORKTREE_ENV: "1",
                    "CLAUDE_PROJECT_DIR": str(project),
                },
            ):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(project),
                        "session_id": "local-policy",
                        "tool_input": {"command": "python3 mutate.py"},
                    }
                )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_read_command_cannot_hide_mutation_in_a_shell_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "shell-chain",
                    "tool_input": {"command": "git status && python3 mutate.py"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_read_command_cannot_hide_mutation_after_a_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "newline-chain",
                    "tool_input": {"command": "git status\npython3 mutate.py"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_fake_runtime_launcher_name_is_not_a_bootstrap_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "fake-launcher",
                    "tool_input": {"command": "./tao-hook start"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_malformed_tracked_policy_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            (project / ".git").mkdir()
            policy = project / gate.WORKTREE_POLICY_PATH
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text("{}", encoding="utf-8")
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "bad-policy",
                    "tool_input": {"command": "python3 mutate.py"},
                }
            )
        self.assertEqual(0, code)
        self.assertIn("worktree gate", _reason(out))

    def test_protected_branch_is_denied_even_in_a_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project, linked=True)
            with patch.object(worktree_gate, "current_branch", return_value="develop"):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(project),
                        "session_id": "protected-branch",
                        "tool_input": {"command": "python3 mutate.py"},
                    }
                )
        self.assertEqual(0, code)
        self.assertIn("protected branch", _reason(out))

    def test_mutating_bash_in_linked_worktree_requires_its_own_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project, linked=True)
            payload = {
                "tool_name": "Bash",
                "cwd": str(project),
                "session_id": "bash-linked",
                "tool_input": {"command": "python3 mutate.py"},
            }
            code, out = _decide(payload)
            self.assertIn("start hook", _reason(out))
            with (
                patch.object(gate, "workflow_entry_allows", return_value=True),
                patch.object(gate, "session_evidence", return_value=project / "preflight.json"),
                patch.object(gate, "is_run_local_continuation_evidence", return_value=False),
            ):
                code_after_start, out_after_start = _decide(payload)
        self.assertEqual(0, code)
        self.assertEqual(0, code_after_start)
        self.assertEqual("", out_after_start)

    def test_main_checkout_override_requires_the_explicit_environment_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _require_linked_worktree(project)
            with (
                patch.dict(os.environ, {gate.MAIN_CHECKOUT_OVERRIDE_ENV: "1"}),
                patch.object(gate, "workflow_entry_allows", return_value=True),
                patch.object(gate, "session_evidence", return_value=project / "preflight.json"),
                patch.object(gate, "is_run_local_continuation_evidence", return_value=False),
            ):
                code, out = _decide(
                    {
                        "tool_name": "Bash",
                        "cwd": str(project),
                        "session_id": "bash-override",
                        "tool_input": {"command": "python3 mutate.py"},
                    }
                )
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
        self.assertEqual(STOP_DECISION, decision["permissionDecision"])
        self.assertIn("start hook", decision["permissionDecisionReason"])
        # A stop the operator can act on names both ways out: approve it here,
        # or turn the gate off. The refusal this replaced named neither, so the
        # only escape was an environment variable nothing mentioned.
        self.assertIn("Approve to proceed", decision["permissionDecisionReason"])
        self.assertIn("TAO_CLAUDE_GATE=0", decision["permissionDecisionReason"])
        # An edit is what this reader did, so it is what the message names.
        self.assertIn("before editing files", decision["permissionDecisionReason"])
        self.assertIn("retry the edit", decision["permissionDecisionReason"])

    def test_a_stopped_command_is_not_described_as_a_file_edit(self) -> None:
        """The gate covered edits when this message was written.

        It has covered commands since, and kept telling whoever ran
        `git commit` to run start "before editing files" and then "retry the
        edit" -- naming a file they had not touched.
        """

        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            code, out = _decide(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m x"},
                    "cwd": str(project),
                    "session_id": "s",
                }
            )

        self.assertEqual(0, code)
        reason = _reason(out)
        self.assertIn("running a command that changes this project", reason)
        self.assertIn("retry the command", reason)
        self.assertNotIn("editing files", reason)
        self.assertNotIn("retry the edit", reason)

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
                STOP_DECISION,
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
                STOP_DECISION,
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
            self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

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
            self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_own_session_evidence_still_expires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "s7")
            _age_preflight(project, gate.DEFAULT_MAX_AGE_SECONDS + 60, "s7")

            code, out = _decide(
                {"tool_name": "Write", "cwd": str(project), "session_id": "s7"}
            )

            self.assertEqual(0, code)
            self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

    def test_payload_without_a_session_id_is_denied(self) -> None:
        # Falling back to freshness here would reopen the original bypass for
        # any payload that omits the session.
        with tempfile.TemporaryDirectory() as tmp:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "s1")

            code, out = _decide({"tool_name": "Write", "cwd": str(project), "session_id": ""})

            self.assertEqual(0, code)
            self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

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
            self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

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
        self.assertEqual(STOP_DECISION, json.loads(out)["hookSpecificOutput"]["permissionDecision"])

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
        self.assertEqual(STOP_DECISION, decision["permissionDecision"])
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


class ImportCostTests(unittest.TestCase):
    """This gate runs in its own process on every gated tool call.

    A session makes far more Bash calls than edits, and only an edit needs the
    continuation adapter. Importing its checkpoint, drift and
    worktree-fingerprint chain at module load put that cost on every call.
    Loading is what is pinned here, in a fresh interpreter, because this test
    module imports the same chain itself.
    """

    CHAIN = ("claude_continuation_hook", "agent_continuation_checkpoint")

    def _loaded_chain(self, payload: dict, state_home: str) -> list[str]:
        probe = "\n".join(
            [
                "import io, json, sys",
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r})",
                "from contextlib import redirect_stdout",
                "import claude_pretool_gate as gate",
                f"payload = json.loads({json.dumps(json.dumps(payload))})",
                "with redirect_stdout(io.StringIO()):",
                "    gate.decide(payload)",
                f"loaded = [m for m in {self.CHAIN!r} if m in sys.modules]",
                "print(json.dumps(loaded))",
            ]
        )
        # The gate records the session's project as it decides. Without its own
        # state home this probe writes into the real one, where another test is
        # entitled to find nothing.
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, STATE_HOME_ENV: state_home},
        )
        return json.loads(completed.stdout)

    def test_a_bash_call_does_not_load_the_continuation_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            project = _opt_in_project(Path(tmp))

            loaded = self._loaded_chain(
                {
                    "tool_name": "Bash",
                    "cwd": str(project),
                    "session_id": "import-cost-session",
                    "tool_input": {"command": "git status --short"},
                },
                state,
            )

        self.assertEqual([], loaded)

    def test_an_edit_still_loads_the_adapter_it_needs(self) -> None:
        """Laziness that never loads is a feature quietly removed."""

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            project = _opt_in_project(Path(tmp))
            _write_preflight(project, "import-cost-session")

            loaded = self._loaded_chain(
                {
                    "tool_name": "Write",
                    "cwd": str(project),
                    "session_id": "import-cost-session",
                    "tool_input": {"file_path": str(project / "note.md")},
                },
                state,
            )

        self.assertEqual(sorted(self.CHAIN), sorted(loaded))


class ClaudePreToolGateSetupTests(unittest.TestCase):
    def test_bash_is_added_only_to_the_workflow_gate_matcher(self) -> None:
        self.assertIn("Bash", _PRETOOL_GATE_MATCHER.split("|"))
        self.assertNotIn("Bash", _EDIT_TOOL_MATCHER.split("|"))

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


def _load_stop_gate():
    """The stop gate must agree with the pretool gate on what a project is."""
    spec = importlib.util.spec_from_file_location(
        "claude_stop_gate_under_test", ROOT / "scripts" / "claude_stop_gate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


from support.global_state import STATE_HOME_ENV


class IsolatedGlobalStateTestCase(unittest.TestCase):
    """Point the global state home at a temp directory for the whole test.

    The gate records every project a session edits into the global state home.
    Without this, running the suite appended these tests' temporary project paths
    to the real user's session index, which the Stop gate then walks.
    """

    def setUp(self) -> None:
        super().setUp()
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        patcher = patch.dict(os.environ, {STATE_HOME_ENV: state.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state_home = Path(state.name)


class ProjectRootIsTheRepositoryTests(unittest.TestCase):
    """A repository's docs subdirectory carries its own `AGENTS.md`.

    Marker opt-in alone then read that subdirectory as a project and it shadowed
    the repository that owned the work, so three things resolved against the
    wrong root at once: run evidence landed outside the repository, the VibeGuard
    scan root was not a Git checkout, and the skill catalog looked for project
    skills one level too deep. A project root is a repository root.
    """

    def setUp(self) -> None:
        super().setUp()
        self._old_home = os.environ.get("HOME")

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home

    @staticmethod
    def _repo(root: Path) -> None:
        (root / ".git").mkdir(parents=True)
        (root / "AGENTS.md").write_text("# tao-agent project\n")

    def test_docs_subdirectory_resolves_to_the_repository(self) -> None:
        stop_gate = _load_stop_gate()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            repo = home / "git" / "project"
            self._repo(repo)
            docs = repo / ".agents"
            docs.mkdir()
            (docs / "AGENTS.md").write_text("# tao-agent shared docs\n")
            deep = docs / "shared" / "llm-skills" / "task"
            deep.mkdir(parents=True)

            for start in (deep, docs):
                with self.subTest(start=start.name):
                    self.assertEqual(repo, gate.find_project_root(start))
                    self.assertEqual(repo, stop_gate.find_project_root(start))

    def test_linked_worktree_is_its_own_project(self) -> None:
        # Nearest repository, not outermost: a worktree owns its own run.
        stop_gate = _load_stop_gate()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            repo = home / "git" / "project"
            self._repo(repo)
            worktree = repo / ".tao" / "worktrees" / "TASK-1"
            worktree.mkdir(parents=True)
            # A linked worktree records .git as a file.
            (worktree / ".git").write_text("gitdir: ../../../.git/worktrees/TASK-1\n")
            (worktree / "AGENTS.md").write_text("# tao-agent project\n")
            inside = worktree / "app" / "src"
            inside.mkdir(parents=True)

            self.assertEqual(worktree, gate.find_project_root(inside))
            self.assertEqual(worktree, stop_gate.find_project_root(inside))

    def test_a_non_repository_marker_directory_still_opts_in(self) -> None:
        # The runtime checkout itself is not a Git repository here; a deliberate
        # marker must keep working when no candidate is a repository.
        stop_gate = _load_stop_gate()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            os.environ["HOME"] = str(home)

            plain = home / "tools" / "runtime"
            plain.mkdir(parents=True)
            (plain / "AGENTS.md").write_text("# tao-agent runtime\n")
            inside = plain / "scripts"
            inside.mkdir()

            self.assertEqual(plain, gate.find_project_root(inside))
            self.assertEqual(plain, stop_gate.find_project_root(inside))


class SessionProjectIndexFollowsStateHomeTests(unittest.TestCase):
    """The session project index belongs to the global state home, not to `$HOME`.

    Both call sites used to build this path from ``Path.home()`` directly, which
    made ``TAO_STATE_HOME`` a partial override: the suite wrote its temporary
    project paths into the real user's index, and the Stop gate then walked them.
    The writer and the reader must agree, so both are asserted here.
    """

    def test_index_path_follows_the_state_home_override(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            with patch.dict(os.environ, {STATE_HOME_ENV: state}):
                index = gate.session_projects_index("probe-session")
            self.assertEqual(
                Path(state) / "claude-session-projects" / "probe-session", index
            )

    def test_recording_a_project_writes_under_the_override(self) -> None:
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "repo"
            project.mkdir()
            with patch.dict(os.environ, {STATE_HOME_ENV: state}):
                gate.record_session_project(project, "probe-session")
                recorded = gate.session_projects_index("probe-session").read_text()

            self.assertIn(str(project), recorded)
            # Nothing may appear beside the override.
            self.assertFalse(
                (Path.home() / ".tao" / "claude-session-projects" / "probe-session").exists()
            )

    def test_stop_gate_reads_the_same_index_the_pretool_gate_writes(self) -> None:
        import claude_stop_gate as stop_gate

        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "repo"
            project.mkdir()
            with patch.dict(os.environ, {STATE_HOME_ENV: state}):
                gate.record_session_project(project, "probe-session")
                roots = stop_gate.session_projects("probe-session", None)

            self.assertIn(project, roots)


if __name__ == "__main__":
    unittest.main()
