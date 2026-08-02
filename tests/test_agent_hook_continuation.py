"""The lifecycle hooks must write checkpoints, and must survive not writing them."""

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
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_continuation_test", "agent-hook.py")

import agent_hook_continuation as wiring
from agent_continuation_packet import validate_continuation_packet
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_context_store import refresh_context_snapshot
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION, doc_hash_record
from agent_gate_evidence import record_gate_evidence
from agent_repair_ledger import (
    REBOUND,
    capture_failure_checkpoint_binding,
    checkpoint_has_recorded_failure,
    record_failure_checkpoints,
)
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import (
    ACTIVE_RUN_STATES,
    register_run,
    registry_path,
    transition_run,
)

GUIDANCE = "guidance.md"
RUN_ID = "0123456789abcdef0123456789abcdef"
ROUTE = {"command": "task", "gates": ["scope", "act", "verify"], "required_docs": [GUIDANCE]}
INTAKE = {"request": "wire the continuation layer into the lifecycle", "request_classified": False}


class HookRun:
    """One registered run whose evidence lives in its own run directory."""

    def __init__(self, directory: str, *, run_id: str = RUN_ID, register: bool = True) -> None:
        self.project = Path(directory) / "project"
        self.rules = Path(directory) / "rules"
        if not self.project.exists():
            (self.project / "src").mkdir(parents=True)
            (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
            self.rules.mkdir()
            (self.rules / GUIDANCE).write_text("# guidance\n", encoding="utf-8")
        self.evidence = self.project / ".tao" / "runs" / run_id / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.run = register_run(self.project, self.evidence, ROUTE, INTAKE) if register else {}
        self.run_id = str(self.run.get("run_id") or run_id)
        self.evidence.write_text(
            json.dumps(
                {
                    "project": str(self.project),
                    "rules": str(self.rules),
                    "route": ROUTE,
                    "request_intake": INTAKE,
                    "execution_snapshot": {
                        "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                        "route_fingerprint": route_fingerprint(ROUTE),
                        "request_fingerprint": request_fingerprint(INTAKE),
                        "required_docs": [doc_hash_record(GUIDANCE, self.rules / GUIDANCE)],
                    },
                }
            ),
            encoding="utf-8",
        )

    def args(self, hook: str = "gate", **overrides: object) -> Namespace:
        values = {
            "hook": hook,
            "project": self.project,
            "rules": self.rules,
            "evidence": self.evidence,
            "output": None,
            "repair_cycle": 0,
            "request": INTAKE["request"],
            "command": "task",
            "gate_name": "",
            "status": "SUCCESS",
        }
        values.update(overrides)
        return Namespace(**values)

    def packet(self) -> dict:
        return read_continuation_packet(
            self.project, continuation_path(self.project, self.run_id)
        )["packet"]


class RunBindingTests(unittest.TestCase):
    def test_the_isolated_run_directory_becomes_the_opaque_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            self.assertEqual(RUN_ID, run.run_id)
            self.assertEqual(run.evidence.resolve(), wiring.run_binding_path(run.args()))

    def test_a_run_id_already_in_the_registry_is_never_adopted_twice(self) -> None:
        """Two records sharing one opaque id make "the run" ambiguous forever."""

        with tempfile.TemporaryDirectory() as directory:
            first = HookRun(directory)

            second = register_run(first.project, first.evidence, ROUTE, INTAKE)

            self.assertEqual(RUN_ID, first.run_id)
            self.assertNotEqual(RUN_ID, second["run_id"])

    def test_evidence_outside_a_run_directory_has_no_reachable_packet(self) -> None:
        """The default `.tao/preflight.json` path is not a run directory.

        The packet binds to a trust record in its own run directory because the
        gate ledger and route manifest are resolved from beside it. Evidence at
        any other path is reported as unreachable rather than bound to a record
        this run cannot prove.
        """

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            args = run.args(evidence=run.project / ".tao" / "preflight.json")

            self.assertIsNone(wiring.run_binding_path(args))
            detail = wiring.record_lifecycle_checkpoint(args, "initial", work={"objective": "x"})

            self.assertEqual(wiring.SKIPPED_DETAIL, detail)
            self.assertIsNone(run.packet())


class CheckpointContentTests(unittest.TestCase):
    def test_the_initial_checkpoint_is_a_valid_packet_bound_to_this_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            detail = wiring.record_lifecycle_checkpoint(
                run.args("start"),
                "initial",
                work={"objective": wiring.start_objective(run.args("start"))},
            )

            packet = run.packet()
            self.assertEqual("continuation checkpoint: initial recorded", detail)
            self.assertEqual([], validate_continuation_packet(packet))
            self.assertEqual(RUN_ID, packet["run_id"])
            self.assertEqual("scoped", packet["phase"])
            self.assertEqual("scope", packet["checkpoint"]["first_unfinished"])
            self.assertEqual("task workflow", packet["work"]["objective"])
            self.assertNotIn(INTAKE["request"], json.dumps(packet))

    def test_raw_request_content_never_becomes_the_initial_objective(self) -> None:
        """Prompt bytes must not be normalized into a supposedly safe summary."""

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            request = "password=demo-value\n" + "private prompt text " * 20
            args = run.args("start", request=request)

            objective = wiring.start_objective(args)
            wiring.record_lifecycle_checkpoint(args, "initial", work={"objective": objective})

            self.assertEqual("task workflow", objective)
            self.assertNotIn("demo-value", json.dumps(run.packet()))
            self.assertNotIn("private prompt text", json.dumps(run.packet()))
            self.assertEqual([], validate_continuation_packet(run.packet()))

    def test_an_empty_request_still_produces_an_objective(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            args = run.args("start", request="", command="bugfix")

            self.assertEqual("bugfix workflow", wiring.start_objective(args))

    def test_a_failed_hook_never_names_a_completed_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            wiring.record_lifecycle_checkpoint(
                run.args("start"), "initial", work={"objective": "wire the layer"}
            )

            with redirect_stdout(io.StringIO()):
                code = wiring.checkpoint_after_hook(
                    run.args(), 1, "lifecycle", last_completed="scope"
                )

            self.assertEqual(1, code)
            self.assertIsNone(run.packet()["checkpoint"]["last_completed"])

    def test_a_successful_hook_records_the_checkpoint_it_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            wiring.record_lifecycle_checkpoint(
                run.args("start"), "initial", work={"objective": "wire the layer"}
            )

            with redirect_stdout(io.StringIO()):
                code = wiring.checkpoint_after_hook(
                    run.args(), 0, "lifecycle", last_completed="scope"
                )

            self.assertEqual(0, code)
            self.assertEqual("scope", run.packet()["checkpoint"]["last_completed"])

    def test_only_a_successful_named_gate_is_offered_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            self.assertEqual(
                "scope", wiring.gate_checkpoint_name(run.args(gate_name="scope"))
            )
            self.assertIsNone(
                wiring.gate_checkpoint_name(run.args(gate_name="scope", status="FAIL"))
            )
            self.assertIsNone(wiring.gate_checkpoint_name(run.args(gate_name="Not/A gate")))


class MutationEntryPointTests(unittest.TestCase):
    """The bracketing is the adapter's job; the entry point it calls is not."""

    def test_a_mutation_is_bracketed_through_the_same_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            args = run.args("start")
            wiring.record_lifecycle_checkpoint(args, "initial", work={"objective": "bracket it"})

            wiring.record_lifecycle_checkpoint(
                args, "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            pending = run.packet()["checkpoint"]["mutation_pending"]
            (run.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
            wiring.record_lifecycle_checkpoint(
                args,
                "post_mutation",
                work={"changed_scope": [{"path": "src/module.py", "role": "modified"}]},
            )

            self.assertEqual("update", pending["kind"])
            self.assertEqual(["src/module.py"], pending["paths"])
            self.assertEqual("acting", run.packet()["phase"])
            self.assertIsNone(run.packet()["checkpoint"]["mutation_pending"])

    def test_a_pre_mutation_without_its_bounded_paths_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            args = run.args("start")
            wiring.record_lifecycle_checkpoint(args, "initial", work={"objective": "bracket it"})

            detail = wiring.record_lifecycle_checkpoint(args, "pre_mutation")

            self.assertIn("continuation checkpoint: unavailable", detail)
            self.assertIsNone(run.packet()["checkpoint"]["mutation_pending"])


class DegradationTests(unittest.TestCase):
    """A checkpoint failure must cost the packet, never the hook."""

    def test_a_write_failure_leaves_the_hook_successful_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            wiring.record_lifecycle_checkpoint(
                run.args("start"), "initial", work={"objective": "wire the layer"}
            )
            packet_path = continuation_path(run.project, run.run_id)
            before = packet_path.read_bytes()

            output = io.StringIO()
            with (
                patch.object(
                    wiring,
                    "write_continuation_checkpoint",
                    side_effect=OSError("no space left on device"),
                ),
                redirect_stdout(output),
            ):
                code = wiring.checkpoint_after_hook(run.args(), 0, "lifecycle")

            self.assertEqual(0, code)
            self.assertIn("continuation checkpoint: unavailable", output.getvalue())
            self.assertIn("lifecycle continues", output.getvalue())
            self.assertEqual(before, packet_path.read_bytes())

    def test_a_gate_hook_still_succeeds_when_the_packet_cannot_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            argv = [
                "agent-hook.py",
                "gate",
                "--project",
                str(run.project),
                "--rules",
                str(run.rules),
                "--evidence",
                str(run.evidence),
                "--gate-name",
                "scope",
            ]

            output = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(agent_hook, "gate_hook", return_value=0),
                patch.dict("os.environ", {}, clear=True),
                patch.object(
                    wiring, "write_continuation_checkpoint", side_effect=RuntimeError("registry gone")
                ),
                redirect_stdout(output),
            ):
                code = agent_hook.main()

            self.assertEqual(0, code)
            self.assertIn("continuation checkpoint: unavailable", output.getvalue())


class DispatchTests(unittest.TestCase):
    """Every lifecycle point the card names must reach the shared writer."""

    def _dispatch(self, run: HookRun, argv: list[str], **patches) -> list[dict]:
        calls: list[dict] = []
        with (
            patch.object(sys, "argv", ["agent-hook.py", *argv]),
            patch.dict("os.environ", {}, clear=True),
            patch.object(wiring, "write_continuation_checkpoint", side_effect=lambda **kw: calls.append(kw)),
            redirect_stdout(io.StringIO()),
        ):
            with self._patched(patches):
                agent_hook.main()
        return calls

    @staticmethod
    def _patched(patches: dict):
        from contextlib import ExitStack

        stack = ExitStack()
        for name, value in patches.items():
            stack.enter_context(patch.object(agent_hook, name, **value))
        return stack

    def _common(self, run: HookRun) -> list[str]:
        return [
            "--project", str(run.project),
            "--rules", str(run.rules),
            "--evidence", str(run.evidence),
        ]

    def test_gate_and_gate_batch_records_checkpoint_the_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            gate = self._dispatch(
                run,
                ["gate", *self._common(run), "--gate-name", "scope"],
                gate_hook={"return_value": 0},
            )
            batch = self._dispatch(
                run,
                ["gate-batch", *self._common(run)],
                gate_batch_hook={"return_value": 0},
            )

            self.assertEqual(["lifecycle"], [call["kind"] for call in gate])
            self.assertEqual("scope", gate[0]["last_completed"])
            self.assertEqual(["lifecycle"], [call["kind"] for call in batch])

    def test_review_checkpoints_the_reviewing_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            calls = self._dispatch(
                run,
                ["review", *self._common(run)],
                review_hook={"return_value": 0},
            )

            self.assertEqual(["lifecycle"], [call["kind"] for call in calls])
            self.assertEqual("reviewing", calls[0]["phase"])

    def test_successful_finish_finalizes_after_the_run_becomes_completed(self) -> None:
        """A completed packet must derive its display state from completed."""

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            states: list[str] = []

            def record(**keywords):
                payload = json.loads(registry_path(run.project).read_text(encoding="utf-8"))
                states.extend(item["state"] for item in payload["runs"])

            with (
                patch.object(sys, "argv", ["agent-hook.py", "finish", *self._common(run)]),
                patch.dict("os.environ", {}, clear=True),
                patch.object(
                    agent_hook, "run_script_main", return_value={"returncode": 0, "stdout": "", "stderr": ""}
                ),
                patch.object(wiring, "write_continuation_checkpoint", side_effect=record),
                redirect_stdout(io.StringIO()),
            ):
                agent_hook.main()

            self.assertEqual(["completed"], states)

    def _finish_state(self, run: HookRun, returncode: int) -> str:
        with (
            patch.object(sys, "argv", ["agent-hook.py", "finish", *self._common(run)]),
            patch.dict("os.environ", {}, clear=True),
            patch.object(
                agent_hook,
                "run_script_main",
                return_value={"returncode": returncode, "stdout": "", "stderr": ""},
            ),
            redirect_stdout(io.StringIO()),
        ):
            agent_hook.main()
        payload = json.loads(registry_path(run.project).read_text(encoding="utf-8"))
        return next(item["state"] for item in payload["runs"] if item["run_id"] == run.run_id)

    def test_pending_closeout_keeps_the_run_claim_active(self) -> None:
        """Owed closeout work is not a failed run.

        Retiring the claim here dropped the run out of the active states, so
        session evidence stopped resolving and the edit gate refused the very
        skill-document writes the closeout asks for.
        """

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            self.assertIn(self._finish_state(run, 3), ACTIVE_RUN_STATES)

    def test_pending_closeout_revives_a_run_an_earlier_failure_retired(self) -> None:
        """The real sequence reaches closeout through an already-failed run.

        Finish fails on a missing gate, the agent records that gate, and the
        retry returns pending closeout. Only holding the current state left the
        run failed exactly when the closeout needs to edit, while the same
        result tells the agent not to run repair-verify.
        """

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            self.assertEqual("failed", self._finish_state(run, 1))

            self.assertIn(self._finish_state(run, 3), ACTIVE_RUN_STATES)

    def test_pending_closeout_never_revives_a_settled_run(self) -> None:
        """A run that already reported its outcome must stay reported.

        The revive went through the general transition, which accepts any prior
        state, so replaying a pending-closeout finish on a completed run put it
        back on the shared evidence path as an active run.
        """

        for settled in ("completed", "cancelled"):
            with self.subTest(settled=settled), tempfile.TemporaryDirectory() as directory:
                run = HookRun(directory)
                transition_run(run.project, run.evidence, settled, run_id=run.run_id)

                self.assertEqual(settled, self._finish_state(run, 3))

    def test_pending_closeout_refuses_a_run_owned_by_another_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            payload = json.loads(registry_path(run.project).read_text(encoding="utf-8"))
            for record in payload["runs"]:
                if record["run_id"] == run.run_id:
                    record["state"] = "failed"
                    record["owner"] = {"pid": 999999, "start_token": "other-session"}
            registry_path(run.project).write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual("failed", self._finish_state(run, 3))

    def test_a_genuinely_failed_finish_still_retires_the_run(self) -> None:
        """Control: the pending-closeout branch must not spare every failure."""

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            self.assertEqual("failed", self._finish_state(run, 1))

    def test_successful_finish_leaves_no_cached_unfinished_checkpoint(self) -> None:
        """The pre-fix control leaves ``first_unfinished`` equal to ``finish``."""

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            wiring.record_lifecycle_checkpoint(
                run.args("start"),
                "initial",
                work={"objective": "finish the lifecycle"},
            )
            preflight = json.loads(run.evidence.read_text(encoding="utf-8"))
            for gate in ROUTE["gates"]:
                record_gate_evidence(
                    evidence_path=run.evidence,
                    preflight=preflight,
                    gate=gate,
                    evidence="completed in the finish regression fixture",
                )

            with (
                patch.object(
                    agent_hook,
                    "run_script_main",
                    return_value={"returncode": 0, "stdout": "", "stderr": ""},
                ),
                redirect_stdout(io.StringIO()),
            ):
                code = agent_hook.finish_hook(
                    run.args("finish", allow_vibeguard_review=None)
                )

            registry = json.loads(
                registry_path(run.project).read_text(encoding="utf-8")
            )
            record = next(
                item for item in registry["runs"] if item["run_id"] == run.run_id
            )
            self.assertEqual(0, code)
            self.assertEqual("completed", record["state"])
            self.assertEqual("done", run.packet()["phase"])
            self.assertIsNone(run.packet()["checkpoint"]["first_unfinished"])

    def test_start_checkpoints_the_initial_packet_after_registering_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory, register=False)
            calls: list[dict] = []

            with (
                patch.object(agent_hook, "_refresh_started_context", return_value=True),
                patch.object(agent_hook, "_bind_read_only_execution_state", return_value=True),
                patch.object(
                    agent_hook, "run_script_main", return_value={"returncode": 0, "stdout": "", "stderr": ""}
                ),
                patch.object(wiring, "write_continuation_checkpoint", side_effect=lambda **kw: calls.append(kw)),
                redirect_stdout(io.StringIO()),
            ):
                agent_hook.start_hook(
                    run.args(
                        "start",
                        command="task",
                        request_classified=False,
                        classification_evidence="",
                        platform=[],
                        concern=[],
                        read_only=False,
                        worker_reservation_token="",
                    )
                )

            self.assertEqual(["initial"], [call["kind"] for call in calls])
            self.assertEqual("task workflow", calls[0]["work"]["objective"])
            self.assertNotIn(INTAKE["request"], json.dumps(calls[0]["work"]))

    def test_context_refresh_marks_required_doc_byte_drift_for_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            refresh_context_snapshot(run.project, run.rules, ROUTE, INTAKE)
            (run.rules / GUIDANCE).write_text("# changed guidance\n", encoding="utf-8")
            details: list[str] = []

            with patch.object(
                agent_hook,
                "rebind_failure_checkpoints_after_required_doc_refresh",
                return_value=REBOUND,
            ) as rebind:
                self.assertTrue(
                    agent_hook._refresh_started_context(
                        run.args("start"),
                        details,
                        prior_repair_binding={"preflight_evidence_sha256": "old"},
                    )
                )

            self.assertTrue(rebind.call_args.kwargs["required_doc_drift"])
            self.assertIn(
                "repair checkpoints: rebound after required-doc drift", details
            )

    def test_context_refresh_preserves_the_same_tasks_failed_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            preflight = json.loads(run.evidence.read_text(encoding="utf-8"))
            refresh_context_snapshot(run.project, run.rules, ROUTE, INTAKE)
            record_failure_checkpoints(
                evidence_path=run.evidence,
                preflight=preflight,
                checkpoints=["review"],
                signature="review-failure",
            )
            binding = capture_failure_checkpoint_binding(run.evidence)
            (run.rules / GUIDANCE).write_text("# changed guidance\n", encoding="utf-8")
            refreshed = {**preflight, "agent_run_id": "new-run"}
            run.evidence.write_text(json.dumps(refreshed), encoding="utf-8")

            self.assertTrue(
                agent_hook._refresh_started_context(
                    run.args("start"),
                    [],
                    prior_repair_binding=binding,
                )
            )
            self.assertTrue(
                checkpoint_has_recorded_failure(
                    route=ROUTE,
                    evidence_path=run.evidence,
                    checkpoint="review",
                )
            )

    def test_context_refresh_does_not_treat_request_replacement_as_doc_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            refresh_context_snapshot(
                run.project,
                run.rules,
                ROUTE,
                {"request": "a different request", "request_classified": False},
            )

            with patch.object(
                agent_hook,
                "rebind_failure_checkpoints_after_required_doc_refresh",
                return_value="not_applicable",
            ) as rebind:
                self.assertTrue(
                    agent_hook._refresh_started_context(
                        run.args("start"),
                        [],
                        prior_repair_binding={"preflight_evidence_sha256": "old"},
                    )
                )

            self.assertFalse(rebind.call_args.kwargs["required_doc_drift"])


if __name__ == "__main__":
    unittest.main()
