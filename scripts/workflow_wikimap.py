"""Pinned Wikimap adapter for Tao Agent OS document discovery.

Only deterministic indexing and read-only search are exposed here. Graphify,
hook installation, migration, semantic notes, and source edits stay outside
this boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence
from support.project_tree import PRUNED_DIRECTORIES, iter_project_files
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
# These sets mirror the pinned vendor's ``INDEX_EXTS``, ``IGNORE_DIRS`` and
# generated ``MAP.md`` exclusion. They are part of the adapter's versioned
# contract: changing the pinned source already requires updating its checksum,
# and a changed parser input boundary must update these sets at the same time.
_WIKIMAP_INDEX_EXTENSIONS = frozenset(
    ".adoc .gif .htm .html .jpeg .jpg .md .org .pdf .png .rst .svg .txt .webp".split()
)
_WIKIMAP_BUILTIN_IGNORED_DIRECTORIES = frozenset(
    ".claude .github .obsidian .trash __pycache__ .venv graphify-out node_modules venv".split()
)

# What the signature walks has to match what the index can read: the same CLI
# ignores the update is given, the vendor's built-in directory ignores, and
# `.git`/`.wikimap`, whose own churn is not a corpus change. The walk may still
# encounter other files, but `_corpus_signature` hashes only indexable types.
# Before that suffix check existed, editing Python or merely creating a `.pyc`
# invalidated the receipt and paid for an unnecessary update subprocess.
_PRUNED_FOR_INDEX = frozenset(
    {
        *PRUNED_DIRECTORIES,
        *_WIKIMAP_BUILTIN_IGNORED_DIRECTORIES,
        *WIKIMAP_IGNORES,
        ".wikimap",
    }
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
    """Refresh the index unless nothing it reads has changed.

    Wikimap's own update is incremental, but reaching that conclusion costs a
    Python start and a walk in a second process -- 90 ms of a 921 ms `start` on
    the reference machine, and near 290 ms on a cold one. Every hook is its own
    process, so the in-process cache above never saved the next one anything.

    The corpus signature is the same shape the document-graph cache uses: size
    and modification time per file, which is cheap next to reading them. It
    also covers the pinned tool and the ignore list, because a graph built by
    other code is not the graph this one would build.

    Every failure path ends in the refresh running: an unreadable signature, an
    unwritable receipt, a missing index. The cost of a needless refresh is the
    90 ms this avoids; the cost of a wrongly skipped one is a search that
    cannot see a document that exists.
    """

    root = Path(root_text)
    # The stage covers the decision as well as the refresh, and is recorded
    # even when nothing runs. A skipped refresh that reported no stage at all
    # would read as one that was never attempted, and the point of these
    # numbers is to say which half of a search to look at.
    with stage("wikimap_index"):
        signature = _corpus_signature(root)
        if signature and _index_receipt(root) == signature:
            return ""
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
        _completed, error = _run(command, root)
        if not error and signature:
            _record_index_receipt(root, signature)
        return error


def _receipt_path(root: Path) -> Path | None:
    """The run-state cache, only where run state already exists.

    `.tao` carries its own ignore file, so writing under it stays out of the
    repository, and a project that has never run a hook has no `.tao` to write
    into.
    """

    state = root / ".tao"
    return state / "cache" / "wikimap-index.json" if state.is_dir() else None


def _corpus_signature(root: Path) -> str:
    """Digest every input the index is built from, or "" when it cannot be."""

    digest = hashlib.sha256()
    digest.update(WIKIMAP_SHA256.encode("utf-8"))
    for ignored in WIKIMAP_IGNORES:
        digest.update(f"\0ignore:{ignored}".encode("utf-8"))
    # Deleting the index is how a person asks for a rebuild, so its absence
    # ends the signature and the refresh runs. Its size and time are
    # deliberately not in the digest: the refresh writes that file, so a
    # signature describing it would never match the state it just recorded, and
    # the receipt would invalidate itself on the way out.
    if not (root / ".wikimap" / "index.db").exists():
        return ""
    try:
        ignore_control = root / ".wikimapignore"
        if ignore_control.exists():
            stat = ignore_control.stat()
            digest.update(
                f"\0.wikimapignore:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
            )
        else:
            digest.update(b"\0.wikimapignore:absent")
        for path in sorted(iter_project_files(root, pruned=_PRUNED_FOR_INDEX)):
            if (
                path.name == "MAP.md"
                or path.suffix.lower() not in _WIKIMAP_INDEX_EXTENSIONS
            ):
                continue
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
            digest.update(f"\0{relative}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
    except (OSError, ValueError):
        return ""
    return digest.hexdigest()


def _index_receipt(root: Path) -> str:
    path = _receipt_path(root)
    if path is None:
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    recorded = payload.get("corpus_signature")
    return recorded if isinstance(recorded, str) else ""


def _record_index_receipt(root: Path, signature: str) -> None:
    path = _receipt_path(root)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"corpus_signature": signature}, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        # A receipt that cannot be written costs the next hook a refresh, which
        # is the outcome this exists to make rarer, not a failure.
        return


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
