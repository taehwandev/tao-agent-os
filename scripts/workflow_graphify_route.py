"""Graphify-specific route readiness policy."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from support.graphify_setup import inspect_target_graphify


GRAPHIFY_SURFACE_NAMES = {"target_project_graphify", "graphify_integration"}


# A request makes Graphify its work target when it asks for a project graph to
# be installed, set up, built or refreshed -- in either word order, or through
# the `/graphify` trigger. A bare mention (gate code that classifies
# `graphify query`, a note about the tool) is not such a request.
_GRAPH_NOUN = r"(?:graphify|(?:knowledge|project|codebase)\s+graphs?|graphs?)"
_GRAPH_VERB = (
    r"(?:install|set\s*up|setup|build|rebuild|refresh|regenerate|re-?extract|extract"
    r"|update|integrate|run|initiali[sz]e|generate|create)"
)
_KOREAN_NOUN = r"(?:graphify|그래피|그래프)"
_KOREAN_VERB = r"(?:설치|설정|세팅|구축|생성|갱신|새로\s*고침|새로고침|빌드|재생성|업데이트|연동|실행|만들)"
GRAPHIFY_TARGET_REQUEST = re.compile(
    rf"(?:^|\s)/graphify\b"
    rf"|\b{_GRAPH_VERB}\w*\W+(?:\w+\W+){{0,3}}?{_GRAPH_NOUN}\b"
    rf"|\b{_GRAPH_NOUN}\W+(?:\w+\W+){{0,2}}?{_GRAPH_VERB}\w*"
    rf"|{_KOREAN_NOUN}[^.\n]{{0,15}}?{_KOREAN_VERB}",
    re.IGNORECASE,
)


def graphify_is_work_target(
    concerns: list[str],
    surface_matches: list[dict[str, object]],
    *,
    inferred_concerns: "set[str] | list[str] | None" = None,
    request_text: str = "",
) -> bool:
    """Whether Graphify readiness belongs to this route.

    A verified Graphify work surface or an explicitly named concern keeps it.
    A concern only inferred from the word "graphify" keeps it only when the
    request asks to install, set up, build or refresh a project graph: the
    readiness gate needs an installed graph, so attaching it to every task
    that merely mentions the tool made those tasks impossible to finish.
    """

    if any(match.get("name") in GRAPHIFY_SURFACE_NAMES for match in surface_matches):
        return True
    if "graphify" not in concerns:
        return False
    if "graphify" not in set(inferred_concerns or ()):
        return True
    return bool(GRAPHIFY_TARGET_REQUEST.search(request_text))


def graphify_route_context(
    *,
    concerns: list[str],
    surface_matches: list[dict[str, object]],
    project_root: Path | None,
    inferred_concerns: "set[str] | list[str] | None" = None,
    request_text: str = "",
) -> dict[str, Any]:
    """Return the readiness, notes, and blockers owned by Graphify routing."""

    requested = graphify_is_work_target(
        concerns,
        surface_matches,
        inferred_concerns=inferred_concerns,
        request_text=request_text,
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
