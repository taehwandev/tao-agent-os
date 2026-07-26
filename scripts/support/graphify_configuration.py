"""Graphify setup orchestration for one shared runtime skill."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_DIR,
    GLOBAL_CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PROJECT_RUNTIME_ASSET_PATHS,
    RUNTIME_BUNDLED_SKILL_DIR,
)
from support.graphify_inspection import inspect_global_graphify, inspect_target_graphify
from support.graphify_paths import (
    install_bundled_skill,
    replace_path_with_relative_link,
)


RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def configure_global_graphify(
    home_path: Path,
    platforms: Iterable[str],
    dry_run: bool,
    *,
    bundled_skill_dir: Path | None = None,
) -> list[dict[str, str]]:
    selected = sorted(set(platforms) | {"agents"})
    source = bundled_skill_dir or (RUNTIME_ROOT / RUNTIME_BUNDLED_SKILL_DIR)
    graphify = shutil.which("graphify")
    results = [
        _result("global.cli", "ok" if graphify else "missing", graphify or "graphify"),
        _result(
            "global.skill.bundle",
            "ok" if (source / "SKILL.md").is_file() else "missing",
            source,
        ),
    ]
    if not dry_run and (source / "SKILL.md").is_file():
        installed = install_bundled_skill(source, home_path)
        results.append(
            _result(
                "global.skill.install",
                "installed" if installed else "missing",
                home_path / GLOBAL_CANONICAL_SKILL_PATH,
            )
        )
        if installed:
            for platform in selected:
                replace_path_with_relative_link(
                    home_path / GLOBAL_PLATFORM_SKILL_DIRS[platform],
                    home_path / GLOBAL_CANONICAL_SKILL_DIR,
                    target_is_directory=True,
                )

    readiness = inspect_global_graphify(home_path, selected)
    results.append(
        _result(
            "global.skill.canonical",
            "ok" if readiness["canonical_skill_exists"] else "missing",
            readiness["canonical_skill_doc"],
        )
    )
    invalid_links = set(readiness["invalid_runtime_links"])
    for platform, path in readiness["runtime_skill_links"].items():
        results.append(
            _result(
                f"global.skill_link.{platform}",
                "missing" if path in invalid_links else "ok",
                path,
            )
        )
    return results


def configure_target_graphify(
    project_path: Path,
    platforms: Iterable[str],
    dry_run: bool,
    *,
    home_path: Path | None = None,
) -> list[dict[str, str]]:
    """Inspect target readiness without installing runtime assets in the repo."""

    del dry_run
    readiness = inspect_target_graphify(
        project_path,
        platforms,
        home_path=home_path,
    )
    results = [
        _result("cli", "ok" if readiness["cli"] else "missing", readiness["cli"] or "graphify"),
        _result(
            "skill.global",
            "ok" if readiness["canonical_skill_exists"] else "missing",
            readiness["canonical_skill_doc"],
        ),
    ]
    invalid_links = set(readiness["invalid_runtime_links"])
    for platform, path in readiness["runtime_skill_links"].items():
        results.append(
            _result(
                f"global.skill_link.{platform}",
                "missing" if path in invalid_links else "ok",
                path,
            )
        )
    for relative in PROJECT_RUNTIME_ASSET_PATHS:
        path = project_path / relative
        if path.exists() or path.is_symlink():
            results.append(_result("project.runtime_asset", "missing", path))
    results.extend(
        (
            _result(
                "graph.project",
                "ok" if readiness["graph_exists"] else "missing",
                readiness["graph_path"],
            ),
            _result(
                "graph.freshness",
                "ok" if readiness["graph_fresh"] is True else "missing",
                (
                    f"built={readiness.get('graph_built_at_commit') or 'missing'}; "
                    f"head={readiness.get('project_head') or 'unknown'}; "
                    f"dirty_sources={readiness.get('graph_source_dirty_count', 0)}; "
                    f"stale_manifest={readiness.get('graph_manifest_stale_count', 0)}"
                ),
            ),
            _result(
                "graph.integrity",
                "ok" if readiness["graph_integrity_ready"] else "missing",
                (
                    f"nodes={readiness.get('graph_node_count', 0)}; "
                    f"edges={readiness.get('graph_edge_count', 0)}; "
                    f"invalid_edges={readiness.get('graph_invalid_edge_count', 0)}; "
                    f"malformed_nodes={readiness.get('graph_malformed_node_count', 0)}; "
                    f"duplicate_nodes={readiness.get('graph_duplicate_node_id_count', 0)}"
                ),
            ),
            _result(
                "graph.input_coverage",
                "ok"
                if readiness["graph_input_policy_ready"]
                and readiness["knowledge_manifest_ready"]
                else "missing",
                (
                    f"project_knowledge={readiness.get('project_knowledge_file_count', 0)}; "
                    f"manifest={readiness.get('knowledge_manifest_file_count', 0)}; "
                    f"missing={readiness.get('knowledge_manifest_missing_count', 0)}; "
                    f"stale={readiness.get('knowledge_manifest_stale_count', 0)}; "
                    f"blanket_exclusions={len(readiness.get('blanket_knowledge_input_exclusions', []))}"
                ),
            ),
            _result(
                "graph.relationships",
                # Semantic document-to-code paths improve query quality, but an
                # AST-only rebuild cannot always produce them.  Report coverage
                # without turning a valid, current graph into an unfixable setup
                # failure; explicit-path repair remains available when applicable.
                "ok",
                (
                    f"ready={str(bool(readiness['graph_relationship_ready'])).lower()}; "
                    f"document_nodes={readiness.get('graph_document_node_count', 0)}; "
                    f"code_nodes={readiness.get('graph_code_node_count', 0)}; "
                    f"direct_edges={readiness.get('graph_document_code_edge_count', 0)}; "
                    f"document_path_nodes={readiness.get('graph_document_code_path_node_count', 0)}; "
                    f"knowledge_path_nodes={readiness.get('graph_knowledge_code_path_node_count', 0)}"
                ),
            ),
        )
    )
    return results


def _result(hook: str, status: str, path: object) -> dict[str, str]:
    return {"tool": "graphify", "hook": hook, "status": status, "path": str(path)}
