"""Lifecycle wiring between the hook CLI and the continuation checkpoint writer.

The writer, the packet store and the resume transaction all landed before
anything called them, and a checkpoint no hook invokes writes nothing. This
module is the single place the live lifecycle reaches that writer, and it holds
one rule: a checkpoint is a side effect of a hook, never a precondition of one.
``_refresh_run_heartbeat`` already treats registry trouble that way, and a
packet is weaker evidence than a heartbeat -- a hook that fails because its
bookkeeping failed is strictly worse than a hook with no bookkeeping.

A packet lives beside the evidence it is bound to, at
``.tao/runs/<run-id>/continuation.json``. A run whose evidence is somewhere else
therefore has no reachable binding, and this module says so instead of writing a
packet bound to a record it cannot prove.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_fields import CHECKPOINT_RE, RUN_ID_RE
from agent_hook_gate_records import preflight_evidence_path


RUNS_DIR = "runs"
SKIPPED_DETAIL = (
    "continuation checkpoint: skipped; this run's evidence is not a "
    ".tao/runs/<run-id>/preflight.json path, so no packet is reachable"
)


def run_binding_path(args: argparse.Namespace) -> Path | None:
    """Return the run-local trust record a packet may bind to, or nothing.

    The binding must sit in the run's own directory: the writer resolves the
    gate ledger and route manifest from beside it, so a binding copied anywhere
    else would report every gate as unfinished while looking authoritative.
    """

    evidence = preflight_evidence_path(args).resolve()
    directory = evidence.parent
    if directory.parent != (args.project / ".tao" / RUNS_DIR).resolve():
        return None
    return evidence if RUN_ID_RE.match(directory.name) else None


def start_objective(args: argparse.Namespace) -> str:
    """Return a content-free initial label derived only from the route enum.

    ``--request`` is prompt content.  Copying, normalizing, summarizing, or
    truncating it here would still persist prompt bytes in the continuation
    packet before an agent had made a bounded semantic decision.  The initial
    packet therefore records only the selected route.  A later explicit
    ``checkpoint`` command may replace this label with a schema-bounded work
    summary supplied through stdin.
    """

    command = str(getattr(args, "command", "") or "task")
    return f"{command} workflow"


def gate_checkpoint_name(args: argparse.Namespace) -> str | None:
    """Name the gate a successful single-gate record just completed."""

    gate = str(getattr(args, "gate_name", "") or "")
    if getattr(args, "status", "") != "SUCCESS" or not CHECKPOINT_RE.match(gate):
        return None
    return gate if len(gate) <= 64 else None


def record_lifecycle_checkpoint(
    args: argparse.Namespace,
    kind: str,
    *,
    work: dict[str, Any] | None = None,
    phase: str | None = None,
    last_completed: str | None = None,
    mutation: dict[str, Any] | None = None,
    finalize_completed: bool = False,
) -> str:
    """Write one checkpoint for this lifecycle point and report what happened.

    Every checkpoint kind reaches the writer through here, including the
    ``pre_mutation`` and ``post_mutation`` pair a runtime adapter brackets its
    file-mutating tools with. That bracketing is the adapter's wiring, but the
    entry point it calls has to exist before the adapter can be written, and a
    ``pre_mutation`` call without its bounded path set is refused by the writer
    rather than recorded as an unbounded one.

    Every failure is caught, including ones no signature predicts. The writer
    reaches the registry, Git, the worktree and the filesystem, and any of them
    can fail for reasons unrelated to the hook that is running; letting one of
    those break a gate record would trade a lost packet for lost work.
    """

    binding_path = run_binding_path(args)
    if binding_path is None:
        return SKIPPED_DETAIL
    try:
        write_continuation_checkpoint(
            project=args.project,
            rules=args.rules,
            run_id=binding_path.parent.name,
            kind=kind,
            binding_path=binding_path,
            work=work,
            phase=phase,
            last_completed=last_completed,
            mutation=mutation,
            finalize_completed=finalize_completed,
        )
    except Exception as error:  # noqa: BLE001 - a packet must never block a hook
        return f"continuation checkpoint: unavailable ({error}); lifecycle continues"
    return f"continuation checkpoint: {kind} recorded"


def checkpoint_after_hook(
    args: argparse.Namespace,
    code: int,
    kind: str,
    **keywords: Any,
) -> int:
    """Checkpoint a completed lifecycle hook without changing its outcome.

    The hook has already printed its own result, so the checkpoint reports on
    its own line and returns the exit status untouched. A failed hook is still
    a lifecycle transition worth recording: a recorded gate failure is exactly
    the checkpoint a resumed session must come back to. What it did not do is
    complete anything, so a failed hook never names a completed checkpoint.
    """

    if code != 0:
        keywords.pop("last_completed", None)
    print(f"- {record_lifecycle_checkpoint(args, kind, **keywords)}")
    return code
