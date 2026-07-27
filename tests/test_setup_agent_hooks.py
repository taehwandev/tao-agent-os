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

from support.permission_entries import (
    claude_legacy_permission_entries,
    codex_legacy_prefix_rule_entries,
    codex_prefix_rule_entries,
)
from support.setup_config_files import merge_codex_prefix_rules, merge_permissions_allow
from support.graphify_setup import (
    GLOBAL_PLATFORM_SKILL_DIRS,
    _normalize_runtime_integrations,
    configure_target_graphify,
    graphify_platforms_for_runtimes,
    inspect_global_graphify,
    inspect_target_graphify,
)
from support.graphify_git_tracking import inspect_graphify_git_tracking
from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_PATH,
    PROJECT_GRAPH_PATH,
    PROJECT_MANIFEST_PATH,
)
from support.graphify_inspection import (
    inspect_project_graph_inputs,
    inspect_project_graph_state,
)
from support.graphify_document_links import repair_project_document_links
from support.graphify_tracking import install_tracking_policies
from support import setup_agent_hooks_impl
from support.setup_agent_hooks_impl import (
    _should_configure_global_graphify,
    configure_external_project,
    ensure_local_claude_excluded,
)
from support.stable_launcher import ensure_stable_launcher, stable_launcher_path, stable_root_pointer_path


class SetupAgentHooksTests(unittest.TestCase):
    def test_default_setup_configures_all_detected_agent_runtimes(self) -> None:
        with (
            patch.object(sys, "argv", ["setup-agent-hooks.py", "--check"]),
            patch.object(setup_agent_hooks_impl, "_has_codex", return_value=True),
            patch.object(setup_agent_hooks_impl, "_has_claude", return_value=True),
            patch.object(setup_agent_hooks_impl, "_has_agy", return_value=True),
            patch.object(setup_agent_hooks_impl, "ensure_stable_launcher", return_value=[]),
            patch.object(setup_agent_hooks_impl, "configure_codex", return_value=[]) as configure_codex,
            patch.object(setup_agent_hooks_impl, "configure_claude", return_value=[]) as configure_claude,
            patch.object(setup_agent_hooks_impl, "configure_agy", return_value=[]) as configure_agy,
            patch.object(setup_agent_hooks_impl, "configure_global_graphify", return_value=[]),
            patch.object(setup_agent_hooks_impl, "configure_target_projects", return_value=[]),
        ):
            setup_agent_hooks_impl.main()

        configure_codex.assert_called_once()
        configure_claude.assert_called_once()
        configure_agy.assert_called_once()

    def test_codex_only_setup_refreshes_shared_global_graphify(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["setup-agent-hooks.py", "--check", "--runtime", "codex"],
            ),
            patch.object(setup_agent_hooks_impl, "_has_codex", return_value=True),
            patch.object(
                setup_agent_hooks_impl,
                "ensure_stable_launcher",
                return_value=[],
            ) as ensure_launcher,
            patch.object(setup_agent_hooks_impl, "configure_codex", return_value=[]),
            patch.object(
                setup_agent_hooks_impl.shutil,
                "which",
                return_value="/tmp/graphify",
            ),
            patch.object(
                setup_agent_hooks_impl,
                "configure_global_graphify",
            ) as configure_global,
            patch.object(setup_agent_hooks_impl, "configure_target_projects", return_value=[]),
        ):
            setup_agent_hooks_impl.main()

        configure_global.assert_called_once()
        ensure_launcher.assert_called_once_with(ROOT, True)

    def test_agy_only_setup_installs_stable_launcher(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["setup-agent-hooks.py", "--runtime", "agy"],
            ),
            patch.object(setup_agent_hooks_impl, "_has_agy", return_value=True),
            patch.object(
                setup_agent_hooks_impl,
                "ensure_stable_launcher",
                return_value=[],
            ) as ensure_launcher,
            patch.object(setup_agent_hooks_impl, "configure_agy", return_value=[]),
            patch.object(setup_agent_hooks_impl, "configure_global_graphify", return_value=[]),
            patch.object(setup_agent_hooks_impl, "configure_target_projects", return_value=[]),
        ):
            setup_agent_hooks_impl.main()

        ensure_launcher.assert_called_once_with(ROOT, False)

    def test_global_graphify_stays_enabled_for_every_runtime_setup(self) -> None:
        self.assertTrue(_should_configure_global_graphify({"codex"}))
        self.assertTrue(_should_configure_global_graphify(set()))
        self.assertTrue(_should_configure_global_graphify({"claude"}))
        self.assertTrue(_should_configure_global_graphify({"codex", "claude"}))

    def test_graphify_readiness_reports_leaked_runtime_assets_as_missing_integrations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            leaked = project / ".codex" / "skills" / "graphify"
            leaked.mkdir(parents=True)
            (leaked / "SKILL.md").write_text("# leaked copy\n", encoding="utf-8")

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ):
                readiness = inspect_target_graphify(
                    project, ["codex"], home_path=root / "home"
                )

        self.assertIn(str(leaked), readiness["missing_integrations"])
        self.assertEqual(
            readiness["unexpected_project_runtime_assets"],
            readiness["missing_integrations"],
        )
        self.assertFalse(readiness["project_integration_ready"])
        self.assertFalse(readiness["ready"])

    def test_git_tracking_shim_reports_no_commit_obligations_for_legacy_runtime_files(self) -> None:
        # Git no longer owns any Graphify asset in target repos: legacy skill
        # copies are runtime-asset leaks (project boundary), not staging work.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            legacy_copy = project / ".codex" / "skills" / "graphify" / "SKILL.md"
            legacy_copy.parent.mkdir(parents=True)
            legacy_copy.write_text("# legacy copy\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "add", "-A"], cwd=project, check=True)

            tracking = inspect_graphify_git_tracking(project, ["codex"])
            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ):
                results = configure_target_graphify(
                    project, ["codex"], dry_run=True, home_path=root / "home"
                )

        self.assertIsNone(tracking["commit_ready"])
        self.assertEqual([], tracking["tracked_runtime_skill_copies"])
        self.assertEqual([], tracking["runtime_link_index_issues"])
        self.assertEqual([], tracking["unstaged_commit_assets"])
        self.assertFalse(
            any(result["hook"].startswith("tracking.") for result in results)
        )
        self.assertTrue(
            any(
                result["hook"] == "project.runtime_asset"
                and result["status"] == "missing"
                and result["path"] == str(legacy_copy.parent)
                for result in results
            )
        )

    def test_global_graphify_readiness_requires_one_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            canonical = home / GLOBAL_CANONICAL_SKILL_PATH
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# canonical graphify\n")
            for platform in ("agents", "antigravity", "claude", "codex"):
                link = home / GLOBAL_PLATFORM_SKILL_DIRS[platform]
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(
                    os.path.relpath(canonical.parent, start=link.parent),
                    target_is_directory=True,
                )

            with patch("support.graphify_inspection.shutil.which", return_value="/tmp/graphify"):
                readiness = inspect_global_graphify(
                    home,
                    ["antigravity", "claude", "codex"],
                    bundled_skill_dir=canonical.parent,
                )

        self.assertTrue(readiness["ready"])
        self.assertEqual(4, len(readiness["runtime_skill_links"]))

    def test_project_graphify_setup_cli_defaults_to_agent_agnostic_install(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "setup-project-graphify.py"), "--help"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("installs all three", result.stdout)
        self.assertIn("--jobs", result.stdout)
        self.assertIn("--repair-input-policy", result.stdout)
        self.assertIn("--repair-document-links", result.stdout)

    def test_target_graphify_readiness_accepts_ast_graph_without_document_code_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            canonical = home / GLOBAL_CANONICAL_SKILL_PATH
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# graphify\n", encoding="utf-8")
            for platform in ("agents", "codex"):
                link = home / GLOBAL_PLATFORM_SKILL_DIRS[platform]
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(
                    os.path.relpath(canonical.parent, start=link.parent),
                    target_is_directory=True,
                )

            source = project / "src" / "main.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            guide = project / ".agents" / "wiki" / "guide.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("# Guide\n", encoding="utf-8")
            (project / ".graphifyignore").write_text(
                ".agents/local/\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "add", "-A"], cwd=project, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Tao Agent OS", "-c",
                    "user.email=tao@example.invalid", "commit", "-qm", "source",
                ],
                cwd=project,
                check=True,
            )
            head = subprocess.run(
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
                        "built_at_commit": head,
                        "nodes": [
                            {
                                "id": "src_main",
                                "file_type": "code",
                                "source_file": "src/main.py",
                            },
                            {
                                "id": "guide",
                                "file_type": "document",
                                "source_file": ".agents/wiki/guide.md",
                            },
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
            (project / PROJECT_MANIFEST_PATH).write_text(
                json.dumps(
                    {
                        "src/main.py": {"mtime": source.stat().st_mtime},
                        ".agents/wiki/guide.md": {"mtime": guide.stat().st_mtime},
                    }
                ),
                encoding="utf-8",
            )

            with patch("support.graphify_inspection.shutil.which", return_value="/tmp/graphify"):
                result = inspect_target_graphify(project, ["codex"], home_path=home)

        self.assertTrue(result["ready"], result)
        self.assertEqual(str(graph), result["graph_path"])
        self.assertEqual(str(canonical), result["canonical_skill_doc"])
        self.assertEqual([], result["unexpected_project_runtime_assets"])
        self.assertTrue(result["graph_integrity_ready"])
        self.assertFalse(result["graph_relationship_ready"])

    def test_graphify_skill_matches_ast_only_readiness_policy(self) -> None:
        skill_dir = ROOT / "docs" / "skills" / "graphify-project-integration"
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        guidance = (
            skill_dir / "references" / "current-guidance.md"
        ).read_text(encoding="utf-8")

        self.assertIn("an AST-only graph", guidance)
        self.assertIn("not mandatory", guidance)
        for text in (skill, guidance):
            self.assertNotIn(
                "When project docs and code both exist, the graph must contain",
                text,
            )

    def test_graphify_input_policy_preserves_project_agent_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            guides = [
                project / ".agents" / "llm-wiki" / "guide.md",
                project / ".agents" / "skills" / "review" / "SKILL.md",
                project / ".agents" / "wiki" / "testing.md",
            ]
            for guide in guides:
                guide.parent.mkdir(parents=True)
                guide.write_text("# Project guide\n", encoding="utf-8")
            managed = (
                "# tao-graphify-inputs:start\n"
                ".tao/\n.agents/\n.agents/local/\ngraphify-out/\n"
                "# tao-graphify-inputs:end\n"
            )
            (project / ".graphifyignore").write_text(managed, encoding="utf-8")
            manifest = project / PROJECT_MANIFEST_PATH
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        guide.relative_to(project).as_posix(): {
                            "mtime": guide.stat().st_mtime
                        }
                        for guide in guides
                    }
                ),
                encoding="utf-8",
            )

            before = inspect_project_graph_inputs(project)
            guides[0].write_text("# Changed project guide\n", encoding="utf-8")
            stale = inspect_project_graph_inputs(project)
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_payload[guides[0].relative_to(project).as_posix()]["mtime"] = (
                guides[0].stat().st_mtime
            )
            manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
            install_tracking_policies(project)
            after = inspect_project_graph_inputs(project)
            policy = (project / ".graphifyignore").read_text(encoding="utf-8")

        self.assertFalse(before["graph_input_policy_ready"])
        self.assertTrue(before["knowledge_manifest_ready"])
        self.assertEqual(3, before["project_knowledge_file_count"])
        self.assertFalse(stale["knowledge_manifest_ready"])
        self.assertEqual(1, stale["knowledge_manifest_stale_count"])
        self.assertTrue(after["graph_input_policy_ready"])
        self.assertTrue(after["knowledge_manifest_ready"])
        self.assertNotIn("\n.agents/\n", policy)
        self.assertIn(".tao/", policy)
        self.assertIn(".agents/local/", policy)
        self.assertIn("graphify-out/", policy)

    def test_graphify_input_policy_rejects_blanket_knowledge_exclusion_before_knowledge_exists(self) -> None:
        # .claude/.codex are user-level runtime homes now, not project
        # knowledge inputs; only a blanket .agents exclusion is a policy break.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".graphifyignore").write_text(
                ".claude/\n.agents/\n",
                encoding="utf-8",
            )

            state = inspect_project_graph_inputs(project)

        self.assertFalse(state["graph_input_policy_ready"])
        self.assertEqual(
            [".graphifyignore:.agents/"],
            state["blanket_knowledge_input_exclusions"],
        )

    def test_graphify_manifest_uses_content_hash_before_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            guide = project / ".agents" / "wiki" / "guide.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("# Guide\n", encoding="utf-8")
            (project / ".graphifyignore").write_text(
                ".agents/local/\n", encoding="utf-8"
            )
            manifest = project / PROJECT_MANIFEST_PATH
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        ".agents/wiki/guide.md": {
                            "mtime": 1,
                            "semantic_hash": hashlib.md5(guide.read_bytes()).hexdigest(),
                        }
                    }
                ),
                encoding="utf-8",
            )

            state = inspect_project_graph_inputs(project)

        self.assertTrue(state["knowledge_manifest_ready"])
        self.assertEqual(0, state["knowledge_manifest_stale_count"])

    def test_graphify_input_policy_detects_root_gitignore_wildcard_blanket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".gitignore").write_text(
                "**/.agents/**/*\n",
                encoding="utf-8",
            )

            state = inspect_project_graph_inputs(project)

        self.assertFalse(state["graph_input_policy_ready"])
        self.assertEqual(
            [".gitignore:**/.agents/**/*"],
            state["blanket_knowledge_input_exclusions"],
        )

    def test_graphify_managed_input_policy_collapses_duplicate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            policy = project / ".graphifyignore"
            policy.write_text(
                "# keep\n.claude/\n.codex/**\n"
                "# tao-graphify-inputs:start\n.agents/\n"
                "# tao-graphify-inputs:end\n"
                "# tao-graphify-inputs:start\n.codex/\n"
                "# tao-graphify-inputs:end\n",
                encoding="utf-8",
            )
            root_ignore = project / ".gitignore"
            root_ignore.write_text(
                ".agents/\n.claude/\n.codex/**\n",
                encoding="utf-8",
            )

            original_root_content = root_ignore.read_text(encoding="utf-8")
            install_tracking_policies(project)
            content = policy.read_text(encoding="utf-8")
            root_content = root_ignore.read_text(encoding="utf-8")

        self.assertEqual(1, content.count("# tao-graphify-inputs:start"))
        self.assertEqual(1, content.count("# tao-graphify-inputs:end"))
        self.assertIn("# keep", content)
        # Only the managed block is rewritten: superseded block bodies are
        # replaced with the current inputs while user-owned lines survive.
        self.assertNotIn("\n.agents/\n", content)
        self.assertNotIn("\n.codex/\n", content)
        self.assertIn("\n.claude/\n", content)
        self.assertIn(".codex/**", content)
        self.assertIn(".tao/", content)
        self.assertIn(".agents/local/", content)
        self.assertIn("graphify-out/", content)
        # Graphify no longer owns the project .gitignore.
        self.assertEqual(original_root_content, root_content)

    def test_graph_freshness_ignores_managed_runtime_adapter_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            source = project / "src" / "main.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            deleted = project / "src" / "deleted.py"
            deleted.write_text("VALUE = 0\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/main.py", "src/deleted.py"],
                cwd=project,
                check=True,
            )
            subprocess.run(
                [
                    "git", "-c", "user.name=Tao Agent OS", "-c",
                    "user.email=tao@example.invalid", "commit", "-qm", "initial",
                ],
                cwd=project,
                check=True,
            )
            head = subprocess.run(
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
                        "built_at_commit": head,
                        "nodes": [
                            {
                                "id": "main",
                                "file_type": "code",
                                "source_file": "src/main.py",
                            }
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
            (project / PROJECT_MANIFEST_PATH).write_text(
                json.dumps({"src/main.py": {"mtime": source.stat().st_mtime}}),
                encoding="utf-8",
            )
            adapter = project / ".agents" / "rules" / "graphify.md"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("# legacy adapter\n", encoding="utf-8")
            nested_evidence = project / "scripts" / ".tao" / "preflight.json"
            nested_evidence.parent.mkdir(parents=True)
            nested_evidence.write_text('{"runtime": true}', encoding="utf-8")

            adapter_only = inspect_project_graph_state(project, graph)
            extra_source = project / "src" / "extra.py"
            extra_source.write_text("VALUE = 2\n", encoding="utf-8")
            uncovered_source = inspect_project_graph_state(project, graph)
            extra_source.unlink()
            deleted.unlink()
            deleted_source = inspect_project_graph_state(project, graph)

        self.assertTrue(adapter_only["graph_fresh"])
        self.assertEqual(0, adapter_only["graph_source_dirty_count"])
        self.assertFalse(uncovered_source["graph_fresh"])
        self.assertEqual(1, uncovered_source["graph_source_dirty_count"])
        self.assertTrue(deleted_source["graph_fresh"])
        self.assertEqual(0, deleted_source["graph_source_dirty_count"])

    def test_project_graph_state_uses_current_manifest_and_reports_relationship_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            source = project / "src" / "main.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            guide = project / ".agents" / "wiki" / "guide.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("# Guide\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/main.py", ".agents/wiki/guide.md"],
                cwd=project,
                check=True,
            )
            subprocess.run(
                [
                    "git", "-c", "user.name=Tao Agent OS", "-c",
                    "user.email=tao@example.invalid", "commit", "-qm", "initial",
                ],
                cwd=project,
                check=True,
            )
            head = subprocess.run(
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
                        "built_at_commit": head,
                        "nodes": [
                            {"id": "guide", "file_type": "document", "source_file": ".agents/wiki/guide.md"},
                            {"id": "concept", "file_type": "rationale", "source_file": ".agents/wiki/guide.md"},
                            {"id": "script_mention", "file_type": "code", "source_file": ".agents/wiki/guide.md"},
                            {"id": "main", "file_type": "code", "source_file": "src/main.py"},
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
            (project / PROJECT_MANIFEST_PATH).write_text(
                json.dumps(
                    {
                        "src/main.py": {"mtime": source.stat().st_mtime},
                        ".agents/wiki/guide.md": {"mtime": guide.stat().st_mtime},
                    }
                ),
                encoding="utf-8",
            )

            disconnected = inspect_project_graph_state(project, graph)
            payload = json.loads(graph.read_text(encoding="utf-8"))
            payload["links"] = [
                {"source": "guide", "target": "concept"},
                {"source": "concept", "target": "main"},
            ]
            graph.write_text(json.dumps(payload), encoding="utf-8")
            connected = inspect_project_graph_state(project, graph)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "src/main.py"], cwd=project, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Tao Agent OS", "-c",
                    "user.email=tao@example.invalid", "commit", "-qm", "change",
                ],
                cwd=project,
                check=True,
            )
            stale = inspect_project_graph_state(project, graph)
            (project / PROJECT_MANIFEST_PATH).write_text(
                json.dumps(
                    {
                        "src/main.py": {"mtime": source.stat().st_mtime},
                        ".agents/wiki/guide.md": {"mtime": guide.stat().st_mtime},
                    }
                ),
                encoding="utf-8",
            )
            rebuilt_from_dirty_worktree = inspect_project_graph_state(project, graph)

        self.assertTrue(disconnected["graph_fresh"])
        self.assertFalse(disconnected["graph_relationship_ready"])
        self.assertEqual(1, disconnected["graph_code_node_count"])
        self.assertEqual(0, disconnected["graph_document_code_edge_count"])
        self.assertTrue(connected["graph_relationship_ready"])
        self.assertEqual(0, connected["graph_document_code_edge_count"])
        self.assertEqual(1, connected["graph_document_code_path_node_count"])
        self.assertEqual(2, connected["graph_knowledge_code_path_node_count"])
        self.assertFalse(stale["graph_fresh"])
        self.assertTrue(rebuilt_from_dirty_worktree["graph_fresh"])

    def test_project_graph_integrity_rejects_malformed_and_duplicate_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            graph = project / PROJECT_GRAPH_PATH
            graph.parent.mkdir(parents=True)
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "main", "file_type": "code"},
                            {"id": "main", "file_type": "code"},
                            {"label": "missing id", "file_type": "document"},
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            state = inspect_project_graph_state(project, graph)

        self.assertFalse(state["graph_integrity_ready"])
        self.assertEqual(1, state["graph_duplicate_node_id_count"])
        self.assertEqual(1, state["graph_malformed_node_count"])

    def test_graphify_document_link_repair_connects_explicit_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            guide = project / ".agents" / "README.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("Use `../src/main.py` for startup.\n", encoding="utf-8")
            source = project / "src" / "main.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            graph = project / PROJECT_GRAPH_PATH
            graph.parent.mkdir(parents=True)
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "agents_readme_guide",
                                "label": "Guide",
                                "file_type": "document",
                                "source_file": ".agents/README.md",
                                "source_location": "L1",
                            },
                            {
                                "id": "src_main",
                                "label": "main.py",
                                "file_type": "code",
                                "source_file": "src/main.py",
                                "source_location": "L1",
                            },
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            first = repair_project_document_links(project)
            second = repair_project_document_links(project)
            payload = json.loads(graph.read_text(encoding="utf-8"))

        self.assertTrue(first["ready"])
        self.assertEqual(1, first["document_source_edges"])
        self.assertFalse(second["changed"])
        self.assertEqual(1, len(payload["links"]))
        self.assertEqual("src_main", payload["links"][0]["target"])

    def test_target_graphify_readiness_fails_closed_without_git_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            graph = project / PROJECT_GRAPH_PATH
            graph.parent.mkdir(parents=True)
            graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "main", "file_type": "code", "source_file": "main.py"}
                        ],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            state = inspect_project_graph_state(project, graph)

        self.assertFalse(state["graph_fresh"])

    def test_target_graphify_readiness_rejects_duplicated_runtime_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            home = root / "home"
            canonical = home / GLOBAL_CANONICAL_SKILL_PATH
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# canonical graphify\n", encoding="utf-8")
            for platform in ("agents", "codex"):
                link = home / GLOBAL_PLATFORM_SKILL_DIRS[platform]
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(
                    os.path.relpath(canonical.parent, start=link.parent),
                    target_is_directory=True,
                )
            copied = project / ".codex" / "skills" / "graphify" / "SKILL.md"
            copied.parent.mkdir(parents=True)
            copied.write_text("# copied graphify\n", encoding="utf-8")
            graph = project / PROJECT_GRAPH_PATH
            graph.parent.mkdir(parents=True)
            graph.write_text("{}", encoding="utf-8")

            with patch("support.graphify_inspection.shutil.which", return_value="/tmp/graphify"):
                result = inspect_target_graphify(project, ["codex"], home_path=home)

        self.assertFalse(result["ready"])
        self.assertFalse(result["project_integration_ready"])
        self.assertEqual(
            [str(copied.parent)], result["unexpected_project_runtime_assets"]
        )
        self.assertEqual([], result["invalid_runtime_links"])

    def test_runtime_integration_normalizer_never_mutates_target_projects(self) -> None:
        # The project-mutation integration design is retired: the shim keeps
        # the entrypoint importable but must not rewrite project instructions,
        # touch runtime settings, or create adapter links in the checkout.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "AGENTS.md").write_text(
                "# Project\n\n## Local\n\nKeep me.\n", encoding="utf-8"
            )
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps({"permissions": {"allow": ["keep-this-permission"]}}),
                encoding="utf-8",
            )
            before = {
                path: path.read_bytes()
                for path in sorted(project.rglob("*"))
                if path.is_file()
            }

            results = _normalize_runtime_integrations(
                project, ["antigravity", "claude", "codex"]
            )

            after = {
                path: path.read_bytes()
                for path in sorted(project.rglob("*"))
                if path.is_file()
            }
            for relative in (
                Path(".agents/rules/graphify.md"),
                Path(".agents/workflows/graphify.md"),
                Path(".tao/skills/graphify"),
            ):
                leaked = project / relative
                self.assertFalse(leaked.exists() or leaked.is_symlink())

        self.assertEqual([], results)
        self.assertEqual(before, after)

    def test_target_graphify_dry_run_reports_missing_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()

            with patch("support.graphify_configuration.shutil.which", return_value="/tmp/graphify"):
                results = configure_target_graphify(
                    project, ["codex"], dry_run=True, home_path=root / "home"
                )

            self.assertTrue(any(result["status"] == "missing" for result in results))
            self.assertEqual([], list(project.iterdir()))

    def test_target_graphify_install_never_runs_initial_extraction(self) -> None:
        # Target configuration is inspection-only: it never invokes the
        # Graphify CLI (install or extract) and never writes into the repo.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ), patch("support.graphify_graph_freshness.subprocess.run") as run:
                configure_target_graphify(
                    project, ["codex"], dry_run=False, home_path=root / "home"
                )

            self.assertEqual([], list(project.iterdir()))

        executed = [call.args[0][0] for call in run.call_args_list]
        self.assertNotIn("/tmp/graphify", executed)
        self.assertTrue(all(command == "git" for command in executed))

    def test_graphify_runtime_mapping_uses_project_platforms(self) -> None:
        self.assertEqual(
            ["antigravity", "claude", "codex"],
            graphify_platforms_for_runtimes({"agy", "claude", "codex"}),
        )

    def test_gemini_binary_selects_existing_agy_adapter(self) -> None:
        from support.setup_agent_hooks_impl import _has_agy

        with tempfile.TemporaryDirectory() as temp_home:
            def which(command: str) -> str | None:
                return "/tmp/gemini" if command == "gemini" else None

            with (
                patch("support.setup_agent_hooks_impl.Path.home", return_value=Path(temp_home)),
                patch("support.setup_agent_hooks_impl.shutil.which", side_effect=which),
            ):
                self.assertTrue(_has_agy())

    def test_stable_launcher_records_current_root_under_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                results = ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                pointer = stable_root_pointer_path()

                self.assertTrue(launcher.exists())
                self.assertTrue(os.access(launcher, os.X_OK))
                self.assertEqual(f"{ROOT.resolve()}\n", pointer.read_text())
                self.assertIn("scripts/workflow.py", launcher.read_text())
                self.assertIn('ROOT_POINTER_NAME = "tao-root"', launcher.read_text())
                self.assertIn('"execution-capsule": "agent_execution_capsule.py"', launcher.read_text())
                self.assertIn('"agent-os-status": "agent-os-status.py"', launcher.read_text())
                self.assertIn('"agent-os-watchdog": "agent-os-watchdog.py"', launcher.read_text())
                self.assertIn('"agent-os-maintenance": "agent-os-maintenance.py"', launcher.read_text())
                self.assertIn('"workflow-dispatch": "workflow_dispatch.py"', launcher.read_text())
                self.assertIn('"handoff"', launcher.read_text())
                self.assertTrue(all(result["status"] == "installed" for result in results))

                check = ensure_stable_launcher(ROOT, dry_run=True)

        self.assertTrue(all(result["status"] == "ok" for result in check))

    def test_codex_setup_is_idempotent_in_a_clean_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            with patch.dict(os.environ, {"HOME": temp_home}):
                first = ensure_stable_launcher(ROOT, dry_run=False)
                first += setup_agent_hooks_impl.configure_codex(False, root=ROOT)
                first_snapshot = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }

                second = ensure_stable_launcher(ROOT, dry_run=False)
                second += setup_agent_hooks_impl.configure_codex(False, root=ROOT)
                second_snapshot = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }

        self.assertTrue(all(result["status"] in {"installed", "ok"} for result in first))
        self.assertTrue(all(result["status"] == "ok" for result in second))
        self.assertEqual(first_snapshot, second_snapshot)

    def test_stable_launcher_soft_fails_when_root_pointer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                stable_root_pointer_path().write_text("/missing/tao-agent-os\n")
                launcher = stable_launcher_path()
                env = os.environ.copy()
                env["TAO_HOOK_SOFT_FAIL"] = "1"

                result = subprocess.run(
                    [str(launcher), "workflow", "validate"],
                    cwd=temp_home,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("Tao Agent OS hook skipped", result.stderr)

    def test_stable_launcher_blocks_by_default_when_alias_is_unsupported(self) -> None:
        # Without the opt-in flag, a misconfigured or misspelled hook alias
        # must not silently exit 0 - required hooks are gated on exit code,
        # so a quiet success here would let callers skip the entire gate
        # system without noticing.
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                env = os.environ.copy()
                env.pop("TAO_HOOK_SOFT_FAIL", None)

                result = subprocess.run(
                    [str(launcher), "totally-bogus-alias"],
                    cwd=temp_home,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unsupported Tao Agent OS script alias", result.stderr)

    def test_stable_launcher_supports_agent_hook_subcommand_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "start", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Tao Agent OS script alias: start", result.stderr)
        self.assertIn("--request-classified", result.stdout)

    def test_stable_launcher_supports_gate_batch_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "gate-batch", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Tao Agent OS script alias: gate-batch", result.stderr)
        self.assertIn("--gate-record", result.stdout)

    def test_stable_launcher_supports_optional_skill_feedback_alias(self) -> None:
        expected = {
            "skill-feedback": "--skill-feedback-outcome",
            "skill-curate": "--skill-feedback-outcome",
            "skill-review": "--skill-review-outcome",
            "skill-maintenance": "--skill-maintenance-outcome",
        }
        for alias, option in expected.items():
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as temp_home:
                with patch.dict(os.environ, {"HOME": temp_home}):
                    ensure_stable_launcher(ROOT, dry_run=False)
                    launcher = stable_launcher_path()

                    result = subprocess.run(
                        [str(launcher), alias, "--help"],
                        cwd=str(ROOT),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )

            self.assertEqual(0, result.returncode)
            self.assertNotIn(f"unsupported Tao Agent OS script alias: {alias}", result.stderr)
            self.assertIn(option, result.stdout)

    def test_external_project_claude_settings_are_excluded_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")

            status = ensure_local_claude_excluded(project, dry_run=False)

            self.assertEqual("installed", status)
            self.assertIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_dry_run_reports_missing_without_writing_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")

            status = ensure_local_claude_excluded(project, dry_run=True)

            self.assertEqual("missing", status)
            self.assertNotIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_tracked_claude_settings_are_not_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text("{}\n")
            self._git(project, "add", ".claude/settings.json")

            status = ensure_local_claude_excluded(project, dry_run=False)

            self.assertEqual("ok", status)
            self.assertNotIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_tracked_claude_settings_remain_machine_portable_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({
                "permissions": {"allow": ["Bash(user-owned-command *)"]}
            }) + "\n")
            self._git(project, "add", ".claude/settings.json")

            first = configure_external_project(
                project,
                ROOT / "scripts",
                dry_run=False,
                spill_available=False,
            )
            first_text = settings.read_text()
            second = configure_external_project(
                project,
                ROOT / "scripts",
                dry_run=False,
                spill_available=False,
            )

            self.assertTrue(all(result["status"] in {"installed", "ok"} for result in first))
            self.assertTrue(all(result["status"] == "ok" for result in second))
            self.assertEqual(first_text, settings.read_text())
            self.assertIn("Bash(user-owned-command *)", first_text)
            self.assertNotIn(str(Path.home()), first_text)
            self.assertNotIn(str(stable_launcher_path()), first_text)

    def test_codex_merge_preserves_unmanaged_rules_added_after_managed_block(self) -> None:
        # The merge canonicalizes the file as unmanaged rules followed by one
        # managed block: a user rule appended after the block is preserved by
        # relocating it ahead of the rebuilt block, then the file is stable.
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "default.rules"
            user_rule = 'prefix_rule(pattern=["user-approved-tool"], decision="allow")'
            entries = codex_prefix_rule_entries(ROOT / "scripts")
            merge_codex_prefix_rules(target, entries, dry_run=False)
            target.write_text(target.read_text() + user_rule + "\n")

            dry_run_status = merge_codex_prefix_rules(target, entries, dry_run=True)
            install_status = merge_codex_prefix_rules(target, entries, dry_run=False)
            settled = target.read_text()
            settled_status = merge_codex_prefix_rules(target, entries, dry_run=True)

            self.assertEqual("missing", dry_run_status)
            self.assertEqual("installed", install_status)
            self.assertEqual("ok", settled_status)
            self.assertEqual(settled, target.read_text())
            self.assertEqual(1, settled.count(user_rule))
            self.assertEqual(1, settled.count("# tao-hooks:begin"))
            self.assertTrue(settled.startswith(user_rule))
            self.assertTrue(settled.rstrip("\n").endswith("# tao-hooks:end"))

    def test_runtime_setup_removes_superseded_brand_content_and_permissions(self) -> None:
        # Setup rebuilds the managed block from current entries only, so
        # obsolete-brand content inside the managed region never survives, and
        # explicit cleanup entries purge obsolete-brand permissions while
        # user-owned entries are preserved.
        obsolete_brand = "agent" + "play" + "book"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules = root / "default.rules"
            settings = root / "settings.json"
            stale_rule = (
                f'prefix_rule(pattern=["/{obsolete_brand}/hook"], decision="allow")'
            )
            rules.write_text(
                "\n".join(
                    [
                        "# tao-hooks:begin",
                        f"# Managed by {obsolete_brand}",
                        stale_rule,
                        "# tao-hooks:end",
                        stale_rule,
                        'prefix_rule(pattern=["custom-tool"], decision="allow")',
                        "",
                    ]
                )
            )
            stale_permission = f"Bash(/Users/example/.{obsolete_brand}/bin/hook *)"
            settings.write_text(json.dumps({
                "permissions": {
                    "allow": [
                        stale_permission,
                        "Bash(custom-tool *)",
                    ]
                }
            }) + "\n")

            merge_codex_prefix_rules(
                rules,
                ['prefix_rule(pattern=["tao-hook"], decision="allow")'],
                dry_run=False,
                cleanup_entries=[stale_rule],
            )
            merge_permissions_allow(
                settings,
                ["Bash(tao-hook *)"],
                dry_run=False,
                cleanup_entries=[stale_permission],
            )

            self.assertNotIn(obsolete_brand, rules.read_text().lower())
            self.assertIn("custom-tool", rules.read_text())
            self.assertIn('prefix_rule(pattern=["tao-hook"]', rules.read_text())
            permissions = json.loads(settings.read_text())["permissions"]["allow"]
            self.assertFalse(any(obsolete_brand in entry.lower() for entry in permissions))
            self.assertIn("Bash(custom-tool *)", permissions)
            self.assertIn("Bash(tao-hook *)", permissions)

    def _git(self, project: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(project), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
