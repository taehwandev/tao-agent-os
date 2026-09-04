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

Use the cheapest authoritative evidence and stop once it decides the branch:

1. For PR-backed branches, fetch once immediately before classification and
   query the forge once for all candidates. A PR is sufficient proof when its
   state is `MERGED`, its base is the integration branch, and its recorded head
   SHA equals the fetched remote branch tip. Delete that branch without an
   ancestry check, `git cherry`, content diff, or repeated per-branch PR query.
2. A PR that is open, closed without merge, aimed at another base, or whose
   head SHA no longer matches the branch tip is unmerged. Preserve it and stop;
   do not run content-equivalence heuristics trying to turn it into a deletion.
3. When no authoritative PR record exists, fall back to
   `git merge-base --is-ancestor <branch> origin/<integration>`. Judge against
   the remote integration branch because the local one may lag.

Do not rely on `git branch -d`'s own merge judgment. A squash or rebase merge is
handled by the authoritative PR result above; without that result, preserve it
unless the ancestry fallback passes or the user explicitly approves a separate
manual recovery decision.

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
4. If slow worktree removal occurred after classification, fetch once more and
   reclassify affected tips. Otherwise do not repeat an unchanged check.
   Checked-out branches cannot be deleted, so preserved worktrees keep their
   branches automatically.
5. Remote deletion, only on explicit request: show the classification table,
   then batch the approved deletes into one push. Bind every deletion to the
   fetched tip with `--force-with-lease=refs/heads/<branch>:<sha>` so a
   concurrently moved branch is refused atomically instead of requiring a
   second fetch/query/check loop. Many remote work branches are already deleted
   by the PR host on merge and show locally as `upstream: gone`; the real
   deletion list is usually short.

## Recovery

Log the tip SHA of every branch before deleting it.

- Local branch: recover the SHA from the cleanup log or `git reflog`, then
  `git branch <name> <sha>`.
- Remote branch: re-push the recorded SHA.

## Do Not

- Do not commit or push content changes from a cleanup task.
- Do not delete a branch another person owns, whatever its merge state.
- Do not replace an authoritative non-merged PR result with content heuristics.
- Do not judge merge state against a local integration branch.
- Do not use `git worktree remove --force` before re-confirming the branch is
  merged.

## Stop If

- The integration branch or the owner-prefix convention cannot be determined.
- The authoritative PR result or ancestry fallback says the branch is not
  merged, or the leased deletion reports that its tip moved.
- A deletion target is checked out, dirty, protected, or not owned.

## Report

After cleanup, report:

- before and after counts for worktrees, local branches, and remote branches
- every preserved item with its reason (dirty worktree, unmerged, not owned,
  protected)
- the logged SHAs of deleted branches
- any incident during cleanup (timeout interruption, concurrent tip movement);
  never hide one
