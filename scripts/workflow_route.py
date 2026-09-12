"""Build workflow route manifests."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Optional

from workflow_catalog import (
    BASELINE_CONCERNS,
    COMMANDS,
    CONCERN_REFERENCE_DOCS,
    CONCERNS,
    CORE_DOCS,
    PLATFORM_CONCERNS,
    PLATFORMS,
    RISK_CONCERNS_REQUIRED_WHEN_INFERRED,
)
from agent_skill_catalog import FEEDBACK_SIGNALS
from workflow_common import (
    REPAIR_CYCLE_LIMIT,
    REPAIR_POLICY,
    REPAIR_STOP_CONDITION,
    RESUME_SCOPE,
    ROOT,
    QUESTION_ROUTE_COMMANDS,
    unique,
)
from workflow_doc_graph import expand_doc_matches, graph_required_docs
from workflow_gate_policy import (
    MULTI_AGENT_GATE,
    SKILL_CURATE_HOOK,
    SKILL_DRAFT_HOOK,
    SKILL_FEEDBACK_HOOK,
    SKILL_MAINTENANCE_HOOK,
    SKILL_REVIEW_HOOK,
    RETROSPECTIVE_CHECK_COMMANDS,
    RETROSPECTIVE_CHECK_GATE,
    WORK_SURFACE_RESOLUTION_GATE,
    add_automatic_gates,
    automatic_docs,
    skill_feedback_policy,
)
from workflow_graphify_route import graphify_route_context
from workflow_doc_resolution import doc_size, resolve_guidance_docs
from workflow_doc_surfaces import infer_surface_docs, required_surface_docs
from workflow_parallel import parallel_execution_plan
from workflow_search import SearchOutcome, search_docs_outcome
from workflow_skill_paths import canonical_doc_path
from support.stable_launcher import stable_launcher_path
from support.stage_timing import stage


OPERATING_SKILL = "common/skills/agent-operating-skill/SKILL.md"
REVIEW_AND_COMMIT_ENTRYPOINT = "workflows/skills/review-and-commit/SKILL.md"
REVIEW_AND_COMMIT_REFERENCE = (
    "workflows/skills/review-and-commit/references/current-guidance.md"
)
MULTI_AGENT_ENTRYPOINT = "workflows/skills/multi-agent-collaboration/SKILL.md"
MULTI_AGENT_REFERENCE = (
    "workflows/skills/multi-agent-collaboration/references/current-guidance.md"
)
SOURCE_DRIVEN_REFERENCE = (
    "common/skills/source-driven-development/references/current-guidance.md"
)

CORE_REQUIRED_DOCS = (OPERATING_SKILL,)

LOOKUP_READING_GUIDANCE = (
    "Lookup reading: keep downstream document recommendations in lookup mode. "
    "Read the directly answering definition or contract and only callers/mappers needed "
    "to resolve that question. Inspecting UI or a module does not authorize implementation "
    "guidance or an additional UI investigation. Module, technology and keyword matches "
    "remain reference candidates; preserve explicit required instructions and dependencies. "
    "Stop discovery when the answer is supported; do not repeat unchanged recommendations."
)

CODE_WORK_REQUIRED_DOCS = (
    "common/skills/llm-coding-discipline/SKILL.md",
    "common/skills/code-conventions/SKILL.md",
    "common/skills/agent-editing-safety/SKILL.md",
    "workflows/skills/multi-agent-collaboration/SKILL.md",
)

COMMAND_REQUIRED_DOCS = {
    "analysis": (),
    "ambiguity": ("workflows/skills/ambiguity-gate/SKILL.md",),
    "bugfix": ("workflows/skills/bugfix-debugging/SKILL.md",),
    "build": ("workflows/skills/feature-implementation/SKILL.md",),
    "code-simplify": ("workflows/skills/refactor-cleanup/SKILL.md", "common/skills/refactoring/SKILL.md"),
    "commit": ("workflows/skills/review-and-commit/SKILL.md", "common/skills/commit-workflow/SKILL.md"),
    "git_commit": ("workflows/skills/review-and-commit/SKILL.md", "common/skills/commit-workflow/SKILL.md"),
    "docs": ("workflows/skills/documentation-update/SKILL.md",),
    "docs-review": ("workflows/skills/review-and-commit/SKILL.md", "common/skills/code-review/SKILL.md"),
    "feature": ("workflows/skills/feature-implementation/SKILL.md",),
    "multi-agent": ("workflows/skills/multi-agent-collaboration/SKILL.md",),
    "plan": ("workflows/skills/planning-research/SKILL.md",),
    "planning": ("workflows/skills/planning-research/SKILL.md",),
    "prd": ("workflows/skills/prd-creation/SKILL.md", "common/skills/product-spec-to-implementation/SKILL.md"),
    "product": ("workflows/skills/product-architecture-delivery/SKILL.md", "common/skills/architecture-selection/SKILL.md"),
    "refactor": ("workflows/skills/refactor-cleanup/SKILL.md", "common/skills/refactoring/SKILL.md"),
    "release": ("workflows/skills/release-readiness/SKILL.md", "common/skills/release-deployment/SKILL.md", "common/skills/release-versioning/SKILL.md"),
    "retrospective": ("workflows/skills/retrospective-learning/SKILL.md",),
    "review": ("workflows/skills/review-and-commit/SKILL.md", "common/skills/code-review/SKILL.md"),
    "ship": ("workflows/skills/release-readiness/SKILL.md", "common/skills/release-deployment/SKILL.md", "common/skills/release-versioning/SKILL.md"),
    "spec": ("workflows/skills/prd-creation/SKILL.md", "common/skills/product-spec-to-implementation/SKILL.md"),
    "task": ("workflows/skills/agent-task-lifecycle/SKILL.md",),
    "test": ("common/skills/testing/SKILL.md", "common/skills/verification-policy/SKILL.md"),
    "triage": ("workflows/skills/request-triage/SKILL.md", "common/skills/task-intake-effort-routing/SKILL.md"),
    "webperf": ("common/skills/performance-verification/SKILL.md", "common/skills/web-performance-verification/SKILL.md"),
    "workflow-setup": ("workflows/skills/agent-task-lifecycle/SKILL.md", "common/skills/tool-failure-recovery/SKILL.md"),
}

REVIEW_HOOK_REQUIRED_COMMANDS = {
    "small-change",
    "build",
    "bugfix",
    "code-simplify",
    "commit",
    "git_commit",
    "docs",
    "docs-review",
    "feature",
    "multi-agent",
    "prd",
    "product",
    "refactor",
    "release",
    "ship",
    "spec",
    "retrospective",
    "review",
    "task",
    "workflow-setup",
}

LIGHTWEIGHT_SURFACE_REFERENCE_COMMANDS = {"commit", "git_commit"}

# A combined commit/push/PR request is one lightweight publication lifecycle.
# The commit workflow card already owns its worktree, remote, visibility, push,
# and idempotent-PR checks, so expanding every inferred concern repeats the
# same context. Any concern outside this closed family keeps normal promotion.
LIGHTWEIGHT_PUBLICATION_CONCERNS = {
    "branch",
    "commit",
    "pr",
    "pull-request",
    "push",
}

BRANCH_CLEANUP_SKILL = "common/skills/branch-cleanup/SKILL.md"
LIGHTWEIGHT_CLEANUP_CONCERNS = {"branch", "worktree"}


def _uses_fixed_cleanup_documents(command: str, concerns: list[str]) -> bool:
    """True when cleanup's one deletion contract owns the whole request."""

    return command == "cleanup" and set(concerns).issubset(
        LIGHTWEIGHT_CLEANUP_CONCERNS
    )


class RoutedDocuments(NamedTuple):
    """Everything the document phase resolved, before any of it is described.

    The route reads its documents once and then answers three questions about
    the same result: which are required, what the notes should say, and what the
    manifest carries. Passing this instead of a dozen locals is what lets those
    three stay separate functions; the fields are exactly the values that cross
    from one to the next.
    """

    routed: list[str]
    required: list[str]
    reference: list[str]
    missing: list[str]
    surface_matches: list[dict[str, object]]
    search_outcome: SearchOutcome
    search_seed_docs: list[str]
    graph_matches: list[dict[str, object]]
    # Required docs that exist only because an explicit `requires` edge named
    # them, so the route note can say whether the graph changed the reading set.
    graph_promoted: list[str]
    resolution: dict[str, object]


def _resolve_documents(
    *,
    command: str,
    platform: Optional[str],
    concerns: list[str],
    profile: object,
    request_text: str,
    surface_paths: list[str],
    advisory: bool = False,
    required_concerns: Optional[list[str]] = None,
) -> RoutedDocuments:
    """Gather every document this route gets from, in the order they compose.

    Deterministic route docs first, then the surfaces the request text and owner
    paths infer, then the search seeds, then what the graph reaches from both.
    Each stage may only add; the split into required and reference happens once,
    at the end, so no stage can quietly promote its own candidates.

    An advisory route resolves the same documents but splits them differently:
    it satisfies no gate, so the documents a route requires *because of its
    gates* are demoted to `reference_docs` and `tao-hook start` requires them
    when the real route runs. The full selection still seeds the graph and the
    missing-document check, so the two routes reach the same documents.

    `required_concerns` is the subset of `concerns` the caller named, plus the
    risk concerns inference alone is allowed to require. Any other concern only
    inferred from request keywords still routes its documents, but as
    `reference_docs`: keyword matching fires on "not a performance change" as
    readily as on a performance change, so it cannot make a document mandatory.
    """

    selection_concerns = concerns if required_concerns is None else required_concerns
    base_gates = route_gates(command)
    # surface_paths are repository-verified owners, never raw request paths.
    # Once a lookup has that anchor, searching the guidance catalog again only
    # creates unrelated reading candidates. Explicit policy selection still runs.
    owner_lookup = command == "analysis" and any(path.strip() for path in surface_paths)
    docs: list[str] = [*CORE_DOCS, *profile.docs]
    docs.extend(automatic_docs(command))
    docs.extend(
        reference
        for gate, reference in ON_DEMAND_GATE_REFERENCES.items()
        if gate in base_gates
    )
    if _uses_fixed_cleanup_documents(command, selection_concerns):
        surface_docs: list[str] = []
        surface_matches: list[dict[str, object]] = []
        search_outcome = SearchOutcome(results=[], backend="fixed-route")
        search_seed_docs: list[str] = []
        doc_graph_matches: list[dict[str, object]] = []
        graph_required: list[str] = []
        selected_sources = route_required_docs(
            command, platform, selection_concerns, profile.docs, []
        )
        owner_surface_docs = []
        advisory_sources = selected_sources
        advisory_graph_required: list[str] = []
    else:
        surface_docs, surface_matches = infer_surface_docs(
            command=command,
            platform=platform,
            request_text=request_text,
            surface_paths=surface_paths,
        )
        if owner_lookup:
            search_outcome = SearchOutcome(results=[], backend="owner-lookup")
        elif request_text.strip():
            search_outcome = search_docs_outcome(ROOT, request_text, max_results=12)
        else:
            # No request text means nothing was searched. Reporting it as an
            # empty Wikimap result told agents a search had completed.
            search_outcome = SearchOutcome(results=[], backend="not-run")
        search_seed_docs = [str(item["path"]) for item in search_outcome.results]
        # `required_surface_docs` stamps each match's selection_reason, so the
        # evidence-backed subset is read after it, not before. A verified owner
        # path and an explicit `required_priority` rule are the two reasons the
        # resolver treats as evidence rather than a keyword guess, and a rule
        # that narrows a broader one carries that priority precisely so it can
        # stand in the broader rule's place.
        eligible_surface_docs = required_surface_docs(surface_matches)
        owner_surface_docs = unique([
            str(doc)
            for match in surface_matches
            if match.get("selection_reason")
            in {"verified_owner_path", "explicit_required_priority", "independent_change"}
            for doc in match.get("docs", [])
        ])
        selected_sources = route_required_docs(
            command, platform, selection_concerns, profile.docs, eligible_surface_docs,
            owner_surface_docs=owner_surface_docs,
        )
        # Withholding gate documents frees budget that lower tiers would refill,
        # which made an advisory route require documents the real route leaves
        # as references. Advisory reading is never more than the real route's.
        advisory_sources = (
            [
                doc
                for doc in route_required_docs(
                    command, platform, selection_concerns, profile.docs,
                    eligible_surface_docs, advisory=True,
                    owner_surface_docs=owner_surface_docs,
                )
                if doc in selected_sources
            ]
            if advisory
            else selected_sources
        )
        if command == "analysis":
            # Owner discovery is not implementation intent. Explicit required
            # rules still augment the compact lookup reading contract.
            for match in surface_matches:
                priority = match.get("required_priority", 0)
                explicit = type(priority) is int and priority > 0
                match["required_eligible"] = explicit
                match["selection_reason"] = (
                    "explicit_required_priority" if explicit else "lookup_reference_candidate"
                )
                if explicit:
                    explicit_docs = resolve_guidance_docs(ROOT, match.get("docs", []))
                    selected_sources = unique([*selected_sources, *explicit_docs])
                    advisory_sources = unique([*advisory_sources, *explicit_docs])
        graph_seeds = (selected_sources if command == "analysis" else
                       unique([*selected_sources, *surface_docs, *search_seed_docs]))
        doc_graph_matches = expand_doc_matches(
            ROOT,
            graph_seeds,
            max_depth=1,
            max_docs=24,
            relation_prefixes=("frontmatter:", "markdown:", "compat:"),
        )
        # A requires edge is authoritative only when its source was selected.
        # Search hits do not get to make their own dependencies mandatory.
        requires_matches = [
            (match, set(resolve_guidance_docs(ROOT, [str(match["source"])])))
            for match in doc_graph_matches
            if str(match.get("relation", "")).startswith("frontmatter:requires")
        ]
        graph_required = graph_required_docs(
            match for match, sources in requires_matches if sources & set(selected_sources)
        )
        # An advisory route requires only what its own required sources require;
        # a demoted gate document's dependencies are demoted with it.
        advisory_graph_required = (
            graph_required_docs(
                match for match, sources in requires_matches
                if sources & set(advisory_sources)
            )
            if advisory
            else graph_required
        )
        if owner_lookup:
            # Keep mandatory sources/dependencies and explicit concerns below;
            # do not offer the generic catalog or incidental graph neighbors as
            # a second reading queue after the code owner has been resolved.
            docs = list(selected_sources)
            surface_docs = []
            doc_graph_matches = [
                match for match in doc_graph_matches if str(match["path"]) in graph_required
            ]
    graph_docs = [str(match["path"]) for match in doc_graph_matches]
    docs.extend(surface_docs)
    docs.extend(search_seed_docs)
    docs.extend(graph_docs)

    if platform and not owner_lookup:
        docs.extend(PLATFORMS[platform])

    for concern in concerns:
        docs.extend(CONCERNS.get(concern, ()))
        docs.extend(CONCERN_REFERENCE_DOCS.get(concern, ()))
        if platform:
            docs.extend(PLATFORM_CONCERNS.get((platform, concern), ()))

    routed_docs = unique(canonical_doc_path(doc) for doc in docs)
    full_required = unique([*selected_sources, *graph_required])
    if advisory:
        required_docs = unique([*advisory_sources, *advisory_graph_required])
        graph_promoted = [
            doc for doc in advisory_graph_required if doc not in advisory_sources
        ]
    else:
        required_docs = full_required
        graph_promoted = [doc for doc in graph_required if doc not in selected_sources]
    # Every routed document stays reachable in exactly one of the two lists.
    # Filtering out entrypoints whose reference was promoted would read better,
    # but it breaks the invariant that `required_docs | reference_docs` covers
    # everything the router resolved, which callers rely on. The full required
    # set is part of that: a document an advisory route demoted may be a
    # resolved reference that no routed entrypoint names directly.
    manifest_docs = unique([*routed_docs, *full_required])
    required_set = set(required_docs)
    reference_docs = [doc for doc in manifest_docs if doc not in required_set]
    missing = [doc for doc in manifest_docs if not (ROOT / doc).exists()]
    return RoutedDocuments(
        routed=routed_docs,
        required=required_docs,
        reference=reference_docs,
        missing=missing,
        surface_matches=surface_matches,
        search_outcome=search_outcome,
        search_seed_docs=search_seed_docs,
        graph_matches=doc_graph_matches,
        graph_promoted=graph_promoted,
        resolution=_document_resolution(
            search_outcome=search_outcome,
            search_seed_docs=search_seed_docs,
            missing=missing,
        ),
    )


def _route_notes(
    *,
    command: str,
    platform: Optional[str],
    concerns: list[str],
    profile: object,
    documents: RoutedDocuments,
    request_classification: Optional[dict[str, object]],
    request_classified: bool,
    classification_evidence: str,
) -> list[str]:
    """Say, in the route's own words, how it reached the documents it reached.

    Every note here is derived from a decision already made above; none of them
    changes one. Keeping them out of the resolver is what makes that readable --
    a reader looking for what the route *does* no longer walks 70 lines of what
    it *says*.
    """

    notes = list(profile.notes)
    if command == "product" and not platform:
        notes.append("Select at least one platform card before writing ARD.")
    for concern in concerns:
        if concern in BASELINE_CONCERNS:
            notes.append(f"Concern `{concern}` is {BASELINE_CONCERNS[concern]}")
    if request_classification:
        notes.append(
            "Request classification is attached to this route; keep it as evidence for the request intake or classify request gate."
        )
    elif request_classified:
        notes.append(
            "Caller asserted the request was already classified or answered; record that evidence for the request intake gate."
        )
        if classification_evidence:
            notes.append("Request classification evidence was provided to the route command.")
    if documents.reference:
        notes.append(
            "Read `required_docs` before work. Apply the Need-Driven Reading Contract "
            "in common/skills/agent-operating-skill/SKILL.md to optional reference "
            "reads: name an unresolved in-scope question and stop when the owner, "
            "constraints, and nearest verification are known."
        )
    notes.extend(_surface_notes(command, documents.surface_matches))
    notes.extend(
        _document_search_notes(
            documents.search_seed_docs, documents.resolution, documents.search_outcome
        )
    )
    if documents.graph_promoted:
        notes.append(
            "Expanded related candidate docs from the local document graph; explicit `requires_docs` edges become required docs."
        )
    elif documents.graph_matches:
        # Claiming an edge promoted something when none did sends a reader
        # looking in `required_docs` for a graph document that is not there.
        notes.append(
            "Expanded related candidate docs from the local document graph; no `requires_docs` edge promoted a required doc, so these neighbors stay on-demand reference candidates."
        )
    return notes


def _surface_notes(command: str, surface_matches: list[dict[str, object]]) -> list[str]:
    """Which of the three ways a surface match can be promoted actually applied."""

    if not surface_matches:
        return []
    if command in LIGHTWEIGHT_SURFACE_REFERENCE_COMMANDS:
        return [
            "Kept surface-inferred docs in `reference_docs` for the lightweight commit route; explicit concerns can still promote required guidance."
        ]
    if any(match.get("type") == "path_surface" for match in surface_matches):
        return [
            "Promoted required docs from semantic request intent or verified owner paths using `workflow-doc-surfaces.json`."
        ]
    return [
        "Matched semantic request-intent guidance. Code routes still require work-surface owner proof before task-specific reading or edits."
    ]


def _document_search_notes(
    search_seed_docs: list[str],
    resolution: dict[str, object],
    search_outcome: SearchOutcome,
) -> list[str]:
    """What the search found, and which of its outcomes are terminal."""

    if search_outcome.backend == "fixed-route":
        return [
            "Skipped natural-language document search for the fixed cleanup route; "
            "its branch-cleanup contract owns the complete safety decision."
        ]
    if search_outcome.backend == "owner-lookup":
        return [
            "Skipped broad document search for a repository-verified lookup owner. "
            "Read the answering code/contract and only necessary callers; retain "
            "explicit required guidance and dependencies. Reopen discovery only "
            "for an unresolved question, not to fill an optional reading queue."
        ]

    notes: list[str] = []
    if search_seed_docs:
        notes.append(
            "Wikimap supplied natural-language seed documents to the router; seeds remain reference candidates unless an explicit route rule or required relation promotes them."
        )
    elif resolution["status"] == "no_matches":
        notes.append(
            "Natural-language document search completed with no matching project documents. This is a terminal no-source outcome, not a retry condition; continue with the deterministic required_docs and record the no-source decision."
        )
    if resolution["status"] == "invalid_manifest":
        notes.append(
            "The route manifest names missing documents. Stop once with the missing paths; do not retry document discovery until the manifest or files are repaired."
        )
    if search_outcome.fallback_reason:
        notes.append(
            "Wikimap was unavailable for this route, so the local legacy scorer supplied recovery candidates."
        )
    return notes



# Selection reasons, strongest first. The order is the attribution order below:
# a document selected by more than one rule is reported under the strongest one,
# because that is the rule that would still require it if the others went away.
PLATFORM_DEFAULT_REASON = "platform_default"


def _required_doc_reasons(
    *,
    command: str,
    platform: Optional[str],
    concerns: list[str],
    required_concerns: list[str],
    inferred_concerns: set[str],
    profile: object,
    documents: RoutedDocuments,
) -> list[dict[str, str]]:
    """Say, for each required document, which rule made it mandatory.

    Nothing here selects anything; it re-derives the attribution from the same
    registries the selection walked. Keeping it derived is the point: a reason
    that could drift from the decision would be worse than no reason at all.

    It exists to make one failure mode visible. A document whose only reason is
    `platform_default` is required because the caller named a platform, not
    because this request touches it -- an Android JSON parsing fix pulling 25 KB
    of app architecture. That is a document-boundary problem, not a selection
    bug: the card bundles the short contract every Android change needs with
    detailed Navigation, Compose and module procedures it does not. Reporting it
    per document is what turns "the route reads too much" into a list of cards
    to split.
    """

    def resolved(docs) -> set[str]:
        return set(resolve_guidance_docs(ROOT, [canonical_doc_path(d) for d in docs]))

    gates = set(route_gates(command))
    core = resolved(CORE_REQUIRED_DOCS)
    command_docs = resolved(COMMAND_REQUIRED_DOCS.get(command, profile.docs))
    gate_docs = resolved(
        [doc for gate, doc in GUARANTEED_GATE_DOCS.items() if gate in gates]
    ) | resolved(automatic_docs(command))
    if "review hook" in gates:
        gate_docs |= resolved(REVIEW_HOOK_GATE_DOCS)
    surface_docs: dict[str, str] = {}
    for match in documents.surface_matches:
        for doc in resolved(match.get("docs", [])):
            surface_docs.setdefault(doc, str(match.get("name", "request_surface")))
    graph_docs = set(documents.graph_promoted)
    platform_docs = resolved(PLATFORMS[platform]) if platform else set()
    discipline = resolved(CODE_WORK_REQUIRED_DOCS)

    # Only a concern that is allowed to require documents can be the reason one
    # is required. A concern that was merely inferred and is not a risk concern
    # routes its cards as references, so crediting it here would blame the wrong
    # rule: a SwiftUI request's Swift cards arrive through the work surface, and
    # reporting them as concern-driven would hide that the surface rule is what
    # to tune.
    concern_docs: dict[str, str] = {}
    for concern in concerns:
        if concern not in required_concerns:
            continue
        kind = (
            "concern_named" if concern not in inferred_concerns
            else "concern_inferred_risk"
        )
        for doc in resolved(CONCERNS.get(concern, ())):
            concern_docs.setdefault(doc, f"{kind}:{concern}")
        if platform:
            for doc in resolved(PLATFORM_CONCERNS.get((platform, concern), ())):
                concern_docs.setdefault(doc, f"{kind}:{concern}")

    reasons: list[dict[str, str]] = []
    for doc in documents.required:
        if doc in core:
            reason = "core_reading_contract"
        elif doc in command_docs:
            reason = f"command_workflow:{command}"
        elif doc in concern_docs:
            reason = concern_docs[doc]
        elif doc in surface_docs:
            reason = f"work_surface:{surface_docs[doc]}"
        elif doc in graph_docs:
            reason = "requires_edge"
        elif doc in gate_docs:
            reason = "gate_contract"
        elif doc in platform_docs:
            reason = f"{PLATFORM_DEFAULT_REASON}:{platform}"
        elif doc in discipline:
            reason = "code_work_discipline"
        else:
            reason = "route_profile"
        reasons.append({"doc": doc, "reason": reason})
    return reasons


def resolve_docs(
    command: str,
    platform: Optional[str],
    concerns: list[str],
    request_classification: Optional[dict[str, object]] = None,
    request_classified: bool = False,
    classification_evidence: str = "",
    request_text: str = "",
    surface_paths: Optional[list[str]] = None,
    project_root: Path | None = None,
    advisory: bool = False,
    inferred_concerns: Optional[list[str]] = None,
) -> dict[str, object]:
    profile = COMMANDS[command]
    inferred = set(inferred_concerns or [])
    required_concerns = [
        concern
        for concern in concerns
        # A risk concern is required on inference alone. Everything else
        # waits to be named; RISK_CONCERNS_REQUIRED_WHEN_INFERRED says which
        # concerns are on that list and why release is not.
        if concern not in inferred
        or concern in RISK_CONCERNS_REQUIRED_WHEN_INFERRED
    ]
    documents = _resolve_documents(
        command=command,
        platform=platform,
        concerns=concerns,
        profile=profile,
        request_text=request_text,
        surface_paths=surface_paths or [],
        advisory=advisory,
        required_concerns=required_concerns,
    )
    routed_docs = documents.routed
    required_docs = documents.required
    reference_docs = documents.reference
    missing = documents.missing
    surface_matches = documents.surface_matches
    search_outcome = documents.search_outcome
    search_seed_docs = documents.search_seed_docs
    doc_graph_matches = documents.graph_matches
    document_resolution = documents.resolution

    graphify_context = graphify_route_context(
        concerns=concerns,
        surface_matches=surface_matches,
        project_root=project_root,
    )
    graphify_requested = bool(graphify_context["requested"])
    gates = route_gates(command, graphify_required=graphify_requested)
    if command not in QUESTION_ROUTE_COMMANDS:
        gates = ["request intake", *gates]

    notes = _route_notes(
        command=command,
        platform=platform,
        concerns=concerns,
        profile=profile,
        documents=documents,
        request_classification=request_classification,
        request_classified=request_classified,
        classification_evidence=classification_evidence,
    )
    graphify_readiness = graphify_context["readiness"]
    blocking = list(graphify_context["blocking"])
    concern_set = set(concerns)
    if (
        command in {"release", "ship"}
        and concern_set & {"pull-request", "push"}
        and not concern_set & {"release", "shipping", "deploy", "deployment", "tag"}
    ):
        blocking.append(
            "branch push and pull-request publication use the lightweight `commit` route; "
            "`release` and `ship` are reserved for release artifacts, deployment, tags, or rollout"
        )
    if command == "small-change" and set(concerns) & {
        "security", "auth", "agent-credentials", "permissions", "persistence", "database",
        "migration", "api", "dependency", "dependencies", "release", "deploy", "deployment",
        "billing", "payment", "architecture", "infrastructure",
    }:
        blocking.append("small-change excludes risk-sensitive concerns; select the matching full route")
    notes.extend(graphify_context["notes"])

    route = {
        "lifecycle_version": 2,
        "root": str(ROOT),
        "command": command,
        "platform": platform,
        "concerns": concerns,
        "request_classification": request_classification,
        "request_classified": request_classified,
        "classification_evidence": classification_evidence,
        "docs": routed_docs,
        "required_docs": required_docs,
        "reference_docs": reference_docs,
        "gates": gates,
        "hooks": route_hooks(command),
        "skill_feedback": skill_feedback_policy(command),
        "repair_cycle_limit": REPAIR_CYCLE_LIMIT,
        "repair_policy": REPAIR_POLICY,
        "resume_scope": RESUME_SCOPE,
        "stop_condition": REPAIR_STOP_CONDITION,
        "parallel_execution": parallel_execution_plan(command, gates),
        "gate_ledger": [
            {
                "gate": gate,
                "status": "not_started",
                "signal": "",
                "evidence": "",
            }
            for gate in gates
        ],
        "notes": notes,
        "missing": missing,
        "blocking": blocking,
    }
    route["required_doc_reasons"] = _required_doc_reasons(
        command=command,
        platform=platform,
        concerns=concerns,
        required_concerns=required_concerns,
        inferred_concerns=inferred,
        profile=profile,
        documents=documents,
    )
    if command == "analysis":
        route["reading_scope"] = {"mode": "lookup", "guidance": LOOKUP_READING_GUIDANCE}
    if surface_paths:
        route["surface_paths"] = surface_paths
    if surface_matches:
        route["doc_surface_matches"] = surface_matches
    if doc_graph_matches:
        route["doc_graph_matches"] = doc_graph_matches
    route["document_search"] = {
        "status": document_resolution["status"],
        "terminal": document_resolution["terminal"],
        "reason": document_resolution["reason"],
        "backend": search_outcome.backend,
        "backend_version": search_outcome.backend_version,
        "fallback_reason": search_outcome.fallback_reason,
        "weak": search_outcome.weak,
        "partial": search_outcome.partial,
        "fused": search_outcome.fused,
        "candidates": search_seed_docs,
    }
    if graphify_readiness:
        route["target_project_graphify"] = graphify_readiness
    return route


def _document_resolution(
    *,
    search_outcome: SearchOutcome,
    search_seed_docs: list[str],
    missing: list[str],
) -> dict[str, object]:
    """Make document-discovery completion explicit for callers and hooks.

    An empty successful search is useful information: it means there is no
    project source to read for this request, not that the router should spin.
    Missing deterministic route documents are different; they are a malformed
    manifest and must fail once with concrete repair targets.
    """

    if missing:
        return {
            "status": "invalid_manifest",
            "terminal": True,
            "reason": "Route references missing document paths.",
        }
    if search_outcome.backend == "fixed-route":
        return {
            "status": "resolved",
            "terminal": True,
            "reason": "The fixed cleanup route uses its deterministic safety contract.",
        }
    if search_outcome.backend == "owner-lookup":
        return {
            "status": "resolved",
            "terminal": True,
            "reason": "A verified lookup owner makes broad document search unnecessary; required guidance is preserved.",
        }
    if search_outcome.backend == "not-run":
        return {
            "status": "not_searched",
            "terminal": True,
            "reason": "No request text was given, so natural-language document search did not run.",
        }
    if not search_seed_docs:
        source = "Wikimap" if search_outcome.backend == "wikimap" else "local recovery search"
        return {
            "status": "no_matches",
            "terminal": True,
            "reason": f"{source} completed without matching project documents.",
        }
    return {
        "status": "resolved",
        "terminal": True,
        "reason": "Natural-language document discovery returned candidate documents.",
    }


# Gate -> guidance mapping for gates that `automatic_docs` does not own.  The
# review hook is added by `route_gates`, not by `automatic_gates`, so its
# contract document was never reachable from the gate spine.  That is the gap
# that let a route enforce the hook's structure-evidence labels while never
# putting the document defining those labels in front of the agent.
# Gates that actively judge the agent's submission, mapped to the document
# defining the evidence each one demands.  These are guaranteed for any route
# that enforces the gate and are never dropped by the byte budget: a route that
# enforces a gate while withholding its contract is precisely the defect this
# change exists to fix, where the review hook rejected work for labelled
# structure evidence the route never put in front of the agent.
GUARANTEED_GATE_DOCS = {
    "review hook": REVIEW_AND_COMMIT_ENTRYPOINT,
    MULTI_AGENT_GATE: MULTI_AGENT_ENTRYPOINT,
    WORK_SURFACE_RESOLUTION_GATE: SOURCE_DRIVEN_REFERENCE,
}

# Detailed gate references remain routed and reachable, but the concise
# substantive entrypoints above carry the always-needed decision/evidence
# contract. Loading these references for every ordinary code task repeats the
# same broad context before GPT can inspect the actual project. Commands whose
# purpose is the gate itself still require the corresponding detail.
ON_DEMAND_GATE_REFERENCES = {
    "review hook": REVIEW_AND_COMMIT_REFERENCE,
    MULTI_AGENT_GATE: MULTI_AGENT_REFERENCE,
}

DETAIL_REQUIRED_COMMANDS = {
    REVIEW_AND_COMMIT_REFERENCE: {"docs-review", "review"},
    MULTI_AGENT_REFERENCE: {"multi-agent"},
}

# These routes already completed intake at start. Keep their own workflow and
# request-specific guidance, not the generic gate/disciplines tier walk.
FOCUSED_READING_COMMANDS = {"docs", "prd", "task"}
# The bugfix/refactoring procedures use the compact ambiguity evidence card.
# Build and feature share a development procedure and must not diverge here.
COMPACT_AMBIGUITY_COMMANDS = {"bugfix", "refactor", "code-simplify"}

REVIEW_HOOK_GATE_DOCS = (
    GUARANTEED_GATE_DOCS["review hook"],
    "common/skills/code-review/SKILL.md",
)

CODE_WORK_COMMANDS_REQUIRING_DISCIPLINE = {
    "build",
    "bugfix",
    "code-simplify",
    "feature",
    "product",
    "refactor",
    "task",
    "workflow-setup",
}

# Selection budget.  Resolving entrypoints to references multiplies the bytes
# behind each required doc roughly fivefold, so membership can no longer be a
# union of every list that mentions the command.  These caps keep a route's
# mandatory reading near its previous byte cost while the documents behind it
# carry actual rules.  Docs that do not fit stay reachable as `reference_docs`.
#
# The budget covers only the *selectable* tiers. `CORE_REQUIRED_DOCS` and the
# concise gate contracts are exempt so request-specific guidance cannot crowd
# them out. The target project's root instructions are loaded before routing;
# Tao's own broad AGENTS.md remains reachable as reference context instead of
# being charged to every target-project task.
REQUIRED_DOC_BUDGET_BYTES = 30_000
# The concise core and guaranteed contracts consume four slots on ordinary
# code routes. Eight preserves the previous four request-specific slots after
# replacing the three always-loaded detailed documents with lazy references.
MAX_REQUIRED_DOCS = 8
# Evidence-backed requirements are not truncated: independent change domains
# may need more than one rule's documents. Budgets constrain optional tiers.


def route_required_docs(
    command: str,
    platform: Optional[str],
    concerns: list[str],
    profile_docs: tuple[str, ...],
    surface_docs: list[str] | None = None,
    *,
    advisory: bool = False,
    owner_surface_docs: list[str] | None = None,
) -> list[str]:
    """Select the documents a route requires, and report what selecting cost.

    Profiling a start put 88 ms here, second only to the wikimap, and almost
    all of it in reading and normalising document bodies to decide which are
    pointer entrypoints. None of it was visible in the recorded stages.

    `advisory` selects for orientation, not execution: the core reading contract
    and explicit concerns, platform or owner guidance. The suggested command
    alone is not evidence that its procedure is needed before a request exists.
    """

    with stage("required_docs"):
        return _route_required_docs(
            command, platform, concerns, profile_docs, surface_docs,
            advisory=advisory, owner_surface_docs=owner_surface_docs,
        )


def _route_required_docs(
    command: str,
    platform: Optional[str],
    concerns: list[str],
    profile_docs: tuple[str, ...],
    surface_docs: list[str] | None = None,
    *,
    advisory: bool = False,
    owner_surface_docs: list[str] | None = None,
) -> list[str]:
    if advisory:
        # No task is being executed yet. Do not pre-read a suggested workflow
        # merely because its command name is in the prompt hook configuration.
        #
        # The platform card set is not selected here either. It is identical for
        # every route on that platform, so it says nothing about this request --
        # and an advisory route has no request text to say it with. Naming
        # `--platform android` before a field lookup required 28.5 KB of Android
        # architecture that the lookup never needed. Platform guidance still
        # becomes required the moment something request-specific asks for it: a
        # concern the caller named carries its PLATFORM_CONCERNS cards through
        # `_unbudgeted_required_docs`, and a repository-verified owner path
        # carries its own through `surface_docs`. Everything else stays one link
        # away in `reference_docs`.
        return unique([*_unbudgeted_required_docs(platform, concerns, set(), advisory=True),
                       *resolve_guidance_docs(ROOT, surface_docs or [])])
    compact = _compact_required_docs(command, platform, concerns)
    if compact is not None:
        # A compact set is the command's whole reading contract, already small;
        # it has no separate gate tier to withhold.
        return compact
    gates = set(route_gates(command))
    selected = _unbudgeted_required_docs(platform, concerns, gates, advisory=advisory)
    if command in COMPACT_AMBIGUITY_COMMANDS:
        # Reserve an enforced contract before spending optional capacity.
        # Named concerns remain unbudgeted; never append another budgeted
        # document after the selection cap has already been reached.
        selected = unique([*selected, "workflows/skills/ambiguity-gate/SKILL.md"])
    # What the route *is* is not the budget's to spend. The command tier was the
    # first thing the tier walk paid for, so anything selected ahead of it could
    # take the last slot and drop the command's own procedure: a concern the
    # caller named, or -- since risk concerns became requirable on inference --
    # a concern the request only implied. "log in the error to the console"
    # infers `auth` and cost the bugfix route its debugging reference; the start
    # hook for this very repair required four auth and security cards and no
    # bugfix card at all. An inference must not outrank a certainty, so the
    # command's documents are selected before the budget rather than out of it.
    command_docs = [
        doc
        for doc in resolve_guidance_docs(
            ROOT,
            [canonical_doc_path(doc) for doc in COMMAND_REQUIRED_DOCS.get(command, ())],
        )
        if doc not in selected
    ]
    selected = unique([*selected, *command_docs])
    # What the change touches, proven by a repository-verified owner path, is
    # the most specific evidence the router has. Leaving it in the tier walk
    # meant it queued behind the core, gate and command contracts and then
    # competed with the platform card set for the last slot -- so an Android DTO
    # parsing fix got 25 KB of app architecture and none of the contract,
    # boundary-value, error or test guidance the change actually needed.
    owner_docs = [
        doc
        for doc in resolve_guidance_docs(
            ROOT, [canonical_doc_path(doc) for doc in (owner_surface_docs or [])]
        )
        if doc not in selected
    ]
    selected = unique([*selected, *owner_docs])
    tiers = _required_doc_tiers(
        command, platform, profile_docs, surface_docs, gates, advisory=advisory
    )
    selected = _select_within_budget(
        command, tiers, selected,
        explicit_docs=resolve_guidance_docs(ROOT, surface_docs or []),
        # Moving the command tier out of the eviction path must not also hand
        # its budget to the tiers below it. Left unspent, that share refilled
        # with gate and discipline references: review and docs-review grew from
        # 46.6 KB to 69.5 KB, triage from 33.6 KB to 49.4 KB, and seven routes
        # gained 115 KB between them. The core contract and the concise gate
        # contracts stay exempt as they always were; only this tier moved, so
        # only this tier's bytes come back.
        prespent_bytes=sum(
            doc_size(ROOT, doc) for doc in (*command_docs, *owner_docs)
        ),
    )
    if command in FOCUSED_READING_COMMANDS:
        # This compact gate contract must not crowd out an owner-specific
        # entrypoint's actual reference at the selection boundary.
        selected = unique([*selected, "workflows/skills/ambiguity-gate/SKILL.md"])
    return selected


def _compact_required_docs(
    command: str, platform: Optional[str], concerns: list[str]
) -> list[str] | None:
    """The routes whose required set is compact, or None for the full policy."""

    # A simple investigation has no work-producing gates. Keep the concise
    # operating entrypoint available without charging every analysis for the
    # broad Tao repository instructions in addition to its target project's
    # already-loaded root instructions.
    if command == "analysis":
        return [OPERATING_SKILL]

    # Cleanup exists only to remove Git state already absorbed by an integration
    # branch. Its branch-cleanup reference contains all ownership, protected-ref,
    # merge, worktree-state, recovery, and reporting rules; general concern and
    # retrospective references repeat context without adding a deletion decision.
    if _uses_fixed_cleanup_documents(command, concerns):
        cleanup_docs = resolve_guidance_docs(ROOT, [BRANCH_CLEANUP_SKILL])
        return unique([OPERATING_SKILL, *cleanup_docs])

    # Commit, push, and pull-request publication after implementation share
    # one compact contract. The commit workflow reference already covers the
    # staged diff, worktree, remote, visibility, push, and idempotent PR checks.
    #
    # A concern outside that family is a risk the caller named, and it is
    # answered with that concern's own documents rather than by abandoning the
    # compact set. Falling through to the full policy instead meant one extra
    # `--concern verification` returned 11 documents and 91KB where the compact
    # route returns 3 and 14KB -- and six of the eight it added were the tier
    # walk's, not the concern's: branch-strategy twice, worktree-hygiene, the
    # review-and-commit reference. The caller asked about verification and was
    # handed branch strategy, which is the opposite of honouring the signal.
    if command == "small-change":
        return unique([OPERATING_SKILL, REVIEW_AND_COMMIT_ENTRYPOINT,
                       "common/skills/agent-operating-skill/references/small-change.md",
                       *_named_concern_docs(platform, concerns)])
    if command in LIGHTWEIGHT_SURFACE_REFERENCE_COMMANDS:
        commit_docs = resolve_guidance_docs(
            ROOT, ["common/skills/commit-workflow/SKILL.md"]
        )
        compact = [OPERATING_SKILL, REVIEW_AND_COMMIT_ENTRYPOINT, *commit_docs]
        named = _named_concern_docs(platform, concerns)
        return unique([*compact, *named])
    return None


def _named_concern_docs(platform: Optional[str], concerns: list[str]) -> list[str]:
    """The documents a caller's own concerns ask for, and nothing besides.

    Concerns inside the publication family add nothing: the commit workflow
    reference already covers the staged diff, worktree, remote, visibility,
    push, and idempotent PR checks that `commit`, `push`, `pr` and `branch`
    would each point at.
    """

    named: list[str] = []
    for concern in concerns:
        if concern in LIGHTWEIGHT_PUBLICATION_CONCERNS:
            continue
        named.extend(CONCERNS.get(concern, ()))
        if platform:
            named.extend(PLATFORM_CONCERNS.get((platform, concern), ()))
    if not named:
        return []
    return resolve_guidance_docs(
        ROOT, unique(canonical_doc_path(doc) for doc in named)
    )


def _required_doc_tiers(
    command: str,
    platform: Optional[str],
    profile_docs: tuple[str, ...],
    surface_docs: list[str] | None,
    gates: set[str],
    *,
    advisory: bool = False,
) -> list[list[str]]:
    """The priority order the budget is spent down, most specific first."""

    # Tiers are ordered by how directly the document is tied to something this
    # route actually activates.  Everything above the budget line becomes
    # required; everything below stays available as `reference_docs`.
    tiers: list[list[str]] = []

    # 1. What the route *is*: its own command skill. A command with its own
    #    entry was already selected ahead of the budget and is skipped here;
    #    this still carries the profile fallback for the commands without one.
    tiers.append(list(COMMAND_REQUIRED_DOCS.get(command, profile_docs)))

    # 2. What this particular request touches.  Surface and graph docs are
    #    matched against the request text and the actual dirty paths, so they
    #    are more specific than both the platform card set below -- which is
    #    identical for every route on that platform -- and the gate spine, which
    #    is identical for every route of this command.  An Android UI request
    #    needs the Compose card ahead of the generic Android card set.
    #    A local commit request reviews work that has already been implemented,
    #    so its dirty-path guidance stays in reference_docs rather than becoming
    #    mandatory implementation reading.
    if command not in LIGHTWEIGHT_SURFACE_REFERENCE_COMMANDS:
        tiers.append(list(surface_docs or []))

    # 4. The platform card set the route selected.
    tiers.append(list(PLATFORMS[platform]) if platform else [])

    if command in FOCUSED_READING_COMMANDS:
        # Keep the concise ambiguity evidence contract. Full question-drill
        # guidance remains available on demand; explicit concerns are selected
        # separately, before this budget, and cannot be demoted here.
        return tiers

    if advisory:
        # An advisory route enforces nothing, so the evidence contracts of the
        # gates it lists and the code-work discipline for the work it does not
        # start stay reference docs until `tao-hook start` routes for real.
        return tiers

    # 5. What the route will enforce: the gates it runs, mapped to the documents
    #    that define their evidence contracts.
    gate_docs = list(automatic_docs(command))
    if "review hook" in gates:
        gate_docs.extend(REVIEW_HOOK_GATE_DOCS)
    tiers.append(gate_docs)

    # 6. General code-work discipline, for routes that produce code.
    if command in CODE_WORK_COMMANDS_REQUIRING_DISCIPLINE:
        tiers.append(list(CODE_WORK_REQUIRED_DOCS))
    return tiers


def _unbudgeted_required_docs(
    platform: Optional[str],
    concerns: list[str],
    gates: set[str],
    *,
    advisory: bool = False,
) -> list[str]:
    """What every route gets before the budget starts counting."""

    # The operating entrypoint is not subject to the budget: every route gets
    # the small progressive-disclosure contract, and a route with no required
    # docs at all would make the source docs gate vacuous. Its broad reference
    # and Tao's AGENTS.md stay in `reference_docs`; the active target project's
    # own root instructions were already loaded before this route started.
    selected = unique(canonical_doc_path(doc) for doc in CORE_REQUIRED_DOCS)

    # Active gates receive an unbudgeted contract. Review and multi-agent use
    # substantive entrypoints that state the machine-checked evidence and
    # decision rules; work-surface resolution keeps its detailed reference
    # because its generated entrypoint carries no owner-proof procedure.
    # An advisory route runs none of those gates, so it guarantees none of them.
    guaranteed = [
        doc for gate, doc in GUARANTEED_GATE_DOCS.items()
        if gate in gates and not advisory
    ]
    selected.extend(
        doc
        for doc in unique(canonical_doc_path(doc) for doc in guaranteed)
        if doc not in selected
    )

    # Concerns the caller named are also exempt after the compact publication
    # family handled above. An operator naming a separate risk such as security
    # or tag publication is stating that risk directly, and silently demoting
    # it to optional context is the worst failure available here. Concern card
    # lists are short, so this does not reopen the union-of-everything problem.
    named: list[str] = []
    for concern in concerns:
        named.extend(CONCERNS.get(concern, ()))
        if platform:
            named.extend(PLATFORM_CONCERNS.get((platform, concern), ()))
    selected.extend(
        doc
        for doc in unique(
            resolve_guidance_docs(ROOT, [canonical_doc_path(doc) for doc in named])
        )
        if doc not in selected
    )
    return selected


def _select_within_budget(
    command: str, tiers: list[list[str]], selected: list[str],
    *, explicit_docs: list[str] | None = None, prespent_bytes: int = 0,
) -> list[str]:
    """Spend the budget down the tiers and stop, rather than skipping past.

    `prespent_bytes` is what a tier selected before this call already spent.
    Only the command tier is prespent: the core contract and the gate contracts
    are exempt from the byte budget by design, and were before the command tier
    moved out of the walk.
    """

    used = prespent_bytes

    # Selection is a strict prefix of the priority order.  The budget *stops*
    # selection rather than skipping over individual documents: skipping would
    # invert the ranking, because references vary from 2 KB to 47 KB and the
    # most specific match is often the largest.  A compose request would then
    # drop the 38 KB Compose card and admit smaller, less relevant cards behind
    # it.  The document that crosses the budget is admitted before stopping, so
    # the highest-priority match is never starved and overshoot is bounded to
    # one document.
    for tier in tiers:
        candidates = unique(
            resolve_guidance_docs(ROOT, [canonical_doc_path(doc) for doc in tier])
        )
        for doc in candidates:
            if doc in selected:
                continue
            if (doc == "workflows/skills/ambiguity-gate/references/current-guidance.md"
                    and command in COMPACT_AMBIGUITY_COMMANDS
                    and doc not in (explicit_docs or [])):
                # The compact evidence contract is guaranteed separately.
                # Detailed blocker discovery needs an actual ambiguity task,
                # not spare capacity. This says nothing about later documents:
                # they retain their own gate, owner and budget eligibility.
                # Explicit concerns and requires are selected outside this budget.
                continue
            if (
                doc in DETAIL_REQUIRED_COMMANDS
                and command not in DETAIL_REQUIRED_COMMANDS[doc]
            ):
                continue
            if len(selected) >= MAX_REQUIRED_DOCS or used >= REQUIRED_DOC_BUDGET_BYTES:
                return selected
            size = doc_size(ROOT, doc)
            selected.append(doc)
            used += size
    return selected


def route_gates(command: str, *, graphify_required: bool = False) -> list[str]:
    gates = add_automatic_gates(command, list(COMMANDS[command].gates))
    if graphify_required and "graphify readiness" not in gates:
        for anchor in ("verify", "verification", "handoff", "report"):
            if anchor in gates:
                gates.insert(gates.index(anchor), "graphify readiness")
                break
        else:
            gates.append("graphify readiness")
    if command not in REVIEW_HOOK_REQUIRED_COMMANDS or "review hook" in gates:
        return gates

    for anchor in (RETROSPECTIVE_CHECK_GATE, "commit readiness", "handoff", "report"):
        if anchor in gates:
            gates.insert(gates.index(anchor), "review hook")
            return gates
    gates.append("review hook")
    return gates


def route_hooks(command: str) -> list[dict[str, object]]:
    launcher = str(stable_launcher_path())
    review_required = command in REVIEW_HOOK_REQUIRED_COMMANDS
    read_only = " --read-only" if command == "analysis" else ""
    hooks: list[dict[str, object]] = [
        {
            "hook": "start",
            "required": True,
            "when": "before edits, reviews, commits, or completion reports",
            "command": (
                f"{launcher} start "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE> "
                f"--command {command} --request \"<USER_REQUEST>\"{read_only}"
            ),
        },
    ]
    hooks.append(
        {
            "hook": "review",
            "required": review_required,
            "when": _review_hook_timing(review_required),
            "command": _review_hook_command(command),
        }
    )
    if command in RETROSPECTIVE_CHECK_COMMANDS:
        hooks.extend(_retrospective_hooks(launcher))
    hooks.append(
        {
            "hook": "finish",
            "required": True,
            "when": ("after verification and review, before final report" if command == "small-change"
                     else "after retrospective check and before final report, commit, release, or handoff"),
            "command": (
                f"{launcher} finish "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE>"
            ),
        }
    )
    return hooks


def _retrospective_hooks(launcher: str) -> list[dict[str, object]]:
    return [
        {
            "hook": SKILL_FEEDBACK_HOOK,
            "required": False,
            "when": (
                "when the required retrospective check records reusable_gap; run in the "
                "same closeout before finish"
            ),
            "command": (
                f"{launcher} {SKILL_FEEDBACK_HOOK} "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE> "
                "--skill-feedback-outcome observed --skill-id <safe_skill_slug> "
                "--feedback-signal <"
                + "|".join(sorted(FEEDBACK_SIGNALS))
                + ">"
            ),
        },
        {
            "hook": SKILL_DRAFT_HOOK,
            "required": False,
            "when": (
                "immediately after the observation, while this run still holds the context "
                "that explains the gap; required before same-closeout review"
            ),
            "command": (
                f"{launcher} {SKILL_DRAFT_HOOK} "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE> "
                "--skill-id <safe_skill_slug> "
                "--feedback-signal <"
                + "|".join(sorted(FEEDBACK_SIGNALS))
                + "> "
                "--draft-proposal-file <bounded rationale file>"
            ),
        },
        {
            "hook": SKILL_CURATE_HOOK,
            "required": False,
            "when": "in the same closeout after the observation, before review",
            "command": (
                f"{launcher} {SKILL_CURATE_HOOK} "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE>"
            ),
        },
        {
            "hook": SKILL_REVIEW_HOOK,
            "required": False,
            "when": "in the same closeout after curation, before the skill-document edit",
            "command": (
                f"{launcher} {SKILL_REVIEW_HOOK} "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE> "
                "--feedback-candidate-id <opaque_candidate_id> "
                "--skill-review-outcome <no_change|stage_patch> "
                "[--feedback-gap <safe_gap_slug> --change-type <safe_change_slug> "
                "--promotion-target <safe_target_slug>]"
            ),
        },
        {
            "hook": SKILL_MAINTENANCE_HOOK,
            "required": False,
            "when": "in the same closeout after the canonical skill-document edit and its verification",
            "command": (
                f"{launcher} {SKILL_MAINTENANCE_HOOK} "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE> "
                "--feedback-candidate-id <opaque_candidate_id> "
                "--skill-maintenance-outcome <applied|rejected> "
                "[--maintenance-target <changed_skill_path> "
                "--verification-kind <py_compile|unittest|vibeguard|workflow_validate> "
                "--maintenance-test-selector <safe_unittest_selector>]"
            ),
        },
    ]


def _review_hook_timing(required: bool) -> str:
    if required:
        return "after meaningful edits and before finish, commit, release, or handoff"
    return "conditional: run if the route creates or changes a diff, or before any commit"


def _review_hook_command(command: str) -> str:
    launcher = str(stable_launcher_path())
    base = (
        f"{launcher} review "
        "--project <TARGET_REPO> --rules <TAO_ROOT> "
        "--evidence <RUN_EVIDENCE> "
        "--review-scope working-tree "
        "--review-outcome <pass|findings> "
        "--code-review-evidence \"<evidence>\" "
        "--docs-freshness-evidence \"<evidence>\" "
        "[--allow-vibeguard-review \"<reason for acceptable Needs review>\"] "
        "[for destructive no-diff branch, worktree, or project-state cleanup "
        "replace the scope with: --review-scope repo-hygiene] "
        "[for an existing commit replace the scope with: --review-scope commit-range "
        "--review-base <base-ref> --review-head <head-ref>] "
    )
    if command in {"commit", "git_commit"}:
        return base + "[--review-path <commit-owned-path>]"
    return (
        base
        + "--structure-review-evidence \"<owner/imports/callers/verification when structure changed>\" "
        "--boundary-plan-evidence \"<owned boundary/scope and nearest verification>\" "
        "--side-effect-audit-evidence \"<final diff and side-effect audit>\" "
        "[--review-path <task-owned-path>]"
    )
