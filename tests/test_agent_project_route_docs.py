"""Project-declared route docs: policy validation and hash records."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import claude_worktree_gate as gate
from agent_project_route_docs import project_route_docs


class ProjectRouteDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def write_policy(self, route_docs) -> None:
        policy = {
            "schema_version": 1,
            "require_linked_worktree": True,
            "protected_branches": ["develop"],
            "route_docs": route_docs,
        }
        path = self.root / gate.WORKTREE_POLICY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(policy), encoding="utf-8")

    def test_valid_route_docs_keep_the_declared_policy(self) -> None:
        self.write_policy({"commit": [".agents/skills/commit/SKILL.md"]})
        policy = gate.worktree_policy(self.root)
        self.assertEqual(["develop"], policy["protected_branches"])
        self.assertIn("route_docs", policy)

    def test_malformed_route_docs_fall_back_to_the_default_policy(self) -> None:
        for route_docs in (
            [],
            {"Commit": ["a.md"]},
            {"commit": []},
            {"commit": ["/etc/passwd"]},
            {"commit": ["../outside.md"]},
            {"commit": ["a.md", "a.md"]},
            {"commit": [7]},
        ):
            with self.subTest(route_docs=route_docs):
                self.write_policy(route_docs)
                self.assertEqual(gate.default_worktree_policy(), gate.worktree_policy(self.root))

    def test_records_hash_existing_declared_docs_for_the_route_only(self) -> None:
        doc = self.root / ".agents/skills/commit/SKILL.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# Commit\n", encoding="utf-8")
        self.write_policy({
            "commit": [".agents/skills/commit/SKILL.md", ".agents/skills/missing.md"],
            "docs": [".agents/skills/commit/SKILL.md"],
        })

        records = project_route_docs(self.root, "commit")

        self.assertEqual([".agents/skills/commit/SKILL.md"], [item["path"] for item in records])
        self.assertEqual(len("# Commit\n"), records[0]["size_bytes"])
        self.assertRegex(records[0]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual([], project_route_docs(self.root, "feature"))

    def test_a_symlink_escaping_the_project_is_not_recorded(self) -> None:
        outside = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        outside.write("outside")
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        link = self.root / "docs/escape.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside.name)
        self.write_policy({"commit": ["docs/escape.md"]})
        self.assertEqual([], project_route_docs(self.root, "commit"))

    def test_no_policy_means_no_project_docs(self) -> None:
        self.assertEqual([], project_route_docs(self.root, "commit"))


if __name__ == "__main__":
    unittest.main()
