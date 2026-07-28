"""The ``resume`` hook: the only entry point sessions have into continuation.

``resume_list`` and ``resume_last`` were written, tested and then reachable by
nobody -- a resume function with no CLI entry point can be reached by no
session. This module is that entry point and nothing more: it selects a mode,
renders the shared result, and maps it onto the two-state hook contract. Every
decision about ownership, drift and takeover stays inside ``claim_resume``,
because a second place that decides them is a second answer to one question.

A refusal is a ``FAIL`` with the reason named, never a third state and never a
quiet fallback to an older task. It is reported as an invocation failure rather
than a failed checkpoint: no gate failed, so there is nothing a repair receipt
could ever bind to, and demanding one would deadlock the caller.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_continuation_resume import resume_last, resume_list
from agent_hook_runtime import finish_with_result
from agent_runtime_session import bind_resumed_runtime_session


LISTED_ENTRY_LIMIT = 12
REFUSAL_GUIDANCE = {
    "not_found": "no unfinished continuation packet for this checkout; start a fresh run",
    "live_owner_refused": (
        "the newest packet's run still has a live owner; resume never substitutes an older task"
    ),
    "owner_unproven_wait": (
        "the newest packet's owner cannot be proven dead and its fallback window has not expired"
    ),
    "drift_refused": (
        "HEAD, worktree, rules, required docs, or a pending mutation moved since the last "
        "checkpoint; reconcile explicitly or carry the objective into a fresh start"
    ),
    "invalid_packet": (
        "the newest packet failed containment, schema, binding, or integrity validation; "
        "its prose is deliberately not rendered"
    ),
    "local_boundary_failed": (
        "the newest packet's project-local, Git-ignored boundary could not be proven"
    ),
    "claim_lost": "another session claimed this run between capture and commit",
    "runtime_binding_refused": (
        "the resume claim completed but could not bind the exact runtime session; "
        "no work summary was rendered"
    ),
}


def add_resume_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the two resume modes beside the code that implements them."""

    resume = parser.add_argument_group("resume hook")
    resume.add_argument(
        "--list",
        dest="list_mode",
        action="store_true",
        help="read-only listing of this checkout's unfinished continuation packets",
    )
    resume.add_argument(
        "--last",
        dest="last_mode",
        action="store_true",
        help="claim the newest unfinished packet, or refuse it by name",
    )
    resume.add_argument(
        "--runtime",
        default="",
        help="runtime name for an exact session binding after a successful claim",
    )
    resume.add_argument(
        "--runtime-session-id",
        default="",
        help="opaque runtime session id to bind after a successful claim",
    )


def resume_hook(args: argparse.Namespace) -> int:
    """Run the read-only listing or the single-packet resume claim."""

    if args.last_mode:
        return _resume_last(args)
    return _resume_list(args)


def _resume_list(args: argparse.Namespace) -> int:
    """Report this checkout's unfinished packets and change nothing at all."""

    result = resume_list(args.project, rules=args.rules)
    entries = result["entries"]
    details = [f"unfinished continuation packets: {len(entries)}"]
    details.extend(_entry_line(entry) for entry in entries[:LISTED_ENTRY_LIMIT])
    if len(entries) > LISTED_ENTRY_LIMIT:
        details.append(f"listed packets truncated: {len(entries) - LISTED_ENTRY_LIMIT} more")
    return finish_with_result(
        "resume",
        True,
        details,
        args.output,
        {"resume": result},
        args.repair_cycle,
    )


def _resume_last(args: argparse.Namespace) -> int:
    """Claim the newest packet, or refuse it by name without picking another."""

    result = resume_last(args.project, rules=args.rules)
    ready = result["result"] == "ready"
    if ready and (args.runtime or args.runtime_session_id):
        if not args.runtime or not args.runtime_session_id:
            result = {
                **result,
                "result": "runtime_binding_refused",
                "reason": "incomplete_runtime_binding",
                "work": None,
                "checkpoint": None,
            }
            ready = False
        else:
            try:
                bind_resumed_runtime_session(
                    project=args.project,
                    evidence_path=Path(result["evidence_path"]),
                    run_id=result["run_id"],
                    resume_generation=int(result["resume_generation"]),
                    runtime=args.runtime,
                    session_id=args.runtime_session_id,
                )
            except (OSError, RuntimeError, ValueError):
                result = {
                    **result,
                    "result": "runtime_binding_refused",
                    "reason": "runtime_binding_refused",
                    "work": None,
                    "checkpoint": None,
                }
                ready = False
    details = [f"resume result: {result['result']}"]
    details.extend(_ready_lines(result) if ready else _refusal_lines(result))
    return finish_with_result(
        "resume",
        ready,
        details,
        args.output,
        {"resume": result},
        args.repair_cycle,
        invocation_error=not ready,
    )


def _ready_lines(result: dict[str, Any]) -> list[str]:
    work = result["work"] or {}
    return [
        f"run: {result['run_id']}",
        f"route command: {result['route_command']}",
        f"evidence: {result['evidence_path']}",
        f"resume checkpoint: {result['checkpoint']}",
        f"resume generation: {result['resume_generation']}",
        f"objective: {work.get('objective', '')}",
        f"remaining work items: {len(work.get('remaining_work') or [])}",
        f"blockers: {len(work.get('blockers') or [])}",
    ]


def _refusal_lines(result: dict[str, Any]) -> list[str]:
    """Name the refusal without rendering any semantic work object."""

    lines = [f"refusal reason: {result['reason'] or result['result']}"]
    if result["run_id"]:
        lines.append(f"run: {result['run_id']}")
    if result["holder_state"]:
        lines.append(f"holder state: {result['holder_state']}")
    if result["changed_signals"]:
        lines.append(f"changed signals: {result['changed_signals']}")
    if result["affected_paths"]:
        lines.append(f"affected paths: {result['affected_paths'][:8]}")
    guidance = REFUSAL_GUIDANCE.get(result["result"])
    if guidance:
        lines.append(guidance)
    return lines


def _entry_line(entry: dict[str, Any]) -> str:
    return (
        f"{entry['run_id']} status={entry['status']} holder={entry['holder']}"
        f" drift={entry['drift'] or 'unknown'}"
        f" checkpoint={entry['first_unfinished'] or 'none'}"
        f" route={entry['route_command'] or 'unknown'}"
        f" updated={entry['updated_at'] or 'unknown'}"
        f" objective={entry['objective'] or 'not rendered'}"
    )
