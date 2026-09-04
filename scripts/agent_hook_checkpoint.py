"""Strict provider-neutral continuation checkpoint command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_continuation_checkpoint import CHECKPOINT_KINDS, write_continuation_checkpoint
from agent_continuation_packet import (
    MAX_PACKET_BYTES,
    MUTATION_KINDS,
    PHASES,
    ContinuationPacketError,
)
from agent_hook_continuation import run_binding_path
from agent_hook_runtime import finish_with_result


def add_checkpoint_arguments(parser: argparse.ArgumentParser) -> None:
    checkpoint = parser.add_argument_group("continuation checkpoint")
    checkpoint.add_argument("--checkpoint-kind", choices=CHECKPOINT_KINDS)
    checkpoint.add_argument("--phase", choices=PHASES)
    checkpoint.add_argument("--last-completed")
    checkpoint.add_argument("--mutation-kind", choices=MUTATION_KINDS)
    checkpoint.add_argument("--mutation-path", action="append", default=[])
    checkpoint.add_argument(
        "--work-stdin",
        action="store_true",
        help="read one schema-bounded partial work object from stdin",
    )
    checkpoint.add_argument(
        "--work-shape",
        action="store_true",
        help="print the work object's fields, limits and enums, and do nothing else",
    )


def checkpoint_hook(args: argparse.Namespace) -> int:
    """Write one strict checkpoint; failures never permit a mutation to start."""

    if getattr(args, "work_shape", False):
        # Asked for, rather than printed by every start in every session. The
        # schema is nine unchanging lines; a reader needs them once.
        from agent_hook_continuation import _work_shape_lines

        return _result(args, True, "\n".join(_work_shape_lines()))

    binding = run_binding_path(args)
    if binding is None:
        return _result(args, False, "checkpoint requires exact run-local evidence")
    try:
        work = _read_work_stdin() if args.work_stdin else None
        mutation = None
        if args.checkpoint_kind == "pre_mutation":
            mutation = {
                "kind": str(args.mutation_kind or ""),
                "paths": list(args.mutation_path),
            }
        packet = write_continuation_checkpoint(
            project=args.project,
            rules=args.rules,
            run_id=binding.parent.name,
            kind=args.checkpoint_kind,
            binding_path=binding,
            work=work,
            phase=args.phase,
            last_completed=args.last_completed,
            mutation=mutation,
        )
    except ContinuationPacketError as error:
        rules = ", ".join(
            f"{item['rule']}@{item['pointer']}" for item in error.failures
        )
        return _result(args, False, f"checkpoint refused: {rules}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        return _result(args, False, f"checkpoint unavailable: {type(error).__name__}")
    return finish_with_result(
        "checkpoint",
        True,
        [
            f"checkpoint kind: {args.checkpoint_kind}",
            f"packet generation: {packet['generation']}",
        ],
        args.output,
        {"checkpoint": {"kind": args.checkpoint_kind, "generation": packet["generation"]}},
        args.repair_cycle,
    )


def _read_work_stdin() -> dict[str, Any]:
    encoded = sys.stdin.buffer.read(MAX_PACKET_BYTES + 1)
    if len(encoded) > MAX_PACKET_BYTES:
        raise ValueError("work input exceeds packet budget")
    payload = json.loads(encoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("work input must be an object")
    return payload


def _result(args: argparse.Namespace, success: bool, detail: str) -> int:
    return finish_with_result(
        "checkpoint",
        success,
        [detail],
        args.output,
        {},
        args.repair_cycle,
        invocation_error=not success,
    )
