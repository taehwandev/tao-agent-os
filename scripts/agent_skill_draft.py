"""Observation-time skill patch drafts.

The observation, curation, review, staging, and maintenance records are
content-free by contract, so a later reviewer sees only `skill_id`, `signal`,
and counts. That is enough to prove recurrence and nothing else: it cannot say
which rule was missing, in what situation, or what the run did instead. Every
review therefore had to reinvent the rule from slugs, which is why staged
proposals terminated as `no_change` or `rejected` and no canonical skill was
ever updated.

This module adds the one artifact that carries that reasoning, written by the
run that actually observed the gap and still holds the context. It is a
deliberately separate store, not a new field on the observation, so the
content-free guarantee of the lifecycle records survives unchanged.

A draft is a proposal only. It grants no authority: the canonical write still
has to traverse curation, bounded review, staging, structural target linkage,
and a live verification receipt.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_skill_catalog import normalize_feedback_signal, normalize_skill_id
from agent_skill_state import (
    CANDIDATE_ID_RE,
    SCHEMA_VERSION,
    candidate_id as derive_candidate_id,
    json_count,
    now,
    opaque_key,
    read_json,
)
from agent_state_lock import state_lock


# Kept at the staged-item cap so the draft store cannot outgrow the pipeline
# it feeds.
MAX_DRAFTS = 100
# A draft is a bounded rationale, not a place to paste a transcript, diff, or
# log. The limit is what a reviewer can actually read in one bounded review.
MAX_PROPOSAL_CHARS = 4000
MIN_PROPOSAL_CHARS = 40

# This store intentionally holds prose, so it must never be mistaken for a
# content-free lifecycle record by a reader that only checks for the marker.
DRAFT_PRIVACY = "local_draft_contains_task_prose"


def draft_dir() -> Path:
    return Path("skill-learning") / "drafts"


def draft_path(candidate: str) -> Path:
    return draft_dir() / f"{candidate}.json"


def draft_lock_path(candidate: str) -> Path:
    return Path("skill-learning") / "locks" / f"draft-{candidate}.json"


def normalize_proposal(value: str) -> str:
    """Return a bounded single-artifact rationale, or "" when unusable."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if any(character in text for character in ("\x00",)):
        return ""
    # Control characters other than tab and newline indicate a pasted binary or
    # terminal capture rather than authored rationale.
    if any(ord(character) < 32 and character not in "\t\n" for character in text):
        return ""
    if not MIN_PROPOSAL_CHARS <= len(text) <= MAX_PROPOSAL_CHARS:
        return ""
    return text


def proposal_sha256(proposal: str) -> str:
    return hashlib.sha256(proposal.encode("utf-8")).hexdigest()


def read_draft(root: Path, candidate: str) -> dict[str, Any]:
    return read_json(root / draft_path(candidate))


def valid_draft(payload: dict[str, Any], candidate: str) -> bool:
    proposal = str(payload.get("proposal") or "")
    return bool(
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("candidate_id") == candidate
        and payload.get("status") == "draft"
        and payload.get("privacy") == DRAFT_PRIVACY
        and normalize_proposal(proposal) == proposal
        and payload.get("proposal_sha256") == proposal_sha256(proposal)
    )


def draft_binding(root: Path, candidate: str) -> dict[str, str]:
    """Return the staged-record binding for a usable draft, or {} when absent.

    Recording the digest at staging time is what lets maintenance prove the
    change it applied corresponds to the proposal that was reviewed, instead of
    to a draft rewritten afterwards.
    """

    payload = read_draft(root, candidate)
    if not valid_draft(payload, candidate):
        return {}
    return {
        "draft_id": str(payload.get("draft_id") or ""),
        "draft_sha256": str(payload.get("proposal_sha256") or ""),
    }


def record_draft(
    root: Path,
    *,
    project: Path,
    rules: Path,
    skill_id: str,
    signal: str,
    proposal: str,
    occurrence_id: str,
) -> dict[str, Any]:
    """Store or revise the draft for one `skill_id + signal` candidate.

    Validation mirrors the observation writer so a draft cannot exist for a
    skill or signal the lifecycle would refuse; otherwise the draft store would
    become a way to smuggle an unbound proposal into review.
    """

    # Imported here because the catalog walks the project tree, and callers
    # that only read drafts should not pay for that.
    from agent_skill_catalog import canonical_skill_ids

    normalized_skill = normalize_skill_id(skill_id)
    if not normalized_skill or normalized_skill not in canonical_skill_ids(project, rules):
        return {"created": False, "reason": "unknown_canonical_skill"}
    normalized_signal = normalize_feedback_signal(signal)
    if not normalized_signal:
        return {"created": False, "reason": "unknown_feedback_signal"}
    normalized_proposal = normalize_proposal(proposal)
    if not normalized_proposal:
        return {"created": False, "reason": "unusable_proposal"}
    occurrence_key = opaque_key(occurrence_id)
    if not CANDIDATE_ID_RE.fullmatch(occurrence_key):
        return {"created": False, "reason": "missing_occurrence"}

    candidate = derive_candidate_id(normalized_skill, normalized_signal)
    destination = root / draft_path(candidate)
    with state_lock(root / draft_lock_path(candidate)):
        existing = read_json(destination)
        revising = valid_draft(existing, candidate)
        if not revising and json_count(root / draft_dir()) >= MAX_DRAFTS:
            return {"created": False, "reason": "draft_store_full"}
        if revising and existing.get("proposal") == normalized_proposal:
            return {
                "created": False,
                "idempotent": True,
                "candidate_id": candidate,
                "draft_id": str(existing.get("draft_id") or ""),
                "status": "draft",
            }
        occurrences = _merged_occurrences(existing if revising else {}, occurrence_key)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate,
            "draft_id": opaque_key(f"{candidate}:{normalized_proposal}"),
            "skill_id": normalized_skill,
            "signal": normalized_signal,
            "status": "draft",
            "privacy": DRAFT_PRIVACY,
            "proposal": normalized_proposal,
            "proposal_sha256": proposal_sha256(normalized_proposal),
            "occurrence_keys": occurrences,
            "revisions": int(existing.get("revisions") or 0) + 1 if revising else 1,
            "created_at": str(existing.get("created_at") or now()) if revising else now(),
            "updated_at": now(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(destination, payload)
    return {
        "created": True,
        "revised": revising,
        "candidate_id": candidate,
        "draft_id": payload["draft_id"],
        "status": "draft",
        "revisions": payload["revisions"],
    }


def _merged_occurrences(existing: dict[str, Any], occurrence_key: str) -> list[str]:
    prior = existing.get("occurrence_keys")
    keys = [
        item
        for item in (prior if isinstance(prior, list) else [])
        if isinstance(item, str) and CANDIDATE_ID_RE.fullmatch(item)
    ]
    if occurrence_key not in keys:
        keys.append(occurrence_key)
    return sorted(set(keys))
