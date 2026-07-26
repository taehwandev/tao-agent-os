---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use when routed to `workflows/skills/review-and-commit/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.
4. Before the first Review Hook invocation, record the review outcome and every
   evidence field required by the active route. Never invoke the hook as a bare
   `review` command; pass the structured review, docs, structure, boundary, and
   side-effect evidence described in `references/current-guidance.md`.
5. When a changed package contains multiple roles, write structure evidence in
   this exact labeled form so the boundary contract is machine-checkable:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.
6. Apply the labeled boundary evidence rule even when the package already
   existed and no file move occurred; changed files can still expose multiple
   roles that the review hook must validate.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
