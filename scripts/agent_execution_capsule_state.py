"""Content-free state and persistence primitives for execution capsules."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from agent_directory_fingerprint import directory_state
from agent_worktree_fingerprint import (
    capture_worktree_state,
    git_output,
    worktree_signature,
)


SCHEMA_VERSION = 4
PREFLIGHT_SNAPSHOT_SCHEMA_VERSION = 1
CAPSULE_FILENAME = "execution-capsule.json"
MAX_GIT_STATE_ATTEMPTS = 2
REUSE_POLICY = {
    "condition": "ready_and_valid",
    "gate_effect": "none",
    "ledger_owner": "parent",
    "worker_may_skip": ["route", "preflight"],
    "worker_may_reuse": ["required-doc-manifest"],
}


def capsule_path_for_evidence(evidence_path: Path) -> Path:
    if evidence_path.name == "preflight.json":
        return evidence_path.parent / CAPSULE_FILENAME
    return evidence_path.parent / f"{evidence_path.stem}-{CAPSULE_FILENAME}"


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {"invalid_json": True}
    return payload if isinstance(payload, dict) else {"invalid_json": True}


def file_hash_record(path: Path) -> dict[str, str]:
    return {"filename": path.name, "sha256": sha256_file(path)}


def doc_hash_record(relative: str, path: Path) -> dict[str, Any]:
    digest, size = _sha256_and_size(path)
    return {
        "path": relative,
        "size_bytes": size,
        "sha256": digest,
    }


def contained_doc_path(rules: Path, relative: str) -> Path:
    candidate = (rules / relative).resolve()
    try:
        candidate.relative_to(rules)
    except ValueError as error:
        raise ValueError(f"required doc escapes rules root: {relative}") from error
    return candidate


def git_state(
    path: Path,
    recorded: dict[str, str] | None = None,
) -> dict[str, str]:
    """Capture Git state, reusing a strong fingerprint only while safely current."""

    for _attempt in range(MAX_GIT_STATE_ATTEMPTS):
        head = git_output(path, "rev-parse", "--verify", "HEAD").strip()
        if (
            _is_reusable_git_state(recorded)
            and recorded["head"] == head
            and recorded["worktree_signature"] == worktree_signature(path)
        ):
            if git_output(path, "rev-parse", "--verify", "HEAD").strip() == head:
                return dict(recorded)
            continue

        snapshot = capture_worktree_state(path)
        if git_output(path, "rev-parse", "--verify", "HEAD").strip() == head:
            return {
                "head": head,
                "worktree_fingerprint": snapshot.fingerprint,
                "worktree_signature": snapshot.signature,
            }
    raise RuntimeError("git HEAD changed during execution-capsule state capture")


def git_repository_root(path: Path) -> Path:
    """Return the canonical top-level repository for a path.

    Capsule callers frequently receive a project root and a rules root that
    are different directories inside the same checkout.  They still describe
    one mutable worktree, so callers must not stream its fingerprint twice.
    """

    return Path(git_output(path, "rev-parse", "--show-toplevel").strip()).resolve()


def git_states_for_paths(
    project: Path,
    rules: Path,
    *,
    project_record: dict[str, str] | None = None,
    rules_record: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Capture project/rules state, supporting non-Git runtime roots."""

    project = project.resolve()
    rules = rules.resolve()
    project_root = _git_repository_root_or_none(project)
    rules_root = _git_repository_root_or_none(rules)
    if project_root is not None and project_root == rules_root:
        shared_record = project_record if project_record == rules_record else None
        shared_state = git_state(project, shared_record)
        return shared_state, shared_state
    return (
        git_state(project, project_record)
        if project_root is not None
        else directory_state(project, project_record),
        git_state(rules, rules_record)
        if rules_root is not None
        else directory_state(rules, rules_record),
    )


def _git_repository_root_or_none(path: Path) -> Path | None:
    try:
        return git_repository_root(path)
    except RuntimeError:
        return None


def _is_reusable_git_state(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"head", "worktree_fingerprint", "worktree_signature"}
        and isinstance(value.get("head"), str)
        and bool(value["head"])
        and is_sha256(value.get("worktree_fingerprint"))
        and is_sha256(value.get("worktree_signature"))
    )


def sha256_file(path: Path) -> str:
    return _sha256_and_size(path)[0]


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def execution_capsule_binding_fingerprint(capsule: dict[str, Any]) -> str | None:
    """Return the stable route/doc identity that gate evidence may reference.

    A finish check runs after implementation, so mutable worktree and ledger
    hashes cannot participate in an evidence binding.  This deliberately uses
    only the preflight, route, and required-document snapshot captured before
    work began.
    """

    required = (
        "schema_version",
        "phase",
        "route_fingerprint",
        "request_fingerprint",
        "preflight_evidence",
        "required_docs",
        "reuse_policy",
    )
    if any(field not in capsule for field in required):
        return None
    if capsule.get("phase") != "ready":
        return None
    payload = {field: capsule[field] for field in required}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preflight_snapshot_binding_fingerprint(snapshot: dict[str, Any]) -> str | None:
    """Return the immutable parent-start binding when no worker is handed off.

    A simple serial task has no reason to create an execution capsule.  Its
    gate evidence still needs one stable, content-free pre-edit binding, so the
    parent preflight snapshot carries the route/request/document identity until
    a later handoff replaces it with a ready execution capsule.
    """

    required = (
        "schema_version",
        "route_fingerprint",
        "request_fingerprint",
        "required_docs",
    )
    if any(field not in snapshot for field in required):
        return None
    if snapshot.get("schema_version") != PREFLIGHT_SNAPSHOT_SCHEMA_VERSION:
        return None
    payload = {field: snapshot[field] for field in required}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.parent.is_symlink():
        raise OSError(f"Symbolic link detected in directory: {path.parent}")

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary_path.write_bytes(encoded)
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        temporary_path.replace(path)
    except BaseException:
        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError:
            pass
        raise


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
