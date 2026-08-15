from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_hook_checkpoint
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


if __name__ == "__main__":
    unittest.main()
