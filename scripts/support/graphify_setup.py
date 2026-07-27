"""Public Graphify setup facade used by Tao Agent OS entrypoints."""

from __future__ import annotations

from typing import Iterable

from support.graphify_configuration import (
    configure_global_graphify,
    configure_target_graphify,
)
from support.graphify_contract import (
    CANONICAL_SKILL_PATH,
    GLOBAL_PLATFORM_SKILL_DIRS,
    PLATFORM_SKILL_DIRS,
    PROJECT_GRAPH_DIR,
    PROJECT_GRAPH_PATH,
    RUNTIME_TO_PLATFORM,
    TRACKING_POLICY_PATHS,
)
from support.graphify_inspection import (
    discover_project_graphify_platforms,
    inspect_global_graphify,
    inspect_target_graphify,
)
from support.graphify_document_links import repair_project_document_links
from support.graphify_graph_integrity import repair_graph_integrity
from support.graphify_runtime_integration import (
    normalize_runtime_integrations as _normalize_runtime_integrations,
)
from support.graphify_tracking import install_graphify_input_policy

__all__ = [
    "CANONICAL_SKILL_PATH",
    "GLOBAL_PLATFORM_SKILL_DIRS",
    "PLATFORM_SKILL_DIRS",
    "PROJECT_GRAPH_DIR",
    "PROJECT_GRAPH_PATH",
    "TRACKING_POLICY_PATHS",
    "configure_global_graphify",
    "configure_target_graphify",
    "discover_project_graphify_platforms",
    "graphify_platforms_for_runtimes",
    "inspect_global_graphify",
    "inspect_target_graphify",
    "install_graphify_input_policy",
    "repair_project_document_links",
    "repair_graph_integrity",
]


def graphify_platforms_for_runtimes(runtimes: Iterable[str]) -> list[str]:
    platforms = {
        RUNTIME_TO_PLATFORM[runtime]
        for runtime in runtimes
        if runtime in RUNTIME_TO_PLATFORM
    }
    return sorted(platforms) or ["agents"]
