from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support import graphify_contract
from support.graphify_configuration import configure_global_graphify
from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_DIR,
    GLOBAL_CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PROJECT_RUNTIME_ASSET_PATHS,
    RUNTIME_BUNDLED_SKILL_DIR,
    is_runtime_source_root,
    leaked_runtime_asset,
)
from support.graphify_inspection import inspect_global_graphify, inspect_target_graphify


def _make_bundle(project: Path) -> Path:
    bundle = project / RUNTIME_BUNDLED_SKILL_DIR
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text("# Graphify\n", encoding="utf-8")
    return bundle


def _link(project: Path, relative: str, target: Path) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    return path


class LeakedRuntimeAssetTests(unittest.TestCase):
    """The runtime source root owns the very paths the contract calls leaks.

    `.tao/skills/graphify` is the canonical bundle the ownership rule is defined
    around, and the Tao Agent OS checkout self-hosts its own discovery links
    into that bundle. Scanning those paths unconditionally made the contract
    flag its own source of truth, so readiness could never pass against this
    repository. Only the bundle and links resolving inside it are excused.
    """

    def test_bundle_and_self_hosted_links_are_not_leaks_in_the_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            bundle = _make_bundle(project)
            _link(project, ".agents/skills/graphify", Path("../../.tao/skills/graphify"))
            _link(project, ".claude/skills/graphify", Path("../../.tao/skills/graphify"))
            _link(
                project,
                ".agents/rules/graphify.md",
                Path("../../.tao/skills/graphify/runtime/antigravity/rule.md"),
            )
            (bundle / "runtime" / "antigravity").mkdir(parents=True)
            (bundle / "runtime" / "antigravity" / "rule.md").write_text("x\n", encoding="utf-8")

            with patch.object(graphify_contract, "RUNTIME_SOURCE_ROOT", project):
                self.assertTrue(is_runtime_source_root(project))
                leaks = [
                    str(relative)
                    for relative in PROJECT_RUNTIME_ASSET_PATHS
                    if leaked_runtime_asset(project, relative)
                ]

            self.assertEqual([], leaks)

    def test_negative_control_ordinary_target_repo_still_reports_every_leak(self) -> None:
        """The control: the exemption must not disable the check elsewhere.

        A target repository carrying the same paths is the exact condition the
        removed project-bundle design produces, and it must keep failing.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            _make_bundle(project)
            _link(project, ".agents/skills/graphify", Path("../../.tao/skills/graphify"))

            leaks = [
                str(relative)
                for relative in PROJECT_RUNTIME_ASSET_PATHS
                if leaked_runtime_asset(project, relative)
            ]

            self.assertIn(".tao/skills/graphify", leaks)
            self.assertIn(".agents/skills/graphify", leaks)

    def test_copied_bundle_in_the_runtime_root_is_still_a_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            _make_bundle(project)
            copied = project / ".claude" / "skills" / "graphify"
            copied.mkdir(parents=True)
            (copied / "SKILL.md").write_text("# copy\n", encoding="utf-8")

            with patch.object(graphify_contract, "RUNTIME_SOURCE_ROOT", project):
                self.assertTrue(leaked_runtime_asset(project, Path(".claude/skills/graphify")))

    def test_link_escaping_the_bundle_in_the_runtime_root_is_still_a_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            _make_bundle(project)
            elsewhere = project / "vendor" / "graphify"
            elsewhere.mkdir(parents=True)
            _link(project, ".codex/skills/graphify", elsewhere)

            with patch.object(graphify_contract, "RUNTIME_SOURCE_ROOT", project):
                self.assertTrue(leaked_runtime_asset(project, Path(".codex/skills/graphify")))

    def test_absent_paths_are_never_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()

            for relative in PROJECT_RUNTIME_ASSET_PATHS:
                self.assertFalse(leaked_runtime_asset(project, relative))


class RuntimeRootReadinessTests(unittest.TestCase):
    def test_this_checkout_reports_no_leaked_runtime_assets(self) -> None:
        """End-to-end: the Tao Agent OS repository must pass its own boundary."""

        readiness = inspect_target_graphify(ROOT)

        self.assertEqual([], readiness["unexpected_project_runtime_assets"])
        self.assertTrue(readiness["project_integration_ready"])


class GraphifyOutputBoundaryTests(unittest.TestCase):
    """Writing has one home; reading has to find the graph that exists.

    This used to refuse any mention of the root-level directory anywhere in the
    bundle, on the reading that it was legacy. It is not: the commit hooks are
    installed by graphify's own installer, carry no `GRAPHIFY_OUT`, and write
    there. Enforcing the ban left this repository's agents pointed at an empty
    `.agents/local/graphify-out` while the only graph on disk, rebuilt on every
    branch switch, sat in the directory they were told never to open.

    So the ban now covers what the bundle *writes*, and the reading path is
    required to name the fallback instead of forbidding it.
    """

    def test_the_skill_writes_only_to_the_project_local_boundary(self) -> None:
        skill_root = ROOT / RUNTIME_BUNDLED_SKILL_DIR
        markdown_files = sorted(skill_root.rglob("*.md"))
        known_output = re.compile(
            r'GRAPHIFY_OUT=(?!(?:\.agents/local/graphify-out|"\$GRAPHIFY_(?:READ|WRITE)_OUT"))'
        )
        bare_cli = re.compile(
            r"(?m)^\s*graphify "
            r"(?:query|path|explain|update|cluster-only|extract|export|"
            r"benchmark|save-result|reflect|add|watch|merge-graphs|clone)\b"
        )

        for path in markdown_files:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(known_output.search(text), path)
            self.assertIsNone(bare_cli.search(text), path)

        query = (skill_root / "references" / "query.md").read_text(encoding="utf-8")
        self.assertIn(
            'GRAPHIFY_WRITE_OUT="$(pwd -P)/.agents/local/graphify-out"',
            query,
        )
        for line in query.splitlines():
            if re.search(r"graphify (?:save-result|reflect)\b", line):
                self.assertIn('GRAPHIFY_OUT="$GRAPHIFY_WRITE_OUT"', line)
                self.assertNotIn('GRAPHIFY_OUT="$GRAPHIFY_READ_OUT"', line)

    def test_the_skill_says_where_to_read_when_nothing_redirected_the_output(self) -> None:
        skill = (ROOT / RUNTIME_BUNDLED_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("root-level default", skill)
        self.assertIn("actual path", skill)
        self.assertIn("fresh and structurally valid", skill)

    def test_query_commands_use_the_readiness_selected_graph(self) -> None:
        skill_root = ROOT / RUNTIME_BUNDLED_SKILL_DIR
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        query = (skill_root / "references" / "query.md").read_text(encoding="utf-8")
        self.assertIn("GRAPHIFY_READ_OUT", skill)
        self.assertIn("setup-project-graphify.py --project . --check --format json", query)
        for field in ("graph_exists", "graph_fresh", "graph_integrity_ready"):
            self.assertIn(field, query)
        self.assertIn('GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify query', query)
        self.assertIn('GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify path', query)
        self.assertIn('GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify explain', query)
        legacy_query = "GRAPHIFY_OUT=.agents/local/graphify-out graphify query"
        for path in sorted(skill_root.rglob("*.md")):
            self.assertNotIn(
                legacy_query,
                path.read_text(encoding="utf-8"),
                path,
            )


class GlobalBundleFreshnessTests(unittest.TestCase):
    def test_check_detects_changed_missing_and_extra_installed_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "runtime-bundle"
            home = root / "home"
            (source / "references").mkdir(parents=True)
            (source / "runtime" / "antigravity").mkdir(parents=True)
            (source / "SKILL.md").write_text("# source\n", encoding="utf-8")
            (source / "references" / "query.md").write_text(
                "# query\n", encoding="utf-8"
            )
            (source / "runtime" / "antigravity" / "rule.md").write_text(
                "# rule\n", encoding="utf-8"
            )

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ), patch(
                "support.graphify_configuration.shutil.which",
                return_value="/tmp/graphify",
            ):
                configure_global_graphify(
                    home,
                    ["agents"],
                    dry_run=False,
                    bundled_skill_dir=source,
                )
                ready = inspect_global_graphify(
                    home,
                    ["agents"],
                    bundled_skill_dir=source,
                )

                installed = home / GLOBAL_CANONICAL_SKILL_DIR
                (installed / "SKILL.md").write_text("# stale\n", encoding="utf-8")
                (installed / "references" / "query.md").unlink()
                (installed / "extra.md").write_text("# extra\n", encoding="utf-8")
                stale = inspect_global_graphify(
                    home,
                    ["agents"],
                    bundled_skill_dir=source,
                )
                changes = configure_global_graphify(
                    home,
                    ["agents"],
                    dry_run=True,
                    bundled_skill_dir=source,
                )

        self.assertTrue(ready["ready"])
        self.assertTrue(ready["canonical_skill_fresh"])
        self.assertFalse(stale["ready"])
        self.assertFalse(stale["canonical_skill_fresh"])
        self.assertEqual(["references/query.md"], stale["canonical_skill_missing_files"])
        self.assertEqual(["extra.md"], stale["canonical_skill_extra_files"])
        self.assertEqual(["SKILL.md"], stale["canonical_skill_changed_files"])
        self.assertTrue(
            any(
                result["hook"] == "global.skill.freshness"
                and result["status"] == "missing"
                for result in changes
            )
        )

    def test_freshness_includes_nested_runtime_adapter_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            home = root / "home"
            adapter = source / "runtime" / "antigravity" / "workflow.md"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("# source adapter\n", encoding="utf-8")
            (source / "SKILL.md").write_text("# source\n", encoding="utf-8")
            installed = home / GLOBAL_CANONICAL_SKILL_DIR
            installed_adapter = installed / "runtime" / "antigravity" / "workflow.md"
            installed_adapter.parent.mkdir(parents=True)
            installed_adapter.write_text("# stale adapter\n", encoding="utf-8")
            (installed / "SKILL.md").write_text("# source\n", encoding="utf-8")
            link = home / GLOBAL_PLATFORM_SKILL_DIRS["agents"]
            link.parent.mkdir(parents=True)
            link.symlink_to(
                os.path.relpath(installed, start=link.parent),
                target_is_directory=True,
            )

            with patch(
                "support.graphify_inspection.shutil.which",
                return_value="/tmp/graphify",
            ):
                state = inspect_global_graphify(
                    home,
                    ["agents"],
                    bundled_skill_dir=source,
                )

        self.assertFalse(state["ready"])
        self.assertEqual(
            ["runtime/antigravity/workflow.md"],
            state["canonical_skill_changed_files"],
        )


if __name__ == "__main__":
    unittest.main()
