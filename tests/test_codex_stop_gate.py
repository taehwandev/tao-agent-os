from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "codex_stop_gate_under_test", ROOT / "scripts" / "codex_stop_gate.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

from agent_run_registry import register_run


def _decide(payload: dict) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = gate.decide(payload)
    return code, buffer.getvalue()


def _project(base: Path) -> Path:
    project = base / "project"
    (project / ".tao").mkdir(parents=True)
    (project / "AGENTS.md").write_text("uses tao\n", encoding="utf-8")
    return project


class CodexStopGateTests(unittest.TestCase):
    def test_nested_instruction_file_does_not_shadow_git_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))
            (project / ".git").mkdir()
            nested = project / "docs"
            nested.mkdir()
            (nested / "AGENTS.md").write_text("nested tao docs\n", encoding="utf-8")

            self.assertEqual(
                project.resolve(), gate._find_project_root(nested.resolve())
            )

    def test_active_exact_session_is_continued_for_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))
            evidence = project / ".tao" / "preflight.json"
            with patch.object(gate, "resolve_runtime_evidence", return_value=evidence):
                code, output = _decide(
                    {"cwd": str(project), "session_id": "codex-session"}
                )

        payload = json.loads(output)
        self.assertEqual(0, code)
        self.assertEqual("block", payload["decision"])
        self.assertIn("finish", payload["reason"])
        self.assertIn("skill", payload["reason"])
        self.assertIn("fresh user authority", payload["reason"])
        self.assertIn("complete the work and gate evidence", payload["reason"])

    def test_real_active_run_resolves_only_its_bound_codex_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))
            evidence = project / ".tao" / "preflight.json"
            register_run(
                project,
                evidence,
                {"command": "task", "gates": ["retrospective check"]},
                {"request": "test closeout", "request_classified": False},
            )
            evidence.write_text(
                json.dumps(
                    {
                        "project": str(project),
                        "rules": str(project),
                        "runtime_session": {
                            "runtime": "codex",
                            "session_id": "bound-session",
                        },
                    }
                ),
                encoding="utf-8",
            )

            _, bound_output = _decide(
                {"cwd": str(project), "session_id": "bound-session"}
            )
            _, foreign_output = _decide(
                {"cwd": str(project), "session_id": "foreign-session"}
            )

        self.assertEqual("block", json.loads(bound_output)["decision"])
        self.assertEqual("", foreign_output)

    def test_completed_or_unrelated_session_may_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))
            with patch.object(gate, "resolve_runtime_evidence", return_value=None):
                code, output = _decide(
                    {"cwd": str(project), "session_id": "codex-session"}
                )

        self.assertEqual(0, code)
        self.assertEqual("", output)

    def test_repeated_unresolved_stop_fails_closed_without_looping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))
            evidence = project / ".tao" / "preflight.json"
            with patch.object(gate, "resolve_runtime_evidence", return_value=evidence):
                code, output = _decide(
                    {
                        "cwd": str(project),
                        "session_id": "codex-session",
                        "stop_hook_active": True,
                    }
                )

        payload = json.loads(output)
        self.assertEqual(0, code)
        self.assertFalse(payload["continue"])
        self.assertIn("incomplete", payload["stopReason"])

    def test_missing_session_id_may_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _project(Path(directory))

            code, output = _decide({"cwd": str(project)})

        self.assertEqual(0, code)
        self.assertEqual("", output)


if __name__ == "__main__":
    unittest.main()
