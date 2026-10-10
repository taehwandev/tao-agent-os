---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use for final review and commit/push/PR preparation. Load
`references/current-guidance.md` for `--commit-ready`, local merges/fast-forward,
same-run continuation, PR reuse, merge order, rejected commands or another
unresolved procedure.

## Process

1. Batch branch/status, paths and scoped diff; review the full patch. Refresh
   evidence after edits/staging/integration.
2. Reuse matching checks under `common/skills/testing/references/final-check.md`
   and gate-batch remaining list. Review Hook replaces duplicate adjacent audits.
3. Count touched legacy owners/spans before edits; put new exports in
   purpose-named modules and extract long handlers. Kotlin overloads and
   compatibility wrappers each count as declarations. Before behavior builds,
   run the stateless preview with `<TAO_ROOT>/scripts/agent-structure-check.py
   --project <TARGET_REPO>`; it checks structure without granting review approval.
   Stale links also block
   review: fix without raising limits. Resume the first failed checkpoint
   only with reproducer, impact, diff cause and nearest check; otherwise stop.
4. Run Review Hook in the shape start prints, never bare `review`. Changed
   multi-role packages (existing ones too) take `--structure-review-evidence`,
   not `--boundary-plan-evidence`, with:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.

## Commit And PR Minimum

Stage/review the exact unit; stop on findings/drift; no implementation under
`commit`. With commit authority, stage before final review/finish. Before push,
check remote, visibility, strict safety gate and authority.

Load `common/skills/commit-workflow/references/current-guidance.md` only for
unresolved branch, tracker/signing, mixed/generated commit, security/migration/
release risk or publication exceptions. Commit/PR work alone needs no
development, branch-strategy or module-design cards.

## Do Not

- Ordinary pushes/PRs use `commit`, not `release`/`ship`, unless release
  artifacts, deployment, tags or rollout are requested.
- Do not rediscover advertised commands with `--help` or implement non-blocking
  observations.
