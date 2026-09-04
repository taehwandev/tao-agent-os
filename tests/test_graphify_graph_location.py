"""The graph is where it is, not where the contract wishes it were.

Setup asks graphify to write under `.agents/local/graphify-out`. The commit
hooks are installed by graphify's own installer, carry no such assignment, and
write to the CLI default at the repository root. Asserting only the first path
left this repository's agents reading an empty directory while the only graph
on disk -- rebuilt on every branch switch -- sat in the second.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.graphify_contract import (  # noqa: E402
    FALLBACK_GRAPH_DIR,
    PROJECT_GRAPH_DIR,
    resolve_graph_path,
)
from support.graphify_inspection import inspect_target_graphify  # noqa: E402


class ResolveGraphPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)

    def _write(self, relative: Path, *, age_seconds: int = 0) -> Path:
        path = self.project / relative / "graph.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"nodes": []}', encoding="utf-8")
        if age_seconds:
            when = path.stat().st_mtime - age_seconds
            os.utime(path, (when, when))
        return path

    def test_a_project_with_no_graph_answers_none(self) -> None:
        self.assertIsNone(resolve_graph_path(self.project))

    def test_the_redirected_location_is_found(self) -> None:
        expected = self._write(PROJECT_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_cli_default_is_found_when_nothing_redirected_it(self) -> None:
        """This is the ordinary case, and the one that used to read as absent."""

        expected = self._write(FALLBACK_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_newer_graph_wins_when_both_exist(self) -> None:
        self._write(PROJECT_GRAPH_DIR, age_seconds=3600)
        expected = self._write(FALLBACK_GRAPH_DIR)

        self.assertEqual(expected, resolve_graph_path(self.project))

    def test_the_redirected_graph_wins_when_it_is_not_older(self) -> None:
        expected = self._write(PROJECT_GRAPH_DIR)
        self._write(FALLBACK_GRAPH_DIR, age_seconds=3600)

        self.assertEqual(expected, resolve_graph_path(self.project))


class FallbackGraphReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        self.source = self.project / "main.py"
        self.source.write_text("VALUE = 1\n", encoding="utf-8")
        self._commit("initial", "main.py")
        self.head = self._head()
        self.graph = self.project / FALLBACK_GRAPH_DIR / "graph.json"
        self.graph.parent.mkdir(parents=True)
        self.graph.write_text(
            json.dumps(
                {
                    "built_at_commit": self.head,
                    "nodes": [
                        {
                            "id": "main",
                            "file_type": "code",
                            "source_file": "main.py",
                        }
                    ],
                    "links": [],
                }
            ),
            encoding="utf-8",
        )
        (self.graph.parent / "manifest.json").write_text(
            json.dumps({"main.py": {"mtime": self.source.stat().st_mtime}}),
            encoding="utf-8",
        )

    def _commit(self, message: str, *paths: str) -> None:
        subprocess.run(["git", "add", *paths], cwd=self.project, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Tao Agent OS",
                "-c",
                "user.email=tao@example.invalid",
                "commit",
                "-qm",
                message,
            ],
            cwd=self.project,
            check=True,
        )

    def _head(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.project,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def _inspect(self) -> dict[str, object]:
        global_state = {
            "cli": "/tmp/graphify",
            "platforms": ["codex"],
            "canonical_skill_doc": "/tmp/SKILL.md",
            "canonical_skill_exists": True,
            "canonical_skill_fresh": True,
            "canonical_skill_missing_files": [],
            "canonical_skill_extra_files": [],
            "canonical_skill_changed_files": [],
            "skill_docs": ["/tmp/SKILL.md"],
            "runtime_skill_links": {"codex": "/tmp/graphify-skill"},
            "invalid_runtime_links": [],
            "ready": True,
        }
        with patch(
            "support.graphify_inspection.inspect_global_graphify",
            return_value=global_state,
        ):
            return inspect_target_graphify(self.project, ["codex"])

    def test_readiness_uses_the_fallback_graph_and_its_sibling_manifest(self) -> None:
        readiness = self._inspect()

        self.assertEqual(str(self.graph), readiness["graph_path"])
        self.assertTrue(readiness["graph_exists"])
        self.assertTrue(readiness["graph_fresh"])
        self.assertTrue(readiness["graph_head_matches"])
        self.assertTrue(readiness["graph_head_comparison_ready"])
        self.assertTrue(readiness["graph_worktree_status_ready"])
        self.assertTrue(readiness["graph_integrity_ready"])
        self.assertTrue(readiness["ready"])

    def test_clean_new_commit_rejects_an_older_graph_manifest(self) -> None:
        added = self.project / "added.py"
        added.write_text("ADDED = True\n", encoding="utf-8")
        self._commit("add source", "added.py")

        readiness = self._inspect()

        self.assertFalse(readiness["graph_head_matches"])
        self.assertTrue(readiness["graph_head_comparison_ready"])
        self.assertFalse(readiness["graph_fresh"])
        self.assertFalse(readiness["ready"])

    def test_committed_local_runtime_state_does_not_stale_the_graph(self) -> None:
        local_state = self.project / ".tao" / "skills" / "local.md"
        local_state.parent.mkdir(parents=True)
        local_state.write_text("# local runtime state\n", encoding="utf-8")
        self._commit("add local state", ".tao/skills/local.md")

        readiness = self._inspect()

        self.assertFalse(readiness["graph_head_matches"])
        self.assertTrue(readiness["graph_head_comparison_ready"])
        self.assertTrue(readiness["graph_fresh"])
        self.assertTrue(readiness["ready"])

    def test_unavailable_graph_commit_comparison_fails_closed(self) -> None:
        payload = json.loads(self.graph.read_text(encoding="utf-8"))
        payload["built_at_commit"] = "0" * 40
        self.graph.write_text(json.dumps(payload), encoding="utf-8")

        readiness = self._inspect()

        self.assertFalse(readiness["graph_head_matches"])
        self.assertFalse(readiness["graph_head_comparison_ready"])
        self.assertFalse(readiness["graph_fresh"])
        self.assertFalse(readiness["ready"])

    def test_unavailable_worktree_status_fails_closed(self) -> None:
        with patch(
            "support.graphify_graph_freshness._dirty_source_paths",
            return_value=([], False),
        ):
            readiness = self._inspect()

        self.assertFalse(readiness["graph_worktree_status_ready"])
        self.assertFalse(readiness["graph_fresh"])
        self.assertFalse(readiness["ready"])

if __name__ == "__main__":
    unittest.main()
