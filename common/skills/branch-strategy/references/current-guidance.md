---
keyflow_id: sys_branch_strategy
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Branch Strategy

Use this as the shared default for git branch naming and branch creation when a
repo has no stricter local policy.

Branch names are collaboration and release surfaces. They should identify the
owner and work unit clearly without leaking private context or pretending a
tracking ticket exists.

## Use When

- Creating or proposing a new work branch.
- Reviewing whether an existing work branch name is acceptable.
- Preparing PR, push, or handoff guidance where the source branch matters.
- Documenting repo-local branch policy when no ticket id is available.

Do not use this card to choose a protected branch, release branch, or deployment
source by memory. Repo-local branch, release, and publishing policy wins.

## Inspect First

1. Repo-local instructions for branch naming, protected branches, PR targets,
   release branches, and direct-push policy.
2. Current worktree state with `git status -sb` before branch creation,
   switching, push, PR, or tag work.
3. Current branch with `git branch --show-current`.
4. Remote and visibility with `git remote -v` before push or PR work.
5. Existing branch names when the repo has an informal but consistent pattern.

Do not let this shared rule override repo-local policy, protected-branch rules,
release procedures, or a host-specific workflow.

## Decision Rule

Use the most specific available branch policy. If repo-local policy names a
branch format, base branch, PR target, ticket placement, or release branch, use
that. If no repo-local branch naming rule exists and no ticket id exists, use
the shared default below.

## Default Naming

When no repo-local rule and no ticket id exists, use:

```text
<git-username>/<work-unit>/<description>
```

Segments:

- `git-username`: the user's git or hosting username, normalized for a branch
  segment. Prefer repo-local policy, then the source-control hosting username
  when it is known, then local git identity. If the source value contains
  spaces or uppercase letters, convert it to lowercase kebab-case.
- `work-unit`: the smallest reviewable unit of work. Prefer the same type
  vocabulary as commit messages: `feat`, `fix`, `refactor`, `docs`, `test`,
  `chore`, `build`, `ci`, `perf`, `security`, `release`, or `spike`.
- `description`: a short lowercase kebab-case summary of the work, normally two
  to six words.

Examples:

```text
taehwan/docs/branch-strategy
taehwan/refactor/skill-routing-cleanup
taehwan/fix/android-preview-coverage
```

If a Jira, GitHub issue, Linear issue, or similar tracking id exists and
repo-local policy allows it, include it at the start of the description segment:

```text
<git-username>/<work-unit>/<ticket-id>-<description>
```

Do not invent a ticket id when none exists.

## Slug Rules

- Use lowercase ASCII letters, digits, and hyphens inside each segment.
- Use `/` only as the segment separator.
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
4. Build the branch name from username, work unit, and description.
5. Confirm the branch name contains no private, secret, customer, account,
   incident, prompt, local-path, or credential material.
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
| "There is no ticket, so any branch name is fine." | Use `<git-username>/<work-unit>/<description>` and omit the ticket. |
| "The username is too personal." | Repo-local policy wins; otherwise the user-requested shared default uses username, so keep it normalized and avoid adding extra identity details. |
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

## Do Not

- Do not create, rename, delete, push, or publish branches unless that external
  state change is in scope.
- Do not assume `main`, `master`, `develop`, or `trunk` is the correct base.
- Do not place secrets, credentials, local paths, customer names, account names,
  private prompts, or sensitive incident details in branch names.
- Do not use vague names such as `misc`, `stuff`, `updates`, `cleanup`, or
  `work` when a concrete description is available.
- Do not reuse a branch for unrelated units of work only because it already
  exists.

## Stop If

- Repo-local policy conflicts with the shared default.
- The correct base branch, PR target, release branch, or protected branch status
  is unknown and the next action would mutate git state or remote state.
- The worktree has unrelated changes and the branch action would carry them
  forward without an explicit decision.
- The only available branch name would expose private or sensitive information.

## Verification

Before branch creation, push, PR, or handoff, verify:

- branch name follows repo-local policy or `<git-username>/<work-unit>/<description>`
- username source is known or explicitly assumed from local git identity
- work unit matches the actual change type
- description is lowercase kebab-case and contains no sensitive material
- base/target branch evidence is known before external state changes
- `common/skills/worktree-hygiene/SKILL.md` checks have been applied when
  moving work, pushing, or opening a PR

## Report

Report:

- proposed or created branch name
- username source, work unit, and description slug
- ticket id source, or that no ticket id was used
- base/target branch evidence when relevant
- any repo-local policy that overrode the shared default
