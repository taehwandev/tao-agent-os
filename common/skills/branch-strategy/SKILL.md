---
keyflow_id: sys_common_branch_strategy_md_skill
status: stable
type: human-reviewed-needed
---

# Branch Strategy

Use when creating, naming, checking, reviewing, or documenting git work
branches in any repository, with or without a tracking ticket.

## Read

- Repo-local branch, PR, protected-branch, release-branch, and push rules first.
- `references/current-guidance.md` for the default shared branch naming and
  branch creation strategy.
- `../worktree-hygiene/SKILL.md` before creating, switching, pushing, or
  publishing branches.
- `../commit-workflow/SKILL.md` when the branch work continues into a commit.

## Process

1. Check repo-local branch policy and protected-branch rules first.
2. Resolve the owner's source-control hosting account ID using the reference;
   apply the shared format to every new work branch:
   ```text
   <account-id>/<work-unit>/<description>
   ```
3. Verify worktree context before any branch creation, push, PR, or tag action.
4. Report the selected branch name with evidence (see Report section).

## Do Not

- Do not invent a Jira, issue, ticket, or tracking id only to fill a branch name.
- Do not substitute a display name, Git author name, email, or repository owner
  for the work owner's hosting account ID.
- Do not choose a base branch, protected branch, release branch, PR target, or
  push target without repo-local evidence.
- Do not put secrets, customer names, unrelated account names, local paths,
  incident details, or private prompt text in a branch name. The required owner
  account ID belongs only in the first segment.

## Stop If

- The correct base or target branch is ambiguous and the next action would move
  work, mutate history, push, or open a PR.
- The worktree contains unrelated or user-owned changes that would be carried
  into the branch unintentionally.
- Repo-local branch policy conflicts with the shared default.
- The owner's hosting account ID is unknown or ambiguous.

## Verification

- Confirm the branch name follows the shared format and compatible repo-local
  policy, with a verified owner account ID.
- Confirm worktree context before branch creation, push, PR, or tag work.
- Run workflow validation when this card is added to routing, search, or tests.

## Report

Report the selected branch name, account ID and its source, work unit,
description slug, base/target evidence when relevant, and any resolved
repo-local policy conflict.
