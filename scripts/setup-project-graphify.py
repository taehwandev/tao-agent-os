#!/usr/bin/env python3
"""Install one shared Graphify skill and inspect target-project graph caches."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from support.graphify_setup import (
    configure_global_graphify,
    configure_target_graphify,
    graphify_platforms_for_runtimes,
    inspect_global_graphify,
    inspect_target_graphify,
    install_graphify_input_policy,
    repair_graph_integrity,
    repair_project_document_links,
)


DEFAULT_RUNTIMES = {"agy", "claude", "codex"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Install the runtime-bundled Graphify skill globally and inspect "
            "project-local graph caches without copying skills into repositories."
        )
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Target repository path; repeat for parallel multi-project setup.",
    )
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Install the runtime bundle under ~/.tao and refresh user-level links.",
    )
    parser.add_argument(
        "--runtime",
        action="append",
        choices=("agy", "claude", "codex"),
        default=[],
        help="Intentionally limit runtime entrypoints; default installs all three.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Maximum parallel target projects (default: 4).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect only; do not modify target repositories.",
    )
    parser.add_argument(
        "--repair-input-policy",
        action="store_true",
        help=(
            "Repair only the managed Graphify input boundary; do not install project "
            "skills, links, hooks, or Graphify output."
        ),
    )
    parser.add_argument(
        "--repair-document-links",
        action="store_true",
        help=(
            "Add deterministic graph references for explicit project-relative source "
            "paths cited by project documents; do not run an LLM extraction."
        ),
    )
    parser.add_argument(
        "--repair-graph-integrity",
        action="store_true",
        help=(
            "Remove only malformed, dangling, and self-loop edges from the "
            "project-local generated graph."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="Output format (default: summary).",
    )
    return parser


def validate_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> list[Path]:
    if not args.project and not args.global_scope:
        parser.error("provide at least one --project or --global")
    if args.repair_input_policy and args.global_scope:
        parser.error("--repair-input-policy supports project targets only")
    if args.repair_document_links and args.global_scope:
        parser.error("--repair-document-links supports project targets only")
    if args.repair_graph_integrity and args.global_scope:
        parser.error("--repair-graph-integrity supports project targets only")
    repair_modes = sum(
        (
            args.repair_input_policy,
            args.repair_document_links,
            args.repair_graph_integrity,
        )
    )
    if repair_modes > 1:
        parser.error("choose only one repair mode per invocation")

    projects = [Path(value).expanduser().resolve() for value in args.project]
    missing = [str(path) for path in projects if not path.is_dir()]
    if missing:
        parser.error("project directory not found: " + ", ".join(missing))
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return projects


def configure_project(
    project: Path, platforms: dict[str, object], args: argparse.Namespace
) -> dict[str, object]:
    document_links: dict[str, object] | None = None
    graph_repair: dict[str, object] | None = None
    if args.repair_input_policy:
        changes = [] if args.check else [install_graphify_input_policy(project)]
    elif args.repair_document_links:
        document_links = repair_project_document_links(project, dry_run=args.check)
        changes = [
            {
                "tool": "graphify",
                "hook": "graph.repair.document-links",
                "status": "ok" if document_links["ready"] else "missing",
                "path": str(document_links["graph_path"]),
            }
        ]
    elif args.repair_graph_integrity:
        graph_repair = repair_graph_integrity(
            project / ".agents" / "local" / "graphify-out" / "graph.json",
            dry_run=args.check,
        )
        changes = [
            {
                "tool": "graphify",
                "hook": "graph.repair.integrity",
                "status": "ok" if graph_repair["ready"] else "missing",
                "path": str(graph_repair["graph_path"]),
            }
        ]
    else:
        changes = configure_target_graphify(project, platforms, dry_run=args.check)
    readiness = inspect_target_graphify(project, platforms)
    return {
        "scope": "project",
        "project": str(project),
        "changes": changes,
        "readiness": readiness,
        "document_links": document_links,
        "graph_repair": graph_repair,
        "success": project_success(args, readiness, document_links, graph_repair),
    }


def project_success(
    args: argparse.Namespace,
    readiness: dict[str, object],
    document_links: dict[str, object] | None,
    graph_repair: dict[str, object] | None,
) -> bool:
    if args.repair_input_policy:
        return bool(readiness["graph_input_policy_ready"])
    if args.repair_document_links:
        return bool(document_links and document_links["ready"])
    if args.repair_graph_integrity:
        return bool(graph_repair and graph_repair["ready"])
    return bool(readiness["ready"])


def print_repair_summary(report: dict[str, object], args: argparse.Namespace) -> bool:
    readiness = report["readiness"]
    if args.repair_input_policy:
        print(
            f"{'SUCCESS' if report['success'] else 'FAIL'} input-policy "
            f"{report['project']} blanket-exclusions="
            f"{len(readiness.get('blanket_knowledge_input_exclusions', []))}"
        )
        return True
    if args.repair_document_links:
        links = report["document_links"] or {}
        print(
            f"{'SUCCESS' if report['success'] else 'FAIL'} document-links "
            f"{report['project']} scanned={links.get('document_files_scanned', 0)} "
            f"paths={links.get('explicit_source_paths_found', 0)} "
            f"edges={links.get('document_source_edges', 0)}"
        )
        return True
    if args.repair_graph_integrity:
        repair = report["graph_repair"] or {}
        print(
            f"{'SUCCESS' if report['success'] else 'FAIL'} graph-integrity "
            f"{report['project']} removed={repair.get('removed_edge_count', 0)} "
            f"edges={repair.get('edge_count', 0)} "
            f"dry-run={str(bool(repair.get('dry_run'))).lower()}"
        )
        return True
    return False


def print_install_summary(report: dict[str, object]) -> None:
    readiness = report["readiness"]
    install_ready = bool(
        readiness["canonical_skill_exists"]
        and not readiness["invalid_runtime_links"]
        and readiness.get("project_integration_ready", True)
    )
    print(
        f"{'SUCCESS' if install_ready else 'FAIL'} install "
        f"{report['project']} canonical={readiness['canonical_skill_doc']} "
        f"links={len(readiness['runtime_skill_links'])}"
    )
    if report["scope"] != "project":
        print(f"{'SUCCESS' if readiness['ready'] else 'FAIL'} global readiness")
        return
    print(
        f"{'SUCCESS' if readiness['ready'] else 'FAIL'} readiness "
        f"graph={readiness['graph_path']}"
    )
    print(
        "  graph-checks "
        f"fresh={str(readiness.get('graph_fresh') is True).lower()} "
        f"integrity={str(bool(readiness.get('graph_integrity_ready'))).lower()} "
        f"inputs={str(bool(readiness.get('graph_input_policy_ready') and readiness.get('knowledge_manifest_ready'))).lower()} "
        f"relationships={str(bool(readiness.get('graph_relationship_ready'))).lower()}"
    )
    print(
        "  graph-counts "
        f"knowledge={readiness.get('project_knowledge_file_count', 0)} "
        f"manifest={readiness.get('knowledge_manifest_file_count', 0)} "
        f"missing={readiness.get('knowledge_manifest_missing_count', 0)} "
        f"stale={readiness.get('knowledge_manifest_stale_count', 0)} "
        f"knowledge-path-nodes={readiness.get('graph_knowledge_code_path_node_count', 0)}"
    )
    print(
        f"{'SUCCESS' if readiness.get('project_integration_ready') else 'FAIL'} "
        "project-boundary "
        f"unexpected-runtime-assets={len(readiness.get('unexpected_project_runtime_assets', []))}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    projects = validate_arguments(parser, args)
    platforms = graphify_platforms_for_runtimes(set(args.runtime) or DEFAULT_RUNTIMES)

    reports: list[dict[str, object]] = []
    if args.global_scope:
        home = Path.home()
        reports.append(
            {
                "scope": "global",
                "project": str(home),
                "changes": configure_global_graphify(home, platforms, dry_run=args.check),
                "readiness": inspect_global_graphify(home, platforms),
            }
        )
    if projects:
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(projects))) as executor:
            reports.extend(
                executor.map(partial(configure_project, platforms=platforms, args=args), projects)
            )

    if args.format == "json":
        print(json.dumps({"projects": reports}, indent=2, ensure_ascii=False))
    else:
        for report in reports:
            if not print_repair_summary(report, args):
                print_install_summary(report)
    if any(
        not report.get("success", report["readiness"]["ready"])
        for report in reports
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
