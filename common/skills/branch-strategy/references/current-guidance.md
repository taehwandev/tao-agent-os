---
keyflow_id: sys_branch_strategy
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Branch Strategy

Use this as the shared naming rule for new Git work branches in all Tao-managed
repositories, including personal, shared, and company repositories, with or
without a tracking ticket.

Branch names are collaboration and release surfaces. They should identify the
owner and work unit clearly without leaking private context or pretending a
tracking ticket exists.

## Use When

- Creating or proposing a new work branch.
- Reviewing whether an existing work branch name is acceptable.
- Preparing PR, push, or handoff guidance where the source branch matters.
- Documenting repo-local branch policy with or without a ticket id.

Do not use this card to choose a protected branch, release branch, or deployment
source by memory. Repo-local branch, release, and publishing policy wins.

## Inspect First

1. Repo-local instructions for branch naming, protected branches, PR targets,
   release branches, and direct-push policy.
2. Current worktree state with `git status -sb` before branch creation,
   switching, push, PR, or tag work.
3. Current branch with `git branch --show-current`.
4. Remote and visibility with `git remote -v` before push or PR work.
5. The work owner's hosting account ID for the target repository's host, using
   the identity sources below. Existing branch names do not prove identity or
   establish an exception to the shared format.

Do not let this shared rule override repo-local policy, protected-branch rules,
release procedures, or a host-specific workflow.

## Decision Rule

Use the shared format below for every new work branch. Repo-local policy still
owns base branches, PR targets, protected refs, release refs, and compatible
ticket placement. If a repo-local naming rule requires a different format,
stop and resolve that conflict before creating a branch; do not silently drop
the owner segment. Shared integration and protected/release refs retain their
repo-defined names.

## Default Naming

For every new work branch, use:

```text
<account-id>/<work-unit>/<description>
```

Segments:

- `account-id`: the work owner's individual source-control hosting account
  login for the target host. Use the verified login, not a real name, display
  name, Git `user.name`, email local-part, repository/organization owner, or
  agent/runtime name. Resolve it as described below.
- `work-unit`: the smallest reviewable unit of work. Prefer the same type
  vocabulary as commit messages: `feat`, `fix`, `refactor`, `docs`, `test`,
  `chore`, `build`, `ci`, `perf`, `security`, `release`, or `spike`.
- `description`: a short lowercase kebab-case summary of the work, normally two
  to six words.

Examples with the illustrative account ID `alice`:

```text
alice/docs/branch-strategy
alice/refactor/skill-routing-cleanup
alice/fix/preview-coverage
```

If a Jira, GitHub issue, Linear issue, or similar tracking id exists and
repo-local policy allows it, include it at the start of the description segment:

```text
<account-id>/<work-unit>/<ticket-id>-<description>
```

Do not invent a ticket id when none exists.

## Owner Account ID

Use an account ID explicitly supplied by the user for the target host, a
repo-local mapping verified against that host account, or an authenticated
hosting profile verified for that host. A repository URL identifies its owner,
not necessarily the person who owns the work branch. An unrelated authenticated
account or automation account does not establish the user's identity.

Preserve the host's canonical login spelling, including permitted dots or
underscores; do not turn a display name into a guessed account slug. If the ID
is missing, ambiguous, or not Git-ref-safe, stop and ask for the correct host
account ID. Agents working for a user use that user's account ID.

Use this same resolved account ID when checking branch ownership during cleanup.
Existing branches are not automatically renamed or deleted by adopting this
rule; a migration needs its own explicit scope.

## Slug Rules

- Preserve the verified account ID in the first segment. Use lowercase ASCII
  letters, digits, and hyphens for the work unit and description, except a
  verified ticket ID whose casing repo-local policy requires.
- Use `/` only as the segment separator.
- Check the complete name with `git check-ref-format --branch <name>`.
- Keep the full branch name short enough to scan in PR lists and CI output.
- Prefer product-neutral descriptions such as `branch-strategy`,
  `login-error-state`, or `billing-webhook-retry`.
- Use the work unit to distinguish intent; do not hide a refactor, release,
  migration, or security change under `chore`.

## Branch Creation Process

1. Confirm the work belongs on a new branch rather than the current branch.
2. Check worktree state and preserve unrelated or user-owned changes.
3. Identify the correct base branch from repo-local policy or current task
   evidence.
4. Resolve the hosting account ID and build the three-segment branch name.
5. Confirm that only the owner segment contains the required account ID; exclude
   private, secret, customer, unrelated account, incident, prompt, local-path,
   or credential material.
6. Create or switch branches only after the base and dirty-worktree handling are
   clear.

## Stacked Integration Branch For Multi-Phase Work

When one large task must land as several reviewable pieces, orchestrate the
split as stacked branches instead of one oversized PR:

1. Split the work into phases; each phase is an independently reviewable unit.
2. Create a parent integration branch off the mainline, then branch each phase
   off the parent.
3. Each phase PR targets the parent integration branch, not the mainline.
4. After a phase PR is approved and merged, merge the phase branch back into
   the parent before branching the next phase.
5. Defer pushing the parent branch until the first phase is approved for push.
   Do not create speculative remote branches.
6. Open the final parent-to-mainline PR only after all phase PRs are merged.
7. Get explicit user approval before every push and every PR creation.
8. When a tracker exists, each phase's commits carry that phase's tracker id.

Use `common/skills/change-size-policy/SKILL.md` to decide whether to split;
this section owns how an approved split lands as branches and PRs. The
mainline is whatever repo-local policy names as the integration target, not an
assumed default branch.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "This is a personal repo, so an owner prefix is unnecessary." | All new work branches use `<account-id>/<work-unit>/<description>`. |
| "There is no ticket, so any branch name is fine." | Keep the shared format and omit only the ticket. |
| "A ticket already identifies the branch." | Keep the account ID and work unit; put the ticket at the start of the description. |
| "Git author metadata tells us the owner." | Resolve the hosting account login; commit authorship does not establish branch ownership. |
| "This is just docs, so branch context does not matter." | Docs can still publish, route, or affect agent behavior. Use `docs` as the work unit. |
| "The current branch is probably fine." | Check branch context before moving work, pushing, or opening a PR. |

## Red Flags

- Branch name uses `main`, `master`, `develop`, `release`, or a protected branch
  as if it were a personal work branch.
- Description contains a customer, account, secret, local path, incident detail,
  prompt text, or private repo codename.
- Branch name says `chore` while the work changes behavior, security, data,
  release, migration, or public contracts.
- Ticket id is guessed from the task text instead of sourced from repo-local
  policy, an issue, or the user.
- Branch is created before the base branch or dirty worktree handling is known.
- Owner segment is guessed from a display name, commit author, email, or remote
  repository owner, or omitted because the branch is local-only.

## Do Not

- Do not create, rename, delete, push, or publish branches unless that external
  state change is in scope.
- Do not assume `main`, `master`, `develop`, or `trunk` is the correct base.
- Do not place secrets, credentials, local paths, customer names, unrelated
  account names, private prompts, or sensitive incident details in branch names.
- Do not omit the account ID for personal, local-only, or ticket-backed branches.
- Do not use vague names such as `misc`, `stuff`, `updates`, `cleanup`, or
  `work` when a concrete description is available.
- Do not reuse a branch for unrelated units of work only because it already
  exists.

## Stop If

- Repo-local policy conflicts with the shared default.
- The work owner's hosting account ID cannot be verified for the target host.
- The correct base branch, PR target, release branch, or protected branch status
  is unknown and the next action would mutate git state or remote state.
- The worktree has unrelated changes and the branch action would carry them
  forward without an explicit decision.
- The only available branch name would expose private or sensitive information.

## Verification

Before branch creation, push, PR, or handoff, verify:

- branch name follows `<account-id>/<work-unit>/<description>` and compatible
  repo-local policy, for both ticket-backed and ticket-free work
- account ID and its source are verified for the target host
- work unit matches the actual change type
- description is lowercase kebab-case and contains no sensitive material
- the complete branch name passes `git check-ref-format --branch`
- base/target branch evidence is known before external state changes
- `common/skills/worktree-hygiene/SKILL.md` checks have been applied when
  moving work, pushing, or opening a PR

## Report

Report:

- proposed or created branch name
- account ID, host and identity source, work unit, and description slug
- ticket id source, or that no ticket id was used
- base/target branch evidence when relevant
- any resolved repo-local naming conflict
