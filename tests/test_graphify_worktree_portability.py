from __future__ import annotations

import hashlib
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

from support.graphify_configuration import (
    configure_global_graphify,
    configure_target_graphify,
)
from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PROJECT_GRAPH_PATH,
)
from support.graphify_inspection import inspect_target_graphify
from support.graphify_input_inspection import inspect_project_graph_inputs
from support.graphify_graph_integrity import repair_graph_integrity
from support.graphify_tracking import install_graphify_input_policy


class GraphifyWorktreePortabilityTests(unittest.TestCase):
    def test_global_setup_copies_runtime_bundle_and_creates_user_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "runtime" / ".tao" / "skills" / "graphify"
            home = root / "home"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("# bundled graphify\n", encoding="utf-8")

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ), patch(
                "support.graphify_configuration.shutil.which",
                return_value="/tmp/graphify",
            ):
                configure_global_graphify(
                    home,
                    ["claude", "codex"],
                    dry_run=False,
                    bundled_skill_dir=source,
                )

            canonical = home / GLOBAL_CANONICAL_SKILL_PATH
            self.assertEqual("# bundled graphify\n", canonical.read_text(encoding="utf-8"))
            for platform in ("agents", "claude", "codex"):
                link = home / GLOBAL_PLATFORM_SKILL_DIRS[platform]
                self.assertTrue(link.is_symlink())
                self.assertEqual(canonical.parent.resolve(), link.resolve())

    def test_target_readiness_uses_global_skill_and_local_graph_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            canonical = home / GLOBAL_CANONICAL_SKILL_PATH
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# global graphify\n", encoding="utf-8")
            for platform in ("agents", "claude", "codex"):
                link = home / GLOBAL_PLATFORM_SKILL_DIRS[platform]
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(
                    os.path.relpath(canonical.parent, start=link.parent),
                    target_is_directory=True,
                )

            source = project / "src" / "main.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            (project / ".graphifyignore").write_text(
                ".agents/local/\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(
                ["git", "add", "src/main.py", ".graphifyignore"],
                cwd=project,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Tao Agent OS",
                    "-c",
                    "user.email=tao@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=project,
                check=True,
            )
            built_at_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            graph = project / PROJECT_GRAPH_PATH
            graph.parent.mkdir(parents=True)
            graph.write_text(
                json.dumps(
                    {
                        "built_at_commit": built_at_commit,
                        "nodes": [
                            {
                                "id": "src_main",
                                "label": "main.py",
                                "file_type": "code",
                                "source_file": "src/main.py",
                            }
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
            (graph.parent / "manifest.json").write_text(
                json.dumps(
                    {
                        "src/main.py": {
                            "semantic_hash": hashlib.md5(source.read_bytes()).hexdigest()
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ):
                ready = inspect_target_graphify(
                    project,
                    ["claude", "codex"],
                    home_path=home,
                )
                leaked = project / ".tao" / "skills" / "graphify" / "SKILL.md"
                leaked.parent.mkdir(parents=True)
                leaked.write_text("# project copy\n", encoding="utf-8")
                rejected = inspect_target_graphify(
                    project,
                    ["claude", "codex"],
                    home_path=home,
                )

        self.assertTrue(ready["ready"])
        self.assertEqual(str(graph), ready["graph_path"])
        self.assertEqual([], ready["unexpected_project_runtime_assets"])
        self.assertFalse(rejected["ready"])
        self.assertEqual([str(leaked.parent)], rejected["unexpected_project_runtime_assets"])

    def test_target_check_never_installs_project_skills_or_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)

            configure_target_graphify(
                project,
                ["antigravity", "claude", "codex"],
                dry_run=False,
                home_path=project / "home",
            )

            self.assertEqual([], list(project.iterdir()))

    def test_input_policy_keeps_runtime_and_graph_cache_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            gitignore = project / ".gitignore"
            gitignore.write_text(".claude/\n.codex/\n", encoding="utf-8")

            install_graphify_input_policy(project)

            policy = (project / ".graphifyignore").read_text(encoding="utf-8")
            root_ignore = gitignore.read_text(encoding="utf-8")
            input_state = inspect_project_graph_inputs(project)

        self.assertIn(".tao/", policy)
        self.assertIn(".agents/local/", policy)
        self.assertEqual(".claude/\n.codex/\n", root_ignore)
        self.assertEqual([], input_state["blanket_knowledge_input_exclusions"])

    def test_integrity_repair_removes_only_invalid_generated_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = Path(temp_dir) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "a", "file_type": "code"},
                            {"id": "b", "file_type": "code"},
                        ],
                        "links": [
                            {"source": "a", "target": "b", "type": "VALID"},
                            {"source": "a", "target": "missing", "type": "DANGLING"},
                            {"source": "a", "target": "a", "type": "SELF"},
                            "malformed",
                        ],
                        "metadata": {"preserved": True},
                    }
                ),
                encoding="utf-8",
            )

            preview = repair_graph_integrity(graph, dry_run=True)
            self.assertEqual(3, preview["removed_edge_count"])
            self.assertEqual(4, len(json.loads(graph.read_text(encoding="utf-8"))["links"]))

            result = repair_graph_integrity(graph)
            repaired = json.loads(graph.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"])
        self.assertEqual(3, result["removed_edge_count"])
        self.assertEqual(
            [{"source": "a", "target": "b", "type": "VALID"}],
            repaired["links"],
        )
        self.assertEqual({"preserved": True}, repaired["metadata"])


if __name__ == "__main__":
    unittest.main()
