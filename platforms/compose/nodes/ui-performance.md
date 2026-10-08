---
keyflow_id: sys_compose_node_ui_performance
status: review
type: ai-generated
use_when: Diagnosing or fixing excess recomposition, skipping failures, slow lazy lists or another Compose performance problem.
skip_when: Ordinary screen authoring with no reported or measured performance problem.
requires:
  - platforms/compose/nodes/ui-authoring-rules.md
  - platforms/compose/nodes/state-model-stability.md
---

# Compose Recomposition Performance

The measurement-independent rules for Compose performance in Jetpack Compose
and Compose Multiplatform. How to measure, and which tools and build variants
count as evidence, stays in the platform reference. The state stability
contract (`@Immutable`, `@Stable`, immutable collections) is in
`platforms/compose/nodes/state-model-stability.md`.

## Rules

### Fix One Diagnosed Cause

- Record the bottleneck category first: recomposition, stability, lazy
  layout, main-thread work, startup, allocation, subcomposition, side effects.
- Fix one diagnosed cause per iteration and remeasure before the next.
- Skippability, recomposition counts and compiler stability reports are
  diagnostics, not success metrics.

### Recomposition Triage

When a screen recomposes too broadly, inspect before guessing: the same large
state passed into many sections; item models, keys, callbacks or lists
recreated every recomposition; a local state read hoisted higher than needed;
a component API forcing unstable product objects into a shared primitive.

For recomposition spikes on unchanged lazy items, check in this order:

1. Cross-phase back-writes: state written from a layout or draw result (a size
   captured in `onSizeChanged`, read in a sibling's composition).
2. Cross-row measurement reads.
3. Per-frame growth during scroll or animation: a deferred-read violation
   (`platforms/compose/nodes/ui-authoring-rules.md`).
4. Only when skipping genuinely fails, parameter stability, one transition at
   a time.

### Diagnosed Fixes

- Use `remember { derivedStateOf { ... } }` only when inputs change more often
  than the output or the calculation is meaningfully expensive; include
  changing non-state captures in the `remember` keys.
- For chatty flows, prefer upstream `distinctUntilChanged`, `conflate` or
  state mapping. Do not wrap already-collected state in `derivedStateOf`.
- Hoist expensive item allocations, painters, shapes, formatters and mappers
  out of lazy item lambdas when measurement shows churn; do not blindly
  `remember` cheap modifier chains.
- Remove nested lazy layouts, `BoxWithConstraints`, nested scaffolds and other
  subcomposition-heavy containers from repeated lazy items unless behavior
  requires them and the cost is measured.
- Configure lazy prefetch only for a measured scroll bottleneck.
- Focusable controls have explicit focus targets, stable ids in lazy lists,
  and tests for keyboard or directional input when focus behavior changes.

### Strong Skipping

- Check the Kotlin and Compose compiler versions before changing stability
  policy; current toolchains enable strong skipping by default, so do not add
  configuration without verifying the current behavior.
- Use `@NonSkippableComposable`, `@DontMemoize` or similar escape hatches only
  with a nearby reason and measured need.

## Do Not

- Call a change a performance fix only because it adds `remember`,
  annotations, packages, module splits or a different architecture pattern.
- Change compiler stability policy or move state across component boundaries
  without measurement or a concrete recomposition reproduction.
- Hide feature state, copy, routing, analytics or permission policy inside a
  shared component and call it an optimization.

## Verification

- The report names the bottleneck category, the user-visible path, the one
  cause fixed and the remeasurement after it, or states that the evidence is
  diagnostic only.
- Diff review: each fix maps to one diagnosed cause, and no escape-hatch
  annotation lacks a reason.
