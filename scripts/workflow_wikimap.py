"""Pinned Wikimap adapter for Tao Agent OS document discovery.

Only deterministic indexing and read-only search are exposed here. Graphify,
hook installation, migration, semantic notes, and source edits stay outside
this boundary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence
from support.stage_timing import stage


WIKIMAP_VERSION = "1.0.0"
WIKIMAP_COMMIT = "9c26d7b66322741532ede0b474f0e5106643f275"
WIKIMAP_SHA256 = "1e81848539ad959d90c15441b08cc95073619331afe4562f3960808f755970e9"
WIKIMAP_SCRIPT = Path(__file__).resolve().parent / "third_party" / "wikimap" / "wikimap.py"
WIKIMAP_TIMEOUT_SECONDS = 15
WIKIMAP_IGNORES = (
    ".tao",
    ".agents/skills/graphify",
    ".claude/skills/graphify",
    ".codex/skills/graphify",
    "graphify-out",
    "scripts/.tao",
    "scripts/third_party",
)


@dataclass(frozen=True)
class WikimapSearchResult:
    """Structured result of one pinned Wikimap query."""

    results: list[dict[str, object]]
    weak: bool = False
    partial: bool = False
    fused: bool = False
    error: str = ""

    @property
    def available(self) -> bool:
        return not self.error


def search_wikimap(root: Path, queries: Sequence[str], max_results: int) -> WikimapSearchResult:
    """Refresh the local index once per process and search it as JSON."""
    normalized_queries = [query.strip() for query in queries if query.strip()]
    if not normalized_queries or max_results <= 0:
        return WikimapSearchResult(results=[])

    root = root.resolve()
    error = _validate_vendor_source()
    if error:
        return WikimapSearchResult(results=[], error=error)

    error = _ensure_index(str(root))
    if error:
        return WikimapSearchResult(results=[], error=error)

    command = [
        sys.executable,
        str(WIKIMAP_SCRIPT),
        "--root",
        str(root),
        "search",
        "--json",
        "-n",
        str(max_results),
        *normalized_queries,
    ]
    # Reported apart from `wikimap_index`: refreshing the index and querying
    # it are two subprocesses with different reasons to be slow, and a single
    # number for the pair cannot say which one to look at.
    with stage("wikimap_search"):
        completed, error = _run(command, root)
    if error:
        return WikimapSearchResult(results=[], error=error)

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return WikimapSearchResult(results=[], error="wikimap returned invalid JSON")
    if not isinstance(payload, dict):
        return WikimapSearchResult(results=[], error="wikimap returned an invalid result object")

    return WikimapSearchResult(
        results=_safe_results(root, payload.get("results")),
        weak=bool(payload.get("weak")),
        partial=bool(payload.get("partial")),
        fused=bool(payload.get("fused")),
    )


def clear_wikimap_cache() -> None:
    """Force the next search to refresh its index, primarily for tests."""
    _ensure_index.cache_clear()


@lru_cache(maxsize=8)
def _ensure_index(root_text: str) -> str:
    root = Path(root_text)
    command = [
        sys.executable,
        str(WIKIMAP_SCRIPT),
        "--root",
        str(root),
        "update",
        "--no-map",
    ]
    for ignored in WIKIMAP_IGNORES:
        command.extend(("--ignore", ignored))
    with stage("wikimap_index"):
        _completed, error = _run(command, root)
    return error


def _validate_vendor_source() -> str:
    try:
        digest = hashlib.sha256(WIKIMAP_SCRIPT.read_bytes()).hexdigest()
    except OSError:
        return "pinned wikimap source is unavailable"
    if digest != WIKIMAP_SHA256:
        return "pinned wikimap source checksum does not match"
    return ""


def _run(command: list[str], root: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=WIKIMAP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _empty_process(command), "wikimap process could not complete"
    if completed.returncode != 0:
        return completed, f"wikimap exited with status {completed.returncode}"
    return completed, ""


def _empty_process(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="")


def _safe_results(root: Path, value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path or not _is_within_root(root, path):
            continue
        results.append(
            {
                "path": path,
                "line": int(item.get("line") or 0),
                "heading": str(item.get("heading") or ""),
                "score": float(item.get("score") or 0.0),
                "matched": [str(line) for line in item.get("matched", []) if isinstance(line, str)],
                "sources": str(item.get("sources") or ""),
            }
        )
    return results


def _is_within_root(root: Path, relative_path: str) -> bool:
    candidate = (root / relative_path).resolve()
    return candidate == root or root in candidate.parents


__all__ = [
    "WIKIMAP_COMMIT",
    "WIKIMAP_SCRIPT",
    "WIKIMAP_SHA256",
    "WIKIMAP_VERSION",
    "WikimapSearchResult",
    "clear_wikimap_cache",
    "search_wikimap",
]
