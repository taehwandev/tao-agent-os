---
keyflow_id: sys_android_compose_performance
status: review
type: human-reviewed-needed
---

# Compose Performance And Stability

Use when the task names jank, recomposition, stability, lazy-list scrolling, startup, or a measured regression. Not needed to author or move a composable.

Split out of `current-guidance.md`, which keeps the Compose
authoring contract every UI change applies.

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

### Stability And Strong Skipping

- Check the Kotlin and Compose compiler versions before changing stability
  policy. Newer Kotlin/Compose toolchains may enable strong skipping by
  default; do not add configuration without verifying the current behavior.
- Stability annotations are contracts. Use `@Immutable` or `@Stable` only for
  owned types whose public properties, equality behavior, and mutation rules are
  defensible.
- Prefer immutable collections or stable UI wrappers before adding a stability
  configuration entry. Stability config is a codebase-wide promise, not a local
  patch.
- Pure Kotlin/data modules that need Compose stability markers should use the
  official runtime annotation artifact or an approved repo-local marker pattern
  without depending on the full Compose runtime.
- `Flow`, channels, repositories, platform objects, and mutable collections are
  not stable UI state. Collect, map, or wrap them before they enter composable
  parameters.
- Use `@NonSkippableComposable`, `@DontMemoize`, or similar escape hatches only
  with a nearby reason and measured need.

### State Reads And Effects

- Use `remember { derivedStateOf { ... } }` only when inputs change more often
  than the derived output or the calculation is meaningfully expensive. Include
  changing non-state captures in the `remember` key list.
- Prefer upstream `distinctUntilChanged`, `conflate`, or state mapping for
  chatty flows. Do not wrap `collectAsStateWithLifecycle()` output in
  `derivedStateOf` just to appear safe.
- Do not pass `Flow<T>` as a composable parameter. Collect lifecycle-aware at
  the route/holder boundary and pass values, state holders, or callbacks down.
- Choose the smallest side-effect API: `SideEffect` to publish after successful
  recomposition, `DisposableEffect` for register/unregister work,
  `LaunchedEffect` for keyed suspending work, `rememberCoroutineScope` for
  user-event launched work, and `snapshotFlow` for Compose state reads that
  drive Flow-based side effects.
- Key long-lived effects by the semantic lifecycle that should restart the
  work. Avoid `Unit` or a whole `UiState` key when individual inputs determine
  the lifecycle.
- Use `rememberUpdatedState` only to provide the latest callback or value to a
  long-lived effect without restarting it. Do not read it eagerly inside
  `remember { ... }`.
- A long-lived effect is not the trigger by itself; a callback that can change
  while it runs is. Show what changes before wrapping. A bound method reference
  such as `viewModel::onEvent` is equal across recompositions when its receiver
  is, and strong skipping memoizes lambdas passed to composables, so neither
  has anything to update. Wrapping anyway is noise the next reader must
  disprove, and in a sample it teaches the habit.
- Never use a remembered boolean event flag as a one-off effect queue. Emit a
  callback, command, event flow, or route effect from the state holder.

### Lazy Layouts And Subcomposition

- Every domain-backed lazy item should have a stable key from server/domain data
  rather than an index, random value, or mutable `hashCode`.
- Use `contentType` for heterogeneous lazy lists so item composition can be
  reused by shape.
- `Modifier.animateItem()` requires stable keys and stable item identity.
- Hoist expensive item allocations, painters, shapes, formatters, and mappers
  out of lazy item lambdas when measurement shows churn. Do not blindly
  `remember` cheap modifier chains.
- Avoid nested lazy layouts, `BoxWithConstraints`, nested `Scaffold`, and other
  subcomposition-heavy containers inside repeated lazy items unless the
  behavior requires them and the cost is measured.
- Configure lazy prefetch only for a real scroll bottleneck and verify with a
  release-like scroll measurement.

### Modifiers, Slots, Focus, And Animation

- Build modifier chains as one fluent value. Avoid mutable modifier variables
  and avoid hiding parent layout decisions inside leaf components.
- New custom modifiers should prefer `Modifier.Node` over legacy
  `Modifier.composed` unless the repo's Compose version or API surface prevents
  it.
- Pick the smallest animation API: `animate*AsState` for one value,
  `updateTransition`/`rememberTransition` for synchronized values,
  `AnimatedVisibility` when the subtree should mount/unmount, and alpha or draw
  changes when the subtree should remain mounted. Use `contentKey` for
  `AnimatedContent` by visual shape.
- Focusable controls should have explicit focus targets, stable ids in lazy
  lists, and tests for keyboard/D-pad/key input when focus behavior changes.

## Stability And Recomposition

Compose performance starts with stable inputs. Treat stability annotations as a
model contract, not an optimization trick:

- In Compose-aware UI modules, annotate screen `UiState`, UI display models,
  component-default holders, and design-system token holders with `@Immutable`
  when all public properties are immutable.
- Annotate sealed marker interfaces with `@Stable` only when all implementations
  are stable or immutable. Annotate leaf implementations with `@Immutable`.
- Do not add Compose annotations to pure domain, repository, or shared model
  modules just for the UI. Keep those types free of Compose runtime and map them
  into annotated UI models at the feature or design-system boundary.
- Use immutable collections for state that enters Compose. Prefer
  `ImmutableList` and persistent collection builders when the repo already uses
  `kotlinx.collections.immutable`.
- Avoid mutable properties, mutable collections, raw platform objects,
  repositories, flows, channels, and callbacks inside `UiState`.
- Keep painter, icon, resource, `Color`, `Dp`, and typography decisions in UI
  display models or design-system tokens, not domain models.
- If state can refresh while showing stale content, model that explicitly
  instead of layering `isLoading`, `error`, and nullable data in contradictory
  combinations.

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
   layout/draw or provider lambda.
4. Only when skipping genuinely fails, diagnose parameter stability with
   compiler reports, one transition at a time, remeasuring after each fix.

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
