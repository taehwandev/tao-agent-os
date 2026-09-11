---
keyflow_id: sys_common_task_intake_effort_routing_md_skill
status: stable
type: ai-generated
---

# Task Intake And Effort Routing

Use when routed to `common/skills/task-intake-effort-routing/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for the intake rules every request applies.
- `references/prd-creation-boundary.md` only when deciding whether work needs a PRD.
- `references/model-tier-selection.md` only when choosing a model or worker tier.
- `references/grill-me-protocol.md` only when a Grill-Me session is required or requested.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` when the task touches request clarity, effort, route selection, the alignment brief, or token controls; open a sibling reference only under its condition above.
3. Select the abstract effort/model tier before applying runtime-specific model ids.
4. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for every file under `references/`.
