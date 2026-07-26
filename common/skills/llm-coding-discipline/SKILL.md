---
keyflow_id: sys_common_llm_coding_discipline_md_skill
status: stable
type: ai-generated
---

# LLM Coding Discipline

Use when routed to `common/skills/llm-coding-discipline/SKILL.md` or when work needs this Tao Agent OS guidance area.

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

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
- Apply owner-count limits as a ratchet for legacy files: fail when the owner count or role mix grows, not when an existing owner is renamed one-for-one without structural growth.
- Review unstaged one-for-one file moves against their previous path instead of counting the full destination as new line growth. Destination package/path rules still apply to the moved file.
