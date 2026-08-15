---
keyflow_id: sys_2005f8bbf4b2
status: stable
type: ai-generated
---

# Commit Review

Use when reviewing one or more commits instead of the current working tree.

## Read

- Commit message: stated intent and scope.
- Diff: actual behavior changed.
- Tests: what was added, changed, or missing.
- Related docs: requirements, service guide, repo instructions.

## Decision Rule

Review the commit as a historical unit: the message, diff, generated artifacts,
and verification must describe one coherent change. If the commit is too broad
to reason about, that is itself a finding because rollback and ownership are
unclear.

When the active route requires the hook-owned `review hook` gate, the prose
review is necessary but not sufficient. Invoke the hook with
`--review-scope commit-range --review-base <base> --review-head <head>` for the
same reviewed subject. The hook resolves immutable commit SHAs and rejects
unrelated, reversed, invalid, or empty subjects rather than treating a clean
working tree as evidence for the commit.

## Check

- Does the commit do what the message claims?
- Is each changed line traceable to the commit purpose?
- Did it mix feature, refactor, formatting, or generated churn?
- Are migrations, API contracts, permissions, or data changes reversible or documented?
- Is there a test or verification path for the changed behavior?

## Do Not Approve When

- The commit message hides a behavior, contract, migration, security, release,
  dependency, or generated-file change.
- The commit mixes unrelated owners or workflows and can be split without
  breaking build or migration order.
- The commit changes public contracts, persisted data, permissions, billing, or
  release behavior without compatibility or rollback evidence.
- Verification only proves formatting or compilation for a runtime behavior
  change.

## Output

Lead with findings. Include commit SHA when useful. If the commit is too broad to review confidently, say what split would make it reviewable.
