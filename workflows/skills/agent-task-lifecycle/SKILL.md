---
keyflow_id: sys_workflows_agent_task_lifecycle_md_skill
status: stable
type: ai-generated
---

# Agent Task Lifecycle Workflow

Use when routed to `workflows/skills/agent-task-lifecycle/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.
4. Ordinary code routes use `start` as the scope baseline and require only
   final `tests`, `review hook`, and a short `retrospective check`. Do not create intermediate
   orientation, alignment, act, documentation, side-effect, verification,
   retrospective, or report records while the scope is unchanged. If A expands
   to A+B, record one semantic checkpoint; start a new route only when the
   project, authority, effect ceiling, or external target changes. Specialized
   routes still follow every gate they explicitly list.
   At closeout, check only skills actually used and concrete unnecessary reads,
   retries, or guidance gaps. Record `skills_checked`, `outcome`, `observation`;
   `no_reusable_gap` pairs with `not_needed`. Load skill-maintenance procedures
   only when a reusable gap remains; ordinary success requires no skill edit.
5. Immediately before `review` and `finish`, compare the active preflight's
   required-document hashes with the current Tao Agent OS files. Refresh
   with the same `start` request and evidence path before the hook when drift is
   found; after a hook has already failed on drift, bind that refresh to the
   verified repair receipt instead of erasing the failed checkpoint.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
