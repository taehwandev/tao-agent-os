---
keyflow_id: sys_android_compose_performance
status: review
type: human-reviewed-needed
---

# Compose Performance And Stability

Read when a task reports or measures jank, excess recomposition, stability
problems, slow lazy-list scrolling, startup cost, or another Compose
performance regression. This file is the measure-first diagnosis procedure.

The authoring rules every composable follows by default (modifier order,
deferred reads, lazy `key`/`contentType`, `Modifier.Node`, animation API
choice, effect keys, `rememberUpdatedState`) are in
[Authoring Rules](current-guidance.md#authoring-rules), not here. When a
diagnosis finds one of them violated, fix it as that section describes.

## Compose Performance Gate

Use a measure-first loop for Compose performance work:

```text
Measure -> Diagnose -> Fix one cause -> Verify
```

Do not call a change a performance fix only because it adds packages,
annotations, `remember`, module splits, or a different architecture pattern.
Record the bottleneck category first: recomposition, stability, lazy layout,
main-thread work, startup, allocation, subcomposition, side effects, tracing,
or release configuration.

Performance claims should use release-like evidence whenever practical:

- Measure Compose runtime behavior in a release or benchmark variant with R8
  enabled and a physical device when the claim is about frame time, jank,
  startup, or scroll smoothness. Debug builds, emulators, and Layout Inspector
  counts are diagnostic only unless the report says so.
- Quote the variant, device, compilation mode, iteration count, and before/after
  numbers when reporting a measured improvement.
- Use compiler reports, Layout Inspector, recomposition tracing,
  Macrobenchmark, Baseline Profiles, Perfetto, or focused manual evidence
  according to the repo's tooling. Do not invent metrics.
- Keep each fix scoped to one diagnosed cause and remeasure before moving to the
  next optimization.
- Do not chase perfect skippability as a success metric. Skippability,
  recomposition counts, compiler stability reports, and Layout Inspector output
  are diagnostics; the task still needs a user-visible path, bottleneck
  category, and verification evidence that matches the claim.

## Recomposition Triage

When a screen still recomposes too broadly, inspect first instead of guessing:

- Check whether the same large `UiState` is passed into many sections.
- Check whether item models, keys, callbacks, or lists are recreated on every
  recomposition.
- Check whether a local state read was hoisted higher than necessary.
- Check whether the component API forces unstable product objects into a shared
  primitive.

Triage recomposition spikes on unchanged lazy items in this order:

1. Cross-phase back-writes: state written from a layout or draw result (a
   value captured via `onSizeChanged`, read in a sibling's composition)
   re-runs rows whose inputs never changed.
2. Cross-row measurement reads, before assuming parameter stability.
3. Per-frame growth during scroll or animation means a deferred-read
   violation: a high-frequency value read in composition instead of a
   layout/draw or provider lambda (see
   [Deferred State Reads](current-guidance.md#deferred-state-reads)).
4. Only when skipping genuinely fails, diagnose parameter stability with
   compiler reports, one transition at a time, remeasuring after each fix.

## Diagnosed Fixes

### State Reads And Flows

- Use `remember { derivedStateOf { ... } }` only when inputs change more often
  than the derived output or the calculation is meaningfully expensive. Include
  changing non-state captures in the `remember` key list.
- Prefer upstream `distinctUntilChanged`, `conflate`, or state mapping for
  chatty flows. Do not wrap `collectAsStateWithLifecycle()` output in
  `derivedStateOf` just to appear safe.

### Lazy Layouts And Subcomposition

- Hoist expensive item allocations, painters, shapes, formatters, and mappers
  out of lazy item lambdas when measurement shows churn. Do not blindly
  `remember` cheap modifier chains.
- Remove nested lazy layouts, `BoxWithConstraints`, nested `Scaffold`, and other
  subcomposition-heavy containers from repeated lazy items unless the behavior
  requires them and the cost is measured.
- Configure lazy prefetch only for a real scroll bottleneck and verify with a
  release-like scroll measurement.

### Focus

- Focusable controls should have explicit focus targets, stable ids in lazy
  lists, and tests for keyboard/D-pad/key input when focus behavior changes.

## Stability And Strong Skipping

Compose performance starts with stable inputs. Treat stability annotations as a
model contract, not an optimization trick.

- Check the Kotlin and Compose compiler versions before changing stability
  policy. Newer Kotlin/Compose toolchains enable strong skipping by default; do
  not add configuration without verifying the current behavior.
- Stability annotations are contracts. Use `@Immutable` or `@Stable` only for
  owned types whose public properties, equality behavior, and mutation rules are
  defensible.
- In Compose-aware UI modules, annotate screen `UiState`, UI display models,
  component-default holders, and design-system token holders with `@Immutable`
  when all public properties are immutable.
- Annotate sealed marker interfaces with `@Stable` only when all implementations
  are stable or immutable. Annotate leaf implementations with `@Immutable`.
- Do not add Compose annotations to pure domain, repository, or shared model
  modules just for the UI. Map them into annotated UI models at the feature or
  design-system boundary. Pure Kotlin modules that need markers use the
  official runtime annotation artifact or an approved repo-local marker.
- Use immutable collections for state that enters Compose. Prefer
  `ImmutableList` and persistent collection builders when the repo already uses
  `kotlinx.collections.immutable`.
- `Flow`, channels, repositories, platform objects, mutable collections and
  callbacks are not stable UI state. Collect, map, or wrap them before they
  enter `UiState` or composable parameters.
- If state can refresh while showing stale content, model that explicitly
  instead of layering `isLoading`, `error`, and nullable data in contradictory
  combinations.
- Use `@NonSkippableComposable`, `@DontMemoize`, or similar escape hatches only
  with a nearby reason and measured need.

## Advanced Stability Options

Use compiler and Gradle-level stability tools only after diagnosing a real
recomposition or performance issue:

- A Compose stability configuration file can mark external or standard-library
  types as stable, but it is a codebase-wide contract. Add entries only for
  types whose immutability and equality behavior the project can defend.
- Do not change compiler stability policy, add stability configuration, or move
  state across component boundaries without measurement or a concrete
  recomposition/jank reproduction.
- Do not use suspected performance as the reason to migrate a View screen to
  Compose, or a Compose screen back to View. Treat framework migration as a
  separate architecture task with its own evidence.
- Do not call feature-specific state, copy, routing, analytics, or permission
  policy a performance optimization by hiding it inside a shared component.

## Report

- Bottleneck category, user-visible path, and the measurement tool used.
- Variant, device, compilation mode, iterations, and before/after numbers, or
  an explicit note that the evidence is diagnostic only.
- The one cause fixed per iteration and the remeasurement after it.
