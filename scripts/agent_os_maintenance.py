"""Shared stale-state recovery and retention implementation.

Owner: the unattended maintenance pass over every Tao-managed checkout.
Allowed imports: the run registry, retention, run-evidence, scheduler and
project-search modules; nothing from the workflow route.
Callers/tests: ``agent-os-maintenance.py`` (the LaunchAgent entry point);
coverage lives in ``tests/test_runs_prune.py`` and
``tests/test_agent_os_maintenance_projects.py``.
Verification: run ``agent-os-maintenance.py --all-projects --dry-run`` and
compare its per-project counts with the run directories it names.

Retention used to run for the Tao checkout alone, while every other project
that ran Tao lifecycles kept its unfinished runs and evidence forever. The pass
now visits every managed checkout, and each one gets exactly the same rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from agent_project_search import (
    default_search_roots,
    env_search_roots,
    load_registry,
    registry_search_roots,
)
from agent_retention import prune_runtime_state
from agent_run_evidence import DEFAULT_ORPHAN_AFTER_SECONDS, prune_run_evidence
from agent_run_registry import (
    recover_stale_runs,
    retention_protected_run_ids,
    settle_expired_runs,
)
from agent_scheduler import recover_stale_tasks, retry_task
from agent_skill_feedback import record_skill_curation

DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
# macOS asks the user before a background process reads these folders. A daily
# LaunchAgent must never raise that prompt by scanning them; a project that
# lives in one is included only when ~/.tao/projects.json names it.
PRIVACY_PROTECTED_HOME_FOLDERS = frozenset({"Desktop", "Documents", "Downloads"})
SKIPPED_SCAN_NAMES = frozenset({"node_modules", "build", "dist", "target"})


def run_maintenance(
    project: Path,
    *,
    stale_after_seconds: int = 3600,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    max_records: int = 100,
    orphan_after_seconds: int = DEFAULT_ORPHAN_AFTER_SECONDS,
    dry_run: bool = False,
    curate_skills: bool = True,
) -> dict[str, Any]:
    """Maintain one checkout; with ``dry_run`` report counts and change nothing."""

    if dry_run:
        settled = settle_expired_runs(
            project, retention_seconds=retention_seconds, apply=False
        )
        protected = retention_protected_run_ids(project)
        return {
            "dry_run": True,
            "settled_runs": len(settled),
            "pruned": prune_runtime_state(
                project,
                retention_seconds=retention_seconds,
                max_records=max_records,
                apply=False,
                assume_settled=settled,
                protected_runs=protected,
            ),
            "pruned_run_evidence": prune_run_evidence(
                project,
                abandoned_after_seconds=retention_seconds,
                orphan_after_seconds=orphan_after_seconds,
                protected=protected,
                apply=False,
            ),
        }

    recovered_runs = recover_stale_runs(project, stale_after_seconds=stale_after_seconds)
    recovered_tasks = recover_stale_tasks(project, stale_after_seconds=stale_after_seconds)
    requeued = [retry_task(project, str(task["task_id"])) for task in recovered_tasks]
    summary: dict[str, Any] = {
        "recovered_runs": len(recovered_runs),
        "recovered_tasks": len(recovered_tasks),
        "requeued_tasks": sum(task is not None for task in requeued),
    }
    if curate_skills:
        summary["skill_curation"], _details = record_skill_curation()
    # Settled before the registry is pruned, so a run abandoned for the window
    # leaves the registry in this pass rather than lingering as `failed`, which
    # resume would keep listing as work to take up.
    summary["settled_runs"] = len(
        settle_expired_runs(project, retention_seconds=retention_seconds)
    )
    # Decided once, before anything is pruned: a record pruned below would
    # otherwise take the evidence that its owner is still live with it.
    protected = retention_protected_run_ids(project)
    summary["pruned"] = prune_runtime_state(
        project,
        retention_seconds=retention_seconds,
        max_records=max_records,
        protected_runs=protected,
    )
    # Pruned after the registry, on the same window, so the directory of a
    # record removed above is recognised as an orphan rather than a live run.
    summary["pruned_run_evidence"] = prune_run_evidence(
        project,
        abandoned_after_seconds=retention_seconds,
        orphan_after_seconds=orphan_after_seconds,
        protected=protected,
    )
    return summary


def managed_projects(
    tao_root: Path,
    *,
    projects_registry: Path | None = None,
    search_roots: Iterable[Path] | None = None,
) -> list[Path]:
    """Every checkout a maintenance pass visits, each named once.

    The Tao root, every project ``projects.json`` names, and every directory
    at or directly under a search root that already holds Tao run state. Then
    the linked worktrees under each one's ``.tao/worktrees``, which keep their
    own run registry and evidence. Missing directories, and ones without a
    ``.tao`` directory, are skipped.
    """

    registry = load_registry(projects_registry)
    candidates: list[Path] = [tao_root]
    for item in registry.get("projects") or []:
        root = item.get("root") if isinstance(item, dict) else item
        if isinstance(root, str) and root:
            candidates.append(Path(root).expanduser())
    roots = (
        list(search_roots)
        if search_roots is not None
        else [
            *registry_search_roots(registry),
            *env_search_roots(),
            *(
                root
                for root in default_search_roots()
                if root.name not in PRIVACY_PROTECTED_HOME_FOLDERS
            ),
        ]
    )
    for root in roots:
        candidates.extend(_projects_under(root))

    checkouts: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        for checkout in [candidate, *_linked_worktrees(candidate)]:
            try:
                resolved = checkout.resolve()
            except OSError:
                continue
            # A checkout that never ran a Tao lifecycle has nothing to maintain,
            # and visiting it would create lock files in it.
            if resolved in seen or not (resolved / ".tao").is_dir():
                continue
            seen.add(resolved)
            checkouts.append(resolved)
    return checkouts


def run_all_maintenance(
    tao_root: Path,
    *,
    projects_registry: Path | None = None,
    search_roots: Iterable[Path] | None = None,
    dry_run: bool = False,
    **options: Any,
) -> dict[str, Any]:
    """Maintain every managed checkout; one failing checkout stops no other."""

    results: dict[str, Any] = {}
    for checkout in managed_projects(
        tao_root, projects_registry=projects_registry, search_roots=search_roots
    ):
        try:
            results[str(checkout)] = run_maintenance(
                checkout, dry_run=dry_run, curate_skills=False, **options
            )
        except (OSError, RuntimeError, ValueError) as error:
            results[str(checkout)] = {"error": type(error).__name__}
    summary: dict[str, Any] = {"dry_run": dry_run, "projects": results}
    if not dry_run:
        # Global state, curated once per pass rather than once per checkout.
        summary["skill_curation"], _details = record_skill_curation()
    return summary


def format_project_line(checkout: str, result: dict[str, Any]) -> str:
    """One report line of counts for a checkout."""

    if "error" in result:
        return f"{checkout}: error={result['error']}"
    evidence = result.get("pruned_run_evidence") or {}
    pruned = result.get("pruned") or {}
    verb = "removable" if result.get("dry_run") else "removed"
    removed = evidence.get("removable", 0) if result.get("dry_run") else evidence.get("removed", 0)
    return (
        f"{checkout}: settle_runs={result.get('settled_runs', 0)}"
        f" registry_prune={pruned.get('runs', 0)}"
        f" run_dirs {verb}={removed}"
        f" (finished={evidence.get('finished', 0)}"
        f" unfinished={evidence.get('unfinished', 0)}"
        f" abandoned={evidence.get('abandoned', 0)}"
        f" orphaned={evidence.get('orphaned', 0)}"
        f" unclassified={evidence.get('unclassified', 0)})"
        f" bytes={evidence.get('removable_bytes', 0)}"
    )


def _has_run_state(path: Path) -> bool:
    tao = path / ".tao"
    return (tao / "run-registry.json").is_file() or (tao / "runs").is_dir()


def _projects_under(root: Path) -> list[Path]:
    """The root itself and its direct children that hold Tao run state."""

    found: list[Path] = []
    try:
        if not root.is_dir():
            return found
        if _has_run_state(root):
            found.append(root)
        children = sorted(root.iterdir())
    except OSError:
        return found
    for child in children:
        if child.name.startswith(".") or child.name in SKIPPED_SCAN_NAMES:
            continue
        try:
            if child.is_dir() and _has_run_state(child):
                found.append(child)
        except OSError:
            continue
    return found


def _linked_worktrees(project: Path) -> list[Path]:
    directory = project / ".tao" / "worktrees"
    try:
        return sorted(path for path in directory.iterdir() if path.is_dir())
    except OSError:
        return []
