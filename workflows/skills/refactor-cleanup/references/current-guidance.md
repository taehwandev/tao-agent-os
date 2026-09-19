---
keyflow_id: sys_refactor_cleanup_workflow
status: stable
type: human-reviewed-needed
---

# Refactor Cleanup Workflow

Use when behavior should stay the same and the goal is structure, naming,
ownership, deletion, or maintainability.

## Read

- `common/skills/refactoring/SKILL.md`
- `common/skills/code-conventions/SKILL.md`
- `common/skills/change-size-policy/SKILL.md`
- `common/skills/testing/SKILL.md`
- `common/skills/verification-policy/SKILL.md`
- matching platform architecture card from `index.md`
- `common/skills/api-contract-compatibility/SKILL.md` when routes, DTOs, schemas, events,
  persisted fields, generated clients, or public APIs may change
- `common/skills/server-side-caching/SKILL.md` when cache keys, tags, TTL, materialized read
  models, or invalidation may change
- generated-files, dependency, security, persistence, or release policy when
  those surfaces change

## Steps

1. Identify the current behavior and the next change that the refactor should make easier.
2. Identify the contracts, state owners, side effects, generated files, and tests
   near the change.
3. Choose one ownership boundary: UI, state, domain, data, platform, contract, or test.
4. Make the smallest move, rename, extraction, deletion, or adapter cleanup that improves that boundary.
   After an extraction unit, check its structural boundaries before broad builds
   or browser suites: `python3 <TAO_ROOT>/scripts/agent-structure-check.py
   --project <TARGET_REPO> --review-path <OWNED_PATH>` (repeat the path option
   for disjoint owners). This read-only preview uses the final review's checks;
   it creates no lifecycle state and does not replace behavior tests or review.
   Fix actual responsibility boundaries, not just declaration counts: do not
   hide independently used types behind an umbrella export or indirect type
   lookup solely to satisfy the counter. Keep private implementation details
   private; separate independently owned public contracts by purpose.
5. Avoid changing product behavior, formatting unrelated files, or mixing dependency updates.
6. Verify behavior with the nearest existing check or a focused smoke path.
7. Report the preserved behavior, structural change, unchanged contracts, verification, and any follow-up left separate.

## Verification

Refactor verification proves preserved behavior, not only formatting:

- nearest unit, component, route, reducer, ViewModel, hook, command, or service
  test for the moved or extracted behavior
- compile/typecheck/build when public exports, package membership, imports, or
  module boundaries changed
- contract, fixture, generated-client, migration, or cache-key check when public
  shape changed intentionally
- manual smoke path only when automated coverage is absent, with the preserved
  behavior stated explicitly

If behavior changed, split or report that portion as a behavior change rather
than a pure refactor.

## Stop If

- The refactor needs product behavior changes to make sense.
- The diff is mostly mechanical churn that obscures the behavior boundary.
- No verification exists and the touched surface is risky enough to need one first.
- The cleanup changes a public contract, cache behavior, permission boundary, or
  persisted data shape without the matching compatibility and verification plan.
