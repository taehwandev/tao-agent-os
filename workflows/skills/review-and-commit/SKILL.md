---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use for final review and commit/push/PR preparation. Reuse unchanged readings.
Load `references/current-guidance.md` for `--commit-ready`, unresolved procedure
or route requirements. Other skills need a finding, unresolved decision or
applicable rule; load references only if their entrypoint cannot resolve it.

## Process

1. Batch branch/status, changed-path and scoped-diff reads; inspect every result
   and full final diff, not stats/truncated patches. Refresh affected evidence
   after edits/staging/integration.
   Keep mutations/dependent checks sequential under runtime permissions.
2. Reuse matching checks under `common/skills/testing/references/final-check.md`
   and gate-batch remaining list. Review Hook replaces duplicate adjacent audits.
   A finished, clean, unchanged worktree's fast-forward is admitted by its
   finish, not a commit route; other merges keep that route.
   Mechanical reuse requires a registered worktree's single-commit attestation,
   clean target at that commit, exact parent/bytes, unchanged rules/checker/limits
   and valid source evidence; else run full checks. Audit/drift checks and the
   new review record stay fresh.
3. Repair findings only with reproducer, impact, current-diff causality, owner
   and nearest falsifying check. Give proven blockers one bounded repair/recheck;
   otherwise record follow-up or stop publication.
4. Run Review Hook with advertised outcome and required evidence, never bare
   `review`. For changed multi-role packages (including existing ones), pass
   `--structure-review-evidence`, not `--boundary-plan-evidence`, with:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.
   TypeScript retains unchanged legacy support declarations; new/expanded
   declarations count as new owners. Details: reference.

## Commit And PR Minimum

Stage/review the exact unit; reuse only unchanged bytes/target evidence. Stop on
findings/drift; no implementation under `commit`. Before push, check remote,
visibility, strict safety gate and authority.

When implementation includes commit authority, stage before final review/finish;
an eligible local commit follows directly without another lifecycle. New
authority, changed scope or stale evidence uses the lightweight `commit` route.

Load `common/skills/commit-workflow/references/current-guidance.md` only for
unresolved branch, tracker/signing, mixed/generated commit, security/migration/
release risk or publication exceptions. This skill's reference owns same-run
continuation, PR reuse, merge order and rejected commands. Commit/PR work alone
needs no development/branch-strategy cards.

## Do Not

- Ordinary pushes/PRs use `commit`, not `release`/`ship`, unless release
  artifacts, deployment, tags or rollout are requested.
- Do not rediscover advertised commands with `--help`, reread unchanged reviewed
  source or implement non-blocking observations.

Tao workflow validation keeps normal-code-route required reading below 100,000
aggregate bytes. Compact duplication, preserve contracts; no Codex-only gate.
