"""Prove a source run may be settled before anything settles it.

Split from `agent_transfer_cancel.py` because deciding whether a transfer is
legitimate and performing the settlement are separate jobs that grew together
past the per-file budget. This half answers one question -- do these two runs
describe the same request in the same repository, with the replacement
complete and the source checkout clean -- and returns findings rather than
acting on them, so the execution half can call it, and a reader can audit the
conditions without reading the transaction.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from agent_run_registry import (
    TRANSFER_CANCELLABLE_RUN_STATES,
    ledger_writable_run_claim_is_owned,
    registered_run,
)


def validate_transfer(
    source_project: Path,
    rules: Path,
    source_evidence: Path | None,
    replacement_evidence: Path | None,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    if source_evidence is None or replacement_evidence is None:
        return ["cancel requires --evidence and --replacement-evidence"], {}
    source_payload = read_preflight(source_evidence, "source", failures)
    replacement_payload = read_preflight(replacement_evidence, "replacement", failures)
    if failures:
        return failures, {}

    source_payload_project = payload_project(source_payload, "source", failures)
    replacement_project = payload_project(replacement_payload, "replacement", failures)
    if source_payload_project is None or replacement_project is None:
        return failures, {}
    if source_payload_project != source_project.resolve():
        failures.append("source evidence does not belong to --project")
    source_rules = payload_path(source_payload, "rules", "source", failures)
    replacement_rules = payload_path(
        replacement_payload, "rules", "replacement", failures
    )
    if source_rules != rules.resolve():
        failures.append("source evidence does not use --rules")
    if replacement_rules != rules.resolve():
        failures.append("replacement evidence does not use the same rules root")
    if source_evidence.resolve() == replacement_evidence.resolve():
        failures.append("replacement evidence must name a different run")
    if not (source_project / ".git").is_dir():
        failures.append("source project must be the repository's main checkout")
    if not (replacement_project / ".git").is_file():
        failures.append("replacement project must be a linked Git worktree")
    source_common_dir = git_common_dir(source_project)
    replacement_common_dir = git_common_dir(replacement_project)
    if (
        source_common_dir is None
        or replacement_common_dir is None
        or source_common_dir != replacement_common_dir
    ):
        failures.append("source and replacement must share one Git common directory")
    status = git(source_project, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        failures.append("source checkout Git status could not be verified")
    elif status.stdout.strip():
        failures.append("source checkout has tracked or untracked changes")

    source_run = registered_run(
        source_project,
        source_evidence,
        run_id=str(source_payload.get("agent_run_id") or ""),
    )
    replacement_run = registered_run(
        replacement_project,
        replacement_evidence,
        run_id=str(replacement_payload.get("agent_run_id") or ""),
    )
    if source_run is None:
        failures.append("source run is not registered for its evidence")
    elif source_run.get("state") not in TRANSFER_CANCELLABLE_RUN_STATES:
        failures.append("source run is already terminal or not cancellable")
    elif not ledger_writable_run_claim_is_owned(
        source_project,
        source_evidence,
        str(source_run.get("run_id") or ""),
    ):
        failures.append("source run is not owned by the current runtime session")
    if replacement_run is None:
        failures.append("replacement run is not registered for its evidence")
    elif replacement_run.get("state") != "completed":
        failures.append("replacement run has not completed successfully")
    if source_run and replacement_run:
        if not source_run.get("request_fingerprint"):
            failures.append("source request fingerprint is missing")
        if source_run.get("request_fingerprint") != replacement_run.get("request_fingerprint"):
            failures.append("source and replacement requests do not match")
        if source_run.get("command") != replacement_run.get("command"):
            failures.append("source and replacement workflow routes do not match")
    source_session = source_payload.get("runtime_session")
    replacement_session = replacement_payload.get("runtime_session")
    if not isinstance(source_session, dict) or not source_session.get("session_id"):
        failures.append("source runtime session is missing")
    elif source_session != replacement_session:
        failures.append("source and replacement runtime sessions do not match")
    return failures, {
        "source_run": source_run,
        "replacement_run": replacement_run,
    }


def read_preflight(path: Path, label: str, failures: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append(f"{label} evidence is missing or malformed")
        return {}
    if not isinstance(payload, dict) or not payload.get("agent_run_id"):
        failures.append(f"{label} evidence is not a registered run preflight")
        return {}
    return payload


def payload_project(
    payload: dict[str, Any],
    label: str,
    failures: list[str],
) -> Path | None:
    raw = payload.get("project")
    if not isinstance(raw, str) or not raw:
        failures.append(f"{label} evidence has no project")
        return None
    project = Path(raw).resolve()
    if not project.is_dir():
        failures.append(f"{label} project does not exist")
        return None
    return project


def payload_path(
    payload: dict[str, Any],
    field: str,
    label: str,
    failures: list[str],
) -> Path | None:
    raw = payload.get(field)
    if not isinstance(raw, str) or not raw:
        failures.append(f"{label} evidence has no {field}")
        return None
    return Path(raw).resolve()


def git_common_dir(project: Path) -> Path | None:
    result = git(project, "rev-parse", "--git-common-dir")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = Path(result.stdout.strip())
    return (project / common).resolve() if not common.is_absolute() else common.resolve()


def git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(project), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess([], 1, "", "")
