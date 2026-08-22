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

    def test_lifecycle_heartbeat_reclaims_a_dead_owner_for_the_same_runtime_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            evidence = json.loads(run.evidence.read_text(encoding="utf-8"))
            evidence["agent_run_id"] = run.run_id
            evidence["runtime_session"] = {
                "runtime": "codex",
                "session_id": "same-session",
            }
            run.evidence.write_text(json.dumps(evidence), encoding="utf-8")
            registry = registry_path(run.project)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            payload["runs"][0]["state"] = "failed"
            payload["runs"][0]["owner"] = {"pid": 999999999, "start_token": ""}
            registry.write_text(json.dumps(payload), encoding="utf-8")

            with patch.dict("os.environ", {"CODEX_THREAD_ID": "same-session"}, clear=True):
                agent_hook._refresh_run_heartbeat(run.args())

            current = json.loads(registry.read_text(encoding="utf-8"))["runs"][0]
            self.assertEqual("resuming", current["state"])
            self.assertEqual(1, current["resume_generation"])

    def test_lifecycle_heartbeat_refuses_a_dead_owner_from_another_runtime_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)
            evidence = json.loads(run.evidence.read_text(encoding="utf-8"))
            evidence["agent_run_id"] = run.run_id
            evidence["runtime_session"] = {
                "runtime": "codex",
                "session_id": "original-session",
            }
            run.evidence.write_text(json.dumps(evidence), encoding="utf-8")
            registry = registry_path(run.project)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            payload["runs"][0]["state"] = "failed"
            payload["runs"][0]["owner"] = {"pid": 999999999, "start_token": ""}
            registry.write_text(json.dumps(payload), encoding="utf-8")

            with patch.dict("os.environ", {"CODEX_THREAD_ID": "different-session"}, clear=True):
                agent_hook._refresh_run_heartbeat(run.args())

            current = json.loads(registry.read_text(encoding="utf-8"))["runs"][0]
            self.assertEqual("failed", current["state"])
            self.assertEqual(0, current["resume_generation"])

    def test_a_genuinely_failed_finish_still_retires_the_run(self) -> None:
        """Control: the pending-closeout branch must not spare every failure."""

        with tempfile.TemporaryDirectory() as directory:
            run = HookRun(directory)

            self.assertEqual("failed", self._finish_state(run, 1))

    def test_failed_finish_never_rewrites_a_settled_run(self) -> None:
        """A stale finish request cannot reopen terminal lifecycle evidence."""

        for settled in ("completed", "cancelled"):
            with self.subTest(settled=settled), tempfile.TemporaryDirectory() as directory:
                run = HookRun(directory)
                transition_run(run.project, run.evidence, settled, run_id=run.run_id)

                self.assertEqual(settled, self._finish_state(run, 1))

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



class UnbindableRunDirectoryTests(unittest.TestCase):
    """A run directory that cannot hold a packet is refused while it can change.

    45 of 48 local run directories had readable names, so every one of those
    runs recorded no checkpoint and none could be resumed. The lifecycle said
    so on each hook, after the choice could no longer be undone, in a sentence
    that named the wrong cause: the evidence *was* a `.tao/runs/<name>/`
    preflight path -- the name simply was not opaque.
    """

    def _args(self, project: Path, evidence: Path | None) -> Namespace:
        return Namespace(project=project, evidence=evidence)

    def test_a_readable_run_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "persist-timings-20260822" / "preflight.json"

            message = wiring.unbindable_run_directory_error(self._args(project, evidence))

        self.assertIn("32-character hex run id", message)

    def test_the_refusal_names_the_way_out(self) -> None:
        """A refusal an agent cannot act on is the silent skip with extra words."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "readable" / "preflight.json"

            message = wiring.unbindable_run_directory_error(self._args(project, evidence))

        self.assertIn("Omit --evidence", message)
        self.assertIn("resume", message)

    def test_an_opaque_run_directory_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            self.assertEqual(
                "", wiring.unbindable_run_directory_error(self._args(project, evidence))
            )

    def test_evidence_outside_the_runs_root_is_left_alone(self) -> None:
        """The default path and worker paths have no packet by design."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for evidence in (
                project / ".tao" / "preflight.json",
                project / ".tao" / "workers" / "abcd1234" / "preflight.json",
                project / ".tao" / "runs" / RUN_ID / "nested" / "preflight.json",
            ):
                with self.subTest(evidence=evidence.name):
                    self.assertEqual(
                        "",
                        wiring.unbindable_run_directory_error(
                            self._args(project, evidence)
                        ),
                    )

    def test_no_evidence_is_not_a_bad_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                "",
                wiring.unbindable_run_directory_error(
                    self._args(Path(directory), None)
                ),
            )

    def test_start_refuses_and_later_hooks_do_not(self) -> None:
        """An already-started run under a bad name must still review and finish.

        Refusing start is what stops the loss; refusing the rest would strand
        every run that began before this check existed.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / "readable" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("{}", encoding="utf-8")

            start = agent_hook._lifecycle_evidence_error(
                Namespace(project=project, evidence=evidence, hook="start")
            )
            review = agent_hook._lifecycle_evidence_error(
                Namespace(project=project, evidence=evidence, hook="review")
            )

        self.assertIn("32-character hex run id", start)
        self.assertEqual("", review)

    def test_the_skip_says_what_was_lost(self) -> None:
        self.assertIn("resume this run", wiring.SKIPPED_DETAIL)



class WorkCheckpointAdviceTests(unittest.TestCase):
    """A packet that binds correctly can still be useless to resume.

    `resume --last` hands back the packet's whole `work` object, and the
    listing renders its objective. A lifecycle that never records one leaves
    `objective` as the route enum and every other field empty -- which is what
    happened, because the `checkpoint` hook is named only inside the session
    continuation reference that a work route does not require, and no hook
    output mentioned it.
    """

    def _args(self, project: Path, evidence: Path) -> Namespace:
        return Namespace(project=project, evidence=evidence)

    def test_a_run_with_a_packet_is_told_how_to_fill_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            advice = wiring.work_checkpoint_advice(self._args(project, evidence))

        printed = "\n".join(advice)

        self.assertIn("tao-hook checkpoint", printed)
        self.assertIn("--work-stdin", printed)
        self.assertIn("--checkpoint-kind", printed)

    def test_the_advice_names_the_fields_a_resume_is_handed(self) -> None:
        """Naming the hook without naming what it carries is not actionable."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        from agent_continuation_packet import WORK_FIELDS

        missing = [
            field
            for field in WORK_FIELDS
            if not any(
                spelling in advice
                for spelling in (field, field.replace("_", " "), field.replace("_", "-"))
            )
        ]
        self.assertEqual([], missing, advice)


    def test_the_advice_spells_the_object_shapes_from_the_schema(self) -> None:
        """Field names alone did not let a checkpoint be recorded.

        The first attempt failed on object shape: the entries are closed key
        sets with enum values, and the advice named none of them. Reading the
        enums from the validator is what keeps a new role or verification kind
        from silently going unmentioned.
        """

        from agent_continuation_packet import (
            DECISION_STATUSES,
            SCOPE_ROLES,
            VERIFICATION_KINDS,
            VERIFICATION_RESULTS,
        )

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        for group in (
            DECISION_STATUSES, SCOPE_ROLES, VERIFICATION_KINDS, VERIFICATION_RESULTS
        ):
            for value in group:
                with self.subTest(value=value):
                    self.assertIn(value, advice)
        for key in ("id", "status", "text", "path", "role", "checkpoint", "action"):
            with self.subTest(key=key):
                self.assertIn(key, advice)

    def test_the_advice_says_absent_keys_are_the_failure(self) -> None:
        """`optional` in the validator means nullable, not omittable."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            advice = "\n".join(
                wiring.work_checkpoint_advice(self._args(project, evidence))
            )

        self.assertIn("every key of an object must be present", advice)

    def test_a_real_start_prints_the_advice_itself(self) -> None:
        """A constant no hook emits is a comment, not an advertisement."""

        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            # The initial packet is written only after the execution state is
            # captured, and that needs a HEAD to read.
            for command in (
                ["git", "config", "user.email", "probe@example.invalid"],
                ["git", "config", "user.name", "probe"],
                ["git", "add", "AGENTS.md"],
                ["git", "commit", "-q", "-m", "probe", "--no-verify"],
            ):
                subprocess.run(command, cwd=project, check=True)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"
            evidence.parent.mkdir(parents=True)

            result = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "probe the packet advice",
                    "--read-only", "--evidence", str(evidence),
                ],
                cwd=project, capture_output=True, text=True,
                env={**os.environ, "TAO_STATE_HOME": state},
            )

        self.assertIn("tao-hook checkpoint", result.stdout, result.stdout)
        self.assertIn("--checkpoint-kind", result.stdout, result.stdout)



    def test_every_array_field_is_shown_with_its_cap(self) -> None:
        """`non_goals: text` is what made the second attempt fail.

        Every field but the objective is an array, and each has a maximum
        entry count. Both are read from the validator, so a printed number is
        the enforced number.
        """

        from agent_continuation_packet import WORK_ITEM_LIMITS

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            advice = "\n".join(
                wiring.work_checkpoint_advice(
                    self._args(project, project / ".tao" / "runs" / RUN_ID / "preflight.json")
                )
            )

        self.assertIn("array", advice)
        for field, limit in WORK_ITEM_LIMITS.items():
            with self.subTest(field=field):
                self.assertIn(f"{field}[{limit}]", advice)
        self.assertNotIn("objective[", advice)

    def test_the_printed_cap_is_the_cap_that_refuses(self) -> None:
        """A number in prose is decoration unless it is the enforced one."""

        from agent_continuation_packet import WORK_ITEM_LIMITS, _work

        limit = WORK_ITEM_LIMITS["non_goals"]
        empty = {
            "objective": "o", "non_goals": [], "decisions": [], "changed_scope": [],
            "inspected_scope": [], "verification": [], "remaining_work": [],
            "blockers": [],
        }

        allowed: list = []
        _work({**empty, "non_goals": ["x"] * limit}, allowed)
        refused: list = []
        _work({**empty, "non_goals": ["x"] * (limit + 1)}, refused)

        self.assertEqual([], allowed)
        self.assertTrue(refused)

    def test_the_advertised_command_records_a_checkpoint_as_printed(self) -> None:
        """Run what the hook prints, exactly as it prints it.

        Checking that the text names the fields proved nothing about whether
        it works: the first attempt at following it failed on a missing
        required flag, the second on `non_goals` being an array rather than a
        line. This test takes the command out of a real start's own output,
        substitutes only the paths, and runs it.
        """

        import os
        import subprocess

        def git(project: Path, *arguments: str) -> None:
            subprocess.run(["git", *arguments], cwd=project, check=True,
                           capture_output=True)

        work = {
            "objective": "prove the printed command runs",
            "non_goals": ["changing the packet schema"],
            "decisions": [
                {"id": "follow_the_advice", "status": "accepted",
                 "text": "the advice is the only instruction used here"}
            ],
            "changed_scope": [{"path": "scripts/agent_hook_continuation.py",
                               "role": "modified"}],
            "inspected_scope": [{"path": "scripts/agent_continuation_packet.py",
                                 "role": "inspected"}],
            "verification": [{"id": "e2e", "kind": "unit", "result": "success",
                              "evidence_sha256": None, "completed_at": None}],
            "remaining_work": [{"checkpoint": "review hook", "action": "review"}],
            "blockers": [],
        }

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            git(project, "init", "-q", ".")
            git(project, "config", "user.email", "probe@example.invalid")
            git(project, "config", "user.name", "probe")
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-q", "-m", "first", "--no-verify")
            environment = {**os.environ, "TAO_STATE_HOME": state}

            started = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "run the printed command",
                    "--read-only", "--runtime-session-id", "printed-command-probe",
                ],
                cwd=project, capture_output=True, text=True, env=environment,
            )
            printed = next(
                line for line in started.stdout.splitlines()
                if "tao-hook checkpoint" in line
            )
            evidence = next((project / ".tao" / "runs").glob("*/preflight.json"))

            # Only the paths are substituted; every flag is the hook's own.
            argv: list[str] = []
            for token in printed.split():
                if token in ("-", "tao-hook"):
                    continue
                if token == "<project>":
                    token = str(project)
                elif token == "<rules>":
                    token = str(ROOT)
                elif token == "<this-run>/preflight.json":
                    token = str(evidence)
                elif token in ("<", "work.json"):
                    continue  # the shell redirect; stdin is piped instead
                argv.append(token)

            recorded = subprocess.run(
                [sys.executable, str(SCRIPTS / "agent-hook.py"), *argv],
                cwd=project, input=json.dumps(work), capture_output=True,
                text=True, env=environment,
            )
            packet = json.loads(
                (evidence.parent / "continuation.json").read_text(encoding="utf-8")
            )

        self.assertIn("checkpoint", argv)
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
        self.assertEqual("prove the printed command runs", packet["work"]["objective"])
        self.assertEqual(["changing the packet schema"], packet["work"]["non_goals"])

    def test_a_run_without_a_packet_is_told_nothing(self) -> None:
        """Advice about a packet that cannot exist is noise on every start."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            self.assertEqual(
                [],
                wiring.work_checkpoint_advice(
                    self._args(project, project / ".tao" / "preflight.json")
                ),
            )



class AdoptedRunStartTests(unittest.TestCase):
    """A start does not always begin a run.

    When the runtime session already owns one, the evidence resolver adopts it,
    and an `initial` checkpoint is refused whenever a valid packet exists --
    which for an adopted run is always. The refusal is non-blocking, so the
    start reported SUCCESS while the packet stayed bound to the earlier start's
    HEAD, and `resume` then called that head_drift and rendered none of the
    saved work.
    """

    def _args(self, project: Path, evidence: Path, command: str = "task"):
        return Namespace(project=project, evidence=evidence, command=command)

    def test_a_run_with_a_packet_is_refreshed_not_initialised(self) -> None:
        from test_agent_runtime_session import RuntimeFixture

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)

            kind, work = wiring.start_checkpoint(
                self._args(fixture.project, fixture.evidence)
            )

        self.assertEqual("lifecycle", kind)
        self.assertIsNone(work)

    def test_the_refresh_keeps_the_objective_the_run_recorded(self) -> None:
        """The objective a start would write is the route enum.

        Overwriting a recorded one with that would lose exactly what the
        refresh exists to preserve.
        """

        from test_agent_runtime_session import RuntimeFixture

        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            args = self._args(fixture.project, fixture.evidence)
            args.rules = fixture.rules

            kind, work = wiring.start_checkpoint(args)
            wiring.record_lifecycle_checkpoint(args, kind, work=work)

            packet = fixture.packet()

        self.assertEqual("resume safe work", packet["work"]["objective"])
        self.assertEqual(1, packet["generation"])

    def test_a_run_with_no_packet_yet_is_initialised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / ".tao" / "runs" / RUN_ID / "preflight.json"

            kind, work = wiring.start_checkpoint(
                self._args(project, evidence, command="bugfix")
            )

        self.assertEqual("initial", kind)
        self.assertEqual({"objective": "bugfix workflow"}, work)

    def test_a_packet_free_run_is_still_asked_for_an_initial(self) -> None:
        """The writer refuses it anyway; the kind must not depend on that."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            kind, work = wiring.start_checkpoint(
                self._args(project, project / ".tao" / "preflight.json")
            )

        self.assertEqual("initial", kind)
        self.assertEqual({"objective": "task workflow"}, work)

    def test_a_real_adopted_start_rebinds_the_packet_to_the_new_head(self) -> None:
        """The end the fix is for: a restart after a commit leaves no drift."""

        import os
        import subprocess

        def git(project: Path, *arguments: str) -> None:
            subprocess.run(["git", *arguments], cwd=project, check=True,
                           capture_output=True)

        def start(project: Path, state: str) -> str:
            return subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "start",
                    "--project", str(project), "--rules", str(ROOT),
                    "--command", "triage", "--request", "one request, twice",
                    "--read-only", "--runtime-session-id", "adopted-run-probe",
                ],
                cwd=project, capture_output=True, text=True,
                env={**os.environ, "TAO_STATE_HOME": state},
            ).stdout

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as state:
            project = Path(directory) / "proj"
            project.mkdir()
            git(project, "init", "-q", ".")
            git(project, "config", "user.email", "probe@example.invalid")
            git(project, "config", "user.name", "probe")
            (project / "AGENTS.md").write_text("uses tao-hook\n", encoding="utf-8")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-q", "-m", "first", "--no-verify")

            first = start(project, state)

            (project / "NEXT.md").write_text("more\n", encoding="utf-8")
            git(project, "add", "NEXT.md")
            git(project, "commit", "-q", "-m", "second", "--no-verify")

            second = start(project, state)

            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            packets = list((project / ".tao" / "runs").glob("*/continuation.json"))
            packet = json.loads(packets[0].read_text(encoding="utf-8"))

        self.assertIn("continuation checkpoint: initial recorded", first)
        self.assertIn("continuation checkpoint: lifecycle recorded", second)
        self.assertNotIn("checkpoint_generation_changed", second)
        self.assertEqual(1, len(packets))
        self.assertEqual(head, packet["drift"]["project"]["head"])


if __name__ == "__main__":
    unittest.main()
