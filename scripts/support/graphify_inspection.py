"""Read-only Graphify global-skill and target-graph inspection."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_DIR,
    GLOBAL_CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PROJECT_GRAPH_PATH,
    PROJECT_RUNTIME_ASSET_PATHS,
)
from support.graphify_graph_state import inspect_project_graph_state
from support.graphify_input_inspection import inspect_project_graph_inputs
from support.graphify_paths import runtime_link_ready


DEFAULT_PLATFORMS = ("antigravity", "claude", "codex")


def discover_project_graphify_platforms(project_path: Path) -> list[str]:
    """Return runtime platforms without reading target-project skill folders."""

    del project_path
    return list(DEFAULT_PLATFORMS)


def inspect_target_graphify(
    project_path: Path,
    platforms: Iterable[str] | None = None,
    *,
    home_path: Path | None = None,
) -> dict[str, object]:
    selected = sorted(set(platforms or DEFAULT_PLATFORMS))
    home = home_path or Path.home()
    global_state = inspect_global_graphify(home, selected)
    unexpected_assets = [
        project_path / relative
        for relative in PROJECT_RUNTIME_ASSET_PATHS
        if (project_path / relative).exists() or (project_path / relative).is_symlink()
    ]
    graph_path = project_path / PROJECT_GRAPH_PATH
    input_state = inspect_project_graph_inputs(project_path)
    graph_state = inspect_project_graph_state(project_path, graph_path)
    project_integration_ready = not unexpected_assets
    runtime_ready = bool(
        global_state["ready"]
        and project_integration_ready
        and graph_path.is_file()
    )
    result = {
        "cli": global_state["cli"],
        "platforms": selected,
        "canonical_skill_doc": global_state["canonical_skill_doc"],
        "canonical_skill_exists": global_state["canonical_skill_exists"],
        "skill_docs": global_state["skill_docs"],
        "runtime_skill_links": global_state["runtime_skill_links"],
        "invalid_runtime_links": global_state["invalid_runtime_links"],
        "runtime_ownership_ready": global_state["ready"],
        "project_integration_ready": project_integration_ready,
        "unexpected_project_runtime_assets": [str(path) for path in unexpected_assets],
        # Compatibility key for current route/report consumers.
        "missing_integrations": [str(path) for path in unexpected_assets],
        "graph_path": str(graph_path),
        "graph_exists": graph_path.is_file(),
        "runtime_ready": runtime_ready,
        **graph_state,
        **input_state,
    }
    static_ready = bool(
        runtime_ready
        and graph_state["graph_integrity_ready"]
        and graph_state["graph_fresh"] is True
        and input_state["graph_input_policy_ready"]
        and input_state["knowledge_manifest_ready"]
    )
    result["static_ready"] = static_ready
    result["ready"] = static_ready
    return result


def inspect_global_graphify(home_path: Path, platforms: Iterable[str]) -> dict[str, object]:
    selected = sorted(set(platforms) | {"agents"})
    canonical_skill = home_path / GLOBAL_CANONICAL_SKILL_PATH
    runtime_links = {
        platform: home_path / GLOBAL_PLATFORM_SKILL_DIRS[platform]
        for platform in selected
    }
    invalid_links = [
        link
        for link in runtime_links.values()
        if not runtime_link_ready(link, home_path / GLOBAL_CANONICAL_SKILL_DIR)
    ]
    cli_path = shutil.which("graphify")
    ready = bool(cli_path and canonical_skill.is_file() and not invalid_links)
    return {
        "cli": cli_path,
        "platforms": selected,
        "canonical_skill_doc": str(canonical_skill),
        "canonical_skill_exists": canonical_skill.is_file(),
        "skill_docs": [str(canonical_skill)] if canonical_skill.is_file() else [],
        "runtime_skill_links": {key: str(value) for key, value in runtime_links.items()},
        "invalid_runtime_links": [str(path) for path in invalid_links],
        "runtime_ownership_ready": ready,
        "ready": ready,
    }
