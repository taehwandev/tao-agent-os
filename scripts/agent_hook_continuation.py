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
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_continuation_fields import CHECKPOINT_RE, RUN_ID_RE
from agent_hook_gate_records import preflight_evidence_path


RUNS_DIR = "runs"
SKIPPED_DETAIL = (
    "continuation checkpoint: skipped; a packet binds to a run directory named "
    "by an opaque 32-character hex run id, and this run's evidence is not in "
    "one, so nothing can resume this run"
)
UNBINDABLE_RUN_DIRECTORY = (
    "start --evidence names a run directory whose name is not an opaque "
    "32-character hex run id. A continuation packet binds to that name, so this "
    "run would record no checkpoint and `tao-hook resume` could never continue "
    "it -- silently, for the whole lifecycle. Omit --evidence and start mints an "
    "opaque run directory for you, or name one yourself with "
    "`python3 -c \'import uuid; print(uuid.uuid4().hex)\'`."
)



WORK_CHECKPOINT_LEAD = (
    "continuation work state: the initial packet holds only the route name. "
    "`tao-hook checkpoint --work-stdin` reads one work object on stdin and is "
    "what fills it -- without it a resume recovers the route and the drift "
    "state but nothing about the work, and the reuse summary it is handed "
    "reports no accepted decision and no successful verification to skip."
)
WORK_CHECKPOINT_CLOSING = (
    "  every key of an object must be present, null when unknown; record one "
    "after reading the required docs and scoping the task, and refresh it at "
    "each material decision"
)


def _work_shape_line() -> str:
    """Spell the work object out of the schema, so the two cannot drift.

    Naming the fields was not enough to record one: the first attempt failed
    on object shape, and the shapes are enums and closed key sets that live in
    the packet validator. Reading them from there means a new role or
    verification kind reaches this advice without anyone remembering to.
    """

    from agent_continuation_packet import (
        DECISION_STATUSES,
        SCOPE_ROLES,
        VERIFICATION_KINDS,
        VERIFICATION_RESULTS,
    )

    return (
        "  work shape -- objective, non_goals, blockers: text; "
        "decisions: {id, status: "
        + "|".join(DECISION_STATUSES)
        + ", text}; changed_scope, inspected_scope: {path, role: "
        + "|".join(SCOPE_ROLES)
        + "} (a renamed entry carries {from, to, role} instead); "
        "verification: {id, kind: "
        + "|".join(VERIFICATION_KINDS)
        + ", result: "
        + "|".join(VERIFICATION_RESULTS)
        + ", evidence_sha256, completed_at}; "
        "remaining_work: {checkpoint, action}"
    )


def work_checkpoint_advice(args: argparse.Namespace) -> list[str]:
    """Say how the packet gets work state, where the packet exists to hold it.

    The `checkpoint` hook is named only inside the session-continuation
    reference, which a work route does not require, and no hook output
    mentioned it. A lifecycle followed faithfully therefore produced packets
    whose objective was the route enum and whose every other field was empty:
    bound correctly, and useless to resume.
    """

    if run_binding_path(args) is None:
        return []
    return [WORK_CHECKPOINT_LEAD, _work_shape_line(), WORK_CHECKPOINT_CLOSING]


def unbindable_run_directory_error(args: argparse.Namespace) -> str:
    """Refuse a run directory that cannot hold a packet, while it can be changed.

    A caller who creates `.tao/runs/<name>/` has asked for a per-run directory;
    getting one that silently drops every checkpoint is not what was asked for.
    The lifecycle deliberately does not fail for evidence kept anywhere else --
    the default `.tao/preflight.json` and worker paths under `.tao/workers/`
    have no packet by design -- so the refusal is narrowed to the one shape that
    is a mistake rather than a choice.
    """

    evidence = getattr(args, "evidence", None)
    if not evidence:
        return ""
    try:
        directory = Path(evidence).expanduser().resolve().parent
        runs_root = (args.project / ".tao" / RUNS_DIR).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    if directory.parent != runs_root or RUN_ID_RE.match(directory.name):
        return ""
    return UNBINDABLE_RUN_DIRECTORY

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


def start_checkpoint(args: argparse.Namespace) -> tuple[str, dict[str, Any] | None]:
    """Name the checkpoint a start writes, and what it may put in it.

    A start does not always begin a run. When the runtime session already owns
    one, `preflight_evidence_path` adopts it -- and an `initial` checkpoint is
    refused whenever a valid packet exists, which for an adopted run is always.
    The refusal is non-blocking, so the start reported SUCCESS while the packet
    stayed bound to the HEAD of the earlier start; `resume` then called that
    head_drift and rendered none of the saved work.

    An adopted run is the same run continuing, so its start refreshes the
    packet instead. It carries no work: the objective it would write is the
    route enum, and overwriting a recorded objective with that would lose
    exactly what the refresh is for.
    """

    binding_path = run_binding_path(args)
    if binding_path is None:
        return "initial", {"objective": start_objective(args)}
    existing = read_continuation_packet(
        args.project, continuation_path(args.project, binding_path.parent.name)
    )
    if existing["status"] == "ok":
        return "lifecycle", None
    return "initial", {"objective": start_objective(args)}


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
