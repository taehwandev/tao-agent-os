from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_lookup_start
import workflow_doc_graph_cache
import workflow_route
import workflow_wikimap
from agent_route_state import request_fingerprint
from workflow_gate_policy import READ_ONLY_LOOKUP

_SPEC = importlib.util.spec_from_file_location("lookup_hook_test", ROOT / "scripts" / "agent-hook.py")
assert _SPEC and _SPEC.loader
agent_hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_hook)


def _arguments(project: Path, **overrides):
    args = agent_hook.build_parser().parse_args([
        "start", "--command", "analysis", "--request", "Explain the bounded lookup contract",
        "--project", str(project), "--rules", str(ROOT), "--runtime-session-id", "lookup-session",
    ])
    intake = {name: getattr(args, name) for name in (
        "request", "continuation_scope", "request_classified", "classification_evidence",
    )}
    args.intent_envelope = json.dumps({
        "schema_version": 1, "request_fingerprint": request_fingerprint(intake),
        "runtime_session_id": args.runtime_session_id, "mode": "answer",
        "intent": "analysis", "target_summary": "bounded lookup behavior",
        "requested_effects": ["read"], "ambiguity": "resolved",
    })
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


class StatelessLookupTests(unittest.TestCase):
    def test_cold_lookup_returns_real_guidance_without_state_or_index_update(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            args = _arguments(project)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(agent_hook, "_parse_args", return_value=args),
                patch.object(agent_hook, "_apply_worker_evidence_boundary", side_effect=AssertionError("worker mutation")),
                patch.object(agent_hook, "_name_timing_sink", side_effect=AssertionError("timing mutation")),
                patch.object(workflow_wikimap, "_corpus_signature", return_value=""),
                patch.object(workflow_wikimap, "_run", side_effect=AssertionError("external index process")),
                patch.object(Path, "write_text", side_effect=AssertionError("persistent write")),
                patch.object(Path, "mkdir", side_effect=AssertionError("persistent directory")),
                redirect_stdout(output),
            ):
                code = agent_hook.main()
            payload = json.loads(output.getvalue())
            self.assertEqual(0, code)
            self.assertTrue(payload["route"]["required_docs"])
            self.assertEqual(2, payload["route"]["lifecycle_version"])
            for field in ("gates", "gate_ledger", "hooks"):
                self.assertEqual([], payload["route"][field])
            self.assertEqual([], list(project.iterdir()))
            self.assertFalse(READ_ONLY_LOOKUP.get())

    def test_rejection_does_not_route_or_write(self):
        for reason in ("missing_envelope", "malformed_envelope", "wrong_session", "write_effect", "output"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                args = _arguments(project)
                envelope = json.loads(args.intent_envelope)
                if reason == "missing_envelope":
                    args.intent_envelope = ""
                elif reason == "malformed_envelope":
                    args.intent_envelope = "{not-json"
                elif reason == "wrong_session":
                    args.runtime_session_id = "another-session"
                elif reason == "write_effect":
                    envelope.update(mode="work", requested_effects=["local_write"])
                    args.intent_envelope = json.dumps(envelope)
                else:
                    args.output = project / ".tao" / "output.json"
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(agent_lookup_start, "resolve_docs", side_effect=AssertionError("unauthorized route")),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(2, agent_lookup_start.lookup_start(args))
                self.assertEqual([], list(project.iterdir()))

    def test_explicit_evidence_and_worker_boundaries_keep_legacy_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            scenarios = (
                ({"evidence": project / ".tao" / "existing" / "preflight.json"}, {}),
                ({}, {"TAO_WORKER_EVIDENCE": str(project / "worker.json")}),
                ({}, {"TAO_PARENT_EVIDENCE_READONLY": "1"}),
                ({"worker_reservation_token": "reservation"}, {}),
            )
            for overrides, environment in scenarios:
                with self.subTest(overrides=overrides, environment=environment):
                    args = _arguments(project, **overrides)
                    with patch.dict(os.environ, environment, clear=True):
                        self.assertIsNone(agent_lookup_start.lookup_start(args))
            self.assertEqual([], list(project.iterdir()))

    def test_existing_legacy_evidence_is_never_overwritten_or_upgraded(self):
        for command in ("analysis", "task"):
            for marker in (None, 1):
                with self.subTest(command=command, marker=marker), tempfile.TemporaryDirectory() as directory:
                    project = Path(directory)
                    evidence = project / "preflight.json"
                    route = {"command": command, "gates": ["legacy gate"]}
                    if marker is not None:
                        route["lifecycle_version"] = marker
                    evidence.write_text(json.dumps({"route": route}))
                    before = evidence.read_bytes()
                    args = _arguments(project, command=command, evidence=evidence)
                    with (
                        patch.dict(os.environ, {}, clear=True),
                        patch.object(agent_hook, "_parse_args", return_value=args),
                        patch.object(agent_hook, "_apply_worker_evidence_boundary", side_effect=AssertionError("state setup")),
                        patch.object(agent_hook, "_name_timing_sink", side_effect=AssertionError("timing setup")),
                        redirect_stdout(io.StringIO()),
                    ):
                        self.assertEqual(2, agent_hook.main())
                    self.assertEqual(before, evidence.read_bytes())
                    self.assertEqual([evidence], list(project.iterdir()))

    def test_verified_surface_paths_reach_the_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _arguments(Path(directory), surface_path=["scripts/owned.py"])
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(agent_lookup_start, "resolve_docs", return_value={"missing": []}) as resolve,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(0, agent_lookup_start.lookup_start(args))
            self.assertEqual(["scripts/owned.py"], resolve.call_args.kwargs["surface_paths"])
            forwarded = agent_hook._preflight_arguments(args)
            self.assertIn("--surface-path", forwarded)
            self.assertIn("scripts/owned.py", forwarded)

    def test_read_only_cache_context_restores_after_resolution_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _arguments(Path(directory))
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(agent_lookup_start, "resolve_docs", side_effect=RuntimeError("resolution failure")),
                self.assertRaises(RuntimeError),
            ):
                agent_lookup_start.lookup_start(args)
            self.assertFalse(READ_ONLY_LOOKUP.get())

    def test_read_only_lookup_keeps_existing_graph_cache_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".tao").mkdir()
            token = READ_ONLY_LOOKUP.set(True)
            try:
                workflow_doc_graph_cache.write_cached_graph(root, "cold", {"owner.md": []})
            finally:
                READ_ONLY_LOOKUP.reset(token)
            self.assertEqual([], list((root / ".tao").iterdir()))


if __name__ == "__main__":
    unittest.main()
