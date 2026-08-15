"""Graphify-specific route readiness policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support.graphify_setup import inspect_target_graphify


GRAPHIFY_SURFACE_NAMES = {"target_project_graphify", "graphify_integration"}


def graphify_route_context(
    *,
    concerns: list[str],
    surface_matches: list[dict[str, object]],
    project_root: Path | None,
) -> dict[str, Any]:
    """Return the readiness, notes, and blockers owned by Graphify routing."""

    requested = "graphify" in concerns or any(
        match.get("name") in GRAPHIFY_SURFACE_NAMES for match in surface_matches
    )
    if not requested:
        return {"requested": False, "readiness": None, "blocking": [], "notes": []}

    blocking: list[str] = []
    notes: list[str] = []
    if project_root:
        readiness = {
            "requested": True,
            "project": str(project_root),
            **inspect_target_graphify(project_root),
        }
    else:
        readiness = {"requested": True, "project": None, "ready": False}
        blocking.append(
            "Graphify readiness cannot be assessed without --project <TARGET_REPO>."
        )

    if project_root and not readiness["ready"]:
        notes.append(
            "Target-project Graphify is incomplete. The graphify readiness gate must prove "
            "CLI, the read canonical SKILL.md, runtime links resolving to it, portable "
            "Git ownership, project integration, a fresh/input-complete graph with valid "
            "endpoints, and query smoke before handoff. Document-to-code relationship "
            "coverage is query-quality guidance, not an AST-only prerequisite."
        )
    return {
        "requested": True,
        "readiness": readiness,
        "blocking": blocking,
        "notes": notes,
    }
