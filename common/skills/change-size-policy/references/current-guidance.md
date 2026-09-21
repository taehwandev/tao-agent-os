---
keyflow_id: sys_change_size_policy
status: stable
type: human-reviewed-needed
---

# Change Size Policy

Use when deciding how much code to change, whether to split work, or whether a
diff is reviewable.

## Default

Prefer one narrow vertical slice that can be understood, tested, and reverted.

Small is not the goal by itself. The goal is a change with one clear intent and
enough surrounding code to be correct.

## Reviewable Unit

A good change usually has:

- one behavior, bug fix, refactor, or infrastructure purpose
- one primary owner boundary
- focused tests or a clear smoke check
- no unrelated formatting, generated churn, dependency update, or cleanup

For behavior-preserving extraction, choose the unit by its contract rather
than by function count. Related moves may share one unit when they serve the
same owner and acceptance criterion, remain reviewable within project limits,
and can be reverted together. Do not create a separate full closeout merely
for every helper moved, or enlarge the scope merely to amortize overhead.
Run focused checks as that unit develops and the required broader verification
on its final state before commit. Explicit per-step project gates still apply.
Unrelated owners, different risks or separate rollback needs remain split
signals; lifecycle savings never justify skipping their checks.

## Split Signals

Consider splitting when:

- behavior change and refactor are both substantial
- formatting or generated files obscure the real diff
- a dependency update is mixed with product behavior
- migrations, API contracts, permissions, or billing rules change alongside UI work
- more than about 10 source files or 300 non-test lines changed without a single obvious intent
- rollback would require reverting unrelated behavior

Do not split when the pieces cannot compile, test, migrate, or make sense
independently.

## Large Change Requirements

For a large but necessary change, record:

- why it cannot be split safely
- which files are mechanical versus behavioral
- what verification covers the risky parts
- what rollback or forward-fix path exists

## Avoid

- Broad cleanup while implementing a feature.
- Moving files and changing behavior in the same diff without a reason.
- Using generated churn to hide manual edits.
- Leaving placeholder behavior that makes the diff look complete.

## Check

- Can this be reviewed in one pass?
- Can this be reverted without removing unrelated work?
- Does every changed line trace to the stated purpose?
- Would a smaller slice still prove the product or technical goal?
