"""Validation checks for workflow documents and route manifests."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from agent_finish_gate_policy import VALIDATED_GATES
from support.project_tree import iter_project_files
from workflow_catalog import COMMANDS, CONCERNS, CORE_DOCS, PLATFORM_CONCERNS, PLATFORMS
from workflow_common import (
    QUESTION_ROUTE_COMMANDS,
    REPAIR_CYCLE_LIMIT,
    REPAIR_POLICY,
    REPAIR_STOP_CONDITION,
    RESUME_SCOPE,
    ROOT,
)
from workflow_doc_surfaces import load_doc_surface_rules, surface_rule_doc_refs
from workflow_gate_policy import (
    SKILL_DRAFT_HOOK,
    SKILL_CURATE_HOOK,
    SKILL_FEEDBACK_HOOK,
    SKILL_MAINTENANCE_HOOK,
    SKILL_REVIEW_HOOK,
    RETROSPECTIVE_CHECK_COMMANDS,
    RETROSPECTIVE_CHECK_GATE,
    automatic_gates,
)
from workflow_parallel_validate import validate_parallel_execution_plan
from workflow_route import REVIEW_HOOK_REQUIRED_COMMANDS, resolve_docs, route_gates
from workflow_spill import validate_spill_label_contracts


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REMOVED_GATE_OPTION_RE = re.compile(r"--gate(?![-\w])")
FRONTMATTER_REQUIRED_KEYS = ("keyflow_id:", "status:", "type:")
STRICT_CARD_MARKER = "tao_card_contract: strict"
STRICT_CARD_REQUIRED_HEADINGS = (
    "## Use When",
    "## Decision Rule",
    "## Common Rationalizations",
    "## Red Flags",
    "## Do Not",
    "## Stop If",
    "## Verification",
)
MARKDOWN_VALIDATE_IGNORED_DIRS = {
    # `local/` holds the user's personal skills, not runtime-owned documents.
    # The frontmatter contract (keyflow_id/status/type) describes runtime
    # bundles; personal skills are also loaded by Claude and Codex directly, so
    # forcing runtime metadata on them would make this validator the owner of
    # files RUNTIME-OWNERSHIP.md explicitly excludes from reference import.
    "local",
    ".tao",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "graphify-out",
    "node_modules",
    "venv",
}
MULTI_AGENT_VALIDATED_GATES = {
    "roles",
    "write scopes",
    "agent briefs",
    "integration review",
}
PROFILE_VALIDATED_GATES = {
    "docs-review": {"review readiness"},
    "product": {"platform selection"},
}


def removed_cli_option_failures(relative: Path, text: str) -> list[str]:
    return [
        f"{relative}:{line_number}: removed CLI option --gate; use gate or gate-batch"
        for line_number, line in enumerate(text.splitlines(), start=1)
        if REMOVED_GATE_OPTION_RE.search(line)
    ]


def validate_route_contracts() -> list[str]:
    failures: list[str] = []
    failures.extend(validate_spill_label_contracts(set(COMMANDS)))

    for command in COMMANDS:
        route = resolve_docs(command, None, [], request_classified=True)
        if route.get("missing"):
            failures.append(f"{command}: route has missing docs: {', '.join(route['missing'])}")

        if route["repair_cycle_limit"] != REPAIR_CYCLE_LIMIT:
            failures.append(f"{command}: repair_cycle_limit must be {REPAIR_CYCLE_LIMIT}")
        if route["repair_policy"] != REPAIR_POLICY:
            failures.append(f"{command}: repair_policy must be {REPAIR_POLICY}")
        if route["resume_scope"] != RESUME_SCOPE:
            failures.append(f"{command}: resume_scope must be {RESUME_SCOPE}")
        if route["stop_condition"] != REPAIR_STOP_CONDITION:
            failures.append(f"{command}: stop_condition must be {REPAIR_STOP_CONDITION}")
        for failure in validate_parallel_execution_plan(route.get("parallel_execution"), route["gates"]):
            failures.append(f"{command}: {failure}")

        expected_gates = route_gates(command)
        if command not in QUESTION_ROUTE_COMMANDS:
            expected_gates = ["request intake", *expected_gates]
        if route["gates"] != expected_gates:
            failures.append(f"{command}: route gates do not match profile gates")
        for gate in automatic_gates(command):
            if gate not in route["gates"]:
                failures.append(f"{command}: automatic gate `{gate}` is missing")
            if gate not in VALIDATED_GATES:
                failures.append(f"{command}: automatic gate `{gate}` has no finish evidence validator")

        hooks = route.get("hooks")
        if not isinstance(hooks, list):
            failures.append(f"{command}: route hooks must be a list")
            hooks = []
        hook_names = [hook.get("hook") for hook in hooks if isinstance(hook, dict)]
        expected_hook_names = ["start", "review"]
        if command in RETROSPECTIVE_CHECK_COMMANDS:
            expected_hook_names.extend(
                [
                    SKILL_FEEDBACK_HOOK,
                    SKILL_DRAFT_HOOK,
                    SKILL_CURATE_HOOK,
                    SKILL_REVIEW_HOOK,
                    SKILL_MAINTENANCE_HOOK,
                ]
            )
        expected_hook_names.append("finish")
        if hook_names != expected_hook_names:
            failures.append(f"{command}: route hooks must be {', '.join(expected_hook_names)}")
        hook_required = {
            hook.get("hook"): hook.get("required")
            for hook in hooks
            if isinstance(hook, dict)
        }
        if hook_required.get("start") is not True:
            failures.append(f"{command}: start hook must be required")
        if hook_required.get("finish") is not True:
            failures.append(f"{command}: finish hook must be required")
        if command in RETROSPECTIVE_CHECK_COMMANDS:
            failures.extend(_retrospective_policy_failures(command, route, hook_required))
        expected_review_required = command in REVIEW_HOOK_REQUIRED_COMMANDS
        if hook_required.get("review") is not expected_review_required:
            failures.append(
                f"{command}: review hook required state must be {expected_review_required}"
            )
        if expected_review_required and "review hook" not in route["gates"]:
            failures.append(f"{command}: required review hook is missing from route gates")
        if command == "multi-agent":
            missing_validators = sorted(MULTI_AGENT_VALIDATED_GATES - VALIDATED_GATES)
            if missing_validators:
                failures.append(
                    f"{command}: missing finish evidence validators for {', '.join(missing_validators)}"
                )
        for gate in sorted(PROFILE_VALIDATED_GATES.get(command, set())):
            if gate not in route["gates"]:
                failures.append(f"{command}: validated profile gate `{gate}` is not in route gates")
            if gate not in VALIDATED_GATES:
                failures.append(f"{command}: validated profile gate `{gate}` has no finish evidence validator")

        ledger = route["gate_ledger"]
        if len(ledger) != len(route["gates"]):
            failures.append(f"{command}: gate_ledger length does not match gates")
            continue

        for gate, item in zip(route["gates"], ledger):
            if item["gate"] != gate:
                failures.append(f"{command}: ledger gate `{item['gate']}` does not match `{gate}`")
            if item["status"] != "not_started":
                failures.append(f"{command}: initial ledger status for `{gate}` must be not_started")
            if item["signal"] != "":
                failures.append(f"{command}: initial ledger signal for `{gate}` must be empty")
            if item["evidence"] != "":
                failures.append(f"{command}: initial ledger evidence for `{gate}` must be empty")

    return failures


def _retrospective_policy_failures(
    command: str,
    route: dict[str, Any],
    hook_required: dict[Any, Any],
) -> list[str]:
    """Check the retrospective hooks and the skill follow-up contract."""
    failures: list[str] = []
    for hook_name in (
        SKILL_FEEDBACK_HOOK,
        SKILL_CURATE_HOOK,
        SKILL_REVIEW_HOOK,
        SKILL_MAINTENANCE_HOOK,
    ):
        if hook_required.get(hook_name) is not False:
            failures.append(f"{command}: {hook_name} hook must be optional")
    feedback_policy = route.get("skill_feedback") or {}
    if feedback_policy.get("enabled") is not True:
        failures.append(f"{command}: retrospective skill feedback must be enabled")
    if feedback_policy.get("evaluation_required") is not True:
        failures.append(f"{command}: retrospective evaluation must be required")
    if feedback_policy.get("evaluation_gate") != RETROSPECTIVE_CHECK_GATE:
        failures.append(f"{command}: retrospective evaluation gate is invalid")
    if feedback_policy.get("blocking") is not True:
        failures.append(
            f"{command}: reusable-gap skill-document follow-up must block finish"
        )
    if feedback_policy.get("blocking_scope") != "reusable_gap_same_closeout":
        failures.append(
            f"{command}: skill follow-up blocking scope must be reusable_gap_same_closeout"
        )
    if feedback_policy.get("threshold_followup_required") is not True:
        failures.append(
            f"{command}: current threshold candidate must require explicit follow-up"
        )
    failures.extend(_threshold_followup_contradictions(command, route, feedback_policy))
    return failures


# Phrases that assert skill follow-up can never hold finish. Each is true only
# below the recurrence threshold, so a route that also requires threshold
# follow-up ships both halves of a contradiction. Checking the boolean alone
# missed this: the flag flipped while the prose telling the agent to ignore it
# stayed in the same route output.
_UNCONDITIONAL_NON_BLOCKING_PHRASES = (
    "must not change finish status",
    "never changes finish",
    "never changes a successful finish",
    "does not change finish status",
)
# A non-blocking claim is only true below the recurrence threshold, so these are
# the phrases that scope it there. Merely naming the threshold is not enough:
# "at the threshold, review must not change finish status" names it while
# asserting the exact contradiction, so the marker has to carry the direction.
_BELOW_THRESHOLD_SCOPE_MARKERS = (
    "first observation",
    "first skill observation",
    "below the threshold",
    "below the recurrence threshold",
)


def _threshold_followup_contradictions(
    command: str,
    route: dict[str, Any],
    feedback_policy: dict[str, Any],
) -> list[str]:
    """Reject route prose that contradicts the threshold follow-up contract."""

    if feedback_policy.get("threshold_followup_required") is not True:
        return []
    failures: list[str] = []
    for location, text in _route_prose(route):
        lowered = text.lower()
        if any(marker in lowered for marker in _BELOW_THRESHOLD_SCOPE_MARKERS):
            continue
        for phrase in _UNCONDITIONAL_NON_BLOCKING_PHRASES:
            if phrase in lowered:
                failures.append(
                    f"{command}: {location} claims skill follow-up {phrase} without "
                    "scoping the claim below the recurrence threshold, which "
                    "contradicts the required threshold follow-up"
                )
                break
    return failures


def _route_prose(route: dict[str, Any]) -> list[tuple[str, str]]:
    """Return every agent-facing route sentence with a label for its location.

    Checking only phase constraints left the same claim free to reach the agent
    through phase tasks or the parallel-execution notes, which the route renders
    just as literally.
    """
    plan = route.get("parallel_execution") or {}
    prose: list[tuple[str, str]] = [
        ("parallel execution notes", str(note)) for note in plan.get("notes") or ()
    ]
    for phase in plan.get("phases") or ():
        if not isinstance(phase, dict):
            continue
        for field in ("constraints", "tasks"):
            for item in phase.get(field) or ():
                prose.append((f"phase `{phase.get('id')}` {field}", str(item)))
    return prose


def validate() -> int:
    refs: set[str] = set(CORE_DOCS)
    for profile in COMMANDS.values():
        refs.update(profile.docs)
    for docs in PLATFORMS.values():
        refs.update(docs)
    for docs in CONCERNS.values():
        refs.update(docs)
    for docs in PLATFORM_CONCERNS.values():
        refs.update(docs)
    surface_rules = load_doc_surface_rules(ROOT)
    surface_docs, bad_surface_refs = surface_rule_doc_refs(surface_rules)
    refs.update(surface_docs)

    missing = sorted(doc for doc in refs if not (ROOT / doc).exists())
    bad_route_contracts = validate_route_contracts()
    markdown_files = markdown_files_to_validate(ROOT)
    bad_frontmatter: list[str] = []
    bad_links: list[str] = []
    bad_card_quality: list[str] = []
    bad_removed_cli_options: list[str] = []

    for path in markdown_files:
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        bad_removed_cli_options.extend(removed_cli_option_failures(relative, text))
        if not text.startswith("---\n"):
            bad_frontmatter.append(f"{relative}: missing frontmatter")
            continue
        end = text.find("\n---", 4)
        if end == -1:
            bad_frontmatter.append(f"{relative}: unterminated frontmatter")
            continue
        header = text[4:end]
        missing_keys = [key[:-1] for key in FRONTMATTER_REQUIRED_KEYS if key not in header]
        if missing_keys:
            bad_frontmatter.append(f"{relative}: missing {', '.join(missing_keys)}")
        if STRICT_CARD_MARKER in header:
            missing_headings = [
                heading for heading in STRICT_CARD_REQUIRED_HEADINGS if not _has_heading(text, heading)
            ]
            if missing_headings:
                bad_card_quality.append(
                    f"{relative}: strict card missing {', '.join(missing_headings)}"
                )

        for raw_link in MARKDOWN_LINK_RE.findall(text):
            link = raw_link.strip()
            target = link.split("#", 1)[0].split(" ", 1)[0].strip("<>")
            if not target or target.startswith("#"):
                continue
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            if not (path.parent / target).resolve().exists():
                bad_links.append(f"{relative}: {raw_link}")

    if missing:
        print("Missing workflow references:", file=sys.stderr)
        for doc in missing:
            print(f"- {doc}", file=sys.stderr)
    if bad_frontmatter:
        print("Invalid markdown frontmatter:", file=sys.stderr)
        for item in bad_frontmatter:
            print(f"- {item}", file=sys.stderr)
    if bad_links:
        print("Broken markdown links:", file=sys.stderr)
        for item in bad_links:
            print(f"- {item}", file=sys.stderr)
    if bad_route_contracts:
        print("Invalid workflow route contracts:", file=sys.stderr)
        for item in bad_route_contracts:
            print(f"- {item}", file=sys.stderr)
    if bad_surface_refs:
        print("Invalid workflow document surface rules:", file=sys.stderr)
        for item in bad_surface_refs:
            print(f"- {item}", file=sys.stderr)
    if bad_card_quality:
        print("Invalid strict card anatomy:", file=sys.stderr)
        for item in bad_card_quality:
            print(f"- {item}", file=sys.stderr)
    if bad_removed_cli_options:
        print("Removed workflow CLI options in Markdown:", file=sys.stderr)
        for item in bad_removed_cli_options:
            print(f"- {item}", file=sys.stderr)

    if (
        missing
        or bad_frontmatter
        or bad_links
        or bad_route_contracts
        or bad_surface_refs
        or bad_card_quality
        or bad_removed_cli_options
    ):
        return 1

    print(
        f"OK: {len(refs)} workflow references exist; "
        f"{len(markdown_files)} markdown frontmatter blocks and links are valid; "
        f"{len(COMMANDS)} route contracts are valid."
    )
    return 0


def _has_heading(text: str, heading: str) -> bool:
    return re.search(rf"^{re.escape(heading)}(?:\s|$)", text, re.MULTILINE) is not None


def markdown_files_to_validate(root: Path) -> list[Path]:
    """List the documents to validate without walking the ones already excluded.

    The ignored set was applied to results, so the walk still descended into
    project state, virtual environments and caches to discard what it found.
    Pruning at the directory gives the same list; the set is unchanged, so a
    file is excluded for exactly the reasons it was before.
    """

    return sorted(iter_project_files(root, "*.md", pruned=MARKDOWN_VALIDATE_IGNORED_DIRS))
