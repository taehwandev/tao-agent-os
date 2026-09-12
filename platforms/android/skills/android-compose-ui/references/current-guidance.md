---
keyflow_id: sys_android_compose_ui
status: review
type: human-reviewed-needed
---

# Android Compose UI

Use when creating, changing, moving, or reviewing Jetpack Compose screens,
state holders, design-system components, or feature UI components.

This card is the authoring contract: how a composable is layered, split, and
typed. Each other decision a Compose change can make has its own reference,
and is read only when the change makes that decision.

## Conditional References

- [`screen-structure.md`](screen-structure.md) when building a new screen,
  choosing an architecture track, or placing files and packages.
- [`compose-performance.md`](compose-performance.md) when the task names jank,
  recomposition, stability, lazy-list scrolling, or a measured regression.
- [`compose-previews.md`](compose-previews.md) when adding or changing previews.
- [`edge-to-edge-insets.md`](edge-to-edge-insets.md) when a screen draws behind
  system bars, handles keyboard overlap, or migrates legacy system-bar
  configuration.
- [`wear-compose.md`](wear-compose.md) for Wear OS Compose Material3 work.
- [`official-source-surfaces.md`](official-source-surfaces.md) for adaptive UI,
  XML-to-Compose migration, Compose Styles, CameraX, or XR/Glimmer.
- `common/skills/reusable-code-design/SKILL.md` and
  `common/skills/design-system/SKILL.md` when extracting reusable UI.
- `../../android-module-structure/references/module-boundaries.md` for feature
  module boundaries and `api`/implementation splits.

## Compose Layers

Use this shape unless the repo has a stricter local pattern:

```text
Screen/Holder Composable -> Content Composable -> Section Composable
-> Feature Component -> Design-System Primitive
```

- Screen/holder composable wires ViewModel, lifecycle collection, effects,
  navigation callbacks, permission launchers, and dependency entry points.
- Content composable is stateless. It receives immutable UI state plus explicit
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
whole UI tree in one `Screen`, `Content`, or file. A screen file may own the
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

- End with `Screen`, `Host`, or another repo-local holder suffix when possible.
  Do not use `Route` as the holder suffix: that name belongs to the navigation
  destination declared in the feature `api` module, and a repo that spends it on
  a composable has no name left for the destination. See
  `../../android-module-structure/references/module-boundaries.md`.
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

## Compose Code Writing Rules

Write Compose code so state ownership, recomposition boundaries, and preview
contracts are visible in the function signature:

- Prefer one public or internal `Screen` holder plus one public or internal
  stateless `Content`; keep helper sections and leaf components private until
  another caller proves a reusable contract.
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
- Key effects by the lifecycle owner or the specific input that should restart
  the effect. Avoid broad keys such as a whole `UiState` unless the whole state
  should restart the work.
- Do not write to Compose state from a composable body in response to the state
  value read earlier in that same composition. Put that transition in a callback,
  effect, state holder, or reducer so recomposition does not loop.

## Component API Rules

- `modifier: Modifier = Modifier` belongs near the top of public composable
  parameters and should be applied to the root layout exactly once. Caller
  placement such as outer padding, width fill, or alignment belongs to the
  caller.
- Prefer plain values, immutable UI models, callbacks, and slots.
- Use slots for caller-owned icons, actions, media, supporting content, and
  trailing content when visual structure is reusable but content varies.
  Optional slots should be nullable when absence should not reserve space.
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
