from __future__ import annotations

import importlib.util
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_read_only_test", "agent-hook.py")
agent_preflight = _load_script("agent_preflight_read_only_test", "agent-preflight.py")
agent_finish = _load_script("agent_finish_read_only_test", "agent-finish-check.py")

from agent_finish_check_steps import check_preflight_vibeguard
from agent_finish_final_checks import _record_vibeguard_signal


class ReadOnlyLifecycleTests(unittest.TestCase):
    def test_analysis_preflight_is_intrinsically_read_only(self) -> None:
        self.assertTrue(agent_preflight.effective_read_only("analysis", False))
        self.assertTrue(agent_preflight.effective_read_only("product", True))
        self.assertFalse(agent_preflight.effective_read_only("product", False))

    def test_finish_recovers_legacy_analysis_evidence_as_read_only(self) -> None:
        self.assertTrue(
            agent_finish.effective_read_only(
                {"execution_mode": {"read_only": False}},
                {"command": "analysis"},
            )
        )
        self.assertFalse(
            agent_finish.effective_read_only(
                {"execution_mode": {"read_only": False}},
                {"command": "product"},
            )
        )

    def test_start_forwards_read_only_to_preflight(self) -> None:
        args = Namespace(
            project=Path("/tmp/project"),
            rules=ROOT,
            command="analysis",
            request="audit repository migration",
            request_classified=True,
            classification_evidence="explicit non-mutating audit",
            platform=[],
            concern=[],
            read_only=True,
            evidence=None,
            worker_reservation_token="",
            output=None,
            repair_cycle=0,
        )
        result = {"returncode": 1, "stdout": "", "stderr": ""}

        with (
            patch.object(agent_hook, "run_script_main", return_value=result) as runner,
            patch.object(agent_hook, "finish_with_result", return_value=1),
        ):
            agent_hook.start_hook(args)

        command = runner.call_args.args[1]
        self.assertIn("--read-only", command)

    def test_read_only_preflight_records_an_explicit_skip(self) -> None:
        result = agent_preflight.skipped_vibeguard(Path("/tmp/project"))

        self.assertTrue(result["skipped"])
        self.assertEqual(0, result["returncode"])
        self.assertEqual("Skipped", result["overall"]["status"])

    def test_finish_accepts_only_a_declared_read_only_skip(self) -> None:
        preflight = {
            "vibeguard": agent_preflight.skipped_vibeguard(Path("/tmp/project"))
        }
        failures: list[str] = []

        check_preflight_vibeguard(preflight, failures, read_only=True)

        self.assertEqual([], failures)

        check_preflight_vibeguard(preflight, failures, read_only=False)
        self.assertIn(
            "preflight VibeGuard was skipped without read-only execution mode",
            failures,
        )

    def test_finish_reports_read_only_vibeguard_as_skipped_success(self) -> None:
        signals: list[dict[str, str]] = []
        failures: list[str] = []

        _record_vibeguard_signal(
            agent_preflight.skipped_vibeguard(Path("/tmp/project")),
            None,
            signals,
            failures,
        )

        self.assertEqual([], failures)
        self.assertEqual("SUCCESS", signals[0]["signal"])
        self.assertEqual("skipped", signals[0]["status"])


if __name__ == "__main__":
    unittest.main()
