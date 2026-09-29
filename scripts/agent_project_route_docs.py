"""Project-owned documents a route must read, declared by the target project.

Tao's route manifest lists only documents under the rules root. A project that
keeps its own commit, PR or platform procedures declares them per route command
in ``route_docs`` of its worktree policy, so the same same-session reuse proof
covers them instead of the project's own pointer chain rereading them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_state import doc_hash_record
from claude_worktree_gate import worktree_policy


def project_route_docs(project: Path, command: str) -> list[dict[str, Any]]:
    """Return hash records for the project's declared docs for ``command``.

    A missing or contained-escape path is skipped rather than failing start: the
    declaration guides reading, it does not gate the route.
    """

    policy = worktree_policy(project) or {}
    paths = (policy.get("route_docs") or {}).get(command) or []
    root = project.resolve()
    records = []
    for relative in paths:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        records.append(doc_hash_record(relative, path))
    return records
