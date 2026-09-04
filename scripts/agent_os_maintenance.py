"""Shared stale-state recovery and retention implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_retention import prune_runtime_state
from agent_run_evidence import prune_run_evidence
from agent_run_registry import recover_stale_runs
from agent_scheduler import recover_stale_tasks, retry_task
from agent_skill_feedback import record_skill_curation


def run_maintenance(
    project: Path,
    *,
    stale_after_seconds: int = 3600,
    retention_seconds: int = 30 * 24 * 60 * 60,
    max_records: int = 100,
) -> dict[str, Any]:
    recovered_runs = recover_stale_runs(project, stale_after_seconds=stale_after_seconds)
    recovered_tasks = recover_stale_tasks(project, stale_after_seconds=stale_after_seconds)
    requeued = [retry_task(project, str(task["task_id"])) for task in recovered_tasks]
    skill_curation, _details = record_skill_curation()
    return {
        "recovered_runs": len(recovered_runs),
        "recovered_tasks": len(recovered_tasks),
        "requeued_tasks": sum(task is not None for task in requeued),
        "skill_curation": skill_curation,
        "pruned": prune_runtime_state(project, retention_seconds=retention_seconds, max_records=max_records),
        # The registry's records were pruned on this window from the first day;
        # the directories those records point at were not pruned by anything,
        # so the index shrank and the disk did not. Same window, so the two
        # halves of retention now agree about what is old.
        "pruned_run_evidence": prune_run_evidence(
            project, abandoned_after_seconds=retention_seconds
        ),
    }
