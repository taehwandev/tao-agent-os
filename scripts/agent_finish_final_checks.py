"""Final validation, diff, and VibeGuard checks for finish-check."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    atomic_write_json,
    file_hash_record,
    git_states_for_paths,
    read_json_object,
)
from agent_finish_common import add_gate_signal, parse_overall, run_command, vibeguard_command
from agent_inprocess import run_workflow_validate
from agent_vibeguard_cache import cached_vibeguard, skipped_vibeguard
from agent_workspace_policy import (
    is_non_git_workspace,
    is_writing_workspace,
    non_git_writing_workspace_note,
)


REVIEW_VALIDATION_SCHEMA_VERSION = 3
REVIEW_VALIDATION_FILENAME = "review-workflow-validation.json"


def run_final_checks(
    tao_root: Path,
    project: Path,
    rules: Path,
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
    read_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    review_validation = reusable_review_workflow_validation(project, rules)
    validate = review_validation or run_workflow_validate(tao_root)
    diff_check = (
        {
            "command": ["git", "diff", "--check"],
            "cwd": str(project),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped": True,
            "review_note": non_git_writing_workspace_note(project),
        }
        if (
            is_writing_workspace(project)
            or (read_only and is_non_git_workspace(project))
        )
        else (
            {
                "command": [],
                "cwd": str(project),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "skipped": True,
                "review_note": (
                    "current successful review diff check: "
                    f"{review_validation['diff_check']['review_scope']}"
                ),
            }
            if review_validation
            else run_command(["git", "diff", "--check"], project)
        )
    )
    vibeguard = (
        skipped_vibeguard(project)
        if read_only
        else cached_vibeguard(
            project=project,
            rules=rules,
            run_command=run_command,
            vibeguard_command=vibeguard_command,
            parse_overall=parse_overall,
        )
    )
    _record_final_check_signals(validate, diff_check, vibeguard, allow_vibeguard_review, gate_signals, failures)
    return validate, diff_check, vibeguard, vibeguard["overall"]["status"]


def _record_final_check_signals(
    validate: dict[str, Any],
    diff_check: dict[str, Any],
    vibeguard: dict[str, Any],
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
) -> None:
    if validate["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "workflow validate", "failed", "non-zero exit")
        failures.append("workflow validate failed")
    elif validate.get("reused"):
        add_gate_signal(gate_signals, "SUCCESS", "workflow validate", "reused", "current review result")
    else:
        add_gate_signal(gate_signals, "SUCCESS", "workflow validate", "executed", "exit 0")
    if diff_check["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "diff check", "failed", "non-zero exit")
        failures.append("git diff --check failed")
    elif diff_check.get("skipped"):
        add_gate_signal(gate_signals, "SUCCESS", "diff check", "review accepted", diff_check["review_note"])
    else:
        add_gate_signal(gate_signals, "SUCCESS", "diff check", "executed", "exit 0")
    _record_vibeguard_signal(vibeguard, allow_vibeguard_review, gate_signals, failures)


def _record_vibeguard_signal(
    vibeguard: dict[str, Any],
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
) -> None:
    overall = vibeguard["overall"]["status"]
    if vibeguard.get("skipped"):
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "skipped", overall)
    elif vibeguard["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "VibeGuard", "failed", "non-zero exit")
        failures.append("final VibeGuard audit failed")
    elif overall != "Ready" and not allow_vibeguard_review:
        add_gate_signal(gate_signals, "FAIL", "VibeGuard", "blocked", overall)
        failures.append(
            "final VibeGuard is not Ready; report the state and pass "
            "--allow-vibeguard-review with a reason if the review is acceptable"
        )
    elif overall != "Ready":
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "review accepted", allow_vibeguard_review or overall)
    else:
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "executed", overall)


def record_successful_review_workflow_validation(
    project: Path,
    rules: Path,
    evidence_path: Path,
    validate: dict[str, Any],
    diff_check: dict[str, Any],
    review_scope: str,
) -> None:
    """Persist successful review checks with their exact source snapshot."""

    if (
        validate.get("returncode") != 0
        or diff_check.get("returncode") != 0
        or not review_scope.strip()
        or not evidence_path.is_file()
    ):
        return
    try:
        project_git, rules_git = git_states_for_paths(project, rules)
        evidence_relative = evidence_path.resolve().relative_to(
            (project.resolve() / ".tao").resolve()
        )
        evidence = {
            "path": evidence_relative.as_posix(),
            "sha256": file_hash_record(evidence_path)["sha256"],
        }
    except (OSError, RuntimeError, ValueError):
        return
    atomic_write_json(
        review_validation_path(project),
        {
            "schema_version": REVIEW_VALIDATION_SCHEMA_VERSION,
            "preflight_evidence": evidence,
            "project_git": project_git,
            "rules_git": rules_git,
            "workflow_validate": {"returncode": 0},
            "diff_check": {
                "returncode": 0,
                "review_scope": review_scope.strip(),
            },
        },
    )


def reusable_review_workflow_validation(project: Path, rules: Path) -> dict[str, Any] | None:
    """Return the review result only while its project/rules state is current."""

    record = read_json_object(review_validation_path(project))
    if not _valid_review_validation_record(record):
        return None
    evidence_path = (
        project.resolve()
        / ".tao"
        / record["preflight_evidence"]["path"]
    ).resolve()
    try:
        evidence_path.relative_to((project.resolve() / ".tao").resolve())
        current_evidence = {
            "path": record["preflight_evidence"]["path"],
            "sha256": file_hash_record(evidence_path)["sha256"],
        }
        if not evidence_path.is_file() or current_evidence != record["preflight_evidence"]:
            return None
        project_git, rules_git = git_states_for_paths(
            project,
            rules,
            project_record=record["project_git"],
            rules_record=record["rules_git"],
        )
    except (OSError, RuntimeError, ValueError):
        return None
    if project_git != record["project_git"] or rules_git != record["rules_git"]:
        return None
    return {
        "command": [],
        "cwd": str(rules),
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "reused": True,
        "source": "review",
        "diff_check": record["diff_check"],
    }


def review_validation_path(project: Path) -> Path:
    return project.resolve() / ".tao" / REVIEW_VALIDATION_FILENAME


def _valid_review_validation_record(record: dict[str, Any]) -> bool:
    if set(record) != {
        "schema_version",
        "preflight_evidence",
        "project_git",
        "rules_git",
        "workflow_validate",
        "diff_check",
    }:
        return False
    if record.get("schema_version") != REVIEW_VALIDATION_SCHEMA_VERSION:
        return False
    if not isinstance(record.get("preflight_evidence"), dict):
        return False
    if set(record["preflight_evidence"]) != {"path", "sha256"}:
        return False
    if not isinstance(record["preflight_evidence"].get("path"), str):
        return False
    if not isinstance(record["preflight_evidence"].get("sha256"), str):
        return False
    for key in ("project_git", "rules_git"):
        value = record.get(key)
        if not isinstance(value, dict) or set(value) != {
            "head",
            "worktree_fingerprint",
            "worktree_signature",
        }:
            return False
    if record.get("workflow_validate") != {"returncode": 0}:
        return False
    diff_check = record.get("diff_check")
    return (
        isinstance(diff_check, dict)
        and set(diff_check) == {"returncode", "review_scope"}
        and diff_check.get("returncode") == 0
        and isinstance(diff_check.get("review_scope"), str)
        and bool(diff_check["review_scope"].strip())
    )
