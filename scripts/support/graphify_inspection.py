"""Read-only Graphify global-skill and target-graph inspection."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Iterable

from support.graphify_contract import (
    GLOBAL_CANONICAL_SKILL_DIR,
    GLOBAL_CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PROJECT_GRAPH_PATH,
    PROJECT_RUNTIME_ASSET_PATHS,
    RUNTIME_BUNDLED_SKILL_DIR,
    leaked_runtime_asset,
    resolve_graph_path,
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
    bundled_skill_dir: Path | None = None,
) -> dict[str, object]:
    selected = sorted(set(platforms or DEFAULT_PLATFORMS))
    home = home_path or Path.home()
    # A caller-provided home is primarily a fixture/alternate-home seam. It can
    # provide its matching bundle explicitly; production inspection uses the
    # active runtime bundle and therefore always enforces freshness.
    check_bundle_freshness = home_path is None or bundled_skill_dir is not None
    global_state = inspect_global_graphify(
        home,
        selected,
        bundled_skill_dir=bundled_skill_dir,
        check_bundle_freshness=check_bundle_freshness,
    )
    unexpected_assets = [
        project_path / relative
        for relative in PROJECT_RUNTIME_ASSET_PATHS
        if leaked_runtime_asset(project_path, relative)
    ]
    graph_path = resolve_graph_path(project_path) or project_path / PROJECT_GRAPH_PATH
    input_state = inspect_project_graph_inputs(
        project_path,
        manifest_path=graph_path.parent / "manifest.json",
    )
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
        "canonical_skill_fresh": global_state["canonical_skill_fresh"],
        "canonical_skill_missing_files": global_state["canonical_skill_missing_files"],
        "canonical_skill_extra_files": global_state["canonical_skill_extra_files"],
        "canonical_skill_changed_files": global_state["canonical_skill_changed_files"],
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


def inspect_global_graphify(
    home_path: Path,
    platforms: Iterable[str],
    *,
    bundled_skill_dir: Path | None = None,
    check_bundle_freshness: bool = True,
) -> dict[str, object]:
    selected = sorted(set(platforms) | {"agents"})
    source_bundle = bundled_skill_dir or (
        Path(__file__).resolve().parents[2] / RUNTIME_BUNDLED_SKILL_DIR
    )
    installed_bundle = home_path / GLOBAL_CANONICAL_SKILL_DIR
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
    freshness = (
        _inspect_bundle_freshness(source_bundle, installed_bundle)
        if check_bundle_freshness
        else {
            "ready": canonical_skill.is_file(),
            "missing_files": [],
            "extra_files": [],
            "changed_files": [],
        }
    )
    canonical_skill_fresh = bool(freshness["ready"])
    ready = bool(
        cli_path
        and canonical_skill.is_file()
        and canonical_skill_fresh
        and not invalid_links
    )
    return {
        "cli": cli_path,
        "platforms": selected,
        "bundled_skill_dir": str(source_bundle),
        "canonical_skill_doc": str(canonical_skill),
        "canonical_skill_exists": canonical_skill.is_file(),
        "canonical_skill_fresh": canonical_skill_fresh,
        "canonical_skill_missing_files": freshness["missing_files"],
        "canonical_skill_extra_files": freshness["extra_files"],
        "canonical_skill_changed_files": freshness["changed_files"],
        "skill_docs": [str(canonical_skill)] if canonical_skill.is_file() else [],
        "runtime_skill_links": {key: str(value) for key, value in runtime_links.items()},
        "invalid_runtime_links": [str(path) for path in invalid_links],
        "runtime_ownership_ready": ready,
        "ready": ready,
    }


def _inspect_bundle_freshness(source: Path, installed: Path) -> dict[str, object]:
    """Compare every installed Graphify asset with the runtime-owned bundle."""

    source_manifest = _bundle_manifest(source)
    installed_manifest = _bundle_manifest(installed)
    source_paths = set(source_manifest)
    installed_paths = set(installed_manifest)
    missing = sorted(source_paths - installed_paths)
    extra = sorted(installed_paths - source_paths)
    changed = sorted(
        path
        for path in source_paths & installed_paths
        if source_manifest[path] != installed_manifest[path]
    )
    return {
        "ready": bool(source_manifest) and not missing and not extra and not changed,
        "missing_files": missing,
        "extra_files": extra,
        "changed_files": changed,
    }


def _bundle_manifest(root: Path) -> dict[str, str]:
    """Return a deterministic recursive file/symlink signature map."""

    if not root.is_dir():
        return {}
    manifest: dict[str, str] = {}
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError:
        return {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            if path.is_symlink():
                manifest[relative] = "symlink:" + os.readlink(path)
            elif path.is_file():
                manifest[relative] = "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            manifest[relative] = "unreadable"
    return manifest
