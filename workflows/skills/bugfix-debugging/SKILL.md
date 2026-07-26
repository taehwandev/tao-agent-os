---
keyflow_id: sys_workflows_bugfix_debugging_md_skill
status: stable
type: ai-generated
---

# Bugfix Debugging Workflow

Use when routed to `workflows/skills/bugfix-debugging/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Review Preparation

- Before the first review, count the task-owned changed paths. If one cohesive
  bugfix legitimately exceeds the default path budget, pass a bounded maximum
  derived from the observed scope; do not discover the limit through a failed
  review or use a broad override for unrelated changes.
- For every changed package that already contains multiple roles, prepare
  structure evidence with the owner, allowed imports, forbidden imports,
  callers/tests, and verification. "No new boundary" alone is insufficient.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
