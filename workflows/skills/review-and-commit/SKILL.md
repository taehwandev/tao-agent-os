---
keyflow_id: sys_workflows_review_and_commit_md_skill
status: stable
type: ai-generated
---

# Review And Commit Workflow

Use for final review and commit preparation.

## Read

For a `commit` or `git_commit` follow-up, including push and PR, use this
entrypoint's publication minimum. Detailed cards are on demand; reuse complete,
unchanged readings.

- `references/current-guidance.md` for `--commit-ready` preparation, unresolved
  review procedure, or an explicit route requirement.
- A related skill only for a concrete finding, an unresolved in-scope question,
  or an explicit applicable project requirement. Follow its detailed reference
  only if the entrypoint does not answer that question.

## Process

1. Collect branch/status, changed paths and scoped diff in one bounded batch of
   independent reads; inspect every result. Read every in-scope final change:
   summaries locate scope, but a stat or truncated patch is not a review.
   Reuse unchanged observations; after edits, staging or integration refresh
   affected facts and review new differences. Keep mutations and dependent
   checks sequential under runtime permission contracts, not a shell-chain
   waiver. Commit/PR work alone needs no development or branch-strategy cards.
2. Reuse tests/builds under `common/skills/testing/references/final-check.md`.
   The Review Hook audit replaces an adjacent identical audit; reuse the
   gate-batch remaining list. Exact fast-forward integration requires clean
   target and commit identity checks, not another source review absent drift or
   new findings. Cite the original review/tests in any required integration
   review. Machine-check reuse requires the original single-commit attestation
   in a registered worktree, clean target at that commit, exact parent and
   changed bytes, unchanged rules/checker/limits, and valid source evidence.
   Otherwise run full checks. Safety audit, drift checks and the new review
   record remain fresh.
3. Repair a final-review finding only with a reproducer, impact, evidence this
   diff caused it, owner, and nearest falsifying check. Give a proven blocker
   one bounded repair and affected recheck; otherwise keep it as follow-up or
   stop publication.
4. Run Review Hook with its advertised outcome and every required evidence
   field, never bare `review`. For any changed multi-role package, even an
   existing one, pass the exact labeled contract separately through
   `--structure-review-evidence`, not `--boundary-plan-evidence`:
   `owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...; verification: ...`.
   TypeScript owner comparison retains unchanged legacy support declarations;
   new or visibility-expanded declarations still count as new owners.
   See `references/current-guidance.md` for rationale and examples.

## Commit And PR Minimum

Stage only the exact unit; review its staged diff and reuse evidence only while
the covered bytes and target are unchanged. Stop on findings or drift; no hidden
implementation under `commit`. Before push, check remote, visibility, strict
safety gate, and authority for the exact action.

When an implementation request also authorizes commits, prepare the exact
staged unit before final review and finish. An eligible local commit then
continues directly without a second lifecycle. New commit authority, changed
scope, or stale evidence uses the lightweight `commit` route.

Load `common/skills/commit-workflow/references/current-guidance.md` only for an
unresolved branch, tracker/signing, mixed/generated commit,
security/migration/release risk, or publication exception. `references/current-guidance.md`
owns the same-run continuation contract, PR reuse and merge order, and how to
read a rejected command.

## Do Not

- Do not select `release` or `ship` for an ordinary branch push or pull request.
  Those publication follow-ups stay on the lightweight `commit` route unless
  the request also names a release artifact, deployment, tag, or rollout.
- Do not rediscover an advertised command with `--help`, reopen unchanged source
  after reviewing its final diff, or turn a non-blocking review observation
  into implementation work.
