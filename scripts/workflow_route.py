"""Build workflow route manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from workflow_catalog import (
    BASELINE_CONCERNS,
    COMMANDS,
    CONCERNS,
    CORE_DOCS,
    PLATFORM_CONCERNS,
    PLATFORMS,
)
from support.graphify_setup import inspect_target_graphify
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
    SKILL_FEEDBACK_HOOK,
    SKILL_MAINTENANCE_HOOK,
    SKILL_REVIEW_HOOK,
    RETROSPECTIVE_CHECK_COMMANDS,
    RETROSPECTIVE_CHECK_GATE,
    add_automatic_gates,
    automatic_docs,
    skill_feedback_policy,
)
from workflow_doc_resolution import doc_size, resolve_guidance_docs
from workflow_doc_surfaces import infer_surface_docs
from workflow_parallel import parallel_execution_plan
from workflow_search import SearchOutcome, search_docs_outcome
from workflow_skill_paths import canonical_doc_path
from workflow_wikimap import WIKIMAP_VERSION
from support.stable_launcher import stable_launcher_path


CORE_REQUIRED_DOCS = (
    "AGENTS.md",
    "common/skills/agent-operating-skill/SKILL.md",
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
) -> dict[str, object]:
    profile = COMMANDS[command]
    docs: list[str] = [*CORE_DOCS, *profile.docs]
    docs.extend(automatic_docs(command))
    surface_docs, surface_matches = infer_surface_docs(
        command=command,
        platform=platform,
        request_text=request_text,
        surface_paths=surface_paths or [],
    )
    search_outcome = (
        search_docs_outcome(ROOT, request_text, max_results=12)
        if request_text.strip()
        else SearchOutcome(results=[], backend="wikimap", backend_version=WIKIMAP_VERSION)
    )
    search_seed_docs = [str(item["path"]) for item in search_outcome.results]
    doc_graph_matches = expand_doc_matches(
        ROOT,
        unique([*surface_docs, *search_seed_docs]),
        max_depth=1,
        max_docs=24,
        relation_prefixes=("frontmatter:", "markdown:", "compat:"),
    )
    graph_docs = [str(match["path"]) for match in doc_graph_matches]
    graph_required = graph_required_docs(doc_graph_matches)
    docs.extend(surface_docs)
    docs.extend(search_seed_docs)
    docs.extend(graph_docs)

    if platform:
        docs.extend(PLATFORMS[platform])

    for concern in concerns:
        docs.extend(CONCERNS.get(concern, ()))
        if platform:
            docs.extend(PLATFORM_CONCERNS.get((platform, concern), ()))

    routed_docs = unique(canonical_doc_path(doc) for doc in docs)
    required_docs = route_required_docs(command, platform, concerns, profile.docs, [*surface_docs, *graph_required])
    # Every routed document stays reachable in exactly one of the two lists.
    # Filtering out entrypoints whose reference was promoted would read better,
    # but it breaks the invariant that `required_docs | reference_docs` covers
    # everything the router resolved, which callers rely on.
    required_set = set(required_docs)
    reference_docs = [doc for doc in routed_docs if doc not in required_set]
    manifest_docs = unique([*routed_docs, *required_docs])
    missing = [doc for doc in manifest_docs if not (ROOT / doc).exists()]
    document_resolution = _document_resolution(
        search_outcome=search_outcome,
        search_seed_docs=search_seed_docs,
        missing=missing,
    )
    notes = list(profile.notes)
    if command == "product" and not platform:
        notes.append("Select at least one platform card before writing ARD.")
    for concern in concerns:
        if concern in BASELINE_CONCERNS:
            notes.append(f"Concern `{concern}` is {BASELINE_CONCERNS[concern]}")

    graphify_requested = "graphify" in concerns or any(
        match["name"] in {"target_project_graphify", "graphify_integration"}
        for match in surface_matches
    )
    gates = route_gates(command, graphify_required=graphify_requested)
    if command not in QUESTION_ROUTE_COMMANDS:
        gates = ["request intake", *gates]

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
    if reference_docs:
        notes.append(
            "Read `required_docs` before work; treat `reference_docs` as on-demand context only when the current task touches that concern."
        )
    if surface_matches:
        if command in LIGHTWEIGHT_SURFACE_REFERENCE_COMMANDS:
            notes.append(
                "Kept docs inferred only from dirty-path surfaces in `reference_docs` for the lightweight commit route; explicit concerns can still promote required guidance."
            )
        else:
            notes.append(
                "Promoted required docs from request intent or touched path surfaces using `workflow-doc-surfaces.json`."
            )
    if search_seed_docs:
        notes.append(
            "Wikimap supplied natural-language seed documents to the router; seeds remain reference candidates unless an explicit route rule or required relation promotes them."
        )
    elif document_resolution["status"] == "no_matches":
        notes.append(
            "Natural-language document search completed with no matching project documents. This is a terminal no-source outcome, not a retry condition; continue with the deterministic required_docs and record the no-source decision."
        )
    if document_resolution["status"] == "invalid_manifest":
        notes.append(
            "The route manifest names missing documents. Stop once with the missing paths; do not retry document discovery until the manifest or files are repaired."
        )
    if search_outcome.fallback_reason:
        notes.append(
            "Wikimap was unavailable for this route, so the local legacy scorer supplied recovery candidates."
        )
    if doc_graph_matches:
        notes.append(
            "Expanded related candidate docs from the local document graph; explicit `requires_docs` edges become required docs."
        )

    graphify_readiness = None
    blocking: list[str] = []
    if graphify_requested:
        if project_root:
            graphify_readiness = {
                "requested": True,
                "project": str(project_root),
                **inspect_target_graphify(project_root),
            }
        else:
            graphify_readiness = {
                "requested": True,
                "project": None,
                "ready": False,
            }
            blocking.append(
                "Graphify readiness cannot be assessed without --project <TARGET_REPO>."
            )
        if project_root and not graphify_readiness["ready"]:
            notes.append(
                "Target-project Graphify is incomplete. The graphify readiness gate must prove "
                "CLI, the read canonical SKILL.md, runtime links resolving to it, portable "
                "Git ownership, project integration, a fresh/input-complete graph with valid "
                "endpoints, and query smoke before handoff. Document-to-code relationship "
                "coverage is query-quality guidance, not an AST-only prerequisite."
            )

    route = {
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
    "review hook": "workflows/skills/review-and-commit/SKILL.md",
    MULTI_AGENT_GATE: "workflows/skills/multi-agent-collaboration/SKILL.md",
}

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
# The budget covers only the *selectable* tiers.  `CORE_REQUIRED_DOCS` is
# exempt: AGENTS.md alone is ~41 KB, and charging it against the budget would
# let the operating contract crowd out the documents actually matched to this
# request.  Total mandatory reading is therefore roughly core + this budget.
REQUIRED_DOC_BUDGET_BYTES = 30_000
# Core and guaranteed review contracts consume six slots on code routes. Ten
# leaves room for the route's own command card plus three request-specific
# branch cards, which is the smallest useful combined-runtime surface.
MAX_REQUIRED_DOCS = 10

# STOPGAP -- not a permanent policy.  A single reference larger than this would
# monopolise the route's mandatory reading: admitting one exhausts
# REQUIRED_DOC_BUDGET_BYTES on its own and stops selection, dropping every
# lower-ranked card that would otherwise have fit.  Oversized documents stay in
# `reference_docs`, where the agent can still reach them.
#
# The real fix is to split an oversized reference into separately routable topic
# siblings, as `platforms/android/skills/android-module-structure` now is -- every
# piece of that bundle is under 11 KB and routes on its own concern, so this guard
# never touches it.  Two routable references still trip the guard:
#
#   workflows/skills/scripted-agent-workflow/references/current-guidance.md  (~46 KB)
#   docs/skills/agent-runtime-integration/references/current-guidance.md     (~41 KB)
#
# Split those two the same way and this constant, its use in the selection loop
# below, and the bundle-size tests can all be deleted.
OVERSIZED_DOC_BYTES = 40_000


def route_required_docs(
    command: str,
    platform: Optional[str],
    concerns: list[str],
    profile_docs: tuple[str, ...],
    surface_docs: list[str] | None = None,
) -> list[str]:
    # A simple investigation has no work-producing gates.  Keep the runtime
    # instruction available, but do not make it pay the full operating-skill
    # document-read cost before it can answer.
    if command == "analysis":
        return ["AGENTS.md"]

    gates = set(route_gates(command))

    # Tiers are ordered by how directly the document is tied to something this
    # route actually activates.  Everything above the budget line becomes
    # required; everything below stays available as `reference_docs`.
    tiers: list[list[str]] = []

    # 1. What the route *is*: its own command skill.
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

    # 5. What the route will enforce: the gates it runs, mapped to the documents
    #    that define their evidence contracts.
    gate_docs = list(automatic_docs(command))
    if "review hook" in gates:
        gate_docs.extend(REVIEW_HOOK_GATE_DOCS)
    tiers.append(gate_docs)

    # 6. General code-work discipline, for routes that produce code.
    if command in CODE_WORK_COMMANDS_REQUIRING_DISCIPLINE:
        tiers.append(list(CODE_WORK_REQUIRED_DOCS))

    # The operating contract is not subject to the budget: every route must
    # read it, and a route with no required docs at all would make the source
    # docs gate vacuous.
    #
    # Core deliberately keeps its entrypoints rather than resolving to
    # references.  The operating-skill reference is ~22 KB and identical for
    # every route, so promoting it would spend more than half the guidance
    # budget on the one document that is never specific to the request -- the
    # exact trade this change exists to reverse.  AGENTS.md already carries the
    # always-on operating contract, and the reference stays in `reference_docs`.
    selected = unique(canonical_doc_path(doc) for doc in CORE_REQUIRED_DOCS)

    # The review hook is not a passive gate: it actively rejects submissions
    # that omit its labelled structure evidence.  A route that enforces the hook
    # must therefore deliver the document defining those labels, and that
    # delivery cannot be subject to the byte budget -- letting a budget drop it
    # is exactly the failure this change was written to fix, where the hook
    # rejected work for a contract the route never put in front of the agent.
    guaranteed = [
        doc for gate, doc in GUARANTEED_GATE_DOCS.items() if gate in gates
    ]
    selected.extend(
        doc
        for doc in unique(
            resolve_guidance_docs(ROOT, [canonical_doc_path(doc) for doc in guaranteed])
        )
        if doc not in selected
    )

    # Concerns the caller named are also exempt.  An operator writing "branch"
    # or "security" is stating the risk directly, and silently demoting that to
    # optional context is the worst failure available here: the route would
    # answer a specific, explicit request with generic reading.  Concern card
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

    used = 0

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
            if len(selected) >= MAX_REQUIRED_DOCS or used >= REQUIRED_DOC_BUDGET_BYTES:
                return selected
            size = doc_size(ROOT, doc)
            if size > OVERSIZED_DOC_BYTES:
                # Skipping here is the one place ranking is not honoured; the
                # document stays reachable as a reference.
                continue
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
        hooks.append(
            {
                "hook": SKILL_FEEDBACK_HOOK,
                "required": False,
                "when": (
                    "after the required retrospective check records reusable_gap; run before "
                    "finish when available, or record deferred without failing the task"
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
            }
        )
        hooks.extend(
            [
                {
                    "hook": SKILL_CURATE_HOOK,
                    "required": False,
                    "when": "later or periodically, when bounded deterministic curation capacity is available",
                    "command": (
                        f"{launcher} {SKILL_CURATE_HOOK} "
                        "--project <TARGET_REPO> --rules <TAO_ROOT> "
                        "--evidence <RUN_EVIDENCE>"
                    ),
                },
                {
                    "hook": SKILL_REVIEW_HOOK,
                    "required": False,
                    "when": "later, when deterministic curation marks a repeated observation review-ready",
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
                    "when": "after separate staged skill maintenance has been verified",
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
        )
    hooks.append(
        {
            "hook": "finish",
            "required": True,
            "when": "after retrospective check and before final report, commit, release, or handoff",
            "command": (
                f"{launcher} finish "
                "--project <TARGET_REPO> --rules <TAO_ROOT> "
                "--evidence <RUN_EVIDENCE>"
            ),
        }
    )
    return hooks


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
