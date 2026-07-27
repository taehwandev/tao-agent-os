"""Deprecated compatibility inspection for the removed project-skill design."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def inspect_graphify_git_tracking(
    project_path: Path,
    platforms: Iterable[str],
) -> dict[str, object]:
    del project_path, platforms
    return {
        "git_repository": False,
        "canonical_untracked_files": [],
        "policy_untracked_files": [],
        "tracked_runtime_skill_copies": [],
        "runtime_link_index_issues": [],
        "adapter_link_index_issues": [],
        "unstaged_commit_assets": [],
        "ignored_commit_assets": [],
        "commit_ready": None,
    }
