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

import agent_continuation_checkpoint as checkpoint_module
from agent_continuation_checkpoint import (
    first_unfinished_checkpoint,
    write_continuation_checkpoint,
)
from agent_continuation_packet import ContinuationPacketError, validate_continuation_packet
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION, doc_hash_record
from agent_gate_evidence import record_gate_evidence
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import register_run, registry_path, transition_run

GUIDANCE = "guidance.md"
ROUTE = {"command": "task", "gates": ["scope", "act", "verify"], "required_docs": [GUIDANCE]}
INTAKE = {"request": "implement the continuation protocol", "request_classified": False}
WORK = {"objective": "implement the shared continuation protocol"}
PRE_MUTATION_CHILD = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agent_continuation_checkpoint import write_continuation_checkpoint
write_continuation_checkpoint(
    project=Path(sys.argv[2]),
    rules=Path(sys.argv[3]),
    run_id=sys.argv[4],
    kind="pre_mutation",
    binding_path=Path(sys.argv[5]),
    mutation={"kind": "update", "paths": ["src/module.py"]},
)
print("READY", flush=True)
time.sleep(300)
"""


def initialize_git(project: Path) -> None:
    (project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
    for command in (
        ("init", "-q"),
        ("config", "user.email", "checkpoint@example.invalid"),
        ("config", "user.name", "Checkpoint Test"),
        ("add", "."),
        ("commit", "-qm", "fixture"),
    ):
        subprocess.run(
            ["git", *command],
            cwd=project,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class Fixture:
    """One registered run with its isolated preflight binding and ledger."""

    def __init__(self, directory: str, *, project: Path | None = None, rules: Path | None = None) -> None:
        self.project = project or Path(directory) / "project"
        self.rules = rules or Path(directory) / "rules"
        if not self.project.exists():
            (self.project / "src").mkdir(parents=True)
            (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        if not self.rules.exists():
            self.rules.mkdir()
            (self.rules / GUIDANCE).write_text("# guidance\n", encoding="utf-8")
        self.run = register_run(
            self.project, self.project / ".tao" / "preflight.json", ROUTE, INTAKE
        )
        self.run_id = self.run["run_id"]
        self.binding_path = self.project / ".tao" / "runs" / self.run_id / "preflight.json"
        self.binding_path.parent.mkdir(parents=True)
        self.preflight = {
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
        self.binding_path.write_text(json.dumps(self.preflight), encoding="utf-8")

    def checkpoint(self, kind: str, **keywords) -> dict:
        keywords.setdefault("work", WORK if kind == "initial" else None)
        keywords.setdefault("binding_path", self.binding_path)
        return write_continuation_checkpoint(
            project=self.project,
            rules=self.rules,
            run_id=self.run_id,
            kind=kind,
            **keywords,
        )

    def gate(self, gate: str, status: str = "SUCCESS") -> None:
        record_gate_evidence(
            evidence_path=self.binding_path,
            preflight=self.preflight,
            gate=gate,
            status=status,
            evidence="recorded by the test fixture",
        )

    def packet(self) -> dict:
        return read_continuation_packet(
            self.project, continuation_path(self.project, self.run_id)
        )["packet"]

    def rewrite_owner(self, owner: dict) -> None:
        path = registry_path(self.project)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for run in payload["runs"]:
            run["owner"] = owner
        path.write_text(json.dumps(payload), encoding="utf-8")


class InitialCheckpointTests(unittest.TestCase):
    def test_the_initial_checkpoint_is_a_complete_valid_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)

            packet = fixture.checkpoint("initial")

            self.assertEqual([], validate_continuation_packet(packet))
            self.assertEqual(0, packet["generation"])
            self.assertEqual("scoped", packet["phase"])
            self.assertEqual("preflight.json", packet["binding"]["filename"])
            self.assertEqual("preflight_snapshot", packet["binding"]["kind"])
            self.assertEqual("scope", packet["checkpoint"]["first_unfinished"])
            self.assertEqual(packet, fixture.packet())

    def test_each_checkpoint_rewrites_the_whole_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")

            second = fixture.checkpoint("decision", work={"blockers": ["waiting on review"]})

            self.assertEqual(1, second["generation"])
            self.assertEqual(WORK["objective"], second["work"]["objective"])
            self.assertEqual(["waiting on review"], second["work"]["blockers"])

    def test_a_stale_checkpoint_generation_cannot_overwrite_a_newer_snapshot(self) -> None:
        """The control would overwrite generation 1 without the packet CAS."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            stale = fixture.packet()
            newer = fixture.checkpoint(
                "decision", work={"blockers": ["newer decision"]}
            )

            with (
                patch.object(checkpoint_module, "_base_packet", return_value=stale),
                self.assertRaises(ContinuationPacketError) as raised,
            ):
                fixture.checkpoint(
                    "decision", work={"blockers": ["stale decision"]}
                )

            self.assertEqual(
                ["checkpoint_generation_changed"],
                [item["rule"] for item in raised.exception.failures],
            )
            self.assertEqual(newer, fixture.packet())

    def test_a_later_checkpoint_requires_an_existing_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)

            with self.assertRaises(ContinuationPacketError):
                fixture.checkpoint("lifecycle")

    def test_a_running_owner_cannot_forge_a_completed_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint(
                    "lifecycle",
                    phase="done",
                    finalize_completed=True,
                )

            self.assertEqual(
                ["invalid_completed_checkpoint"],
                [item["rule"] for item in raised.exception.failures],
            )

    def test_a_binding_outside_the_run_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            outside = fixture.project / ".tao" / "preflight.json"
            outside.write_text(fixture.binding_path.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("initial", binding_path=outside)

            self.assertEqual(
                ["binding_outside_run"], [item["rule"] for item in raised.exception.failures]
            )


class MutationBracketTests(unittest.TestCase):
    def test_the_pre_mutation_record_makes_an_interrupted_tool_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")

            packet = fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )

            pending = packet["checkpoint"]["mutation_pending"]
            self.assertEqual("acting", packet["phase"])
            self.assertEqual(["src/module.py"], pending["paths"])
            self.assertEqual(packet["drift"]["project"], pending["project"])
            baseline = fixture.binding_path.parent / ".mutation-baseline.json"
            payload = json.loads(baseline.read_text(encoding="utf-8"))
            # The boundary map is written now: without it a deletion inside a
            # declared directory has no boundary to be attributed to and reads
            # as an undeclared changed path. It stays path-opaque, which the
            # next assertion checks against the whole file.
            self.assertEqual(
                {"packet_generation", "states", "path_boundaries"}, set(payload)
            )
            self.assertNotIn("src/module.py", baseline.read_text(encoding="utf-8"))
            self.assertEqual(0, baseline.stat().st_mode & 0o077)

    def test_the_post_mutation_checkpoint_clears_the_pending_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            pre = fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

            packet = fixture.checkpoint(
                "post_mutation",
                work={"changed_scope": [{"path": "src/module.py", "role": "modified"}]},
            )

            self.assertIsNone(packet["checkpoint"]["mutation_pending"])
            # The refreshed state is what makes the packet and the bytes agree
            # again; without it the next resume would read the change as drift.
            self.assertNotEqual(
                pre["drift"]["project"]["worktree_fingerprint"],
                packet["drift"]["project"]["worktree_fingerprint"],
            )
            self.assertFalse((fixture.binding_path.parent / ".mutation-baseline.json").exists())

    def test_post_mutation_rejects_caller_verification_without_rewriting_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            prior_verification = [
                {
                    "id": "before_edit",
                    "kind": "unit",
                    "result": "success",
                    "evidence_sha256": "a" * 64,
                    "completed_at": "2026-08-13T00:00:00+00:00",
                }
            ]
            fixture.checkpoint(
                "initial",
                work={"objective": "edit after checking", "verification": prior_verification},
            )
            pending = fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            (fixture.project / "src" / "module.py").write_text(
                "value = 2\n", encoding="utf-8"
            )

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation", work={"verification": []})

            self.assertEqual(
                [
                    {
                        "rule": "post_mutation_verification_not_allowed",
                        "pointer": "/work/verification",
                    }
                ],
                raised.exception.failures,
            )
            self.assertEqual(pending, fixture.packet())
            self.assertTrue((fixture.binding_path.parent / ".mutation-baseline.json").is_file())

            completed = fixture.checkpoint("post_mutation")

            self.assertEqual([], completed["work"]["verification"])
            self.assertIsNone(completed["checkpoint"]["mutation_pending"])

    def test_an_undeclared_changed_path_fails_the_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.checkpoint("pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]})

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint(
                    "post_mutation",
                    work={"changed_scope": [{"path": "src/other.py", "role": "modified"}]},
                )

            self.assertEqual(
                ["undeclared_changed_path"], [item["rule"] for item in raised.exception.failures]
            )

    def test_an_actual_undeclared_path_fails_even_when_changed_scope_omits_it(self) -> None:
        """The control proves the writer inspects bytes, not adapter prose."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            pending = fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            (fixture.project / "src" / "other.py").write_text("unexpected = True\n", encoding="utf-8")

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation")

            self.assertEqual(
                ["undeclared_changed_path"], [item["rule"] for item in raised.exception.failures]
            )
            self.assertEqual(pending, fixture.packet())

    def test_a_symlinked_baseline_is_refused_without_reading_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/module.py"]}
            )
            baseline = fixture.binding_path.parent / ".mutation-baseline.json"
            victim = Path(directory) / "outside.json"
            victim.write_bytes(baseline.read_bytes())
            baseline.unlink()
            baseline.symlink_to(victim)
            before = victim.read_bytes()

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation")

            self.assertEqual(
                ["missing_mutation_baseline"],
                [item["rule"] for item in raised.exception.failures],
            )
            self.assertEqual(before, victim.read_bytes())

    def test_an_undeclared_index_change_is_detected_from_the_git_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            initialize_git(fixture.project)
            (fixture.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
            fixture.checkpoint("initial")
            pending = fixture.checkpoint(
                "pre_mutation", mutation={"kind": "update", "paths": ["src/allowed.py"]}
            )
            baseline = fixture.binding_path.parent / ".mutation-baseline.json"
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", str(baseline)],
                cwd=fixture.project,
                check=False,
            )
            self.assertEqual(0, ignored.returncode)
            self.assertEqual(fixture.binding_path.parent, baseline.parent)
            subprocess.run(
                ["git", "add", "src/module.py"],
                cwd=fixture.project,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation")

            self.assertEqual(
                ["undeclared_changed_path"], [item["rule"] for item in raised.exception.failures]
            )
            self.assertEqual(pending, fixture.packet())

    def test_a_killed_writer_leaves_the_baseline_usable_for_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    PRE_MUTATION_CHILD,
                    str(ROOT / "scripts"),
                    str(fixture.project),
                    str(fixture.rules),
                    fixture.run_id,
                    str(fixture.binding_path),
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual("READY", process.stdout.readline().strip())
            finally:
                process.kill()
                process.wait()
                process.stdout.close()
            (fixture.project / "src" / "other.py").write_text(
                "unexpected = True\n", encoding="utf-8"
            )

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation")

            self.assertEqual(
                ["undeclared_changed_path"],
                [item["rule"] for item in raised.exception.failures],
            )
            self.assertTrue((fixture.binding_path.parent / ".mutation-baseline.json").is_file())

    def test_a_post_mutation_checkpoint_without_a_pending_record_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("post_mutation")

            self.assertEqual(
                ["no_pending_mutation"], [item["rule"] for item in raised.exception.failures]
            )


class RequiredDocRebaseTests(unittest.TestCase):
    def test_a_normal_checkpoint_never_rebases_the_required_doc_digest(self) -> None:
        """A document that changed under the run stays drift until a fresh start.

        Refreshing the digest here would let the writer bless its own stale
        guidance, which is exactly the failure the drift check exists to catch.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            first = fixture.checkpoint("initial")
            (fixture.rules / GUIDANCE).write_text("# guidance, revised\n", encoding="utf-8")

            second = fixture.checkpoint("decision")

            self.assertEqual(
                first["drift"]["required_docs_sha256"], second["drift"]["required_docs_sha256"]
            )


class FirstUnfinishedTests(unittest.TestCase):
    def test_the_checkpoint_advances_with_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.gate("scope")

            self.assertEqual("act", fixture.checkpoint("lifecycle")["checkpoint"]["first_unfinished"])

    def test_a_recorded_failure_stays_the_checkpoint_despite_later_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.gate("scope")
            fixture.gate("act", status="FAIL")
            fixture.gate("verify")

            self.assertEqual("act", fixture.checkpoint("lifecycle")["checkpoint"]["first_unfinished"])

    def test_every_gate_recorded_leaves_finish_as_the_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            for gate in ROUTE["gates"]:
                fixture.gate(gate)

            self.assertEqual("finish", first_unfinished_checkpoint(fixture.binding_path))
            self.assertIsNone(
                first_unfinished_checkpoint(fixture.binding_path, run_state="completed")
            )

    def test_evidence_recorded_against_another_route_is_not_inherited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.gate("scope")
            ledger = fixture.binding_path.parent / "gate-evidence.json"
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            payload["route_fingerprint"] = "0" * 64
            ledger.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual("scope", first_unfinished_checkpoint(fixture.binding_path))


class OwnerCompareAndSwapTests(unittest.TestCase):
    def test_a_previous_owner_cannot_overwrite_a_newer_owners_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            fixture.checkpoint("initial")
            fixture.rewrite_owner({"pid": 999_999, "start_token": "other-session"})

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("decision")

            self.assertEqual(
                ["owner_changed"], [item["rule"] for item in raised.exception.failures]
            )

    def test_a_takeover_after_initial_inspection_prevents_the_old_owner_write(self) -> None:
        """The control fails if owner validation and packet replace are separated."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            original = fixture.checkpoint("initial")
            capture = checkpoint_module.capture_drift_state

            def capture_after_takeover(*args, **keywords):
                fixture.rewrite_owner({"pid": 999_999, "start_token": "new-owner"})
                return capture(*args, **keywords)

            with patch.object(
                checkpoint_module,
                "capture_drift_state",
                side_effect=capture_after_takeover,
            ):
                with self.assertRaises(ContinuationPacketError) as raised:
                    fixture.checkpoint("decision")

            self.assertEqual(
                ["owner_changed"], [item["rule"] for item in raised.exception.failures]
            )
            self.assertEqual(original, fixture.packet())

    def test_a_resume_generation_change_prevents_the_stale_checkpoint_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            original = fixture.checkpoint("initial")
            capture = checkpoint_module.capture_drift_state

            def capture_after_claim(*args, **keywords):
                path = registry_path(fixture.project)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["runs"][0]["resume_generation"] = 1
                path.write_text(json.dumps(payload), encoding="utf-8")
                return capture(*args, **keywords)

            with patch.object(
                checkpoint_module,
                "capture_drift_state",
                side_effect=capture_after_claim,
            ):
                with self.assertRaises(ContinuationPacketError) as raised:
                    fixture.checkpoint("decision")

            self.assertEqual(
                ["resume_generation_changed"],
                [item["rule"] for item in raised.exception.failures],
            )
            self.assertEqual(original, fixture.packet())

    def test_a_run_the_registry_does_not_know_cannot_be_checkpointed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            transition_run(
                fixture.project,
                fixture.project / ".tao" / "preflight.json",
                "completed",
                run_id=fixture.run_id,
            )
            path = registry_path(fixture.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runs"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ContinuationPacketError) as raised:
                fixture.checkpoint("initial")

            self.assertEqual(["unknown_run"], [item["rule"] for item in raised.exception.failures])


if __name__ == "__main__":
    unittest.main()
