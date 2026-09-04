"""Compare Graphify output with Git and manifest source state."""

from __future__ import annotations

import subprocess
from pathlib import Path

from support.graphify_input_inspection import (
    is_graphify_runtime_adapter_input,
    read_manifest_state,
)
from support.graphify_contract import PROJECT_GRAPH_DIR
from support.bounded_git import run_git


GRAPH_INPUT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".java", ".js", ".json",
    ".kt", ".kts", ".md", ".mdx", ".mjs", ".py", ".rs", ".rst", ".sh",
    ".swift", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}


def inspect_graph_freshness(
    project_path: Path,
    built_at_commit: object,
    graph_mtime: float,
    *,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    head = _git_head(project_path)
    dirty_sources, worktree_status_ready = _dirty_source_paths(project_path)
    manifest, stale_manifest = read_manifest_state(
        project_path,
        manifest_path=manifest_path,
    )
    uncovered = {
        path
        for path in dirty_sources
        if path not in manifest
        and _is_potential_graph_input(path)
        and not is_graphify_runtime_adapter_input(path)
        and not _is_local_graph_state(path)
        and not _policy_change_covered(project_path, path, graph_mtime)
    }
    built_head = built_at_commit if isinstance(built_at_commit, str) else ""
    committed_sources, commit_comparison_ready = _changed_source_paths(
        project_path,
        built_head,
        head or "",
    )
    # Manifest hashes prove that known files match, but they cannot name a new
    # committed source that an older graph never indexed. Compare only the
    # bounded commit range for additions/renames instead of rescanning the whole
    # repository. Existing changed files remain covered by their manifest hash.
    uncovered_committed = {
        path
        for path in committed_sources
        if path not in manifest
        and _is_potential_graph_input(path)
        and not is_graphify_runtime_adapter_input(path)
        and not _is_local_graph_state(path)
    }
    head_matches = bool(head and built_head and head == built_head)
    return {
        "project_head": head,
        # The manifest hashes describe the inputs actually indexed.  A graph
        # rebuilt while the worktree is dirty deliberately retains the last
        # commit in ``built_at_commit``; treating that diagnostic field as an
        # input-freshness requirement makes a successful in-place rebuild
        # impossible until the user commits.  Stale manifest entries and
        # uncovered dirty inputs detect worktree changes, while the bounded
        # commit comparison catches new committed sources absent from an older
        # manifest. An unavailable comparison must fail closed.
        "graph_fresh": bool(
            manifest
            and not stale_manifest
            and not uncovered
            and not uncovered_committed
            and commit_comparison_ready
            and worktree_status_ready
        ),
        "graph_head_matches": head_matches,
        "graph_head_comparison_ready": commit_comparison_ready,
        "graph_worktree_status_ready": worktree_status_ready,
        "graph_manifest_stale_count": len(stale_manifest),
        "graph_source_dirty_count": len(
            set(stale_manifest) | uncovered | uncovered_committed
        ),
    }


def _git_head(project_path: Path) -> str | None:
    completed = run_git(
        ["git", "rev-parse", "HEAD"],
        cwd=project_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None


def _dirty_source_paths(project_path: Path) -> tuple[list[str], bool]:
    completed = run_git(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return [], False
    paths: list[str] = []
    for line in (completed.stdout or "").splitlines():
        status = line[:2]
        # A deleted path has no remaining input bytes to cover.  If it was
        # indexed, its lingering manifest entry is already stale; if it was
        # never indexed, counting it as an uncovered input makes a successful
        # Graphify update permanently report stale after the deletion.
        if "D" in status:
            continue
        value = line[3:].split(" -> ")[-1] if len(line) > 3 else ""
        if not value or _is_local_graph_state(value):
            continue
        paths.append(value)
    return paths, True


def _changed_source_paths(
    project_path: Path,
    built_head: str,
    current_head: str,
) -> tuple[list[str], bool]:
    if not built_head and not current_head:
        return [], True
    if not built_head or not current_head:
        return [], False
    if built_head == current_head:
        return [], True
    completed = run_git(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            built_head,
            current_head,
            "--",
        ],
        cwd=project_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return [], False
    return [line for line in (completed.stdout or "").splitlines() if line], True


def _is_potential_graph_input(relative: str) -> bool:
    return relative in {".gitignore", ".graphifyignore"} or (
        Path(relative).suffix.lower() in GRAPH_INPUT_SUFFIXES
    )


def _is_local_graph_state(relative: str) -> bool:
    parts = Path(relative).parts
    return (
        ".tao" in parts
        or parts[:2] == (".agents", "local")
        or relative.startswith("graphify-out/")
        or relative.startswith(f"{PROJECT_GRAPH_DIR.as_posix()}/")
    )


def _policy_change_covered(
    project_path: Path, relative: str, graph_mtime: float
) -> bool:
    if relative not in {".gitignore", ".graphifyignore"}:
        return False
    try:
        return graph_mtime >= (project_path / relative).stat().st_mtime
    except OSError:
        return False
