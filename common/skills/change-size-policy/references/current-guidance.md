---
keyflow_id: sys_change_size_policy
status: stable
type: human-reviewed-needed
---

# Change Size Policy

Use when deciding how much code to change, whether to split work, or whether a
diff is reviewable.

## Default

Prefer one understandable, testable, revertible vertical slice with a clear
intent and enough surrounding code to be correct; function count is not the goal.

## Reviewable Unit

A good change usually has:

- one behavior, bug fix, refactor, or infrastructure purpose
- one primary owner boundary
- focused tests or a clear smoke check
- no unrelated formatting, generated churn, dependency update, or cleanup

Related behavior-preserving moves may share a closeout when they have one owner
and acceptance criterion, fit project review limits and can be reverted together.
Run focused checks during development and required broader checks on the final
state before commit; preserve explicit per-step gates. Do not split per helper
or enlarge scope just to amortize overhead. Different owners, risks or rollback
needs still favor splitting.

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

## Check / Avoid

Every changed line must serve the stated purpose and be reviewable in one pass;
choose a smaller slice if it still proves the goal. Do not mix unjustified file
moves and behavior changes, broad cleanup, generated churn that hides manual
edits, or placeholder behavior that only makes the diff look complete.
