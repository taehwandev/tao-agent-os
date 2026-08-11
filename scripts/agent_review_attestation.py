"""Run-bound evidence that the Review Hook actually completed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    atomic_write_json,
    file_hash_record,
    git_states_for_paths,
    is_sha256,
    read_json_object,
)
from agent_route_state import route_fingerprint


SCHEMA_VERSION = 1
REVIEW_HOOK_GATE = "review hook"


class ReviewAttestation:
    """Create and verify the hook-owned review result for one evidence file."""

    @staticmethod
    def path(evidence_path: Path) -> Path:
        name = (
            "review-attestation.json"
            if evidence_path.name == "preflight.json"
            else f"{evidence_path.stem}-review-attestation.json"
        )
        return evidence_path.parent / name

    @staticmethod
    def record(
        *,
        project: Path,
        rules: Path,
        evidence_path: Path,
        preflight: dict[str, Any],
        review_scope: str,
        review_paths: list[str],
        changed_path_count: int,
        checks: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically bind one successful review to its exact current bytes."""

        scope = review_scope.strip()
        paths = [str(path).strip() for path in review_paths]
        if not scope or any(not path for path in paths) or len(paths) != len(set(paths)):
            raise ValueError("review attestation requires one exact normalized review scope")
        if changed_path_count < 0:
            raise ValueError("review attestation changed path count cannot be negative")
        run_id = str(preflight.get("agent_run_id") or "").strip()
        if not run_id:
            raise ValueError("review attestation requires a bound agent run id")
        if str(checks.get("review_outcome") or "").strip() != "pass":
            raise ValueError("review attestation requires review outcome pass")
        if (checks.get("workflow_validate") or {}).get("returncode") != 0:
            raise ValueError("review attestation requires successful workflow validation")
        if (checks.get("diff_check") or {}).get("returncode") != 0:
            raise ValueError("review attestation requires successful diff check")
        vibeguard = checks.get("vibeguard") or {}
        if vibeguard.get("returncode") != 0:
            raise ValueError("review attestation requires successful VibeGuard execution")

        project = project.resolve()
        rules = rules.resolve()
        evidence_path = evidence_path.resolve()
        relative = evidence_path.relative_to((project / ".tao").resolve()).as_posix()
        project_git, rules_git = git_states_for_paths(project, rules)
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": "SUCCESS",
            "agent_run_id": run_id,
            "preflight_evidence": {
                "path": relative,
                "sha256": file_hash_record(evidence_path)["sha256"],
            },
            "route_fingerprint": route_fingerprint(preflight.get("route") or {}),
            "project_git": project_git,
            "rules_git": rules_git,
            "review_scope": scope,
            "review_paths": paths,
            "review_paths_fingerprint": _paths_fingerprint(paths),
            "changed_path_count": changed_path_count,
            "checks": {
                "review_outcome": "pass",
                "workflow_validate": 0,
                "diff_check": 0,
                "vibeguard": str(vibeguard.get("overall") or ""),
                "worktree_unchanged": True,
            },
        }
        payload["attestation_id"] = _attestation_id(payload)
        atomic_write_json(ReviewAttestation.path(evidence_path), payload)
        return payload

    @staticmethod
    def ledger_fields(attestation: dict[str, Any]) -> dict[str, str]:
        return {
            "review_attestation": str(attestation.get("attestation_id") or ""),
            "review_scope": str(attestation.get("review_scope") or ""),
            "review_paths_fingerprint": str(
                attestation.get("review_paths_fingerprint") or ""
            ),
            "changed_path_count": str(attestation.get("changed_path_count", "")),
        }

    @staticmethod
    def failures(
        *,
        project: Path,
        rules: Path,
        evidence_path: Path,
        route: dict[str, Any],
        ledger_fields: dict[str, str],
        ledger_source: str,
    ) -> list[str]:
        """Return why the latest ledger success lacks a current real review."""

        return _attestation_failures(
            project=project,
            rules=rules,
            evidence_path=evidence_path,
            route=route,
            ledger_fields=ledger_fields,
            ledger_source=ledger_source,
        )


def _attestation_failures(
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
    route: dict[str, Any],
    ledger_fields: dict[str, str],
    ledger_source: str,
) -> list[str]:
    record = read_json_object(ReviewAttestation.path(evidence_path.resolve()))
    if not record or record.get("invalid_json"):
        return ["review hook attestation is missing or invalid"]
    failures = _record_shape_failures(record)
    if failures:
        return failures

    if record["attestation_id"] != _attestation_id(record):
        failures.append("review hook attestation integrity does not match")
    if ledger_source != "review":
        failures.append("review hook ledger source is not the review hook")
    expected_fields = ReviewAttestation.ledger_fields(record)
    for field, expected in expected_fields.items():
        if ledger_fields.get(field) != expected:
            failures.append(f"review hook attestation {field} does not match the ledger")

    try:
        project = project.resolve()
        rules = rules.resolve()
        evidence_path = evidence_path.resolve()
        expected_path = evidence_path.relative_to(project / ".tao").as_posix()
        current_evidence = file_hash_record(evidence_path)
        project_git, rules_git = git_states_for_paths(
            project,
            rules,
            project_record=record["project_git"],
            rules_record=record["rules_git"],
        )
        preflight = read_json_object(evidence_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        return failures + ["review hook attestation current binding cannot be verified"]

    if record["preflight_evidence"] != {
        "path": expected_path,
        "sha256": current_evidence["sha256"],
    }:
        failures.append("review hook attestation preflight binding is stale or foreign")
    if record["route_fingerprint"] != route_fingerprint(route):
        failures.append("review hook attestation route binding is stale or foreign")
    if record["agent_run_id"] != str(preflight.get("agent_run_id") or ""):
        failures.append("review hook attestation run binding is stale or foreign")
    if project_git != record["project_git"]:
        failures.append("review hook attestation project worktree binding is stale")
    if rules_git != record["rules_git"]:
        failures.append("review hook attestation rules worktree binding is stale")
    return list(dict.fromkeys(failures))


def _paths_fingerprint(paths: list[str]) -> str:
    encoded = json.dumps(paths, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _attestation_id(payload: dict[str, Any]) -> str:
    bounded = {key: value for key, value in payload.items() if key != "attestation_id"}
    encoded = json.dumps(
        bounded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_shape_failures(record: dict[str, Any]) -> list[str]:
    expected_keys = {
        "schema_version",
        "status",
        "agent_run_id",
        "preflight_evidence",
        "route_fingerprint",
        "project_git",
        "rules_git",
        "review_scope",
        "review_paths",
        "review_paths_fingerprint",
        "changed_path_count",
        "checks",
        "attestation_id",
    }
    if set(record) != expected_keys:
        return ["review hook attestation schema fields are invalid"]
    if record.get("schema_version") != SCHEMA_VERSION or record.get("status") != "SUCCESS":
        return ["review hook attestation schema version or status is invalid"]
    if not isinstance(record.get("agent_run_id"), str) or not record["agent_run_id"].strip():
        return ["review hook attestation run id is invalid"]
    evidence = record.get("preflight_evidence")
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"path", "sha256"}
        or not isinstance(evidence.get("path"), str)
        or not is_sha256(evidence.get("sha256"))
    ):
        return ["review hook attestation preflight evidence is invalid"]
    for field in ("route_fingerprint", "review_paths_fingerprint", "attestation_id"):
        if not is_sha256(record.get(field)):
            return [f"review hook attestation {field} is invalid"]
    paths = record.get("review_paths")
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
        return ["review hook attestation review paths are invalid"]
    if record["review_paths_fingerprint"] != _paths_fingerprint(paths):
        return ["review hook attestation review paths fingerprint is invalid"]
    if not isinstance(record.get("review_scope"), str) or not record["review_scope"].strip():
        return ["review hook attestation review scope is invalid"]
    if not isinstance(record.get("changed_path_count"), int) or record["changed_path_count"] < 0:
        return ["review hook attestation changed path count is invalid"]
    checks = record.get("checks")
    if checks != {
        "review_outcome": "pass",
        "workflow_validate": 0,
        "diff_check": 0,
        "vibeguard": str((checks or {}).get("vibeguard") or ""),
        "worktree_unchanged": True,
    }:
        return ["review hook attestation successful checks are invalid"]
    return []
