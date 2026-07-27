---
keyflow_id: sys_d1a668105819
status: stable
type: human-reviewed-needed
---

# Review And Commit Workflow

Use after implementation, before handing off or committing.

## Read

- `common/skills/code-review/SKILL.md`
- `common/skills/change-size-policy/SKILL.md`
- `common/skills/worktree-hygiene/SKILL.md`
- `workflows/skills/development-cycle/SKILL.md` for side-effect audit questions
- matching platform review card
- `common/skills/commit-workflow/SKILL.md`
- `common/skills/branch-strategy/SKILL.md` when branch creation, branch naming, PR source
  branch, or push target is in scope
- `common/skills/commit-review/SKILL.md` when reviewing existing commits
- `common/skills/generated-files-policy/SKILL.md` when generated files, lockfiles, or snapshots changed
- `common/skills/api-contract-compatibility/SKILL.md` when API, route, DTO, event, webhook, or fixture contracts changed
- `common/skills/release-deployment/SKILL.md` when packaging, deployment, signing, migration rollout, or release config changed

## Steps

1. Inspect the final diff, not memory of the work.
2. Use the Review Hook as the default final code-review gate when it is
   installed and applicable. Do not duplicate a full manual code review only to
   repeat hook checks. When the hook identifies a multi-role runtime package,
   make the structure evidence explicit with `owner`, `allowed imports`,
   `forbidden imports`, `callers/tests`, and `verification`; a prose-only
   boundary summary does not satisfy that contract.
   The hook validates evidence; it does not discover or infer it. Never invoke
   a bare `review` command for a completed change. Pass the review decision and
   every route-required evidence field in the same call:

   ```text
   tao-hook review --project <TARGET_REPO> --rules <TAO_ROOT> \
     --review-outcome pass \
     --code-review-evidence "<exact diff and request/rule review>" \
     --docs-freshness-evidence "<updated or grounded unchanged docs>" \
     --structure-review-evidence "<runtime size and ownership review>" \
     --boundary-plan-evidence "<owned scope and nearest verification>" \
     --side-effect-audit-evidence "<final diff and side-effect audit>"
   ```

   Omit a field only when `tao-hook review --help` and the active route both
   confirm it is not required. A missing field is a failed checkpoint, not a
   prompt for the hook to perform that review.
   Use `--review-outcome findings` only when unresolved findings intentionally
   keep the checkpoint failed. When the hook reports structure pressure, record
   whether the diff increased the unit size or added a responsibility; do not
   omit `--structure-review-evidence` merely because the pressure was
   pre-existing.
3. Confirm boundary-plan evidence exists for code work, or record why the
   change had no code boundary.
4. Confirm affected docs are updated, or record why no docs changed.
5. Confirm side-effect audit evidence names the final diff and unexpected
   generated, lockfile, public-contract, external-state, formatting, or
   unrelated behavior.
6. Run or record the nearest useful verification.
7. Remove only unused code created by the change.
8. Split unrelated work before committing.
9. Confirm Commit Readiness Gate evidence from `common/skills/commit-workflow/SKILL.md`.
10. Discover repo-local policy before any branch creation, push, PR, tag, or
   release publication.
11. Write a commit message that states intent, context, and verification.

Run a targeted manual review only when the Review Hook is unavailable, fails,
does not cover the changed surface, or the task touches high-risk behavior that
requires human judgment beyond the hook: auth, permissions, data loss,
migrations, billing, release, deployment, public API compatibility, or broad
architecture changes.

## Verification

Before handoff or commit, confirm:

- every required scripted workflow gate is `🐱🟢 SUCCESS`
- VibeGuard or the repo-local safety gate passed when required
- Review Hook passed with code review evidence and docs freshness evidence, and
  it did not mutate the worktree or hide broad fixes inside the hook
- for code-work routes, Review Hook received boundary-plan and side-effect audit
  evidence from the actual route, not a generic "done" phrase
- if the Review Hook was unavailable or skipped, the final report explains the
  replacement review evidence and residual risk
- the nearest behavior, contract, build, or manual smoke check ran or the skip
  reason and residual risk are explicit
- `git diff --check` or repo formatter/lint covered whitespace or formatting
  when documentation/code formatting changed
- If the Review Hook reports workflow validation failure, preserve the
  validator diagnostic in the failure output and reproduce that exact validator
  before selecting and applying the durable repair. A generic failure without
  the invalid path or contract hides the repair scope and cannot authorize
  checkpoint resume.
- staged diff matches the intended commit scope when a commit is being created
- Commit Readiness Gate evidence is satisfied
- external-state targets are discovered from repo-local policy before branch
  creation, push, PR, tag, release, or deploy

Do not commit based on memory. Review the exact staged diff and verification
evidence that will be represented by the commit message.

## Output

Report changed files or commit SHA, verification results, skipped checks,
remaining risk, and any intentionally unstaged or unrelated user-owned changes.

## Stop If

- The diff includes unrelated feature, refactor, generated, dependency, or release changes that can be split.
- The Review Hook reports that the changed path count is too broad for one
  review pass.
- The review requires a fix larger than the current scoped task; start a
  separate routed task instead of folding the update into review.
- Required verification failed and the failure is not understood.
- Secrets, local config, signing material, or private data appear in the diff.
- The commit message would need to hide uncertainty about product behavior,
  migration risk, security impact, or skipped checks.
- The correct base branch, PR target, release branch, or tag target is ambiguous
  and the next action would mutate git history or remote state.
