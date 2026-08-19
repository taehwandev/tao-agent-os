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
) -> dict[str, object]:
    head = _git_head(project_path)
    dirty_sources = _dirty_source_paths(project_path)
    manifest, stale_manifest = read_manifest_state(project_path)
    uncovered = {
        path
        for path in dirty_sources
        if path not in manifest
        and _is_potential_graph_input(path)
        and not is_graphify_runtime_adapter_input(path)
        and not _policy_change_covered(project_path, path, graph_mtime)
    }
    return {
        "project_head": head,
        # The manifest hashes describe the inputs actually indexed.  A graph
        # rebuilt while the worktree is dirty deliberately retains the last
        # commit in ``built_at_commit``; treating that diagnostic field as an
        # input-freshness requirement makes a successful in-place rebuild
        # impossible until the user commits.  Stale manifest entries and
        # uncovered dirty inputs already detect both changed and newly-created
        # source files without that deadlock.
        "graph_fresh": bool(
            manifest
            and not stale_manifest
            and not uncovered
        ),
        "graph_manifest_stale_count": len(stale_manifest),
        "graph_source_dirty_count": len(set(stale_manifest) | uncovered),
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


def _dirty_source_paths(project_path: Path) -> list[str]:
    completed = run_git(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return []
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
        if (
            not value
            or ".tao" in Path(value).parts
            or Path(value).parts[:2] == (".agents", "local")
            or value.startswith("graphify-out/")
            or value.startswith(f"{PROJECT_GRAPH_DIR.as_posix()}/")
        ):
            continue
        paths.append(value)
    return paths


def _is_potential_graph_input(relative: str) -> bool:
    return relative in {".gitignore", ".graphifyignore"} or (
        Path(relative).suffix.lower() in GRAPH_INPUT_SUFFIXES
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
