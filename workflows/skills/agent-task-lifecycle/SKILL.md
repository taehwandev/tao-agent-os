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
4. Before invoking `review`, compare the active route order with the gate
   ledger. Every gate before `review hook` must have a structurally complete
   `SUCCESS` record; this includes `act`, `documentation`, `tests`,
   `side-effect audit`, and `verify` when the route lists them. Record those
   facts before the call because `review` validates prerequisites and does not
   backfill them.
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
