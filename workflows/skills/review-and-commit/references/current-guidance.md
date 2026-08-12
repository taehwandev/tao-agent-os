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
   including an added runtime file entering an existing multi-role package,
   make the structure evidence explicit with `owner`, `allowed imports`,
   `forbidden imports`, `callers/tests`, and `verification`; a prose-only
   boundary summary or "no new package" claim does not satisfy that contract.
   Before invoking review, measure both the changed file and each changed class
   or function block against the route's structural limits. A file below its
   line budget can still fail because one owner block exceeds the function
   limit; do not wait for the hook to discover that avoidable split.
   Also count public and non-private top-level owners in every new runtime file,
   and inspect every new package path for broad segments such as `utils`,
   `helpers`, `common`, or `misc`. Move the implementation to a purpose-named
   package and collapse private support behind one public owner before review;
   existing legacy placement does not exempt a newly added runtime file.
   Use those exact literal labels followed by a colon (for example,
   `owner: domain; allowed imports: contracts`); grammatical variants such as
   `allowed imports remain ...` are still prose and will be rejected.
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
   Treat route startup's short evidence list as the universal minimum, not the
   final invocation shape: inspect the exact staged or working-tree diff first,
   and include conditional structure and side-effect evidence on the first
   review attempt whenever file-size pressure, a new runtime boundary, or a net
   deletion threshold applies. This also applies to the lightweight `commit`
   route after an implementation lifecycle has already finished.
   The `review hook` gate is hook-owned. Generic `gate` and `gate-batch`
   commands must reject it even when the caller supplies `source=review`,
   because a caller-provided source label is not execution provenance. A
   successful `tao-hook review` writes a run-local review attestation and binds
   the ledger entry to that attestation's current run, preflight hash, route
   fingerprint, full worktree fingerprint, exact review pathspec, and changed
   path count. Finish accepts the gate only while those bindings still match.
   Finish must revalidate the review attestation after all final checks and
   immediately before it reports completion. The initial validation establishes
   eligibility to run those checks; it is not permission to accept a worktree
   that changed while they ran.
   Copying an attestation to another run, changing any tracked or untracked
   worktree byte after review, or claiming a broader ledger scope than the
   attested pathspec must fail closed. Pathspec review remains valid for an
   explicitly scoped task; the attestation preserves that exact scope rather
   than silently upgrading it to a working-tree review.
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
   When any reviewed path has a net deletion of 50 lines or more, name that
   exact path in `--side-effect-audit-evidence`, identify what content was
   removed, and state why it is no longer needed. A generic final-diff summary
   does not account for a large deletion.
   When recovery changes a document that the active route already lists in
   `required_docs`, record its `documentation` SUCCESS artifact receipt before
   rerunning review or finish. A repair receipt alone does not bind required-doc
   drift to the execution snapshot.
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

## Remote Review Publication

When publishing review findings as comments on a hosted PR or review system:

1. Draft every comment locally first: one top-level summary plus per-finding
   comments, each carrying severity, the file and new-side line anchor, and
   the cited rule-source path. A finding without evidence does not enter the
   draft.
2. Show the full draft to the user and gate on explicit approval with these
   options: approve all, edit specific items, exclude specific items by
   number, or cancel. Never post without explicit approval; do not infer
   approval from silence or from earlier consent to review.
3. Post idempotently: skip a comment whose equivalent body already exists on
   the review. On partial posting failure, retry only the failed items and
   never re-post succeeded ones.
4. Count a post as successful only when the API returns a created-comment id,
   not merely a zero exit code. Report posted, skipped, and excluded counts.

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
