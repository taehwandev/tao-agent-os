from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_hook_checkpoint
from agent_continuation_fields import MAX_SHORT_TEXT, MAX_TEXT
from test_agent_runtime_session import RuntimeFixture

_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_checkpoint_parser_test", ROOT / "scripts" / "agent-hook.py"
)
assert _SPEC and _SPEC.loader
agent_hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_hook)


def _args(fixture: RuntimeFixture, **overrides) -> Namespace:
    values = {
        "project": fixture.project,
        "rules": fixture.rules,
        "evidence": fixture.evidence,
        "output": None,
        "repair_cycle": 0,
        "checkpoint_kind": "decision",
        "phase": None,
        "last_completed": None,
        "mutation_kind": None,
        "mutation_path": [],
        "work_stdin": True,
    }
    values.update(overrides)
    return Namespace(**values)


def _stdin(payload: dict) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")))


class CheckpointCommandTests(unittest.TestCase):
    def test_overlong_prose_reports_canonical_limits_without_writing_or_echoing(self) -> None:
        for field, limit in (("objective", MAX_TEXT), ("non_goals", MAX_SHORT_TEXT)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = RuntimeFixture(directory)
                before = fixture.packet()
                value = "가" * (limit + 1)
                work = {field: [value] if field == "non_goals" else value}
                output = io.StringIO()
                with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(output):
                    code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

                self.assertNotEqual(0, code)
                self.assertEqual(before, fixture.packet())
                self.assertIn(f"prose_too_long@/work/{field}", output.getvalue())
                self.assertIn(f"{MAX_TEXT} Unicode characters", output.getvalue())
                self.assertIn(f"{MAX_SHORT_TEXT} for each non_goals entry", output.getvalue())
                self.assertNotIn(value, output.getvalue())

    def test_prose_accepts_unicode_characters_at_the_canonical_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work = {
                "objective": "가" * MAX_TEXT,
                "non_goals": ["나" * MAX_SHORT_TEXT],
            }
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(io.StringIO()):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertEqual(0, code)
            self.assertEqual(work["objective"], fixture.packet()["work"]["objective"])
            self.assertEqual(work["non_goals"], fixture.packet()["work"]["non_goals"])

    def test_template_cannot_silently_discard_a_requested_checkpoint(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args([
            "checkpoint", "--work-template", "--checkpoint-kind", "decision",
        ])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            agent_hook._run_checkpoint_hook(parser, args)
        self.assertEqual(2, raised.exception.code)

    def test_template_is_read_only_json_and_can_be_submitted_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            output = io.StringIO()
            parser = agent_hook.build_parser()
            args = parser.parse_args(["checkpoint", "--work-template"])
            with redirect_stdout(output), patch.object(
                agent_hook_checkpoint, "run_binding_path",
                side_effect=AssertionError("template must not resolve run state"),
            ):
                self.assertEqual(0, agent_hook._run_checkpoint_hook(parser, args))
            work = json.loads(output.getvalue())
            self.assertEqual(before, fixture.packet())
            work["objective"] = "Complete the bounded change"
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(io.StringIO()):
                self.assertEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
            self.assertEqual(work["objective"], fixture.packet()["work"]["objective"])

    def test_semantic_checkpoint_reads_only_the_closed_work_object_from_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work = {
                "objective": "finish the continuation adapter",
                "decisions": [
                    {
                        "id": "runtime_adapter",
                        "status": "accepted",
                        "text": "Claude supplies only exact lifecycle events",
                    }
                ],
            }
            output = io.StringIO()
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(output):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertEqual(0, code)
            self.assertIn("SUCCESS checkpoint", output.getvalue())
            self.assertEqual(
                "finish the continuation adapter", fixture.packet()["work"]["objective"]
            )

    def test_transcript_shaped_unknown_field_is_refused_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            output = io.StringIO()
            with (
                patch.object(
                    sys,
                    "stdin",
                    _stdin({"transcript": "password=do-not-print"}),
                ),
                redirect_stdout(output),
            ):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertNotEqual(0, code)
            self.assertEqual(before, fixture.packet())
            self.assertNotIn("do-not-print", output.getvalue())
            self.assertIn("unknown_field", output.getvalue())
            self.assertIn("--work-template", output.getvalue())
            self.assertIn("Do not fabricate", output.getvalue())

    def test_parser_exposes_the_provider_neutral_checkpoint_command(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "checkpoint",
                "--checkpoint-kind",
                "pre_mutation",
                "--mutation-kind",
                "update",
                "--mutation-path",
                "src/module.py",
            ]
        )

        self.assertEqual("checkpoint", parsed.hook)
        self.assertEqual(["src/module.py"], parsed.mutation_path)

    def test_parser_exposes_exact_commit_range_review_arguments(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "commit-range",
                "--review-base",
                "base-ref",
                "--review-head",
                "head-ref",
            ]
        )

        self.assertEqual("commit-range", parsed.review_scope)
        self.assertEqual("base-ref", parsed.review_base)
        self.assertEqual("head-ref", parsed.review_head)

    def test_parser_exposes_local_config_review_scope(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "local-config",
                "--review-path",
                ".codex/hooks.json",
            ]
        )

        self.assertEqual("local-config", parsed.review_scope)
        self.assertEqual([".codex/hooks.json"], parsed.review_path)

    def test_parser_exposes_repo_hygiene_review_scope_without_paths(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "repo-hygiene",
            ]
        )

        self.assertEqual("repo-hygiene", parsed.review_scope)
        self.assertEqual([], parsed.review_path)

    def test_invalid_repair_cycle_cli_is_rejected_before_claiming_the_attempt(self) -> None:
        scenarios = (
            ["start", "--repair-cycle", "1"],
            ["review", "--repair-cycle", "1", "--review-scope", "pathspec"],
            ["gate", "--repair-cycle", "1"],
        )

        for arguments in scenarios:
            with self.subTest(hook=arguments[0]):
                stderr = io.StringIO()
                with (
                    patch.object(sys, "argv", ["agent-hook.py", *arguments]),
                    patch.object(agent_hook, "_apply_worker_evidence_boundary", return_value=""),
                    patch.object(agent_hook, "_refresh_run_heartbeat"),
                    patch.object(agent_hook, "_apply_repair_cycle_context") as claim_attempt,
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit),
                ):
                    agent_hook.main()

                claim_attempt.assert_not_called()
                self.assertIn("error:", stderr.getvalue())

    def test_fingerprint_hook_prints_the_bound_request_fingerprint(self) -> None:
        from agent_route_state import request_fingerprint

        parser = agent_hook.build_parser()
        args = parser.parse_args(["fingerprint", "--request", "do the thing"])
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            returncode = agent_hook._fingerprint_hook(parser, args)

        expected = request_fingerprint(
            {
                "request": "do the thing",
                "continuation_scope": "",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        self.assertEqual(0, returncode)
        self.assertIn(expected, stdout.getvalue())
        self.assertIn('"request_fingerprint"', stdout.getvalue())

    def test_fingerprint_hook_binds_the_continuation_scope(self) -> None:
        """The helper must hash the same full intake the start call will bind.

        Envelopes bind to the full request intake, so a helper that hashed the
        request alone handed every terse follow-up a fingerprint its own start
        call then rejected as describing a different request -- and the agent's
        recovery was to ask the user to reword the request.
        """

        from agent_route_state import request_fingerprint

        parser = agent_hook.build_parser()
        args = parser.parse_args(
            [
                "fingerprint",
                "--request",
                "응 수정해줘",
                "--continuation-scope",
                "the previously agreed bounded target",
            ]
        )
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            returncode = agent_hook._fingerprint_hook(parser, args)

        full_intake = request_fingerprint(
            {
                "request": "응 수정해줘",
                "continuation_scope": "the previously agreed bounded target",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        request_only = request_fingerprint(
            {
                "request": "응 수정해줘",
                "continuation_scope": "",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        self.assertEqual(0, returncode)
        self.assertIn(full_intake, stdout.getvalue())
        self.assertNotIn(request_only, stdout.getvalue())
        self.assertIn("binding covers --request, --continuation-scope", stdout.getvalue())

    def test_fingerprint_hook_requires_the_request(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(["fingerprint"])

        with self.assertRaises(SystemExit):
            agent_hook._fingerprint_hook(parser, args)


if __name__ == "__main__":
    unittest.main()
