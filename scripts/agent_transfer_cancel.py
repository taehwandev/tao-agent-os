"""Safely settle a source run whose work completed in a linked worktree."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_hook_runtime import finish_with_result
from agent_run_registry import (
    TRANSFER_CANCELLABLE_RUN_STATES,
    cancel_run,
    ledger_writable_run_claim_is_owned,
    registered_run,
)


CANCEL_RECEIPT_NAME = "cancel.json"


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

    recorded = cancellation.get("verified_worktree_signature")
    if not isinstance(recorded, str) or not recorded:
        return None
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
        "reason": "transferred_to_completed_linked_worktree",
        "source_run_id": source_run["run_id"],
        "replacement_run_id": replacement_run["run_id"],
        "request_fingerprint": source_run["request_fingerprint"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
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
        run_id=str(source_run["run_id"]),
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
        "cancel",
        True,
        [
            "source checkout is clean",
            "replacement is a completed linked-worktree run for the same request and session",
            "source run settled as cancelled; existing evidence was preserved",
        ],
        args.output,
        {"cancellation": receipt},
        args.repair_cycle,
    )


def validate_transfer(
    source_project: Path,
    rules: Path,
    source_evidence: Path | None,
    replacement_evidence: Path | None,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    if source_evidence is None or replacement_evidence is None:
        return ["cancel requires --evidence and --replacement-evidence"], {}
    source_payload = read_preflight(source_evidence, "source", failures)
    replacement_payload = read_preflight(replacement_evidence, "replacement", failures)
    if failures:
        return failures, {}

    source_payload_project = payload_project(source_payload, "source", failures)
    replacement_project = payload_project(replacement_payload, "replacement", failures)
    if source_payload_project is None or replacement_project is None:
        return failures, {}
    if source_payload_project != source_project.resolve():
        failures.append("source evidence does not belong to --project")
    source_rules = payload_path(source_payload, "rules", "source", failures)
    replacement_rules = payload_path(
        replacement_payload, "rules", "replacement", failures
    )
    if source_rules != rules.resolve():
        failures.append("source evidence does not use --rules")
    if replacement_rules != rules.resolve():
        failures.append("replacement evidence does not use the same rules root")
    if source_evidence.resolve() == replacement_evidence.resolve():
        failures.append("replacement evidence must name a different run")
    if not (source_project / ".git").is_dir():
        failures.append("source project must be the repository's main checkout")
    if not (replacement_project / ".git").is_file():
        failures.append("replacement project must be a linked Git worktree")
    source_common_dir = git_common_dir(source_project)
    replacement_common_dir = git_common_dir(replacement_project)
    if (
        source_common_dir is None
        or replacement_common_dir is None
        or source_common_dir != replacement_common_dir
    ):
        failures.append("source and replacement must share one Git common directory")
    status = git(source_project, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        failures.append("source checkout Git status could not be verified")
    elif status.stdout.strip():
        failures.append("source checkout has tracked or untracked changes")

    source_run = registered_run(
        source_project,
        source_evidence,
        run_id=str(source_payload.get("agent_run_id") or ""),
    )
    replacement_run = registered_run(
        replacement_project,
        replacement_evidence,
        run_id=str(replacement_payload.get("agent_run_id") or ""),
    )
    if source_run is None:
        failures.append("source run is not registered for its evidence")
    elif source_run.get("state") not in TRANSFER_CANCELLABLE_RUN_STATES:
        failures.append("source run is already terminal or not cancellable")
    elif not ledger_writable_run_claim_is_owned(
        source_project,
        source_evidence,
        str(source_run.get("run_id") or ""),
    ):
        failures.append("source run is not owned by the current runtime session")
    if replacement_run is None:
        failures.append("replacement run is not registered for its evidence")
    elif replacement_run.get("state") != "completed":
        failures.append("replacement run has not completed successfully")
    if source_run and replacement_run:
        if not source_run.get("request_fingerprint"):
            failures.append("source request fingerprint is missing")
        if source_run.get("request_fingerprint") != replacement_run.get("request_fingerprint"):
            failures.append("source and replacement requests do not match")
        if source_run.get("command") != replacement_run.get("command"):
            failures.append("source and replacement workflow routes do not match")
    source_session = source_payload.get("runtime_session")
    replacement_session = replacement_payload.get("runtime_session")
    if not isinstance(source_session, dict) or not source_session.get("session_id"):
        failures.append("source runtime session is missing")
    elif source_session != replacement_session:
        failures.append("source and replacement runtime sessions do not match")
    return failures, {
        "source_run": source_run,
        "replacement_run": replacement_run,
    }


def read_preflight(path: Path, label: str, failures: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append(f"{label} evidence is missing or malformed")
        return {}
    if not isinstance(payload, dict) or not payload.get("agent_run_id"):
        failures.append(f"{label} evidence is not a registered run preflight")
        return {}
    return payload


def payload_project(
    payload: dict[str, Any],
    label: str,
    failures: list[str],
) -> Path | None:
    raw = payload.get("project")
    if not isinstance(raw, str) or not raw:
        failures.append(f"{label} evidence has no project")
        return None
    project = Path(raw).resolve()
    if not project.is_dir():
        failures.append(f"{label} project does not exist")
        return None
    return project


def payload_path(
    payload: dict[str, Any],
    field: str,
    label: str,
    failures: list[str],
) -> Path | None:
    raw = payload.get(field)
    if not isinstance(raw, str) or not raw:
        failures.append(f"{label} evidence has no {field}")
        return None
    return Path(raw).resolve()


def git_common_dir(project: Path) -> Path | None:
    result = git(project, "rev-parse", "--git-common-dir")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = Path(result.stdout.strip())
    return (project / common).resolve() if not common.is_absolute() else common.resolve()


def git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(project), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess([], 1, "", "")
