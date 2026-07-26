---
keyflow_id: sys_f6cb537c3133
status: stable
type: ai-generated
---

# Refactoring Guidance

Use when behavior should stay the same and structure should improve.

Refactoring is not a shortcut for changing product behavior. If behavior,
contract, persistence, permissions, or output changes, treat that part as a
behavior change and verify it separately.

## Order

1. Identify the current behavior to preserve.
2. Identify the public contracts and side effects near the change.
3. Find one responsibility boundary.
4. Rename, extract, delete, or move the smallest useful unit.
5. Move code only after ownership and callers are clear.
6. Run the nearest verification.

## Before Refactoring

Confirm:

- Current behavior is understood through tests, fixtures, logs, docs, or a manual
  scenario.
- Repo-local instructions allow the kind of cleanup being attempted.
- The worktree has no user-owned changes that would be overwritten.
- The touched code's state owner, data owner, and side-effect owner are known.
- The nearest verification is identified before editing.
- Generated files, dependency changes, and formatting churn can stay separate.

For risky surfaces, add or run a characterization check before moving code.
Risky surfaces include auth, permissions, billing, persistence, cache,
migrations, public APIs, platform integration, release packaging, external
state, and security-sensitive logs or diagnostics.

## Refactor Types

- Rename only: keep behavior and call graph unchanged; update all references and
  tests together.
- Extract pure helper: prefer logic with no IO, mutation, time, randomness,
  process state, global state, or platform calls.
- Move file or module: preserve exports first; change import paths separately
  from behavior when possible.
- Split large file: map responsibilities, callers, state, side effects, and
  tests before extracting.
- Delete dead code: prove it is unreachable, unused, or replaced; avoid deleting
  unrelated suspicious code during feature work.
- Introduce adapter: use when a platform, SDK, storage, network, or permission
  boundary needs one owner.
- Contract-facing cleanup: routes, DTOs, schemas, events, persisted fields,
  generated clients, cache keys, and public APIs need compatibility review.

## Good Targets

- UI file owns too much state calculation.
- API/DTO mapping leaks into UI.
- Permission checks repeat inline.
- Platform SDK calls appear across screens.
- Error mapping, serialization, or cache invalidation repeats differently across
  callers.
- Tests need a smaller boundary to verify the product rule.

## Large File Rule

Do not split a large file first.

First map:

- responsibilities
- public exports and callers
- state ownership
- side effects and external systems
- persistence, cache, auth, permission, or billing contracts
- nearest tests or smoke paths

Then extract pure helpers before moving side-effectful code. Move behavior and
change behavior in separate steps unless the repo-local plan explains why they
cannot be split.

## Structural Hard-Gate Recovery

When review reports that a changed function or component grew beyond its hard
limit, do not treat a written justification as a bypass. Extract the smallest
cohesive responsibility until the changed unit is within the limit. If the
project genuinely needs a different limit, use only an explicit,
project-reviewed limit with repository evidence; never raise it ad hoc for one
diff. For integration merges, inherited changes are still part of the combined
result when they enlarge the unit, so resolve the boundary before committing
the merge.

## Contract Rule

A refactor that changes any of these is not pure refactoring:

- route, URL, deep link, command, or public API
- request, response, DTO, schema, fixture, or generated client
- persisted field, migration, import/export format, or read model
- event, webhook, queue message, background job payload, or cache key
- auth, permission, entitlement, tenant, billing, or visibility behavior

When a contract-facing item changes, also use the matching compatibility,
security, persistence, caching, or release guidance from the shared index and
the repo-local instructions.

## Avoid

- Big file moves without behavior checks.
- New abstractions before real duplication.
- Mixing feature change, formatting churn, and refactor.
- Renaming public APIs, packages, routes, events, or persisted fields without a
  compatibility plan.
- Refactoring through unclear product behavior; clarify the behavior first.

## Do Not Refactor When

- The current task needs a targeted bug fix or release recovery.
- The diff would hide security, billing, migration, or contract risk.
- Existing tests cannot protect the behavior and the touched surface is risky.
- The proposed abstraction has only one caller and no real boundary to protect.
- The cleanup requires changing product behavior before the behavior is agreed.
- The refactor would mix unrelated dependency, generated, formatting, migration,
  release, or platform changes.

## Verification

For pure refactors, verify that preserved behavior still passes:

- nearest unit, component, route, or integration test
- typecheck/build when exported contracts or module boundaries changed
- manual smoke path when no useful automated check exists
- contract or consumer check when public shape changed intentionally

Do not report a refactor as complete when only formatting passed for behavior
that can break at runtime.

## Done

Report:

- preserved behavior
- structural change made
- files or contracts intentionally not changed
- verification run or skipped with residual risk
- follow-up cleanup left separate

The next change location should be clearer, failure flow should be easier to
see, and tests or smoke checks should still pass.
