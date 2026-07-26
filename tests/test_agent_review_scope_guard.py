from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_hook import review_hook


class ReviewScopeGuardTests(unittest.TestCase):
    def test_changed_path_limit_stops_before_review_and_does_not_record_failure(self) -> None:
        changed_paths = [f" M src/file_{index}.py" for index in range(26)]
        git_status_result = {
            "command": ["git", "status", "--short", "--untracked-files=all"],
            "cwd": str(ROOT),
            "returncode": 0,
            "stdout": "\n".join(changed_paths),
            "stderr": "",
        }
        result_payload: dict[str, object] = {}

        def git_status(_project: Path) -> tuple[dict[str, object], list[str]]:
            return git_status_result, changed_paths

        def unexpected_command(*_args: object, **_kwargs: object) -> object:
            self.fail("substantive review checks must not run when the scope limit is exceeded")

        def finish_with_result(
            name: str,
            success: bool,
            details: list[str],
            output: Path | None,
            payload: dict[str, object],
            repair_cycle: int,
            invocation_error: bool = False,
        ) -> int:
            result_payload.update(
                name=name,
                success=success,
                details=details,
                invocation_error=invocation_error,
            )
            return 0 if success else 1

        args = SimpleNamespace(
            project=ROOT,
            evidence=None,
            review_path=[],
            review_scope="working-tree",
            max_changed_paths=25,
            output=None,
            repair_cycle=0,
        )

        with (
            patch("agent_review_hook.record_review_prerequisite_readiness"),
            patch("agent_review_hook.record_review_failure") as record_failure,
        ):
            result = review_hook(
                args,
                unexpected_command,
                git_status,
                unexpected_command,
                unexpected_command,
                finish_with_result,
            )

        self.assertEqual(1, result)
        self.assertFalse(result_payload["success"])
        self.assertTrue(result_payload["invocation_error"])
        self.assertTrue(
            any("--max-changed-paths 26" in detail for detail in result_payload["details"])
        )
        record_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
