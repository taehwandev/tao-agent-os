---
keyflow_id: sys_common_code_structure_ownership_md_skill
status: stable
type: ai-generated
---

# Code Structure And Ownership

Use when routed to `common/skills/code-structure-ownership/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for where new code belongs, ownership levels,
  package layout, and what must not import what.
- `references/unit-size.md` when judging whether a unit has grown past one owner
  and one verification path.
- `references/structure-stops.md` when checking whether a condition stops the
  change outright before writing it.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this
   area, and its siblings only for the question each one answers.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for
  `references/current-guidance.md`, `references/unit-size.md`, and
  `references/structure-stops.md`.
