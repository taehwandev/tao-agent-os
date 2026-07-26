from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
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


agent_hook = _load_script("agent_hook_start_binding_test", "agent-hook.py")

from agent_run_registry import active_runs, register_run, registry_path


class StartRunBindingTests(unittest.TestCase):
    """Start refuses evidence held by another live request -- but only a live one.

    An interrupted run keeps its `running` record forever: recovery lives in a
    separate maintenance entrypoint that no lifecycle hook invokes. Because the
    Claude pre-tool gate only ever reads the default `.tao/preflight.json`, an
    abandoned run that still claims that path denies every later edit with no
    in-band way out. Start therefore sweeps stale runs before deciding whether a
    conflicting request is actually active.
    """

    def _args(self, project: Path, request: str) -> Namespace:
        return Namespace(
            project=project,
            rules=ROOT,
            command="bugfix",
            request=request,
            request_classified=True,
            classification_evidence="clear-scoped; blockers resolved",
            platform=[],
            concern=[],
            read_only=False,
            evidence=None,
            worker_reservation_token="",
            output=None,
            repair_cycle=0,
        )

    @staticmethod
    def _age_runs(project: Path, *, hours: int) -> None:
        registry = registry_path(project)
        payload = json.loads(registry.read_text(encoding="utf-8"))
        old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        for run in payload["runs"]:
            run["updated_at"] = old
        registry.write_text(json.dumps(payload), encoding="utf-8")

    def _start(self, args: Namespace) -> tuple[bool, list[str]]:
        """Run start far enough to observe the conflict decision, no further."""

        captured: dict[str, object] = {}

        def record(hook, success, details, *rest, **kwargs):
            captured["success"] = success
            captured["details"] = details
            return 0 if success else 1

        with (
            patch.object(agent_hook, "run_script_main", return_value={"returncode": 1, "stdout": "", "stderr": ""}),
            patch.object(agent_hook, "finish_with_result", side_effect=record),
        ):
            agent_hook.start_hook(args)

        return bool(captured.get("success")), list(captured.get("details") or [])

    def test_abandoned_run_no_longer_holds_the_default_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "docs"},
                {"request": "an earlier, unrelated request", "request_classified": False},
            )
            self._age_runs(project, hours=2)

            _success, details = self._start(self._args(project, "repair the review gate defects"))

            self.assertFalse(
                any("already bound to another active request" in line for line in details),
                msg=f"stale run still blocked the default evidence path: {details}",
            )
            self.assertEqual([], active_runs(project))

    def test_negative_control_live_run_still_blocks_the_shared_path(self) -> None:
        """The control: recovery must not turn the conflict guard into a no-op.

        A genuinely concurrent agent holding the same evidence file must still
        be protected, or this fix would trade a deadlock for silent clobbering.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "preflight.json",
                {"command": "docs"},
                {"request": "a concurrent live request", "request_classified": False},
            )

            success, details = self._start(self._args(project, "repair the review gate defects"))

            self.assertFalse(success)
            self.assertTrue(
                any("already bound to another active request" in line for line in details),
                msg=f"a live run stopped blocking the shared evidence path: {details}",
            )

    def test_recovery_leaves_an_unrelated_evidence_path_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            register_run(
                project,
                project / ".tao" / "runs" / "other" / "preflight.json",
                {"command": "review"},
                {"request": "another agent's isolated run", "request_classified": False},
            )

            self._start(self._args(project, "repair the review gate defects"))

            self.assertEqual(
                ["preflight.json"],
                [run["evidence_name"] for run in active_runs(project)],
            )


if __name__ == "__main__":
    unittest.main()
