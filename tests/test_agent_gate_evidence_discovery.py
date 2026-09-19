"""Evidence discovery must not require writes to unrelated ancestor registries."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_gate_evidence import _claim_project
from agent_run_registry import register_run, registry_path


class ReadOnlyDiscoveryTests(unittest.TestCase):
    def test_ancestor_discovery_never_acquires_write_locks(self):
        with tempfile.TemporaryDirectory() as folder:
            ancestor = Path(folder).resolve()
            project = ancestor / "project"
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            route = {"command": "bugfix", "gates": []}
            register_run(ancestor, ancestor / ".tao" / "other.json", route, {})
            register_run(project, evidence, route, {})
            before = {p: p.read_bytes() for p in ancestor.rglob("*") if p.is_file()}
            with patch("agent_run_registry.project_state_lock", side_effect=PermissionError("write denied")):
                self.assertEqual(project, _claim_project(evidence))
            after = {p: p.read_bytes() for p in ancestor.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_duplicate_claim_still_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            ancestor = Path(folder).resolve()
            project = ancestor / "project"
            evidence = project / ".tao" / "preflight.json"
            evidence.parent.mkdir(parents=True)
            route = {"command": "bugfix", "gates": []}
            register_run(ancestor, evidence, route, {})
            register_run(project, evidence, route, {})
            with self.assertRaisesRegex(PermissionError, "multiple ancestor"):
                _claim_project(evidence)

    def test_malformed_ancestor_is_not_silently_unclaimed(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder).resolve()
            path = registry_path(project)
            path.parent.mkdir()
            for value in ("{", json.dumps({"schema_version": 1, "runs": [None]})):
                with self.subTest(value=value):
                    path.write_text(value)
                    with self.assertRaises((ValueError, PermissionError)):
                        _claim_project(project / ".tao" / "preflight.json")
