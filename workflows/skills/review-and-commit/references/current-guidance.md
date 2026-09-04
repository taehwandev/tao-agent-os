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
   fingerprint, full worktree fingerprint, exact review pathspec or commit
   subject, and changed path count. Finish accepts the gate only while those
   bindings still match. For commit ranges, finish re-resolves both commit
   objects and recomputes the exact changed-path list before accepting the
   attestation.
   The Review Hook defaults to working-tree changes. Run that form before
   commit in the worktree that owns the uncommitted diff. A clean checkout or
   pathspec is not evidence for an already committed range. When the requested
   subject is an existing commit, first apply the commit-review workflow, then
   attest the same exact range through the hook:

   On a checkout that concurrent sessions share, the default working-tree scope
   often does not describe this task's change, and the fix is the scope flag
   rather than the evidence text. Two shapes recur:

   - **The tree holds changes this task did not make.** The hook then demands
     structure-review evidence for files this run neither wrote nor read. Scope
     to your own paths instead:
     `--review-scope pathspec --review-path <path> [--review-path <path> ...]`.
     Never attest structure review for a foreign path; if the demanded evidence
     covers one, the scope is wrong, not the evidence. Passing merely because
     unrelated modified files satisfied the scope guard is the right answer for
     the wrong reason.
   - **The task route only prepares external task state** (for example, a tracked
     work item plus a sibling branch/worktree) and deliberately keeps the protected
     checkout clean. Use `--review-scope pathspec` with the exact existing task
     workflow `.../task/SKILL.md` that was followed. The hook accepts this clean
     scope only when the bound preflight route is `task` and its effective effect is
     `git_write` or `external_write`; boundary-plan and side-effect-audit evidence
     must still name the protected checkout and the created state. The implementation
     worktree starts and closes its own review lifecycle. Do not manufacture a diff.
   - **The task restores a tracked path that was already dirty at route start.**
     Use `--review-scope pathspec` with every exact existing path restored to
     committed bytes. The hook accepts this clean scope only when the same
     preflight recorded every path in `surface_candidates.dirty_paths`, the run
     has write authority, and it is not read-only. This proves a bounded cleanup
     outcome without admitting an arbitrary clean checkout; paths that were not
     dirty at start, globs, and removed or missing paths remain rejected.
   - **Another task changes no files at all** (repo hygiene: removing merged
     worktrees, branches or stashes without a task-setup preflight). Use
     `--review-scope repo-hygiene` without `--review-path`. The hook accepts this
     scope only when the bound preflight records destructive authority, routes a
     `branch` or `worktree` concern, and the protected checkout is clean. Review
     and report the exact post-action Git state re-reads in the evidence fields;
     the attestation binds the clean checkout and current runtime state through
     finish. Do not manufacture a diff, reuse this scope for source changes, or
     attest another session's cleanup.
   - **The run is explicitly read-only and inspects existing source files.** A
     clean checkout has no diff, but the route may still require review evidence
     for the inspected boundary. Use `--review-scope pathspec` with one or more
     exact existing repo-relative files or directories. The hook accepts this
     only when the bound preflight declares `execution_mode.read_only=true`, the
     checkout is clean, every path exists inside the project, and no glob is
     used. This attests the named inspection surface; it is not a substitute for
     working-tree or commit-range review of a mutation.
   - **The task changes an ignored local agent boundary.** Use
     `--review-scope local-config --review-path <exact-path>` only for the
     allowlisted project-root adapter files `.codex/hooks.json`,
     `.claude/settings.json`, and `.claude/settings.local.json`, or the canonical
     Graphify final artifacts `.agents/local/graphify-out/graph.json`,
     `.agents/local/graphify-out/manifest.json`,
     `.agents/local/graphify-out/GRAPH_REPORT.md`, and
     `.agents/local/graphify-out/graph.html`. The hook requires each path to be
     an existing, non-symlink, Git-ignored file; it rejects globs, tracked files,
     Graphify caches/intermediates/cost records, and every other ignored path.
     Because Git has no diff for this boundary, review the current bytes and
     report that scope in the evidence fields. The attestation binds each file's
     path, size, and SHA-256 and finish recomputes them, so a post-review edit
     invalidates the gate. Never manufacture a staged diff or use this scope for
     secrets, arbitrary ignored files, product source, or committed changes.

   ```text
   tao-hook review --project <TARGET_REPO> --rules <TAO_ROOT> \
     --review-scope commit-range \
     --review-base <BASE_COMMIT> --review-head <HEAD_COMMIT> \
     --review-outcome pass \
     --code-review-evidence "<exact committed diff and request/rule review>" \
     --docs-freshness-evidence "<updated or grounded unchanged docs>" \
     --structure-review-evidence "<runtime size and ownership review>" \
     --boundary-plan-evidence "<owned scope and nearest verification>" \
     --side-effect-audit-evidence "<committed diff and side-effect audit>"
   ```

   Commit-range review resolves both refs to immutable commit SHAs, requires
   the base to be an ancestor of the head, and rejects an empty range. It reads
   changed paths and line counts from that exact Git diff, materializes the
   head commit in an isolated local clone for structural and VibeGuard checks,
   and runs `git diff --check <base-sha> <head-sha> --`. It never substitutes
   the clean checkout's current file bytes for the committed subject.
   When the target branch is rebased onto a newer integration base, treat the
   rebase as a new committed subject: resolve the new base and head to
   immutable SHAs, rerun commit-range review, and re-record the route's
   retrospective check and remaining closeout gates before pushing. Do not
   carry a review attestation or finish evidence across that rebase.
   Finish must revalidate the review attestation after all final checks and
   immediately before it reports completion. The initial validation establishes
   eligibility to run those checks; it is not permission to accept a worktree
   that changed while they ran.
   A successful finish settles the run and closes its gate ledger. If any
   tracked or untracked worktree byte changes afterward (for example, a rebase
   or conflict-resolution merge), do not reuse that run's preflight evidence or
   invoke review against its closed ledger. Carry the same bounded objective and
   approvals into a fresh start, then record source-doc, review, readiness, and
   finish evidence for the new worktree snapshot.
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
   drift to the execution snapshot. First compare the current bytes with the
   preflight snapshot: if the drift predates this task and the task did not own
   that document, preserve the canonical bytes and bind them with the exact
   required-doc receipt; do not rewrite the document merely to clear the
   snapshot. Run `repair-verify` only when the current task actually changed the
   required document or when the failed checkpoint identifies a runtime repair
   target.
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
