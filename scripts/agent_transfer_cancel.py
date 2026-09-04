"""Safely settle a source run whose work completed in a linked worktree."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_hook_runtime import finish_with_result
from agent_run_registry import cancel_run, registered_run
from agent_transfer_validate import git, validate_transfer


CANCEL_RECEIPT_NAME = "cancel.json"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

TRANSFERRED = "transferred_to_completed_linked_worktree"
NO_CHANGE = "no_change_required"

# A transfer names the run that finished the work instead. Nothing finished a
# no-change run, so it names no replacement; what it names instead is the two
# observations that make "nothing changed" checkable rather than asserted.
CANCEL_REASONS = frozenset({TRANSFERRED, NO_CHANGE})


def cancellation_receipt_failure(
    cancellation: dict,
    *,
    source_run_id: str | None = None,
    request_fingerprint: str | None = None,
) -> str | None:
    """Return why a transfer-cancellation receipt cannot be trusted."""

    if cancellation.get("schema_version") != 1:
        return "cancellation receipt schema_version must be 1"
    if cancellation.get("status") != "cancelled":
        return "cancellation receipt status must be cancelled"
    reason = cancellation.get("reason")
    if reason not in CANCEL_REASONS:
        return (
            "cancellation receipt reason is not a completed linked-worktree "
            "transfer or a proven no-change close"
        )

    required = ["source_run_id"]
    if reason == TRANSFERRED:
        required.append("replacement_run_id")
    for field in required:
        value = cancellation.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"cancellation receipt {field} must be a non-empty string"
    if reason == NO_CHANGE and cancellation.get("recorded_changed_scope") != 0:
        return (
            "cancellation receipt recorded_changed_scope must be 0 for a "
            "no-change close"
        )

    fingerprint = cancellation.get("request_fingerprint")
    if not isinstance(fingerprint, str) or SHA256_PATTERN.fullmatch(fingerprint) is None:
        return "cancellation receipt request_fingerprint must be a SHA-256 hex digest"

    created_at = cancellation.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        return "cancellation receipt created_at must be a timezone-aware timestamp"
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return "cancellation receipt created_at must be a parseable timestamp"
    if created.tzinfo is None or created.utcoffset() is None:
        return "cancellation receipt created_at must be timezone-aware"

    signature = cancellation.get("verified_worktree_signature")
    if not isinstance(signature, str) or SHA256_PATTERN.fullmatch(signature) is None:
        return (
            "cancellation receipt verified_worktree_signature must be a SHA-256 hex digest"
        )

    if source_run_id is not None and cancellation["source_run_id"] != source_run_id:
        return "cancellation receipt source_run_id does not match the bound source run"
    if (
        request_fingerprint is not None
        and cancellation["request_fingerprint"] != request_fingerprint
    ):
        return "cancellation receipt request_fingerprint does not match the bound source run"
    return None


def worktree_signature(project: Path) -> str | None:
    """Hash the checkout's Git status, or None when it cannot be read."""

    status = git(project, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return None
    return hashlib.sha256(status.stdout.encode("utf-8")).hexdigest()


def cancellation_worktree_drift(project: Path, cancellation: dict) -> str | None:
    """Report a checkout that no longer matches the cancellation's own record.

    A cancellation cannot be made simultaneous with the filesystem observation
    it rests on, so the pairing is recorded rather than guaranteed. This is the
    reader that makes the record worth writing: without it the signature was
    only a claim.
    """

    receipt_failure = cancellation_receipt_failure(cancellation)
    if receipt_failure is not None:
        return receipt_failure
    recorded = cancellation["verified_worktree_signature"]
    current = worktree_signature(project)
    if current is None:
        return "source checkout Git status could not be verified against the cancellation"
    if current != recorded:
        return "source checkout no longer matches the state the cancellation verified"
    return None


def restore_missing_receipt(args: Any, evidence: Path) -> int | None:
    """Rewrite a receipt the registry already describes, or return None.

    A crash or a full disk between settling the run and writing its receipt
    used to be unrecoverable: the run was terminal, so validation refused to
    run again, and the file explaining why never existed. The registry now
    carries the same record, which makes the file reproducible -- so a rerun
    against an already-cancelled run rewrites it instead of failing. Rewriting
    an identical file is harmless, which is what lets this run first and
    unconditionally.
    """

    run = registered_run(args.project, evidence)
    if run is None or run.get("state") != "cancelled":
        return None
    cancellation = run.get("cancellation")
    if not isinstance(cancellation, dict):
        return None
    receipt_failure = cancellation_receipt_failure(
        cancellation,
        source_run_id=str(run.get("run_id") or ""),
        request_fingerprint=str(run.get("request_fingerprint") or ""),
    )
    if receipt_failure is not None:
        return finish_with_result(
            "cancel",
            False,
            [
                "source run is settled as cancelled",
                receipt_failure,
                "repair the registry cancellation record before restoring its receipt",
            ],
            args.output,
            {"cancellation": cancellation},
            args.repair_cycle,
            invocation_error=True,
        )
    # The recorded signature exists to be checked, and until this read it was
    # written and never compared -- a claim of detectability with no detector.
    # A cancellation vouches for the checkout it saw, and the residual race it
    # cannot rule out is exactly a checkout that changed immediately after; the
    # rerun is where that shows up, so the mismatch is reported rather than
    # papered over by rewriting the receipt.
    drift = cancellation_worktree_drift(args.project, cancellation)
    if drift is not None:
        return finish_with_result(
            "cancel",
            False,
            [
                "source run is settled as cancelled",
                drift,
                "reconcile the checkout against the recorded cancellation before continuing",
            ],
            args.output,
            {"cancellation": cancellation},
            args.repair_cycle,
            invocation_error=True,
        )
    receipt_path = evidence.parent / CANCEL_RECEIPT_NAME
    try:
        atomic_write_json(receipt_path, cancellation)
    except OSError as error:
        return finish_with_result(
            "cancel",
            False,
            [f"cancellation receipt could not be written: {type(error).__name__}"],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    return finish_with_result(
        "cancel",
        True,
        [
            "source run was already settled as cancelled",
            "cancellation receipt restored from the registry record",
        ],
        args.output,
        {"cancellation": cancellation},
        args.repair_cycle,
    )


def cancel_transferred_run(args: Any) -> int:
    """Cancel only after a completed same-request linked-worktree run is proven."""

    evidence = args.evidence
    replacement = args.replacement_evidence
    restored = restore_missing_receipt(args, evidence)
    if restored is not None:
        return restored
    failures, context = validate_transfer(args.project, args.rules, evidence, replacement)
    if failures:
        return finish_with_result(
            "cancel",
            False,
            failures,
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )

    source_run = context["source_run"]
    replacement_run = context["replacement_run"]
    receipt = {
        "schema_version": 1,
        "status": "cancelled",
        "reason": TRANSFERRED,
        "source_run_id": source_run["run_id"],
        "replacement_run_id": replacement_run["run_id"],
        "request_fingerprint": source_run["request_fingerprint"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return _settle_cancellation(
        args,
        evidence,
        receipt,
        [
            "source checkout is clean",
            "replacement is a completed linked-worktree run for the same request and session",
            "source run settled as cancelled; existing evidence was preserved",
        ],
    )


def cancel_no_change_run(args: Any) -> int:
    """Settle a run whose outcome is that nothing needed changing.

    An investigation can be finished and correct and still produce no diff --
    the reported defect was a deliberate guard, the measurement did not support
    the change. Until now such a run could not be closed: the review hook
    refuses every scope with "no changed paths", and the transfer cancellation
    above needs a replacement run that finished the work, which is exactly what
    does not exist here. The run was left unfinished, which is its own hazard.

    "Nothing changed" is proven here, not asserted, by two observations that
    already exist: the checkout is clean, and the run's own continuation packet
    records no changed scope. The second is what covers a run that changed files
    and committed them, which the first would not catch.

    The residual limit is stated rather than hidden: a file written outside the
    governed path leaves no record in either place. Preventing that is the
    pretool gate's job, not this one's.
    """

    evidence = args.evidence
    restored = restore_missing_receipt(args, evidence)
    if restored is not None:
        return restored
    run = registered_run(args.project, evidence)
    if run is None:
        return finish_with_result(
            "cancel",
            False,
            ["no registered run is bound to this evidence path"],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    changed = recorded_changed_scope(args.project, str(run.get("run_id") or ""))
    if changed:
        return finish_with_result(
            "cancel",
            False,
            [
                f"this run recorded {changed} changed path(s), so it is not a "
                "no-change run",
                "complete the review hook and finish instead of cancelling",
            ],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    receipt = {
        "schema_version": 1,
        "status": "cancelled",
        "reason": NO_CHANGE,
        "source_run_id": run["run_id"],
        "request_fingerprint": run.get("request_fingerprint") or "",
        "recorded_changed_scope": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return _settle_cancellation(
        args,
        evidence,
        receipt,
        [
            "source checkout is clean",
            "the run's continuation packet records no changed scope",
            "run settled as cancelled with no change; existing evidence was preserved",
        ],
    )


def recorded_changed_scope(project: Path, run_id: str) -> int:
    """How many paths this run recorded changing, as its own packet reports it.

    A run with no readable packet recorded nothing, which is the same answer a
    packet with an empty changed scope gives. Both are only half the proof; the
    clean-checkout precondition is the other half.
    """

    if not run_id:
        return 0
    from agent_continuation_store import continuation_path, read_continuation_packet

    result = read_continuation_packet(project, continuation_path(project, run_id))
    if result["status"] != "ok":
        return 0
    work = (result["packet"] or {}).get("work") or {}
    scope = work.get("changed_scope")
    return len(scope) if isinstance(scope, list) else 0


def _settle_cancellation(
    args: Any, evidence: Path, receipt: dict, details: list[str]
) -> int:
    """Take the clean-checkout observation and the transition in one transaction."""

    receipt_path = evidence.parent / CANCEL_RECEIPT_NAME
    # The clean-checkout test is only true at the instant it runs, and no
    # placement makes it simultaneous with the write. Running it as a
    # precondition inside the registry lock is what keeps the check and the
    # settlement in one transaction; the observation it made is recorded on the
    # receipt so a later reader can compare it against the checkout instead of
    # taking the cancellation's word for it.
    def source_checkout_is_still_clean() -> str | None:
        status = git(args.project, "status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode != 0:
            return "source checkout Git status could not be verified"
        if status.stdout.strip():
            return "source checkout changed after validation"
        receipt["verified_worktree_signature"] = hashlib.sha256(
            status.stdout.encode("utf-8")
        ).hexdigest()
        return None

    transitioned = cancel_run(
        args.project,
        evidence,
        run_id=str(receipt["source_run_id"]),
        precondition=source_checkout_is_still_clean,
        cancellation=receipt,
    )
    if transitioned is None:
        return finish_with_result(
            "cancel",
            False,
            [
                "source run changed or the checkout stopped being clean before the "
                "cancellation transition; rerun the cancellation"
            ],
            args.output,
            {},
            args.repair_cycle,
            invocation_error=True,
        )
    # The registry already carries this record, written in the same transaction
    # as the state, so the file is a convenience copy. Losing it to a crash no
    # longer loses the outcome, and rewriting it is idempotent -- which is why a
    # failure here is reported as a result rather than raised: the cancellation
    # succeeded, only its copy did not, and rerunning restores it.
    try:
        atomic_write_json(receipt_path, receipt)
    except OSError as error:
        return finish_with_result(
            "cancel",
            False,
            [
                "source run was settled as cancelled and the registry holds its record",
                f"cancellation receipt could not be written: {type(error).__name__}",
                "rerun the cancellation to restore the receipt from the registry",
            ],
            args.output,
            {"cancellation": receipt},
            args.repair_cycle,
            invocation_error=True,
        )
    return finish_with_result(
        "cancel", True, details, args.output, {"cancellation": receipt}, args.repair_cycle
    )
