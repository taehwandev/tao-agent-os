"""Fail-closed guards for Tao-owned continuation outbound boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


CONTINUATION_STORAGE_CLASS = "project_local_never_sync"
OUTBOUND_BOUNDARIES = frozenset(
    {
        "artifact",
        "diagnostic",
        "execution_capsule",
        "export",
        "global_lesson",
        "ipc",
        "publish",
        "sync",
        "telemetry",
    }
)
_CONTINUATION_PATH = re.compile(
    r"(?:^|/)\.tao/runs/[0-9a-f]{32}/continuation\.json(?:$|[?#])"
)


class _ContinuationOutboundError(ValueError):
    """Raised without echoing content rejected at an outbound boundary."""


def _continuation_outbound_failures(value: Any) -> list[str]:
    """Return stable rule ids when a value identifies continuation content."""

    failures: set[str] = set()
    visited: set[int] = set()

    def inspect(candidate: Any) -> None:
        if isinstance(candidate, Path):
            inspect(candidate.as_posix())
            return
        if isinstance(candidate, str):
            if candidate == CONTINUATION_STORAGE_CLASS:
                failures.add("continuation_schema_marker")
            normalized = candidate.replace("\\", "/")
            if _CONTINUATION_PATH.search(normalized):
                failures.add("continuation_packet_path")
            return
        if isinstance(candidate, (bytes, bytearray, memoryview)):
            return
        if isinstance(candidate, Mapping):
            identity = id(candidate)
            if identity in visited:
                return
            visited.add(identity)
            for key, item in candidate.items():
                inspect(key)
                inspect(item)
            return
        if isinstance(candidate, (list, tuple, set, frozenset)):
            identity = id(candidate)
            if identity in visited:
                return
            visited.add(identity)
            for item in candidate:
                inspect(item)

    inspect(value)
    return sorted(failures)


def assert_no_continuation_outbound(value: Any, *, boundary: str) -> None:
    """Reject continuation markers and canonical packet paths before output."""

    if boundary not in OUTBOUND_BOUNDARIES:
        raise ValueError("unknown continuation outbound boundary")
    failures = _continuation_outbound_failures(value)
    if failures:
        rules = ",".join(failures)
        raise _ContinuationOutboundError(
            f"continuation outbound denied at {boundary}: {rules}"
        )
