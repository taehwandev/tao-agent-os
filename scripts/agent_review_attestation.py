"""Run-bound evidence that the Review Hook actually completed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    atomic_write_json,
    doc_hash_record,
    file_hash_record,
    git_states_for_paths,
    is_sha256,
    read_json_object,
)
from agent_worktree_fingerprint import git_output
from agent_route_state import route_fingerprint


SCHEMA_VERSION = 3
REVIEW_HOOK_GATE = "review hook"
LOCAL_AGENT_CONFIG_PATHS = frozenset(
    {
        ".agents/local/graphify-out/GRAPH_REPORT.md",
        ".agents/local/graphify-out/graph.html",
        ".agents/local/graphify-out/graph.json",
        ".agents/local/graphify-out/manifest.json",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".codex/hooks.json",
    }
)


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
    def local_config_subject(project: Path, review_paths: list[str]) -> dict[str, Any]:
        """Snapshot an explicit allowlisted ignored agent-local boundary."""

        return _local_config_subject(project, review_paths)

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
        review_subject: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically bind one successful review to its exact current bytes."""

        scope = review_scope.strip()
        paths = [str(path).strip() for path in review_paths]
        run_id, vibeguard = _validate_record_inputs(
            scope, paths, changed_path_count, preflight, checks
        )

        project = project.resolve()
        rules = rules.resolve()
        evidence_path = evidence_path.resolve()
        subject = _normalize_review_subject(review_subject)
        _verify_subject_scope(project, subject, scope, paths, changed_path_count)
        try:
            relative = evidence_path.relative_to((project / ".tao").resolve()).as_posix()
        except ValueError as error:
            raise ValueError(
                "review attestation evidence path must be inside the review project .tao root"
            ) from error
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
            "review_subject": subject,
            "review_subject_fingerprint": _subject_fingerprint(subject),
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
        fields = {
            "review_attestation": str(attestation.get("attestation_id") or ""),
            "review_scope": str(attestation.get("review_scope") or ""),
            "review_paths_fingerprint": str(
                attestation.get("review_paths_fingerprint") or ""
            ),
            "changed_path_count": str(attestation.get("changed_path_count", "")),
        }
        subject_fingerprint = str(attestation.get("review_subject_fingerprint") or "")
        if subject_fingerprint:
            fields["review_subject_fingerprint"] = subject_fingerprint
        return fields

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


def _validate_record_inputs(
    scope: str,
    paths: list[str],
    changed_path_count: int,
    preflight: dict[str, Any],
    checks: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Reject a record call whose inputs cannot describe one passed review."""

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
    return run_id, vibeguard


def _verify_subject_scope(
    project: Path,
    subject: dict[str, Any],
    scope: str,
    paths: list[str],
    changed_path_count: int,
) -> None:
    """Bind a non-working-tree subject to the exact bytes the scope names."""

    if subject["kind"] == "commit-range":
        expected_scope = f"commit-range: {subject['base_sha']}..{subject['head_sha']}"
        if scope != expected_scope:
            raise ValueError("review attestation commit range scope does not match its SHAs")
        committed_paths = _commit_subject_paths(project, subject)
        if paths != committed_paths or changed_path_count != len(committed_paths):
            raise ValueError(
                "review attestation commit range paths do not match the exact Git diff"
            )
    elif subject["kind"] == "local-config":
        expected_scope = "local-config: " + ", ".join(paths)
        if scope != expected_scope:
            raise ValueError("review attestation local config scope does not match its paths")
        current_subject = _local_config_subject(project, paths)
        if subject != current_subject or changed_path_count != len(paths):
            raise ValueError(
                "review attestation local config subject does not match current file bytes"
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
    failures.extend(_current_subject_failures(project, record))
    if project_git != record["project_git"]:
        failures.append("review hook attestation project worktree binding is stale")
    if rules_git != record["rules_git"]:
        failures.append("review hook attestation rules worktree binding is stale")
    return list(dict.fromkeys(failures))


def _paths_fingerprint(paths: list[str]) -> str:
    encoded = json.dumps(paths, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _subject_fingerprint(subject: dict[str, str]) -> str:
    encoded = json.dumps(
        subject,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_review_subject(subject: dict[str, Any] | None) -> dict[str, Any]:
    if subject is None:
        return {"kind": "working-tree"}
    if subject == {"kind": "working-tree"}:
        return dict(subject)
    if not isinstance(subject, dict):
        raise ValueError("review attestation subject is invalid")
    if subject.get("kind") == "local-config":
        if set(subject) != {"kind", "files"}:
            raise ValueError("review attestation local config subject is invalid")
        files = subject.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("review attestation local config files are invalid")
        normalized_files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for record in files:
            if not isinstance(record, dict) or set(record) != {
                "path",
                "sha256",
                "size_bytes",
            }:
                raise ValueError("review attestation local config file record is invalid")
            path = record.get("path")
            size = record.get("size_bytes")
            if (
                not isinstance(path, str)
                or path not in LOCAL_AGENT_CONFIG_PATHS
                or path in seen_paths
                or not is_sha256(record.get("sha256"))
                or not isinstance(size, int)
                or size < 0
            ):
                raise ValueError("review attestation local config file record is invalid")
            seen_paths.add(path)
            normalized_files.append(dict(record))
        return {"kind": "local-config", "files": normalized_files}
    if set(subject) != {"kind", "base_sha", "head_sha"}:
        raise ValueError("review attestation subject is invalid")
    if subject.get("kind") != "commit-range":
        raise ValueError("review attestation subject kind is invalid")
    base_sha = str(subject.get("base_sha") or "")
    head_sha = str(subject.get("head_sha") or "")
    if not _is_git_sha(base_sha) or not _is_git_sha(head_sha) or base_sha == head_sha:
        raise ValueError("review attestation commit range SHAs are invalid")
    return {"kind": "commit-range", "base_sha": base_sha, "head_sha": head_sha}


def _commit_subject_paths(project: Path, subject: dict[str, str]) -> list[str]:
    base_sha = subject["base_sha"]
    head_sha = subject["head_sha"]
    for sha in (base_sha, head_sha):
        resolved = git_output(project, "rev-parse", "--verify", f"{sha}^{{commit}}").strip()
        if resolved != sha:
            raise ValueError("review attestation commit object is unavailable")
    git_output(project, "merge-base", "--is-ancestor", base_sha, head_sha)
    output = git_output(
        project,
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACDMRTUXB",
        base_sha,
        head_sha,
        "--",
    )
    return [path for path in output.split("\0") if path]


def _current_subject_failures(project: Path, record: dict[str, Any]) -> list[str]:
    subject = record.get("review_subject") or {"kind": "working-tree"}
    if subject == {"kind": "working-tree"}:
        return []
    if subject.get("kind") == "local-config":
        try:
            current = _local_config_subject(project, record["review_paths"])
        except (OSError, RuntimeError, TypeError, ValueError):
            return ["review hook attestation local config subject is no longer verifiable"]
        if current != subject:
            return ["review hook attestation local config bytes changed after review"]
        return []
    try:
        paths = _commit_subject_paths(project, subject)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ["review hook attestation commit range is no longer verifiable"]
    if paths != record["review_paths"] or len(paths) != record["changed_path_count"]:
        return ["review hook attestation commit range paths are stale or foreign"]
    return []


def _local_config_subject(project: Path, review_paths: list[str]) -> dict[str, Any]:
    project = project.resolve()
    paths = [str(path).strip() for path in review_paths]
    if not paths or any(not path for path in paths) or len(paths) != len(set(paths)):
        raise ValueError("local config review requires unique explicit paths")

    files: list[dict[str, Any]] = []
    for path in paths:
        normalized = Path(path).as_posix()
        if normalized != path or path not in LOCAL_AGENT_CONFIG_PATHS:
            raise ValueError(f"local config review path is not allowlisted: {path}")
        unresolved = project / path
        if unresolved.is_symlink():
            raise ValueError(f"local config review rejects symlinks: {path}")
        candidate = unresolved.resolve()
        try:
            candidate.relative_to(project)
        except ValueError as error:
            raise ValueError(f"local config review path escapes the project: {path}") from error
        if not candidate.is_file():
            raise ValueError(f"local config review path is not a file: {path}")
        try:
            git_output(project, "check-ignore", "--quiet", "--", path)
        except RuntimeError as error:
            raise ValueError(f"local config review path is not Git-ignored: {path}") from error
        files.append(doc_hash_record(path, candidate))
    return {"kind": "local-config", "files": files}


def _is_git_sha(value: str) -> bool:
    return len(value) in {40, 64} and all(
        character in "0123456789abcdef" for character in value
    )


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
    legacy_keys = {
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
    expected_keys = {
        *legacy_keys,
        "review_subject",
        "review_subject_fingerprint",
    }
    schema_version = record.get("schema_version")
    if schema_version == 1:
        if set(record) != legacy_keys:
            return ["review hook attestation schema fields are invalid"]
        expected_keys = legacy_keys
    if set(record) != expected_keys:
        return ["review hook attestation schema fields are invalid"]
    if schema_version not in {1, 2, SCHEMA_VERSION} or record.get("status") != "SUCCESS":
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
    fingerprint_fields = [
        "route_fingerprint",
        "review_paths_fingerprint",
        "attestation_id",
    ]
    if schema_version in {2, SCHEMA_VERSION}:
        fingerprint_fields.append("review_subject_fingerprint")
    for field in fingerprint_fields:
        if not is_sha256(record.get(field)):
            return [f"review hook attestation {field} is invalid"]
    paths = record.get("review_paths")
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
        return ["review hook attestation review paths are invalid"]
    if record["review_paths_fingerprint"] != _paths_fingerprint(paths):
        return ["review hook attestation review paths fingerprint is invalid"]
    subject = {"kind": "working-tree"}
    if schema_version in {2, SCHEMA_VERSION}:
        try:
            subject = _normalize_review_subject(record.get("review_subject"))
        except ValueError:
            return ["review hook attestation review subject is invalid"]
        if subject != record["review_subject"]:
            return ["review hook attestation review subject is invalid"]
        if record["review_subject_fingerprint"] != _subject_fingerprint(subject):
            return ["review hook attestation review subject fingerprint is invalid"]
        if schema_version == 2 and subject.get("kind") == "local-config":
            return ["review hook attestation local config subject requires schema version 3"]
    if not isinstance(record.get("review_scope"), str) or not record["review_scope"].strip():
        return ["review hook attestation review scope is invalid"]
    if not isinstance(record.get("changed_path_count"), int) or record["changed_path_count"] < 0:
        return ["review hook attestation changed path count is invalid"]
    if subject["kind"] == "commit-range" and record["changed_path_count"] != len(paths):
        return ["review hook attestation commit range path count is invalid"]
    if subject["kind"] == "local-config" and record["changed_path_count"] != len(paths):
        return ["review hook attestation local config path count is invalid"]
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
