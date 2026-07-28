from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_hook_gate_records import preflight_evidence_path
from agent_route_state import request_fingerprint, route_fingerprint
from agent_run_registry import register_run, registry_path
from agent_runtime_session import (
    bind_resumed_runtime_session,
    resolve_runtime_evidence,
)

ROUTE = {"command": "task", "gates": ["finish"], "required_docs": []}
INTAKE = {"request": "runtime fixture request", "request_classified": False}


class RuntimeFixture:
    def __init__(self, directory: str, *, session_id: str = "old-session") -> None:
        self.project = Path(directory) / "project"
        self.rules = Path(directory) / "rules"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        self.rules.mkdir()
        self.run_id = uuid.uuid4().hex
        self.evidence = (
            self.project / ".tao" / "runs" / self.run_id / "preflight.json"
        )
        self.evidence.parent.mkdir(parents=True)
        run = register_run(self.project, self.evidence, ROUTE, INTAKE)
        if run["run_id"] != self.run_id:
            raise AssertionError("fixture run id was not adopted")
        self.preflight = {
            "project": str(self.project),
            "rules": str(self.rules),
            "route": ROUTE,
            "request_intake": INTAKE,
            "runtime_session": {"runtime": "claude", "session_id": session_id},
            "execution_snapshot": {
                "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
                "route_fingerprint": route_fingerprint(ROUTE),
                "request_fingerprint": request_fingerprint(INTAKE),
                "required_docs": [],
            },
        }
        self.evidence.write_text(json.dumps(self.preflight), encoding="utf-8")
        write_continuation_checkpoint(
            project=self.project,
            rules=self.rules,
            run_id=self.run_id,
            kind="initial",
            binding_path=self.evidence,
            work={"objective": "resume safe work"},
        )

    def packet(self) -> dict:
        return read_continuation_packet(
            self.project, continuation_path(self.project, self.run_id)
        )["packet"]

    def set_generation(self, generation: int) -> None:
        path = registry_path(self.project)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for run in payload["runs"]:
            if run["run_id"] == self.run_id:
                run["resume_generation"] = generation
        path.write_text(json.dumps(payload), encoding="utf-8")


class RuntimeEvidenceTests(unittest.TestCase):
    def test_exact_session_resolves_only_its_run_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)

            resolved = resolve_runtime_evidence(
                fixture.project,
                {"runtime": "claude", "session_id": "old-session"},
            )

            self.assertEqual(fixture.evidence.resolve(), resolved.resolve())
            self.assertIsNone(
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "other-session"},
                )
            )

    def test_resume_binding_replaces_the_session_and_refreshes_packet_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()["binding"]["file_sha256"]
            fixture.set_generation(1)

            bind_resumed_runtime_session(
                project=fixture.project,
                evidence_path=fixture.evidence,
                run_id=fixture.run_id,
                resume_generation=1,
                runtime="claude",
                session_id="new-session",
            )

            self.assertIsNone(
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "old-session"},
                )
            )
            self.assertEqual(
                fixture.evidence.resolve(),
                resolve_runtime_evidence(
                    fixture.project,
                    {"runtime": "claude", "session_id": "new-session"},
                ).resolve(),
            )
            self.assertNotEqual(before, fixture.packet()["binding"]["file_sha256"])

    def test_start_without_explicit_evidence_allocates_one_stable_run_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            args = Namespace(project=project, evidence=None, hook="start")
            with patch.dict(
                "os.environ", {"CLAUDE_CODE_SESSION_ID": "session-1"}, clear=True
            ):
                first = preflight_evidence_path(args)
                second = preflight_evidence_path(args)

            self.assertEqual(first, second)
            self.assertEqual("preflight.json", first.name)
            self.assertEqual(project / ".tao" / "runs", first.parent.parent)
            self.assertEqual(32, len(first.parent.name))


if __name__ == "__main__":
    unittest.main()
