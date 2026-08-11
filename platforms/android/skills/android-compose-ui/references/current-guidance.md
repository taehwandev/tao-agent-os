---
keyflow_id: sys_android_compose_ui
status: review
type: human-reviewed-needed
---

# Android Compose UI

Use when creating, changing, moving, or reviewing Jetpack Compose screens,
state holders, design-system components, feature UI components, previews, or UI
tests.

For reusable UI extraction, also read `common/skills/reusable-code-design/SKILL.md` and
`common/skills/design-system/SKILL.md`.

For feature module boundaries, `api`/implementation splits, package ownership,
and shared holder/design-system promotion, also read
`android-module-structure.md`.

For Compose performance, stability, modifier, effect, slot, focus, animation,
and testing work that cites external skill repositories, also read
`android-external-skill-source-coverage.md` before editing or reviewing.

## Android Skill Source Check

When the task names or implies Jetpack Compose performance, recomposition,
stability, lazy layouts, modifier APIs, side effects, Flow collection, focus,
animation, previews, UI testing, or Android platform UI behavior, apply the
external source manifest before implementation. Use it as a no-omission check,
not as a replacement for this card's local architecture.

- Use Compose performance sources when the claim involves jank, skippability,
  compiler reports, `LazyColumn`/`LazyRow`, `Modifier.Node`, R8/release-mode
  measurement, Baseline Profiles, or Macrobenchmark evidence.
- Use Compose state/effect sources when the risk is broad recomposition from
  whole-screen state, frame-rate reads in composition, effect restart keys,
  state-holder split, or `Flow` parameters crossing into leaf composables.
- Use official Android skills when the surface is edge-to-edge, IME insets,
  testing setup, Navigation 3 scenes, Wear Compose Material3, R8, Android
  CLI/device inspection, or another platform SDK feature.
- Use the Android source-coverage skill bundle when the surface is adaptive UI,
  XML-to-Compose migration, Compose Styles, CameraX preview in Compose,
  XR/Glimmer, or another official Android skill surface not summarized directly
  in this card.

If a route for Android Compose or performance work does not load
`android-external-skill-source-coverage.md`, fix the route or load the manifest
manually before editing.

## Compose Layers

Use this shape unless the repo has a stricter local pattern:

```text
Route/Holder Composable -> Screen Composable -> Section Composable
-> Feature Component -> Design-System Primitive
```

- Route/holder composable wires ViewModel, lifecycle collection, effects,
  navigation callbacks, permission launchers, and dependency entry points.
- Screen composable is stateless. It receives immutable UI state plus explicit
  callbacks and renders the whole screen.
- Section composables group screen areas and accept only the state they need.
- Feature components may know product display models but not repositories,
  ViewModels, activities, or routers.
- Design-system primitives know visual and interaction contracts, not product
  routes, analytics labels, or fake data.
- Each layer should pass the smallest stable model or value set needed by the
  next layer. Avoid sending a whole screen `UiState` into sections and leaf
  components when a narrower value keeps recomposition and ownership clearer.

## Mandatory Component Split

Compose screens must be split into named composables instead of placing the
whole UI tree in one `Route`, `Screen`, or file. A screen file may own the
top-level state switch, but headers, filters, summary strips, forms, list
regions, rows, cards, dialogs, empty states, error states, and bottom actions
must become section or component composables as soon as they have a distinct
visual or interaction responsibility.

Use a feature-local `components/` package for reusable pieces inside a feature,
and split it by role from the start with packages such as `inputs`, `feedback`,
`cards`, `lists`, `dialogs`, `navigation`, or `data`. Promote only stable,
domain-free controls into the design-system module.

Do not:

- Do not approve Compose UI that keeps distinct sections, rows, cards, dialogs,
  feedback states, and actions in one screen function or one file.
- Do not put every composable for a screen into one file because Compose makes
  nesting easy.
- Do not leave header, body, list item, empty/error/loading state, dialog, and
  bottom bar composables inside one large `Screen` function.
- Do not keep many named composables in one `Components.kt` file once they can
  be previewed, tested, imported, or reviewed independently.
- Do not pass a full screen `UiState` into every section or leaf to avoid
  creating smaller models.
- Do not create a flat `components` package that mixes inputs, cards, dialogs,
  table/list rows, feedback states, and feature-only product sections.
- Do not import raw Material components throughout feature screens when the app
  has or needs product-prefixed design-system wrappers.
- Do not expose a Material wrapper unchanged as the product component. A design
  system wrapper must define semantic variants, slots, accessibility,
  loading/disabled/error behavior, and token ownership.

## Stateful And Stateless

Stateful composables:

- End with `Route`, `Host`, or another repo-local holder suffix when possible.
- Collect `StateFlow` with lifecycle-aware APIs.
- Own lifecycle-aware effects for one-off commands such as navigation,
  snackbar, focus, permission launch, or external activity launch.
- Prefer `LifecycleEventEffect` for a single lifecycle callback,
  `LifecycleStartEffect` for `ON_START`/`ON_STOP` work with cleanup, and
  `LifecycleResumeEffect` for `ON_RESUME`/`ON_PAUSE` work with cleanup. Use
  `LaunchedEffect` when the coroutine is tied only to composition lifetime and
  does not need a lifecycle start/stop boundary.
- Translate platform results into ViewModel actions or route events.
- Delegate rendering to a stateless screen/content composable.

Stateless composables:

- Take `state: FooUiState`, explicit callbacks, slots, and `modifier`.
- Do not obtain ViewModels, repositories, activities, nav controllers, or
  service locators.
- Do not launch coroutines for business work.
- Keep UI-local state only when it affects rendering or interaction locally,
  such as scroll, focus, gesture, animation, expanded, selected tab, or text
  field draft state.
- Expose user intent as callbacks such as `onBackClick`, `onRetryClick`,
  `onQueryChange`, or `onAction` when the action set is already typed.
- Keep state reads as close as practical to the composable that needs them. A
  screen can branch on high-level status, but repeated rows and leaf components
  should receive row models or plain values.

## Route And Screen Template

For a ViewModel-backed Compose screen, generate or review both the holder and the
stateless screen. Replace `hiltViewModel()` with the repo's DI pattern.

```kotlin
@Composable
fun ProfileRoute(
    onBack: () -> Unit,
    onOpenEditor: (ProfileId) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ProfileViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LifecycleStartEffect(viewModel) {
        val collectJob = this.lifecycleScope.launch {
            viewModel.effects.collect { effect ->
                when (effect) {
                    ProfileEffect.NavigateBack -> onBack()
                    is ProfileEffect.OpenEditor -> onOpenEditor(effect.id)
                    is ProfileEffect.ShowSnackbar -> {
                        snackbarHostState.showSnackbar(effect.message.text)
                    }
                }
            }
        }

        onStopOrDispose {
            collectJob.cancel()
        }
    }

    ProfileScreen(
        state = state,
        onAction = viewModel::onAction,
        snackbarHostState = snackbarHostState,
        modifier = modifier,
    )
}
```

```kotlin
@Composable
fun ProfileScreen(
    state: ProfileUiState,
    onAction: (ProfileAction) -> Unit,
    modifier: Modifier = Modifier,
    snackbarHostState: SnackbarHostState = remember { SnackbarHostState() },
) {
    Scaffold(
        modifier = modifier,
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { contentPadding ->
        when (val status = state.status) {
            ProfileStatus.Loading -> ProfileLoading(
                modifier = Modifier.padding(contentPadding),
            )
            ProfileStatus.Empty -> EmptyState(
                onRetryClick = { onAction(ProfileAction.RetryClick) },
                modifier = Modifier.padding(contentPadding),
            )
            is ProfileStatus.Error -> ErrorState(
                message = status.message,
                onRetryClick = { onAction(ProfileAction.RetryClick) },
                modifier = Modifier.padding(contentPadding),
            )
            ProfileStatus.PermissionDenied -> PermissionDeniedState(
                modifier = Modifier.padding(contentPadding),
            )
            is ProfileStatus.Content -> ProfileContent(
                profile = status.profile,
                canEdit = state.canEdit,
                onBackClick = { onAction(ProfileAction.BackClick) },
                onEditClick = { onAction(ProfileAction.EditClick) },
                modifier = Modifier.padding(contentPadding),
            )
        }
    }
}
```

Rules for applying this template:

- `Route` may know ViewModel, lifecycle collection, navigation outputs,
  permission launchers, activity results, and snackbar/focus effects.
- `Screen` must be previewable without DI, ViewModel, navigation, database,
  network, or platform services.
- Leaf components should receive the smallest model or values they need, not the
  whole screen `UiState`.
- If a callback count becomes noisy, introduce a typed `UiAction`; do not pass a
  ViewModel into the screen to reduce parameters.
- Keep `modifier` on the public composable and apply it to the root layout once.

## Compose Code Writing Rules

Write Compose code so state ownership, recomposition boundaries, and preview
contracts are visible in the function signature:

- Prefer one public or internal `Route` plus one public or internal stateless
  `Screen`; keep helper sections and leaf components private until another
  caller proves a reusable contract.
- Keep public composable parameters ordered as stable inputs, callbacks or
  slots, `modifier`, then optional visual defaults. Follow the repo's local
  ordering when it is stricter.
- Avoid reading `ViewModel`, DI, `LocalContext`, `LocalActivity`, `NavController`,
  or service locators below the route/holder boundary. If a platform value is
  required by a leaf, pass a plain value or callback instead.
- Stay on the current technical surface. Inside Compose code, use Compose
  idioms for strings, dimensions, state, and effects (`stringResource`,
  `remember`, `LaunchedEffect`). Do not pull View-era helpers like
  `Context.getString()` into Compose code as a bypass; they belong only to
  screens the legacy surface still owns. Growing legacy bypasses in
  new-surface work is a review stop signal.
- Use `remember` for UI-local objects, expensive calculations, gesture or
  animation state, and stable wrappers. Do not wrap every expression in
  `remember`; cheap derived values can be recomputed.
- Use `derivedStateOf` only when a derived value is expensive or changes less
  often than its inputs and can reduce real recomposition work.
- Use `rememberUpdatedState` for callbacks or values captured by long-lived
  `LaunchedEffect`, `LifecycleEventEffect`, `LifecycleStartEffect`,
  `LifecycleResumeEffect`, `DisposableEffect`, or animation callbacks.
- Use `DisposableEffect` for external listeners, receivers, observers, or
  platform callbacks that need explicit registration and cleanup. Prefer
  lifecycle-compose effects when the cleanup is tied to `ON_STOP` or
  `ON_PAUSE`.
- Register listeners, receivers, observers, and platform callbacks from an
  effect with a matching dispose path. Do not create heavy platform resources
  from a composable body without a clear owner and release point.
- Defer high-frequency state reads as far down the tree as practical. Prefer a
  lambda or lambda-based modifier when a parent only needs to pass a changing
  value to a child and should not recompose for every frame.
- Key effects by the lifecycle owner or the specific input that should restart
  the effect. Avoid broad keys such as a whole `UiState` unless the whole state
  should restart the work.
- Do not write to Compose state from a composable body in response to the state
  value read earlier in that same composition. Put that transition in a callback,
  effect, state holder, or reducer so recomposition does not loop.
- For `LazyColumn`, `LazyRow`, pager, and grid content, provide stable `key` and
  `contentType` when items can reorder, update independently, animate, or hold
  local state.
- Keep row item models stable and immutable. Avoid constructing a new mutable
  list, random id, formatter, painter, or callback wrapper for every item during
  every recomposition.
- Keep layout dimensions stable for repeated cells, navigation items, controls,
  and animated surfaces. Dynamic content should not resize the whole control
  unless the product intentionally owns that layout shift.

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

- Public composables that emit layout must expose `modifier: Modifier =
  Modifier` and apply it to the root once. Caller placement such as outer
  padding, width fill, or alignment usually belongs to the caller.
- Build modifier chains as one fluent value. Avoid mutable modifier variables
  and avoid hiding parent layout decisions inside leaf components.
- New custom modifiers should prefer `Modifier.Node` over legacy
  `Modifier.composed` unless the repo's Compose version or API surface prevents
  it.
- Use slot APIs for caller-owned icons, actions, media, supporting content, and
  trailing content. Optional slots should be nullable when absence should not
  reserve space.
- Pick the smallest animation API: `animate*AsState` for one value,
  `updateTransition`/`rememberTransition` for synchronized values,
  `AnimatedVisibility` when the subtree should mount/unmount, and alpha or draw
  changes when the subtree should remain mounted. Use `contentKey` for
  `AnimatedContent` by visual shape.
- Focusable controls should have explicit focus targets, stable ids in lazy
  lists, and tests for keyboard/D-pad/key input when focus behavior changes.

## UI State

Model screen states explicitly:

```text
loading -> content -> empty -> error -> permission denied -> offline
```

- Prefer immutable `UiState` data classes or sealed interfaces over scattered
  nullable values and boolean flags.
- Keep one-off effects separate from persistent state.
- Keep domain models free of Compose types such as `Color`, `Dp`, `TextStyle`,
  painter, icon lambdas, or resource ids.
- Map domain models to UI models in the feature UI/state boundary.
- User-facing strings should follow repo-local localization rules.

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

- Check Compose compiler reports, Layout Inspector, benchmark traces, or another
  repo-local measurement before changing stability policy.
- Strong skipping is a compiler behavior, not a replacement for good state
  modeling. Check the repo's Kotlin/Compose compiler version before adding any
  explicit strong-skipping configuration, because newer toolchains may enable it
  by default.
- A Compose stability configuration file can mark external or standard-library
  types as stable, but it is a codebase-wide contract. Add entries only for
  types whose immutability and equality behavior the project can defend.
- If normal `List`, `Set`, or `Map` parameters keep a composable unstable, first
  prefer immutable collections or a small annotated wrapper in the UI boundary.
  Do not annotate a mutable collection holder only to silence compiler output.
- Use `@NonSkippableComposable` or equivalent opt-outs only when a composable has
  a deliberate side-effect or measurement contract that must run even with
  unchanged inputs, and document the reason near the call or component.
- Do not change compiler stability policy, add stability configuration, or move
  state across component boundaries without measurement or a concrete
  recomposition/jank reproduction.
- Do not use suspected performance as the reason to migrate a View screen to
  Compose, or a Compose screen back to View. Treat framework migration as a
  separate architecture task with its own evidence.
- Do not call feature-specific state, copy, routing, analytics, or permission
  policy a performance optimization by hiding it inside a shared component.

## Architecture Tracks

Choose the smallest track that makes ownership clear:

| Track | Use When | Shape |
| --- | --- | --- |
| Simple Compose | Local interaction only, no async data or product workflow. | `Composable -> local remember state` |
| MVVM | Loading, forms, async fetch, permission state, navigation output, or reusable screen logic. | `Route -> ViewModel -> Screen` |
| Clean Architecture | Domain policy, offline/sync, auth/tenant/billing, multiple clients, or complex test boundary. | `Route -> ViewModel -> UseCase -> Repository -> DataSource` |
| Reducer/MVI | Many events, replayable transitions, optimistic updates, or concurrency races. | `Route -> ViewModel/Store -> Reducer -> Effects/UseCases` |

Do not add use cases, repositories, reducers, or modules only for ceremony. Add
them when they isolate a real product rule, side effect, or test boundary.

## Edge-To-Edge And IME Insets

Edge-to-edge ownership, legacy window-API deletion, IME insets, and gesture
areas are owned by [`edge-to-edge-insets.md`](edge-to-edge-insets.md). Read it
when a screen draws behind system bars, handles keyboard overlap, or migrates
legacy system-bar configuration.

## Wear Compose Material 3

For Wear OS Compose Material3 creation, updates, or migration, use the external
source manifest and start with `android/skills`
`wear/wear-compose-m3/SKILL.md` plus its migration reference before changing
code or dependencies.

- Confirm the Wear Compose Material3, Foundation, and Navigation versions from
  the repo dependency catalog or official Maven metadata before editing. Do not
  downgrade only because an editor initially reports unresolved references after
  a version change.
- Wear Compose Material3 work needs Kotlin 2.0 or newer and the Compose compiler
  Gradle plugin when the repo uses Kotlin 2.x. Keep `minSdk` at least 25 for
  Wear OS 2.0 unless repo-local policy is stricter.
- Before adding or migrating a Wear Material3 component, read the version-matched
  official component samples from the local Gradle cache or downloaded
  `-samples-sources.jar`. Library source alone is not enough for component slot,
  default, padding, and interaction decisions.
- Use one outer `AppScaffold` with `ScreenScaffold` children. Pass
  `ScreenScaffold` content padding into scrollable content instead of recreating
  padding locally.
- Prefer `TransformingLazyColumn` over `ScalingLazyColumn` for Material3 Wear
  lists. Use stable list state, transformation specs, component default padding,
  `transformedHeight`, and matching rotary/fling behavior when snapping is
  configured.
- Do not use Horologist Compose UI or Wear Material 2.5 components as the
  long-term target during a Material3 migration. Expect screenshot baselines to
  change because Material3 defaults are the source of truth.
- Use Wear-specific previews such as device and font-scale previews when the
  repo supports them, and avoid hard-coded colors, text sizes, and component
  spacing where `MaterialTheme` or component defaults own the contract.
- For Wear Navigation3, use the Wear navigation scene strategy required by the
  current Wear Compose Navigation library instead of assuming phone/tablet
  navigation defaults.

## Source-Specific Compose Surfaces

For Android Compose surfaces that are driven by official Android skills, keep
this card as the architecture baseline and load the matching source bundle
before implementation:

- Adaptive UI: verify screenshot coverage across form factors before changing
  navigation areas, multi-pane scenes, or grid/list adaptations. Use Navigation
  3 scene strategies when the source skill requires them.
- XML-to-Compose migration: migrate one XML candidate at a time, capture the old
  UI, keep XML theming for interoperability, add a Compose preview, compare
  visual parity, and remove XML only after usages are replaced.
- Compose Styles API: treat it as experimental and version-gated. Use it for
  custom design-system components only after compile SDK, Compose foundation or
  BOM, and opt-in requirements are confirmed.
- CameraX in Compose: keep camera provider/use-case binding lifecycle-aware,
  model `SurfaceRequest` state explicitly, update target rotation, and handle
  tap-to-focus through the correct coordinate transform.
- XR/Glimmer: treat display glasses as a separate form factor. Use Glimmer
  components and theme, pure black root background, projected Activity hardware
  checks, one-dimensional focus, and readable text sizing; do not substitute
  standard Material components.

## Preview Rule

Every named stateless composable that renders UI needs a colocated Compose
preview, with no omissions. This includes `Screen`, section, state surface, row,
card, dialog, empty/error/loading, and reusable component composables. Screenshot
tests, Compose UI tests, and manual smoke paths are additional verification, not
replacements for this preview requirement.

Previews should:

- Target stateless composables, not ViewModel-backed holders.
- Cover every named stateless UI composable directly. Do not count a parent
  preview as coverage for a separately named stateless child unless the child is
  inlined and no longer exists as its own visual owner.
- Keep one-off preview functions and preview-only sample state in the same
  Kotlin file as the stateless `Screen`, section, or leaf component they render.
  Reviewers should be able to open the component file and inspect the visual
  contract without jumping to a separate preview package.
- Use deterministic sample state from a same-file private preview owner by
  default. Use a separate `preview`, `sample`, or `fixture` owner only when the
  same states are reused by several composable files, a design-system module
  owns shared examples, or the sample setup would otherwise hide the component
  contract.
- Prefer `@PreviewParameter` with a private same-file
  `PreviewParameterProvider<T>` when one composable needs several deterministic
  states.
- Cover the changed states: at least content plus loading, empty, error,
  permission denied, offline, long text, or disabled when affected.
- Wrap content in the app theme or design-system theme.
- Avoid network, database, DI containers, real credentials, random data, current
  time, or device-only services.
- Stay small enough that agents and reviewers can quickly understand the visual
  contract.

If a named stateless UI composable cannot be previewed, refactor its parameters
until it is previewable or inline it into the nearest previewed parent instead
of keeping it as an unpreviewed function. Replacement verification is allowed
only for route holders, platform-service wrappers, or stateful integration
surfaces that are intentionally not stateless UI composables.

## Preview Implementation

Previews should be built from each stateless `Screen`, section, state surface,
or leaf component, with sample state owned by private preview-only values in the
same file. Keep sample data deterministic and domain-safe.

Use the official Compose preview parameter APIs for multi-state previews:
`@PreviewParameter` can annotate a parameter of an `@Preview`, and the provider
class supplies a `Sequence<T>` of values. Use the annotation's `limit` argument
when a provider exposes more values than the current preview needs. Override
`PreviewParameterProvider.getDisplayName(index)` only after confirming the
repo's `androidx.compose.ui:ui-tooling-preview` version supports it; otherwise
use explicit `@Preview(name = ...)` functions for named states.

```kotlin
private object ProfilePreviewData {
    val content = ProfileUiState(
        status = ProfileStatus.Content(
            ProfileViewData(
                id = ProfileId("preview"),
                name = "Ada Lovelace",
                subtitle = "Long subtitle that verifies wrapping and spacing",
                avatarUrl = null,
            ),
        ),
        canEdit = true,
    )

    val loading = ProfileUiState(status = ProfileStatus.Loading)
    val empty = ProfileUiState(status = ProfileStatus.Empty)
    val error = ProfileUiState(
        status = ProfileStatus.Error(UiMessage("Unable to load profile")),
    )
}

private class ProfileScreenPreviewProvider : PreviewParameterProvider<ProfileUiState> {
    override val values = sequenceOf(
        ProfilePreviewData.content,
        ProfilePreviewData.loading,
        ProfilePreviewData.empty,
        ProfilePreviewData.error,
    )
}

@Preview(name = "Profile states")
@Composable
private fun ProfileScreenPreview(
    @PreviewParameter(ProfileScreenPreviewProvider::class)
    state: ProfileUiState,
) {
    AppTheme {
        ProfileScreen(
            state = state,
            onAction = {},
        )
    }
}
```

Preview requirements:

- Add at least one direct content preview for every named stateless UI
  composable, plus affected edge-state previews when the change touches loading,
  empty, error, permission, offline, disabled, or long text behavior.
- Add dark mode, font scale, small-width, or locale previews when the change is
  likely to break them and the repo already supports preview parameters or
  screenshot coverage.
- Keep preview functions, private preview data, and one-off
  `PreviewParameterProvider` classes beside the composable by default. Move them
  to `preview/` or `sample/` only with a reuse reason named in the change.
- Do not create a fake ViewModel only to make a preview work. Preview the
  stateless composable instead.
- Do not move one-off previews to a distant package just to keep the component
  file short. Split the production component first; keep the preview next to the
  composable it validates.
- Do not hide missing stateless UI previews behind "not runnable locally",
  screenshot tests, Compose UI tests, or manual smoke paths.

## Package Structure

Use package names that reveal ownership and dependency direction. A typical
feature implementation can use:

```text
feature/<name>/impl/src/main/.../<name>/
  <Name>Route.kt        stateful holder and lifecycle wiring
  <Name>Screen.kt       stateless screen content
  <Name>ViewModel.kt    UI state owner
  <Name>UiState.kt      state, actions, effects, UI models
  components/           feature-local reusable pieces
  preview/              shared preview providers only when reused across files
```

This `impl` layout is the default even when it contains `compose/` or `ui/`
packages. A separate `feature/<name>/ui` Gradle module is optional: create it
only when a named consumer outside the implementation must reuse the concrete
Compose surface. Move the stateless composables, their smallest visual models
and callbacks or slots, previews, and UI tests; keep `Route`, `ViewModel`,
loading/orchestration state, mapping, DI, navigation execution, Activity, and
Intent/result handling in `impl`. The canonical module contract lives in
`../../android-module-structure/references/module-boundaries.md`.

Use `components/` for feature-local pieces and promote only stable visual
contracts to a shared design-system module. Shared design-system modules can use:

```text
core/designsystem/.../theme/
core/designsystem/.../tokens/
core/designsystem/.../components/
core/designsystem/.../components/<domain-free-group>/
core/designsystem/.../preview/
```

Keep generated resources, route contracts, domain models, repositories, and fake
services outside shared UI component packages unless the repo documents a more
specific boundary.

Design-system modules should own theme, semantic tokens, typography, shapes,
component defaults, accessibility semantics, and domain-free primitives. Feature
modules should own product copy, route events, analytics labels, permission
policy, domain-to-UI mapping, and feature-only cards or sections.

When a repo has design-system wrappers, feature modules should prefer those
wrappers over direct Material, platform, or third-party UI primitives. Direct
imports of raw UI primitives belong primarily inside the design system, or in a
feature-local one-off with a clear reason to avoid promotion.

## Component API Rules

- `modifier: Modifier = Modifier` belongs near the top of public composable
  parameters and should be applied to the root layout exactly once.
- Prefer plain values, immutable UI models, callbacks, and slots.
- Use slots for caller-owned icons, actions, media, and trailing content when
  visual structure is reusable but content varies.
- Keep default parameters simple and side-effect free.
- Do not pass full `UiState` into leaf components when a smaller model or value
  set is enough.
- Do not make leaf components depend on ViewModel, repository, router, Activity,
  Context side effects, or DI.
- Accessibility labels, roles, selected states, enabled states, and content
  descriptions are part of the component contract.
- Defaults objects such as `FooButtonDefaults`, `FooCardDefaults`, and token
  holders should be stable or immutable and should read theme values through
  composable getters only when the value is theme-dependent.

## Reuse Decision

Before moving Compose UI into a shared package, ask:

- Is there a named module outside the feature implementation that must import
  this concrete Compose surface?
- Is this a design-system primitive, a feature product component, or just a local
  screen section?
- Can the component be named without the original screen or feature name?
- Are product copy, route events, analytics, permissions, and business rules
  still owned by the caller?
- Can previews demonstrate the reusable states without feature setup?
- Will extraction reduce duplicated fixes without creating a flag-heavy API?
- Does the shared API use semantic tokens and slots instead of leaking one
  feature's exact colors, padding, copy, or route policy?

If the answer is no, keep it local or in feature common rather than promoting it
to the design system.

When the surface remains feature-specific but has that outside consumer, put it
in the feature `ui` module. When it is domain-free and broadly reusable, put it
in the design system. When neither condition is true, keep it inside `impl`.

## Verification

Choose the closest checks configured in the repo:

- compile check for changed modules
- ViewModel/state unit test for state transitions
- Compose UI test for interaction, semantics, and navigation events
- screenshot or preview validation for visual component changes
- accessibility check for labels, roles, focus order, touch targets, and text
  scaling when affected

Review the final diff for direct repository calls from UI, missing previews,
stateful logic inside leaf components, and shared components that absorbed
product-specific behavior.
