---
keyflow_id: sys_branch_cleanup
status: review
type: ai-generated
---

# Branch Cleanup

Use when deleting merged local branches, removing their worktrees, or pruning
remote branches. Deletion is destructive git-state work: a branch is deleted
only when every gate below passes; everything else is reported, not deleted.

## Use When

- Local branches or worktrees have accumulated and need cleanup.
- Asked to remove merged branches or stale worktrees.
- Asked explicitly to clean remote branches. Remote deletion never happens
  without an explicit user request.

## Inspect First

1. Repo-local policy for the integration branch, protected branches, and the
   branch owner-prefix convention. When no repo-local rule exists, use the
   `common/skills/branch-strategy/SKILL.md` default
   `<git-username>/<work-unit>/<description>`, where the first segment is the
   owner.
2. `git fetch --prune`, then `git worktree list` and `git branch -vv` for the
   current state.

## Deletion Gates

Every deletion target must pass all gates. A failed gate means report, not
delete.

### Ownership

Delete only branches whose owner segment matches the current git identity.
Branches owned by someone else are never deleted, regardless of merge state or
how abandoned they look. Branches with no owner prefix have an unknown owner
and are never deleted. Report both kinds when noticed.

### Protected Branches

Never delete the integration branch, `main`/`master`/`trunk`, or `release/*`
branches, even when they appear fully merged. Release branches are history;
versioning and CI may derive values from their tags.

### Merge Judgment

Treat a branch as merged only when
`git merge-base --is-ancestor <branch> origin/<integration>` passes.

- Judge against the remote integration branch. The local one may lag.
- Do not rely on `git branch -d`'s own merge judgment; use `-D` only on
  branches that passed the ancestry check above.
- Squash- or rebase-merged branches fail the ancestry check even when their
  content landed. Do not auto-delete on that guess: collect
  `git cherry origin/<integration> <branch>` evidence and ask the user to
  confirm before deleting.

### Worktree State

Uncommitted changes in a branch's worktree mean in-progress work. Preserve
both the worktree and the branch even when the branch tip is merged. Show the
user the dirty status output that justified preserving them.

## Process

1. `git fetch --prune`; classify each worktree as clean, dirty, or
   gone-directory.
2. `git worktree prune -v` to drop registrations whose directory is gone.
3. Remove clean worktrees whose branch passed all gates with
   `git worktree remove <path>`, before deleting the branch itself. Removal of
   large build outputs can take minutes per worktree; use a generous command
   timeout. An interrupted removal leaves a half-deleted tree; if that
   happens, re-confirm the branch is merged, then finish with
   `git worktree remove --force <path>`.
4. Immediately before deleting branches, fetch again and re-run the ancestry
   check per branch. Concurrent sessions can move the branch tip or the
   remote integration branch while slow worktree removal runs. Checked-out
   branches cannot be deleted, so preserved worktrees keep their branches
   automatically.
5. Remote deletion, only on explicit request: show the classification table
   first, then re-verify ancestry immediately before each
   `git push origin --delete <branch>`. Many remote work branches are already
   deleted by the PR host on merge and show locally as `upstream: gone`; the
   real deletion list is usually short.

## Recovery

Log the tip SHA of every branch before deleting it.

- Local branch: recover the SHA from the cleanup log or `git reflog`, then
  `git branch <name> <sha>`.
- Remote branch: re-push the recorded SHA.

## Do Not

- Do not commit or push content changes from a cleanup task.
- Do not delete a branch another person owns, whatever its merge state.
- Do not delete on squash/rebase-merge suspicion without user confirmation.
- Do not judge merge state against a local integration branch.
- Do not use `git worktree remove --force` before re-confirming the branch is
  merged.

## Stop If

- The integration branch or the owner-prefix convention cannot be determined.
- Ancestry re-verification fails or disagrees with the earlier classification.
- A deletion target is checked out, dirty, protected, or not owned.

## Report

After cleanup, report:

- before and after counts for worktrees, local branches, and remote branches
- every preserved item with its reason (dirty worktree, unmerged, not owned,
  protected)
- the logged SHAs of deleted branches
- any incident during cleanup (timeout interruption, concurrent tip movement);
  never hide one
