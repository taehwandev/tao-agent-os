from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentHookSummaryTests(unittest.TestCase):
    def test_start_rejects_preflight_evidence_outside_project_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            with tempfile.TemporaryDirectory() as external_directory:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/agent-hook.py"),
                        "start",
                        "--project",
                        project_directory,
                        "--rules",
                        str(ROOT),
                        "--evidence",
                        str(Path(external_directory) / "preflight.json"),
                        "--request",
                        "verify lifecycle evidence paths",
                    ],
                    capture_output=True,
                    text=True,
                )

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "start --evidence must be under the current project's .tao",
                result.stderr,
            )

    def test_start_rejects_output_named_preflight_without_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "start",
                    "--project",
                    directory,
                    "--rules",
                    str(ROOT),
                    "--output",
                    str(Path(directory) / "preflight.json"),
                    "--request",
                    "verify lifecycle evidence paths",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "start --output stores the hook result, not preflight evidence",
                result.stderr,
            )
            self.assertIn("pass the preflight path with --evidence", result.stderr)

    def test_finish_rejects_start_output_as_preflight_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            start_output = Path(directory) / "start.json"
            start_output.write_text(
                json.dumps(
                    {
                        "hook": "start",
                        "status": "SUCCESS",
                        "preflight": {"returncode": 0},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "finish",
                    "--project",
                    directory,
                    "--rules",
                    str(ROOT),
                    "--evidence",
                    str(start_output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "--evidence must name the preflight evidence written by start --evidence",
                result.stderr,
            )
            self.assertIn("not the start hook result", result.stderr)

    def test_invalid_command_surfaces_the_real_argparse_error(self) -> None:
        for invalid_command in ("code-review", "implement"):
            with self.subTest(invalid_command=invalid_command):
                with tempfile.TemporaryDirectory() as directory:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts/agent-hook.py"),
                            "start",
                            "--project",
                            directory,
                            "--rules",
                            str(ROOT),
                            "--command",
                            invalid_command,
                            "--request",
                            "review everything that is not committed yet",
                        ],
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("FAIL start", result.stdout)
                    self.assertIn(
                        f"invalid choice: '{invalid_command}'", result.stdout
                    )

    def test_rejected_invocation_does_not_demand_an_impossible_repair_cycle(self) -> None:
        # A usage error happens before any gate runs, so nothing reaches the
        # ledger. Sending the caller into the repair cycle deadlocks them:
        # repair-verify builds its receipt from a recorded failed checkpoint,
        # and this failure never recorded one.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "start",
                    "--project",
                    directory,
                    "--rules",
                    str(ROOT),
                    "--command",
                    "implement",
                    "--request",
                    "anything",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("invocation request:", result.stdout)
            self.assertIn("nothing to repair", result.stdout)
            self.assertNotIn("recovery request:", result.stdout)
            self.assertNotIn("--repair-cycle", result.stdout)

    def test_request_intake_rejection_does_not_demand_an_impossible_repair_cycle(self) -> None:
        # Clarification blocks happen before route creation, so there is no
        # route fingerprint or failed gate checkpoint for repair-verify to bind.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "start",
                    "--project",
                    directory,
                    "--rules",
                    str(ROOT),
                    "--command",
                    "build",
                    "--request",
                    "검증해줘",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("session-bound intent envelope", result.stdout)
            self.assertIn("invocation request:", result.stdout)
            self.assertIn("nothing to repair", result.stdout)
            self.assertNotIn("recovery request:", result.stdout)
            self.assertNotIn("--repair-cycle", result.stdout)

    def test_rejected_classification_evidence_is_an_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "start",
                    "--project",
                    directory,
                    "--rules",
                    str(ROOT),
                    "--command",
                    "refactor",
                    "--request",
                    "simplify the WebView UI structure",
                    "--request-classified",
                    "--classification-evidence",
                    "scope was reviewed previously",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("invocation request:", result.stdout)
            self.assertIn("nothing to repair", result.stdout)
            self.assertNotIn("recovery request:", result.stdout)
            self.assertNotIn("--repair-cycle", result.stdout)

    def test_rules_file_is_rejected_as_an_invocation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rules_file = Path(directory) / "AGENTS.md"
            rules_file.write_text("# rules\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/agent-hook.py"),
                    "start",
                    "--project",
                    directory,
                    "--rules",
                    str(rules_file),
                    "--command",
                    "feature",
                    "--request",
                    "add a screen",
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("expected a directory", result.stderr)
            self.assertNotIn("recovery request:", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
