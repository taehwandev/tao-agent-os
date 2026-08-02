#!/usr/bin/env python3
"""Resolve shared Tao Agent OS workflow routes.

This CLI does not run project commands. It produces the document route and
gates an agent should use before it executes work in a target repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_worktree_identity import WorktreeSessionError
from agent_worktree_integration import finalize_worker_worktree
from workflow_catalog import COMMANDS, CONCERNS, PLATFORM_CONCERNS, PLATFORMS
from workflow_common import ROOT, unique
from workflow_dispatch import (
    WORK_KINDS,
    build_dispatch_manifest,
    execute_dispatch_manifest,
    print_dispatch_manifest,
)
from workflow_dispatch_cli import (
    dispatch_isolation_required,
    parent_dispatch_route,
    preflight_identity_matches,
)
from workflow_classified_exemption import (
    classified_intake_decision,
    parent_evidence_path,
)
from agent_route_state import request_fingerprint
from workflow_intent_dual_run import (
    classification_from_envelope,
    dual_run_decision,
    route_intake_decision,
)
from workflow_intent_envelope import read_intent_envelope
from workflow_request import (
    classify_request,
    infer_concerns_from_request,
    print_classification,
)
from workflow_output import print_markdown
from workflow_route import resolve_docs
from workflow_search import print_query_results, search_docs_outcome
from workflow_spill import spill_label_for_args, write_spill_label
from workflow_validate import validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve Tao Agent OS workflow routes.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    route = subparsers.add_parser("route", help="Print a workflow route manifest.")
    route.add_argument("command", choices=sorted(COMMANDS), help="Task command profile.")
    route.add_argument(
        "--project",
        help="Target project root used for target-project readiness checks.",
    )
    route.add_argument("--platform", choices=sorted(PLATFORMS), help="Affected platform.")
    route.add_argument(
        "--concern",
        action="append",
        default=[],
        choices=sorted(set(CONCERNS) | {key[1] for key in PLATFORM_CONCERNS}),
        help="Affected concern. Can be repeated.",
    )
    route.add_argument("--request", help="Current user request text. Required for every non-advisory route.")
    route.add_argument(
        "--continuation-scope",
        default="",
        help=(
            "Bounded prior scope for a terse follow-up. It supplies target identity "
            "only and is never concatenated into the current request classifier."
        ),
    )
    route.add_argument(
        "--intent-envelope",
        default="",
        help=(
            "Runtime intent envelope as JSON or a path to it. When supplied it is "
            "the authority for intent, target and effect; the request text is not "
            "re-read to second-guess it."
        ),
    )
    route.add_argument(
        "--runtime-session-id",
        default="",
        help="Current opaque runtime session id that must match the intent envelope.",
    )
    route.add_argument(
        "--surface-path",
        action="append",
        default=[],
        help="Path already known to be in scope; can be repeated. Used to promote required docs from workflow-doc-surfaces.json.",
    )
    route.add_argument(
        "--request-classified",
        action="store_true",
        help=(
            "Delegated-worker only: reuse request intake from a ready, valid, "
            "matching parent execution capsule."
        ),
    )
    route.add_argument(
        "--classification-evidence",
        help=(
            "Required with --request-classified; describes the matching parent's "
            "resolved classification or answer-first handling."
        ),
    )
    route.add_argument("--rules", type=Path, default=ROOT)
    route.add_argument(
        "--parent-evidence",
        type=Path,
        help=(
            "Parent preflight evidence whose execution capsule may honor "
            "--request-classified. Defaults to <project>/.tao/preflight.json."
        ),
    )
    route.add_argument(
        "--advisory",
        action="store_true",
        help=(
            "Print the document listing and label context without asserting request "
            "intake. An advisory route satisfies no downstream gate."
        ),
    )
    route.add_argument("--format", choices=("markdown", "json"), default="markdown")

    _add_dispatch_parser(subparsers)
    _add_dispatch_finalize_parser(subparsers)

    classify = subparsers.add_parser("classify", help="Classify request clarity and effort.")
    classify.add_argument("request", help="User request text to classify.")
    classify.add_argument("--continuation-scope", default="")
    classify.add_argument("--command", default="task")
    classify.add_argument(
        "--intent-envelope",
        default="",
        help="runtime intent envelope as JSON or a path to it; when given it decides",
    )
    classify.add_argument("--runtime-session-id", default="")
    classify.add_argument("--format", choices=("markdown", "json"), default="markdown")

    query = subparsers.add_parser("query", help="Search Tao Agent OS docs by keyword relevance.")
    query.add_argument("terms", nargs="+", help="Search terms (space-separated keywords).")
    query.add_argument(
        "--max",
        type=int,
        default=8,
        dest="max_results",
        help="Maximum results to return (default: 8).",
    )
    query.add_argument("--format", choices=("markdown", "json"), default="markdown")

    subparsers.add_parser("list", help="List available commands, platforms, and concerns.")
    subparsers.add_parser("validate", help="Validate route references, markdown frontmatter, and links.")
    return parser


def _add_dispatch_parser(subparsers: argparse._SubParsersAction) -> None:
    dispatch = subparsers.add_parser(
        "dispatch", help="Build a Codex task handoff from a workflow profile."
    )
    dispatch.add_argument("command", choices=sorted(COMMANDS), help="Task command profile.")
    dispatch.add_argument("--request", required=True, help="Current user request text.")
    dispatch.add_argument("--continuation-scope", default="")
    dispatch.add_argument("--intent-envelope", default="")
    dispatch.add_argument("--runtime-session-id", default="")
    dispatch.add_argument(
        "--request-classified",
        action="store_true",
        help=(
            "Delegated-worker only: reuse request intake from a ready, valid, "
            "matching parent execution capsule."
        ),
    )
    dispatch.add_argument(
        "--classification-evidence",
        default="",
        help="Resolved-scope evidence from that matching parent.",
    )
    dispatch.add_argument("--project", default=".", help="Target project root for the delegated Codex task.")
    dispatch.add_argument("--rules", type=Path, default=ROOT)
    dispatch.add_argument("--evidence", type=Path)
    dispatch.add_argument("--worker-evidence", type=Path)
    dispatch.add_argument("--worker-reservation-token", default="")
    dispatch.add_argument("--work-kind", choices=WORK_KINDS, default="auto")
    dispatch.add_argument("--complexity-evidence", default="")
    dispatch.add_argument("--platform", choices=sorted(PLATFORMS), help="Affected platform.")
    dispatch.add_argument(
        "--concern",
        action="append",
        default=[],
        choices=sorted(set(CONCERNS) | {key[1] for key in PLATFORM_CONCERNS}),
        help="Affected concern. Can be repeated.",
    )
    dispatch.add_argument("--format", choices=("markdown", "json"), default="markdown")
    dispatch.add_argument("--parent-model", default="")
    dispatch.add_argument("--parent-reasoning-effort", default="")
    dispatch.add_argument("--parent-sandbox-mode", default="")
    dispatch.add_argument("--require-isolation", action="store_true")
    dispatch.add_argument(
        "--worker-id",
        default="",
        help=(
            "Delegation-plan worker id. A worker the plan declares worktree-isolated "
            "dispatches isolated even without --require-isolation."
        ),
    )
    dispatch.add_argument(
        "--delegation-plan",
        type=Path,
        default=None,
        help="Delegation plan path (default: <project>/.tao/agent-delegation-plan.json).",
    )
    dispatch.add_argument("--heartbeat-interval-seconds", type=float, default=0)
    dispatch.add_argument("--execute", action="store_true")


def _add_dispatch_finalize_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    finalize = subparsers.add_parser(
        "dispatch-finalize",
        help="Verify lead integration and remove a completed worker worktree.",
    )
    finalize.add_argument("--project", default=".", help="Lead checkout root.")
    finalize.add_argument("--worktree", required=True, type=Path)
    finalize.add_argument(
        "--discard-ignored",
        action="store_true",
        help="Explicitly permit removal of ignored files inside the worker tree.",
    )
    finalize.add_argument("--format", choices=("markdown", "json"), default="markdown")


def print_supported_values() -> None:
    print("Commands:")
    for name in sorted(COMMANDS):
        print(f"- {name}")
    print("Platforms:")
    for name in sorted(PLATFORMS):
        print(f"- {name}")
    print("Concerns:")
    for name in sorted(set(CONCERNS) | {key[1] for key in PLATFORM_CONCERNS}):
        print(f"- {name}")


def print_query(args: argparse.Namespace) -> int:
    query_str = " ".join(args.terms)
    outcome = search_docs_outcome(ROOT, query_str, max_results=args.max_results)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "query": query_str,
                    "backend": outcome.backend,
                    "backend_version": outcome.backend_version,
                    "fallback_reason": outcome.fallback_reason,
                    "weak": outcome.weak,
                    "partial": outcome.partial,
                    "fused": outcome.fused,
                    "results": outcome.results,
                },
                indent=2,
            )
        )
    else:
        print_query_results(query_str, outcome.results)
    return 0


def print_request_classification(args: argparse.Namespace) -> int:
    result = classify_request(
        args.request,
        continuation_scope=args.continuation_scope,
    )
    envelope = read_intent_envelope(getattr(args, "intent_envelope", ""))
    if envelope is not None:
        # Dual run: the envelope decides and the classifier result is kept only
        # as a comparison. Letting the classifier override on disagreement
        # would keep the natural-language path authoritative, which is what the
        # transition removes.
        decision = dual_run_decision(
            getattr(args, "command", "task") or "task",
            envelope,
            result,
            request_fingerprint=request_fingerprint({"request": args.request or ""}),
            runtime_session_id=str(getattr(args, "runtime_session_id", "") or ""),
        )
        if decision["failures"]:
            result["intent_envelope"] = decision
        else:
            result = classification_from_envelope(envelope, decision)
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_classification(result)
    return 0


def print_route(args: argparse.Namespace) -> int:
    advisory = bool(getattr(args, "advisory", False))
    if advisory and args.request_classified:
        print(
            "Route --advisory does not assert request intake, so it cannot be combined "
            "with --request-classified. Drop one of the two flags.",
            file=sys.stderr,
        )
        return 2
    if args.request_classified and not args.classification_evidence:
        print(
            "Route --request-classified requires --classification-evidence so request intake cannot be skipped silently.",
            file=sys.stderr,
        )
        return 2
    project_root = Path(args.project).resolve() if args.project else None
    if advisory:
        # An advisory route only lists documents and writes label context. It
        # never claims the request was classified, so it must not reach the
        # intake decision at all.
        request_classification = None
    else:
        request_classification, failures = route_intake_decision(
            args.command,
            read_intent_envelope(getattr(args, "intent_envelope", "")),
            request_fingerprint=request_fingerprint({"request": args.request or ""}),
            runtime_session_id=str(getattr(args, "runtime_session_id", "") or ""),
        )
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 2
        if request_classification is None:
            request_classification, block_reason = classified_intake_decision(
                args.command,
                args.request,
                args.request_classified,
                args.classification_evidence or "",
                args.continuation_scope,
                project=project_root,
                rules=getattr(args, "rules", None),
                parent_evidence=parent_evidence_path(
                    project_root, getattr(args, "parent_evidence", None)
                ),
            )
            if block_reason:
                print(block_reason, file=sys.stderr)
                if request_classification:
                    print(
                        f"Classification: {request_classification['clarity']} / "
                        f"response_mode: {request_classification['response_mode']} / "
                        f"grill_me: {str(request_classification['grill_me']).lower()}",
                        file=sys.stderr,
                    )
                return 2

    intent_text = "" if advisory else (args.request or args.classification_evidence or "")
    inferred_concerns = infer_concerns_from_request(intent_text)
    if args.request_classified and args.classification_evidence and args.request:
        # Classification evidence describes the resolved scope, and it used to be
        # the only intent text available. Now that a request is always required
        # alongside the flag, keep inferring concerns from the evidence too so a
        # scope named only there does not silently drop its route concern.
        inferred_concerns = unique(
            [*inferred_concerns, *infer_concerns_from_request(args.classification_evidence)]
        )
    concerns = unique([*args.concern, *inferred_concerns])
    newly_inferred = [concern for concern in inferred_concerns if concern not in args.concern]

    route = resolve_docs(
        args.command,
        args.platform,
        concerns,
        request_classification=request_classification,
        request_classified=args.request_classified,
        classification_evidence=args.classification_evidence or "",
        request_text=intent_text,
        surface_paths=args.surface_path,
        project_root=project_root,
    )
    if advisory:
        route["advisory"] = True
        notes = route.get("notes")
        if isinstance(notes, list):
            notes.append(
                "Advisory listing only: this route asserted no request intake and "
                "satisfies no downstream gate. Rerun with `--request \"<USER_REQUEST>\"` "
                "before editing, reviewing, or reporting completion."
            )
    if newly_inferred:
        route["inferred_concerns"] = newly_inferred
        notes = route.get("notes")
        if isinstance(notes, list):
            joined = ", ".join(f"`{concern}`" for concern in newly_inferred)
            notes.append(f"Inferred concern(s) from request keywords: {joined}.")
    if args.format == "json":
        print(json.dumps(route, indent=2, sort_keys=True))
    else:
        print_markdown(route)
    return 1 if route["missing"] or route.get("blocking") else 0


def _dispatch_request_classification(
    args: argparse.Namespace,
    *,
    project: Path,
    rules: Path,
    evidence_path: Path,
) -> tuple[dict[str, object] | None, str | None]:
    """Resolve dispatch intake without letting the entrypoint own policy details."""

    request_classification, failures = route_intake_decision(
        args.command,
        read_intent_envelope(getattr(args, "intent_envelope", "")),
        request_fingerprint=request_fingerprint({"request": args.request or ""}),
        runtime_session_id=str(getattr(args, "runtime_session_id", "") or ""),
    )
    if failures:
        return None, "\n".join(failures)
    if request_classification is not None:
        return request_classification, None
    return classified_intake_decision(
        args.command,
        args.request,
        args.request_classified,
        args.classification_evidence,
        args.continuation_scope,
        project=project,
        rules=rules,
        parent_evidence=evidence_path,
    )


def print_dispatch(args: argparse.Namespace) -> int:
    if args.request_classified and not args.classification_evidence:
        print(
            "Dispatch --request-classified requires --classification-evidence so request intake cannot be skipped silently.",
            file=sys.stderr,
        )
        return 2
    project = Path(args.project).resolve()
    rules = args.rules.expanduser().resolve()
    evidence_path = (
        args.evidence.expanduser().resolve()
        if args.evidence
        else project / ".tao" / "preflight.json"
    )
    request_classification, block_reason = _dispatch_request_classification(
        args,
        project=project,
        rules=rules,
        evidence_path=evidence_path,
    )
    if block_reason:
        print(block_reason, file=sys.stderr)
        return 2

    parent_identity_matches = preflight_identity_matches(
        evidence_path,
        project=project,
        rules=rules,
    )
    parent_route = parent_dispatch_route(
        evidence_path,
        command=args.command,
        request=args.request,
        continuation_scope=args.continuation_scope,
        request_classified=args.request_classified,
        classification_evidence=args.classification_evidence,
        platform=args.platform,
        concerns=args.concern,
        project=project,
        rules=rules,
    )
    if not parent_identity_matches:
        evidence_path = project / ".tao" / "preflight.json"
    route = parent_route
    if route is None:
        inferred_concerns = infer_concerns_from_request(args.request)
        route = resolve_docs(
            args.command,
            args.platform,
            unique([*args.concern, *inferred_concerns]),
            request_classification=request_classification,
            request_classified=args.request_classified,
            classification_evidence=args.classification_evidence,
            request_text=args.request,
            project_root=project,
        )
    if route["missing"] or route.get("blocking"):
        print("Dispatch route is blocked:", file=sys.stderr)
        for item in [*route["missing"], *(route.get("blocking") or [])]:
            print(f"- {item}", file=sys.stderr)
        return 1
    try:
        isolation_required = dispatch_isolation_required(args, project)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        manifest = build_dispatch_manifest(
            args.command,
            args.request,
            Path(args.project),
            continuation_scope=args.continuation_scope,
            work_kind=args.work_kind,
            complexity_evidence=args.complexity_evidence,
            route=route,
            request_classified=args.request_classified,
            classification_evidence=args.classification_evidence,
            request_classification=request_classification,
            parent_model=args.parent_model,
            parent_reasoning_effort=args.parent_reasoning_effort,
            parent_sandbox_mode=args.parent_sandbox_mode,
            isolation_required=isolation_required,
            heartbeat_interval_seconds=args.heartbeat_interval_seconds,
            rules=rules,
            evidence_path=evidence_path,
            worker_evidence_path=args.worker_evidence,
            reserve_worker_evidence=args.execute,
            worker_reservation_token=args.worker_reservation_token,
            parent_context_reusable=parent_route is not None,
            defer_capsule_validation=args.execute,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    if args.execute:
        try:
            return execute_dispatch_manifest(manifest)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
        except (OSError, RuntimeError) as error:
            print(error, file=sys.stderr)
            return 1
    print_dispatch_manifest(manifest, args.format)
    return 0


def print_dispatch_finalize(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    try:
        result = finalize_worker_worktree(
            project,
            args.worktree,
            discard_ignored=args.discard_ignored,
        )
    except WorktreeSessionError as error:
        print(error, file=sys.stderr)
        return 2
    payload = {
        "discarded_ignored_path_count": result.discarded_ignored_path_count,
        "integrated_path_count": result.integrated_path_count,
        "status": "finalized",
    }
    if args.format == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "Finalized worker worktree "
            f"({result.integrated_path_count} integrated paths, "
            f"{result.discarded_ignored_path_count} explicitly discarded ignored paths)."
        )
    return 0


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    task_type, stage = spill_label_for_args(args)
    write_spill_label(task_type, stage)

    if args.action == "list":
        print_supported_values()
        return 0
    try:
        return _dispatch_action(args)
    except ValueError as error:
        # The bounded continuation-scope contract is enforced by raising, which
        # reached the terminal as a traceback. A caller that violates the bound
        # needs the reason, not a stack, and the run must still fail closed.
        print(f"invalid request input: {error}", file=sys.stderr)
        return 2


def _dispatch_action(args: argparse.Namespace) -> int:
    if args.action == "validate":
        return validate()
    if args.action == "query":
        return print_query(args)
    if args.action == "classify":
        return print_request_classification(args)
    if args.action == "dispatch":
        return print_dispatch(args)
    if args.action == "dispatch-finalize":
        return print_dispatch_finalize(args)
    return print_route(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
