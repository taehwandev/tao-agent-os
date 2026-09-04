"""Strong drift verification between a continuation packet and current bytes.

A packet is a set of conclusions, and every one of them was reached against
specific bytes. Resuming onto different bytes reuses reasoning whose premises
have changed, which is worse than starting over because it looks like progress.
So this module answers one question -- are these still the bytes the packet was
written against -- and answers it by content, never by cache metadata.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    contained_doc_path,
    doc_hash_record,
    git_states_for_paths,
)


def required_docs_digest(records: Any) -> str:
    """Hash the ordered required-document trust record.

    This digest is only an invalidation cache. The content-free trust record
    keeps the authoritative path/hash/size entries, so a weaker fingerprint here
    would silently become the thing that decides whether guidance moved.
    """

    ordered = [
        {
            "path": str(record.get("path") or ""),
            "size_bytes": int(record.get("size_bytes") or 0),
            "sha256": str(record.get("sha256") or ""),
        }
        for record in records or []
        if isinstance(record, dict)
    ]
    payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_drift_state(
    project: Path,
    rules: Path,
    required_docs_sha256: str,
    *,
    git_states: tuple[dict[str, str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Capture the strong project/rules state a checkpoint is written against.

    No previously recorded state is offered to ``git_states_for_paths``: reusing
    a record on a matching cheap signature is what makes identity depend on
    metadata, and a file rewritten with identical bytes must not read as drift.

    ``git_states`` lets a caller comparing many packets against one checkout
    capture that state once. Only the required-document digest differs per
    packet; the project and rules fingerprints are a property of the checkout,
    and recomputing them per packet was 56% of a listing's time. A caller
    passing them takes responsibility for their freshness, which is why the
    default still captures.
    """

    project_state, rules_state = git_states or git_states_for_paths(project, rules)
    return {
        "project": project_state,
        "rules": rules_state,
        "required_docs_sha256": required_docs_sha256,
    }


def verify_drift(
    project: Path,
    rules: Path,
    packet: dict[str, Any],
    *,
    required_doc_records: Any = (),
    git_states: tuple[dict[str, str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compare the packet's recorded state with current bytes.

    Reports only the changed signal and repo-relative affected paths. Worktree
    identity is a single content fingerprint, so a worktree signal names no
    paths rather than inventing them; the required-document snapshot does hold
    per-path hashes, so its affected paths are exact.

    The signals are `head`, `project_worktree`, `rules_worktree`,
    `required_docs` and `pending_mutation`, appended as literals below. That
    list used to also exist as a module constant, which nothing read: two places
    named the same vocabulary and only one of them was true, so a reader who
    trusted the constant could be reading a name this function no longer emits.
    Stated here instead, next to the appends, where the two cannot disagree.
    """

    recorded = packet.get("drift") or {}
    current = capture_drift_state(
        project,
        rules,
        str(recorded.get("required_docs_sha256") or ""),
        git_states=git_states,
    )
    signals: list[str] = []
    if _state_field(recorded, "project", "head") != _state_field(current, "project", "head"):
        signals.append("head")
    if _fingerprint(recorded, "project") != _fingerprint(current, "project"):
        signals.append("project_worktree")
    if (recorded.get("rules") or {}) != (current.get("rules") or {}):
        signals.append("rules_worktree")
    affected = _required_doc_drift(rules, recorded, required_doc_records)
    if affected is not None:
        signals.append("required_docs")
    pending_changed = _pending_changed(packet, current)
    if pending_changed:
        signals.append("pending_mutation")
    return _verdict(packet, signals, affected or [], pending_changed)


def _verdict(
    packet: dict[str, Any],
    signals: list[str],
    affected: list[str],
    pending_changed: bool,
) -> dict[str, Any]:
    pending = (packet.get("checkpoint") or {}).get("mutation_pending")
    if pending is None:
        pending_state = None
    else:
        pending_state = "pending_changed" if pending_changed or signals else "pending_clean"
    if signals:
        return {
            "status": "drift_refused",
            "phase": "reconcile_required",
            "changed_signals": signals,
            "affected_paths": affected,
            "pending_state": pending_state,
        }
    return {
        "status": "clean",
        "phase": packet.get("phase"),
        "changed_signals": [],
        "affected_paths": [],
        "pending_state": pending_state,
    }


def _state_field(state: dict[str, Any], root: str, field: str) -> str:
    return str((state.get(root) or {}).get(field) or "")


def _fingerprint(state: dict[str, Any], root: str) -> str:
    return _state_field(state, root, "worktree_fingerprint")


def _pending_changed(packet: dict[str, Any], current: dict[str, Any]) -> bool:
    """Report whether bytes moved since a pre-mutation checkpoint was written.

    An interrupted tool that never wrote bytes leaves the pre-mutation state
    intact and the same checkpoint can simply be restarted. Once bytes changed
    without the matching post-mutation rewrite, the packet's summary no longer
    describes the worktree and only reconciliation is honest.
    """

    pending = (packet.get("checkpoint") or {}).get("mutation_pending")
    if not isinstance(pending, dict):
        return False
    return (
        (pending.get("project") or {}) != (current.get("project") or {})
        or (pending.get("rules") or {}) != (current.get("rules") or {})
    )


def _required_doc_drift(
    rules: Path,
    recorded: dict[str, Any],
    required_doc_records: Any,
) -> list[str] | None:
    """Return the changed required-doc paths, or ``None`` when nothing moved."""

    records = [record for record in required_doc_records or [] if isinstance(record, dict)]
    if required_docs_digest(records) != str(recorded.get("required_docs_sha256") or ""):
        # The packet is not bound to the trust record it was handed, so the
        # per-path comparison below would be measuring the wrong snapshot.
        return []
    changed: list[str] = []
    for record in records:
        relative = str(record.get("path") or "")
        try:
            current = doc_hash_record(relative, contained_doc_path(rules.resolve(), relative))
        except (OSError, ValueError):
            changed.append(relative)
            continue
        if current.get("sha256") != record.get("sha256"):
            changed.append(relative)
    return sorted(changed) or None
