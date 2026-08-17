---
keyflow_id: sys_docs_agent_runtime_integration_md_skill
status: review
type: ai-generated
---

# Agent Runtime Integration

Use when routed to `docs/skills/agent-runtime-integration/SKILL.md` or when work needs this Tao Agent OS guidance area.

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

## Required-document drift recovery

- If finish reports that a required document changed during the run, stop before
  final reporting and record a documentation-success receipt for each affected
  route-relative document.
- The receipt must include `decision=updated`,
  `artifact_receipt_version=1`, `baseline_sha256`, `final_sha256`, and
  `final_size_bytes`; then run the prescribed repair verification and resume
  from the first failed checkpoint.
- Do not bypass the required-document snapshot or treat a successful code
  review as sufficient evidence for finish while the receipt is missing.
