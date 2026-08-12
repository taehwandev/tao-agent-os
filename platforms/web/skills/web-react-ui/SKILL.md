---
keyflow_id: sys_platforms_web_web_react_ui_md_skill
status: review
type: ai-generated
---

# Web React UI

Use when the target Web repository is confirmed to use React, Next.js, Remix,
JSX, or TSX and work changes or reviews React UI structure, state, rendering,
interaction, or tests.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.
- `../../../../common/skills/react-rn-external-skill-source-coverage/SKILL.md`
  when external React skill provenance, source completeness, composition
  patterns, performance rules, or View Transition source behavior matters.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not load this card solely because the selected platform is Web. Confirm a
  React-family framework from the request, target paths, manifests, or existing
  source first.
- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
