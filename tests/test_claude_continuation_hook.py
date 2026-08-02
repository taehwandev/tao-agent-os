from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import claude_continuation_hook
from claude_continuation_hook import ClaudeContinuationAdapter
from agent_run_registry import register_run, registry_path
from agent_runtime_session import resolve_runtime_evidence
from support.claude_continuation_setup import (
    CONTINUATION_ALIAS,
    SESSION_START_MATCHER,
    configure_claude_continuation,
)
from support.setup_config_files import read_json
from test_agent_runtime_session import RuntimeFixture


def _payload(
    fixture: RuntimeFixture,
    *,
    event: str,
    session_id: str = "old-session",
) -> dict:
    return {
        "hook_event_name": event,
        "tool_name": "Write",
        "tool_use_id": "toolu_fixture",
        "cwd": str(fixture.project),
        "session_id": session_id,
        "tool_input": {"file_path": str(fixture.project / "src" / "module.py")},
    }


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    return process.pid


def _kill_owner(fixture: RuntimeFixture) -> None:
    path = registry_path(fixture.project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for run in payload["runs"]:
        if run["run_id"] == fixture.run_id:
            run["owner"] = {"pid": _dead_pid(), "start_token": "recorded"}
    path.write_text(json.dumps(payload), encoding="utf-8")


class ClaudeMutationAdapterTests(unittest.TestCase):
    def test_custom_evidence_post_hook_skips_unreachable_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            target = project / "src" / "module.py"
            target.parent.mkdir(parents=True)
            target.write_text("value = 1\n", encoding="utf-8")
            evidence = project / ".tao" / "custom" / "preflight-hotfix.json"
            evidence.parent.mkdir(parents=True)
            route = {"command": "task", "gates": [], "required_docs": []}
            intake = {"request": "custom evidence test"}
            register_run(project, evidence, route, intake)
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
            payload = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "cwd": str(project),
                "session_id": "custom-session",
                "tool_input": {"file_path": str(target)},
            }

            with patch.object(
                claude_continuation_hook,
                "_checkpoint",
                side_effect=AssertionError(
                    "custom evidence cannot own a continuation packet"
                ),
            ):
                post = ClaudeContinuationAdapter.post_mutation(payload)

            self.assertIsNone(post)

    def test_successful_file_tool_is_bracketed_and_records_actual_changed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            payload = _payload(fixture, event="PreToolUse")

            pre = ClaudeContinuationAdapter.pre_mutation(
                payload,
                root=fixture.project,
                cwd=fixture.project,
                session_id="old-session",
            )
            (fixture.project / "src" / "module.py").write_text(
                "value = 2\n", encoding="utf-8"
            )
            post = ClaudeContinuationAdapter.post_mutation(
                {**payload, "hook_event_name": "PostToolUse"}
            )

            self.assertIsNone(pre)
            self.assertIsNone(post)
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])
            self.assertEqual(
                [{"path": "src/module.py", "role": "modified"}],
                fixture.packet()["work"]["changed_scope"],
            )

    def test_failed_noop_tool_clears_pending_without_claiming_a_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            payload = _payload(fixture, event="PreToolUse")
            self.assertIsNone(
                ClaudeContinuationAdapter.pre_mutation(
                    payload,
                    root=fixture.project,
                    cwd=fixture.project,
                    session_id="old-session",
                )
            )

            post = ClaudeContinuationAdapter.post_mutation(
                {**payload, "hook_event_name": "PostToolUseFailure"}
            )

            self.assertIsNone(post)
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])
            self.assertEqual([], fixture.packet()["work"]["changed_scope"])

    def test_an_open_pending_is_refused_only_once_its_tool_wrote(self) -> None:
        # An open pending means "a mutation was announced and never closed".
        # Whether that must refuse the next one depends on what the announced
        # tool actually did, because only PostToolUse clears the record: a
        # declined permission prompt leaves it open just as an interrupted write
        # does. Refusing on the record alone made one declined prompt end the
        # session's ability to edit, so the pending's own recorded state decides
        # -- unchanged bytes mean the tool never ran and the pending describes
        # nothing, while changed bytes are the interrupted write that genuinely
        # needs reconciling.
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            payload = _payload(fixture, event="PreToolUse")

            def announce() -> str | None:
                return ClaudeContinuationAdapter.pre_mutation(
                    payload,
                    root=fixture.project,
                    cwd=fixture.project,
                    session_id="old-session",
                )

            self.assertIsNone(announce())
            self.assertIsNone(announce(), "an unwritten pending must be superseded")

            (fixture.project / "src" / "module.py").write_text(
                "value = 2\n", encoding="utf-8"
            )
            self.assertIn("mutation_already_pending", announce() or "")


class ClaudeSessionResumeTests(unittest.TestCase):
    def test_session_start_takes_over_a_dead_owner_and_injects_the_bounded_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            _kill_owner(fixture)

            output = ClaudeContinuationAdapter.session_start(
                {
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "cwd": str(fixture.project),
                    "session_id": "new-session",
                }
            )

            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("resume safe work", context)
            self.assertNotIn("runtime fixture request", context)
            self.assertIsNotNone(
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "new-session"},
                )
            )

    def test_session_start_refuses_drift_without_rendering_saved_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            (fixture.project / "src" / "module.py").write_text(
                "drifted = True\n", encoding="utf-8"
            )
            _kill_owner(fixture)

            output = ClaudeContinuationAdapter.session_start(
                {
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "cwd": str(fixture.project),
                    "session_id": "new-session",
                }
            )

            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("drift_refused", context)
            self.assertNotIn("resume safe work", context)


class ClaudeContinuationSetupTests(unittest.TestCase):
    def test_setup_installs_session_and_both_post_tool_events_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            launcher = Path(directory) / "tao-hook"

            first = configure_claude_continuation(
                target,
                dry_run=False,
                launcher_path=launcher,
                matcher="Edit|Write",
            )
            before = target.read_bytes()
            second = configure_claude_continuation(
                target,
                dry_run=False,
                launcher_path=launcher,
                matcher="Edit|Write",
            )

            config = read_json(target)
            self.assertTrue(all(item["status"] == "installed" for item in first))
            self.assertTrue(all(item["status"] == "ok" for item in second))
            self.assertEqual(before, target.read_bytes())
            self.assertEqual(
                SESSION_START_MATCHER,
                config["hooks"]["SessionStart"][0]["matcher"],
            )
            for event in ("SessionStart", "PostToolUse", "PostToolUseFailure"):
                command = config["hooks"][event][0]["hooks"][0]["command"]
                self.assertIn(CONTINUATION_ALIAS, command)


if __name__ == "__main__":
    unittest.main()
