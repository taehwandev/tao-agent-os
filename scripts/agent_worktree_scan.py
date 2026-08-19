"""Bounded streaming primitives for execution-capsule worktree capture."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from support.bounded_git import stream_stall_guard


class WorktreeFingerprintLimitExceeded(RuntimeError):
    """Raised when a strong fingerprint would exceed its bounded scan budget."""


@dataclass
class UntrackedBudget:
    max_files: int
    max_bytes: int
    files: int = 0
    stated_bytes: int = 0
    read_bytes: int = 0

    def add_file(self, size: int) -> None:
        self.files += 1
        self.stated_bytes += max(size, 0)
        if self.files > self.max_files:
            raise WorktreeFingerprintLimitExceeded(
                f"untracked file count exceeds execution-capsule limit ({self.max_files})"
            )
        if self.stated_bytes > self.max_bytes:
            raise WorktreeFingerprintLimitExceeded(
                f"untracked byte size exceeds execution-capsule limit ({self.max_bytes})"
            )

    def add_read_bytes(self, size: int) -> None:
        self.read_bytes += size
        if self.read_bytes > self.max_bytes:
            raise WorktreeFingerprintLimitExceeded(
                f"untracked bytes read exceed execution-capsule limit ({self.max_bytes})"
            )


def hash_git_component(
    digest: Any,
    label: bytes,
    path: Path,
    *args: str,
) -> None:
    with subprocess.Popen(
        ["git", *args],
        cwd=path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process, stream_stall_guard(process, args):
        assert process.stdout is not None
        nested = hashlib.sha256()
        size = 0
        while chunk := process.stdout.read(1024 * 1024):
            nested.update(chunk)
            size += len(chunk)
        if process.wait() != 0:
            raise RuntimeError(
                f"cannot capture git state for execution capsule: git {args[0]} failed"
            )
    hash_stream_digest(digest, label, size, nested.digest())


def visit_git_null_records(
    path: Path,
    args: tuple[str, ...],
    visitor: Callable[[bytes], None],
) -> None:
    process = subprocess.Popen(
        ["git", *args],
        cwd=path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        with stream_stall_guard(process, args):
            assert process.stdout is not None
            buffer = b""
            while chunk := process.stdout.read(64 * 1024):
                buffer += chunk
                records = buffer.split(b"\0")
                buffer = records.pop()
                for record in records:
                    if record:
                        visitor(record)
            if buffer:
                visitor(buffer)
            if process.wait() != 0:
                raise RuntimeError(
                    f"cannot capture git state for execution capsule: git {args[0]} failed"
                )
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()


def hash_file_component(
    digest: Any,
    label: bytes,
    path: Path,
    budget: UntrackedBudget,
) -> None:
    nested = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            budget.add_read_bytes(len(chunk))
            nested.update(chunk)
            size += len(chunk)
    hash_stream_digest(digest, label, size, nested.digest())


def hash_stream_digest(
    digest: Any,
    label: bytes,
    size: int,
    content_digest: bytes,
) -> None:
    hash_component(digest, label + b"-size", str(size).encode("ascii"))
    hash_component(digest, label + b"-sha256", content_digest)


def hash_component(digest: Any, label: bytes, payload: bytes) -> None:
    digest.update(len(label).to_bytes(4, "big"))
    digest.update(label)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
