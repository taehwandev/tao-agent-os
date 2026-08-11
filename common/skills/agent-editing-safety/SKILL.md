---
keyflow_id: sys_common_agent_editing_safety_md_skill
status: stable
type: ai-generated
---

# Agent Editing Safety

Use when routed to `common/skills/agent-editing-safety/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.
- Do not report a zero-reference result from an ignore-aware searcher. Before a
  delete, rename, or migration, answer "is anything still referencing this?" with
  an ignore-unaware sweep (`/usr/bin/grep -r`, or `rg --no-ignore --hidden`) and
  name which searcher produced the count. A shell `grep` may be a wrapper that
  skips gitignored and hidden paths, so its silence is not evidence of absence.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
- If a reference sweep decides a removal, state the searcher used and its count;
  a bare zero from an ignore-aware tool does not clear the check.
