"""Bounded, path-opaque state for continuation mutation checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from agent_continuation_fields import failure
from agent_continuation_packet import ContinuationPacketError
from agent_continuation_store import continuation_path
from agent_execution_capsule_state import is_sha256
from agent_worktree_fingerprint import MAX_UNTRACKED_BYTES, MAX_UNTRACKED_FILES
from agent_worktree_scan import WorktreeFingerprintLimitExceeded
from agent_workspace_policy import is_non_git_workspace


class _MutationPathState:
    """Own the sidecar path and its project-local containment check."""

    FILENAME = ".mutation-baseline.json"
    MAX_BYTES = 1024 * 1024

    @classmethod
    def path(cls, project: Path, run_id: str) -> Path:
        return continuation_path(project, run_id).parent / cls.FILENAME

    @classmethod
    def is_local(cls, project: Path, path: Path) -> bool:
        if any(
            candidate.is_symlink()
            for candidate in (path, path.parent, path.parent.parent, path.parent.parent.parent)
        ):
            return False
        if is_non_git_workspace(project):
            return True
        return subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=project,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0


class _MutationCaptureState:
    """Capture path-opaque worktree state for one mutation boundary."""

    @classmethod
    def capture(cls, project: Path) -> dict[str, str]:
        """Capture a bounded baseline without storing project-relative paths."""

        records = (
            cls._git_changed_records(project)
            if not is_non_git_workspace(project)
            else {path: b"" for path in cls._local_paths(project)}
        )
        if len(records) > MAX_UNTRACKED_FILES:
            raise WorktreeFingerprintLimitExceeded("mutation baseline path count exceeds limit")
        total = 0
        states: dict[str, str] = {}
        for relative, record in records.items():
            candidate = project / relative
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                payload = record + b"\0missing"
            else:
                total += metadata.st_size
                if total > MAX_UNTRACKED_BYTES:
                    raise WorktreeFingerprintLimitExceeded(
                        "mutation baseline bytes exceed limit"
                    )
                mode = str(stat.S_IMODE(metadata.st_mode)).encode("ascii")
                if stat.S_ISLNK(metadata.st_mode):
                    payload = (
                        record
                        + b"\0link\0"
                        + mode
                        + b"\0"
                        + os.fsencode(os.readlink(candidate))
                    )
                elif stat.S_ISREG(metadata.st_mode):
                    payload = record + b"\0file\0" + mode + b"\0" + candidate.read_bytes()
                else:
                    payload = record + b"\0mode:" + mode
            states[cls._path_key(relative.as_posix())] = hashlib.sha256(payload).hexdigest()
        return states


class _MutationScopeState:
    """Reconcile declared mutation scope with the captured byte state."""

    @classmethod
    def merge_changed_scope(
        cls,
        project: Path,
        run_id: str,
        base: dict[str, Any],
        update: dict[str, Any],
    ) -> dict[str, Any]:
        """Add only declared paths whose bytes really changed after the tool."""

        pending = (base.get("checkpoint") or {}).get("mutation_pending")
        if not isinstance(pending, dict):
            return update
        baseline = cls._read(project, run_id)
        before = baseline.get("states")
        if not isinstance(before, dict):
            return update
        current = cls.capture(project)
        changed_paths = [
            str(path)
            for path in pending.get("paths") or []
            if before.get(cls._path_key(str(path))) != current.get(cls._path_key(str(path)))
        ]
        existing = list((base.get("work") or {}).get("changed_scope") or [])
        supplied = update.get("changed_scope")
        if supplied is not None:
            existing = list(supplied)
        known = set(cls._scope_paths(existing))
        role = {
            "create": "created",
            "delete": "deleted",
        }.get(str(pending.get("kind") or ""), "modified")
        for path in changed_paths:
            if path not in known:
                existing.append({"path": path, "role": role})
        return {**update, "changed_scope": existing}

    @classmethod
    def reject_undeclared_paths(
        cls,
        project: Path,
        run_id: str,
        base: dict[str, Any],
        packet: dict[str, Any],
    ) -> None:
        """Fail when a mutation changes bytes outside its declared path set."""

        declared = set(
            (base.get("checkpoint") or {}).get("mutation_pending", {}).get("paths") or []
        )
        known = cls._scope_paths((base.get("work") or {}).get("changed_scope") or [])
        changed_scope = cls._scope_paths((packet.get("work") or {}).get("changed_scope") or [])
        for index, path in enumerate(changed_scope):
            if path not in known and path not in declared:
                raise ContinuationPacketError(
                    [failure("undeclared_changed_path", f"/work/changed_scope/{index}")]
                )
        baseline = cls._read(project, run_id)
        if (
            baseline.get("packet_generation") != base.get("generation")
            or not isinstance(baseline.get("states"), dict)
        ):
            raise ContinuationPacketError(
                [failure("missing_mutation_baseline", "/checkpoint/mutation_pending")]
            )
        current = cls.capture(project)
        changed = {
            key
            for key in set(baseline["states"]) | set(current)
            if baseline["states"].get(key) != current.get(key)
        }
        allowed = {cls._path_key(path) for path in declared}
        if changed - allowed:
            raise ContinuationPacketError(
                [failure("undeclared_changed_path", "/checkpoint/mutation_pending/paths")]
            )


class _MutationStorageState:
    """Read and validate the owner-only baseline sidecar."""

    @classmethod
    def _read(cls, project: Path, run_id: str) -> dict[str, Any]:
        """Read the closed, owner-only sidecar without following its symlink."""

        path = cls.path(project, run_id)
        if not cls.is_local(project, path):
            return {}
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > cls.MAX_BYTES
            ):
                os.close(descriptor)
                return {}
            with os.fdopen(descriptor, "rb") as stream:
                encoded = stream.read(cls.MAX_BYTES + 1)
            payload = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or set(payload) != {"packet_generation", "states"}:
            return {}
        generation = payload.get("packet_generation")
        states = payload.get("states")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or not isinstance(states, dict)
            or len(states) > MAX_UNTRACKED_FILES
            or any(not is_sha256(key) or not is_sha256(value) for key, value in states.items())
        ):
            return {}
        return payload

    @staticmethod
    def _scope_paths(records: Any) -> list[str]:
        paths: list[str] = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            paths.extend(
                str(record[key]) for key in ("path", "from", "to") if record.get(key)
            )
        return paths


class _MutationScanState:
    """Provide bounded Git and non-Git file discovery for capture."""

    @staticmethod
    def _git_changed_records(project: Path) -> dict[Path, bytes]:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"],
            cwd=project,
            check=False,
            stdout=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise RuntimeError("cannot capture mutation baseline: git status failed")
        records: dict[Path, bytes] = {}
        items = [item for item in completed.stdout.split(b"\0") if item]
        index = 0
        while index < len(items):
            record = items[index]
            kind = record[:1]
            limit = {b"1": 8, b"2": 9, b"u": 10}.get(kind)
            relative = (
                record[2:]
                if kind == b"?"
                else record.split(b" ", limit)[limit]
                if limit is not None
                else b""
            )
            if relative:
                records[Path(os.fsdecode(relative))] = record
            if kind == b"2" and index + 1 < len(items):
                index += 1
                records[Path(os.fsdecode(items[index]))] = b"rename-source\0" + record
            index += 1
        return records

    @staticmethod
    def _local_paths(project: Path) -> set[Path]:
        return {
            path.relative_to(project)
            for path in project.rglob("*")
            if (path.is_file() or path.is_symlink())
            and not ({".tao", ".git"} & set(path.relative_to(project).parts))
        }

    @staticmethod
    def _path_key(path: str) -> str:
        return hashlib.sha256(path.encode("utf-8", errors="surrogateescape")).hexdigest()


class MutationCheckpointState(
    _MutationPathState,
    _MutationCaptureState,
    _MutationScopeState,
    _MutationStorageState,
    _MutationScanState,
):
    """Own mutation baselines and the scope they prove actually changed."""
