---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use when routed to `workflows/skills/review-and-commit/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Read

For a `commit` or `git_commit` follow-up, including push and PR, use this
entrypoint and the routed commit card. Do not open the full reference or its
related skills merely because files are being committed. Reuse complete,
unchanged readings still in context; an unavailable reading is loaded only if
it is required for the current decision, not to rebuild a development library.

- `references/current-guidance.md` for an unresolved review procedure or when
  explicitly required by the route.
- A related skill only for a concrete finding, an unresolved in-scope question,
  or an explicit applicable project requirement. Follow its detailed reference
  only if the entrypoint does not answer that question.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Apply the Read conditions above; a commit or PR request alone does not require
   development-cycle, platform, API, branch-strategy, or worktree-hygiene reading.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.
4. Before the first Review Hook invocation, record the review outcome and every
   evidence field required by the active route. Never invoke the hook as a bare
   `review` command; pass the structured review, docs, structure, boundary, and
   side-effect evidence required by the route's returned review command. Open
   `references/current-guidance.md` only if that command leaves a question.
5. When a changed package contains multiple roles, write structure evidence in
   this exact labeled form so the boundary contract is machine-checkable:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.
6. Apply the labeled boundary evidence rule even when the package already
   existed and no file move occurred; changed files can still expose multiple
   roles that the review hook must validate.
7. Copy that exact labeled boundary contract into `--structure-review-evidence`;
   do not paraphrase it or assume `--boundary-plan-evidence` is merged into the
   structure field, because each review evidence field is validated independently.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
