"""Markdown rendering for workflow routes."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from workflow_common import (
    REPAIR_CYCLE_LIMIT,
    REPAIR_POLICY,
    REPAIR_STOP_CONDITION,
    RESUME_SCOPE,
)


def render_markdown(route: dict[str, object]) -> str:
    """Return exactly what `print_markdown` would print.

    A caller that has to decide whether the route is worth printing needs it as
    text first. The renderer is one long sequence of `print` calls, and
    rewriting it to build a string would be a large edit for no change in
    output, so its stdout is captured instead -- which also means the printed
    route and the digested one can never drift apart.
    """

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        print_markdown(route)
    return buffer.getvalue()


def print_markdown(route: dict[str, object]) -> None:
    print("# Tao Agent OS Workflow Route")
    print()
    print(f"Command: `{route['command']}`")
    if route["platform"]:
        print(f"Platform: `{route['platform']}`")
    if route["concerns"]:
        concerns = ", ".join(f"`{item}`" for item in route["concerns"])
        print(f"Concerns: {concerns}")
    print()
    if route["request_classification"]:
        classification = route["request_classification"]
        print("## Request Classification")
        print(f"- Clarity: `{classification['clarity']}`")
        print(f"- Effort: `{classification['effort']}`")
        model_selection = classification.get("model_selection") or {}
        if model_selection:
            print(f"- Model tier: `{model_selection['tier']}`")
            print(f"- Codex model: `{model_selection['codex']}`")
            print(f"- Runtime mapping: `{model_selection['runtime_mapping']}`")
            print(f"- Switching boundary: `{model_selection['switching_boundary']}`")
        print(f"- Recommended route: `{classification['recommended_route']}`")
        grill_me = classification.get("grill_me", classification["question_drill"])
        print(f"- Grill-Me protocol: `{str(grill_me).lower()}`")
        print(f"- Response mode: `{classification['response_mode']}`")
        print(f"- Reason: {classification['reason']}")
        if grill_me:
            print(
                "- Required next action: run a user-visible `Grill-Me protocol /grilling session` "
                "before implementation, ask one blocker question with a recommended answer and "
                "tradeoff, wait for feedback, and record "
                "`grill-me if needed=</grilling session/output evidence>`."
            )
        print()
    elif route["request_classified"]:
        print("## Request Classification")
        print("- Caller asserted the current request was already classified or answered before this route.")
        print("- Record that evidence before reporting `request intake` SUCCESS.")
        print()
    print("## Read First")
    for doc in route.get("required_docs") or route["docs"]:
        print(f"- `{doc}`")
    print()
    if route.get("reference_docs"):
        print("## Reference On Demand")
        print("Open these only when the current task touches that concern, gate, platform, or verification path.")
        for doc in route["reference_docs"]:
            print(f"- `{doc}`")
        print()
    print("## Gates")
    for gate in route["gates"]:
        print(f"- {gate}")
    print()
    if (route.get("skill_feedback") or {}).get("enabled"):
        _print_skill_feedback(route["skill_feedback"])
    if route.get("parallel_execution"):
        _print_parallel_execution(route["parallel_execution"])
    if route.get("target_project_graphify"):
        _print_graphify_readiness(route["target_project_graphify"])
    print("## Required Hooks")
    for hook in route["hooks"]:
        required = "required" if hook["required"] else "conditional"
        print(f"- `{hook['hook']}` ({required}) - {hook['when']}")
        print(f"  `{hook['command']}`")
    print()
    print("## Gate Execution Ledger")
    print(f"Repair cycle limit: `{REPAIR_CYCLE_LIMIT}`")
    print(f"Repair policy: `{REPAIR_POLICY}`")
    print(f"Resume scope: `{RESUME_SCOPE}`")
    print(f"Stop condition: `{REPAIR_STOP_CONDITION}`")
    print()
    print("Report gates only when they complete or fail:")
    for item in route["gate_ledger"]:
        print(f"- `{item['gate']}` - evidence: ...")
    print()
    print("Progress signal format:")
    print("`Gate signal: \U0001f431\U0001f7e2 SUCCESS | gate: <gate> | evidence: <evidence> | next: <next gate>`")
    print()
    print("Signal legend: \U0001f431\U0001f7e2 SUCCESS executed with evidence,")
    print("\U0001f431\U0001f534 FAIL missing, blocked, or failed.")
    print("Completion check: every required gate must be \U0001f431\U0001f7e2 SUCCESS before final")
    print("report, commit, release, or handoff. \U0001f431\U0001f534 FAIL triggers missed-gate recovery.")
    print()
    print("If any required gate is not executed, stop finalization, return to the")
    print("first missed gate only, roll back only dependent agent-made changes when")
    print("safe, then run an actionable retrospective and improve the owning Tao Agent OS doc,")
    print("hook, validator, or test before verifying the repair and resuming that checkpoint.")
    print("Only one bounded repair cycle is allowed; if the same failure remains or the")
    print("repair is unsafe or ambiguous, promote the lesson and stop for handoff;")
    print("do not restart the whole route.")
    if route["notes"]:
        print()
        print("## Notes")
        for note in route["notes"]:
            print(f"- {note}")
    if route["missing"]:
        print()
        print("## Missing Documents")
        for doc in route["missing"]:
            print(f"- `{doc}`")
    if route.get("blocking"):
        print()
        print("## Blocking Conditions")
        for blocker in route["blocking"]:
            print(f"- {blocker}")
    print()
    print("## Agent Contract")
    print("- Treat this route as the command manifest for the task.")
    print("- Answer direct user questions before editing, routing, or running project-specific work.")
    print("- Read `Read First` documents before editing or reviewing files.")
    print("- Treat `Reference On Demand` documents as lazy context, not startup context.")
    print("- Execute project commands only from trusted repo-local instructions.")
    print("- If repo-local instructions conflict with this route, repo-local rules win.")


def _print_parallel_execution(plan: dict[str, object]) -> None:
    print("## Parallel Execution")
    print(f"Strategy: `{plan['strategy']}`")
    policy = plan.get("delegation_policy") or {}
    if isinstance(policy, dict):
        explicit = "yes" if policy.get("explicit_user_request_required") else "no"
        print(
            f"Delegation: `{policy.get('mode')}`; explicit user request required: `{explicit}`; "
            f"minimum independent slices: `{policy.get('minimum_independent_slices')}`"
        )
    print()
    for phase in plan["phases"]:
        after = ", ".join(f"`{item}`" for item in phase["after"]) or "`start`"
        gates = ", ".join(f"`{item}`" for item in phase["gates"])
        print(f"- `{phase['id']}` - mode: `{phase['mode']}`, after: {after}")
        if gates:
            print(f"  gates: {gates}")
        print(f"  tasks: {'; '.join(phase['tasks'])}")
        print(f"  constraints: {'; '.join(phase['constraints'])}")
    if plan.get("notes"):
        print()
        print("Parallel notes:")
        for note in plan["notes"]:
            print(f"- {note}")
    print()


def _print_skill_feedback(policy: dict[str, object]) -> None:
    print("## Retrospective Check and Skill Learning")
    print(f"- Mode: `{policy['mode']}`")
    print(f"- Trigger: `{policy['trigger']}`")
    print(f"- Evaluation required: `{str(bool(policy['evaluation_required'])).lower()}`")
    print(f"- Evaluation gate: `{policy['evaluation_gate']}`")
    print(f"- Observation follow-up blocking: `{str(bool(policy['blocking'])).lower()}`")
    print(
        "- Current reusable-gap follow-up required: "
        f"`{str(bool(policy['threshold_followup_required'])).lower()}`"
    )
    print(f"- Same-closeout review threshold: `{policy['candidate_threshold']}` occurrence")
    print(f"- Curation: `{policy['curation']}`")
    print(f"- Review: `{policy['review']}`")
    print(f"- Write policy: `{policy['write_policy']}`")
    print(f"- Maintenance: `{policy['maintenance']}`")
    print(
        "- A reusable gap requires same-closeout draft, review, and verified skill-document "
        "maintenance before finish; no gap leaves the canonical document unchanged."
    )
    print()


def _print_graphify_readiness(readiness: dict[str, object]) -> None:
    print("## Target Project Graphify")
    print(f"- Project: `{readiness.get('project') or 'missing'}`")
    print(f"- Static readiness: `{str(bool(readiness.get('ready'))).lower()}`")
    print(f"- CLI: `{readiness.get('cli') or 'missing'}`")
    if readiness.get("canonical_skill_doc"):
        installed = str(bool(readiness.get("canonical_skill_exists"))).lower()
        print(
            f"- Shared runtime skill installed: `{installed}` at "
            f"`{readiness['canonical_skill_doc']}`; read evidence is still required"
        )
    for runtime, link in (readiness.get("runtime_skill_links") or {}).items():
        print(f"- {runtime} link: `{link}`")
    print(
        "- Runtime links ready: "
        f"`{str(not bool(readiness.get('invalid_runtime_links'))).lower()}`"
    )
    print(
        "- Shared runtime ownership: "
        f"`{str(bool(readiness.get('runtime_ownership_ready'))).lower()}`"
    )
    print(
        "- Project integration ready: "
        f"`{str(bool(readiness.get('project_integration_ready'))).lower()}`"
    )
    if readiness.get("graph_path"):
        print(f"- Graph: `{readiness['graph_path']}`")
    print(
        "- Graph checks: "
        f"fresh=`{str(readiness.get('graph_fresh') is True).lower()}`, "
        f"integrity=`{str(bool(readiness.get('graph_integrity_ready'))).lower()}`, "
        f"inputs=`{str(bool(readiness.get('graph_input_policy_ready') and readiness.get('knowledge_manifest_ready'))).lower()}`, "
        f"relationships=`{str(bool(readiness.get('graph_relationship_ready'))).lower()}`"
    )
    print("- Query/path smoke: `manual evidence required`")
    print(
        "- Static inspection does not substitute for canonical skill read evidence or "
        "the scoped query/path smoke result."
    )
    print()
