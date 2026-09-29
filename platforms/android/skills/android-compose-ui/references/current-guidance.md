---
keyflow_id: sys_android_compose_ui
status: review
type: human-reviewed-needed
---

# Android Compose UI

The Compose authoring contract: which design-system API a screen or component
consumes, how holder and stateless content are named and split, how the screen
skeleton owns bars, insets and the keyboard, which modifier, effect, lazy-list
and animation APIs it uses, and which previews it ships with.

## Steps

Follow these in order for every Compose change that adds, changes, moves or
reviews a composable. Read the section each step names at that step, even when
the request does not mention its topic.

1. Classify each composable (holder, content, section, feature component,
   design-system primitive): [Compose Layers](#compose-layers).
2. Pass the [Design-System Consumption Gate](#design-system-consumption-gate)
   before writing UI code.
3. Split holder and content with the repo's naming:
   [Stateful And Stateless](#stateful-and-stateless); for a new screen, the
   template, track and packages in [screen-structure.md](screen-structure.md).
4. Split by responsibility: [Component Split](#component-split) and
   [Composable Dependencies](#composable-dependencies).
5. Build the [Screen Skeleton](#screen-skeleton) with one IME owner; window,
   system-bar and `adjustResize` rules are in
   [edge-to-edge-insets.md](edge-to-edge-insets.md).
6. Write modifiers, state reads, lists, animation and effects:
   [Authoring Rules](#authoring-rules).
7. Add a preview for every new or meaningfully changed renderable stateless
   composable, with long-copy and large-fontScale variants for text
   containers: [compose-previews.md](compose-previews.md).
8. [Verification](#verification), then report.

Other references, read only for their own decision:
[compose-performance.md](compose-performance.md) (measure-first diagnosis of a
reported or measured regression; authoring defaults stay here),
[wear-compose.md](wear-compose.md), and
[official-source-surfaces.md](official-source-surfaces.md) (adaptive UI,
XML-to-Compose, Compose Styles, CameraX, XR). State, actions and effects are
owned by [android-viewmodel-state](../../android-viewmodel-state/SKILL.md);
resource lifetimes by
[android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md).

Stop and decide explicitly when: the screen mixes Views and Compose and the
inset owner is unknown; the change would alter navigation, scroll, keyboard or
system-bar behavior the request did not ask for; no component fits and the
choice is a new shared component or a raw Material exception
([design-system](../../../../../common/skills/design-system/SKILL.md)).

Report the classification and naming convention found, the components and
`Defaults` reused (and any raw Material exception with its reason), the IME
owner per changed screen, previews added, and verification run or not run.

## Compose Layers

Use this shape unless the repo has a stricter local pattern:

```text
Screen/Holder Composable -> Content Composable -> Section Composable
-> Feature Component -> Design-System Primitive
```

- The holder wires the ViewModel, lifecycle collection, effects, navigation
  callbacks, permission launchers and dependency entry points.
- Content is stateless. It receives immutable UI state plus explicit callbacks
  and renders the whole screen.
- Sections group screen areas and accept only the state they need.
- Feature components may know product display models but not repositories,
  ViewModels, activities or routers.
- Design-system primitives know visual and interaction contracts, not product
  routes, analytics labels or fake data.
- Each layer passes the smallest stable model or value set the next layer
  needs, not the whole screen `UiState`.

When a screen mixes Views and Compose, decide first which side owns the window
insets and the keyboard, and keep the bridge at an existing repo boundary.

## Design-System Consumption Gate

Before writing screen, section or component code, search the repo in this
order and stop at the first level that expresses the design:

1. A finished design-system component (button, card, top bar, scaffold,
   dialog, list row, text field).
2. Design-system primitives and shared modifiers.
3. Theme tokens: color, typography, shape, spacing, elevation.
4. Foundation layout: `Row`, `Column`, `Box`, lazy layouts.
5. Raw Material or platform widgets, only with a reason written in the change.

- Do not reassemble the look of an existing component from shape, color and
  text style. If a variant or slot is missing, extend the existing API
  minimally, and say so in the report.
- When a component exposes public defaults (`FooButtonDefaults`,
  `FooCardDefaults`), take padding, icon size, colors and styles at the call
  site from them. Do not duplicate their numbers in the feature.
- Do not create a new product-prefixed wrapper for a single screen. A new
  shared component is a design-system decision
  ([design-system](../../../../../common/skills/design-system/SKILL.md)).
- A design-system wrapper is not a renamed Material widget: it defines semantic
  variants, slots, accessibility, loading/disabled/error behavior and token
  ownership.

## Stateful And Stateless

**Naming.** First read two or three neighbouring screens and follow the repo's
existing holder/stateless naming, whatever the suffixes are. Only in a repo
without a convention, use the default: `FooScreen` for the stateful holder and
`FooContent` for the stateless content. In that default, do not use `Route` as
the holder suffix: in Navigation Compose `Route` names the destination type,
declared in the feature `api` module (see
[module-boundaries.md](../../android-module-structure/references/module-boundaries.md)).

Stateful holders:

- Collect `StateFlow` with `collectAsStateWithLifecycle()`.
- Own lifecycle-aware effects for one-off commands such as navigation,
  snackbar, focus, permission launch or external activity launch.
- Prefer `LifecycleEventEffect` for a single lifecycle callback,
  `LifecycleStartEffect` for `ON_START`/`ON_STOP` work with cleanup, and
  `LifecycleResumeEffect` for `ON_RESUME`/`ON_PAUSE` work with cleanup. Use
  `LaunchedEffect` when the coroutine is tied only to composition lifetime.
- Translate platform results into ViewModel actions.
- Delegate rendering to the stateless content.

Stateless composables:

- Take `state`, explicit callbacks, slots and `modifier`.
- Do not obtain ViewModels, repositories, activities, nav controllers,
  `LocalContext`-driven side effects or service locators. If a leaf needs a
  platform value, pass a plain value or callback.
- Do not launch coroutines for business work.
- Keep UI-local state only when it affects rendering or local interaction:
  scroll, focus, gesture, animation, expanded, selected tab, text-field draft.
- Expose user intent as callbacks (`onBackClick`, `onRetryClick`,
  `onQueryChange`) or one `onAction` when the action set is already typed.
  When callbacks grow past three or four, consider a sealed action type.

## Component Split

Compose screens must be split into named composables by responsibility, not by
reuse potential:

- When one composable assembles the layout, derives state, renders list rows,
  owns an input area and a bottom bar, split it into sections that each draw
  one thing: header, filters, form, list region, row, card, dialog,
  empty/error/loading surface, bottom action.
- The default home for those sections is the same file, as `private`
  composables below the public one. Keep helper modifiers private too.
- Move a section to its own file when it grows past easy review or gets a
  second caller. Create a feature-local `components/` package only when two or
  more files need the same piece; group it by role only once it holds enough
  files to need grouping.
- Promote to the design system only stable, domain-free controls
  ([screen-structure.md](screen-structure.md#reuse-decision)).

Do not:

- Keep distinct sections, rows, dialogs and actions inline in one large
  holder or content function.
- Split only to wrap another composable, only to name an unrepeated style, or
  under a name vaguer than its call site.
- Pass a full screen `UiState` into every section or leaf to avoid a smaller
  model.
- Use `Scaffold`, `BoxWithConstraints` or `SubcomposeLayout` as convenience
  wrappers inside lazy items.

## Composable Dependencies

- Call top-level composables directly, including those from another module the
  feature already depends on. Express differences as data, callbacks or slots.
- Use a renderer interface or registry behind DI only when there are two or
  more real implementations chosen at runtime, or a registry that features add
  to. A single implementation behind `interface + Impl + DI binding` only hides
  a composable call.
- If the composable lives in a module you cannot depend on, revisit the module
  boundary or navigation entry instead of injecting a renderer into the
  Activity.
- Do not add a generic "get any dependency" helper for composables, and do not
  use a `CompositionLocal` to carry repositories, renderers or services.
  `CompositionLocal` is for tree-scoped UI values such as theme or content
  color, not dependency injection.
- A DI scope is not a composition lifetime. Release what a composable creates
  from the composition: `DisposableEffect` `onDispose`, `AndroidView`
  `onRelease`, or a lifecycle effect. See
  [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md).

## Screen Skeleton

- Start the screen from one root `Scaffold`, or the repo's scaffold wrapper
  when it has one. Put the top bar in `topBar` only when the screen has one,
  and bottom navigation or a fixed CTA or input bar in `bottomBar`.
- The body consumes the scaffold's inner padding
  (`Modifier.padding(innerPadding)` or `contentPadding` on the lazy layout).
  Do not compute bar heights by hand.
- Choose exactly one IME owner per screen. A stock Material3 `Scaffold` does
  not lift `bottomBar` above the keyboard: `contentWindowInsets` only pads the
  body, and with a bottom bar the body's bottom padding is the bar's height.
  The owner is therefore `Modifier.imePadding()` on the `Scaffold` itself (the
  whole scaffold, bar included, sits above the keyboard; keep `ime` out of
  `contentWindowInsets` so it is not applied twice), or `imePadding()` on the
  `bottomBar` content when only the bar should move, or a repo scaffold
  wrapper that already does one of these. Check what the wrapper consumes
  before adding anything.
- Do not place a fixed CTA as a `Box` sibling overlay with its own
  `imePadding()`. Bottom UI that must move with the keyboard belongs in
  `bottomBar`, lifted by the one owner above.
- Do not wrap the whole root in `safeDrawingPadding()`. Apply insets where they
  matter: bars, interactive edges, input areas.
- Do not assume a shrunken viewport scrolls the focused field into view; verify
  the last field of a long form separately.
- Use one scaffold per screen root; never inside lazy items.

Window policy, `enableEdgeToEdge()`, system-bar contrast, `imePadding()` order
and `adjustResize` rules are in
[edge-to-edge-insets.md](edge-to-edge-insets.md); read it at this step.

## Authoring Rules

### Modifiers

- Order a chain as layout (`padding`, `size`) -> shape (`clip`) -> drawing
  (`background`, `border`) -> interaction (`clickable`), so the ripple and hit
  area follow the shape:
  `Modifier.padding(8.dp).size(48.dp).clip(shape).background(color).clickable { }`.
- `modifier: Modifier = Modifier` is the first optional parameter of a public
  composable and is applied to the root layout exactly once. Caller
  placement such as outer padding, width fill or alignment belongs to the
  caller.
- Build a chain as one fluent value; no mutable modifier variables.
- Text-bearing containers (rows, cards, dialogs, sheets, banners, buttons with
  copy) never get a fixed `height(x.dp)`. Content plus padding decides the
  height; use `heightIn(min = ...)` for a design minimum. Fixed or max widths
  are fine.
- In a custom `BasicTextField`, put the placeholder and `innerTextField()` in
  the same decoration container with one alignment (usually `CenterStart`).
  Do not nudge either with separate padding.
- New custom modifiers use `Modifier.Node` (`ModifierNodeElement`).
  `Modifier.composed` is only for legacy interop the Node API cannot express.

### Deferred State Reads

Read a value that changes every frame (animation, scroll offset, drag) in the
layout or draw phase, not in composition:

```kotlin
// Recomposes every frame.
val offset by animateDpAsState(target)
Box(Modifier.offset(x = offset))

// Reads in layout; composition is untouched.
val offset = animateDpAsState(target)
Box(Modifier.offset { IntOffset(offset.value.roundToPx(), 0) })
```

- Use `graphicsLayer { alpha = ... }`, `drawBehind { }`, `offset { }` and
  similar lambda modifiers for fast values.
- Pass a fast value across a composable boundary as a provider `() -> T`, not
  a plain `T`.
- `val state by viewModel.state.collectAsStateWithLifecycle()` in the holder is
  fine for screen state. Do not use `by` to read a high-frequency value high in
  the tree; keep the `State<T>` and read `.value` in the lowest scope that
  needs it.
- Reading in composition is correct when the value decides what to emit.
- Do not write Compose state from a composable body in response to a value
  read in that same composition, or from a layout/draw result into state a
  sibling reads in composition. Put the transition in a callback, effect or
  state holder.

### Lazy Layouts

- Every domain-backed lazy item should have a stable key from server/domain data
  (its id), never an index or random value. Add `contentType` when the list
  mixes item shapes.
- `Modifier.animateItem()` needs those stable keys.
- Do not pass `Flow<T>` into composables; collect at the holder and pass values.

### Animation

Pick the smallest API: `animate*AsState` for one value;
`updateTransition`/`rememberTransition` for several synchronized values;
`AnimatedVisibility` when the subtree should mount and unmount; alpha or draw
changes when it should stay mounted; `AnimatedContent` with a `contentKey`
based on visual shape for content swaps.

### Effects And Remember

- Choose the effect by lifetime: `LaunchedEffect` for keyed suspending work,
  `DisposableEffect` for register/unregister, lifecycle effects when cleanup
  follows `ON_STOP`/`ON_PAUSE`, `rememberCoroutineScope` for work started by a
  user event, `SideEffect` to publish after a successful composition,
  `snapshotFlow` to turn Compose state into a flow.
- Key an effect by the specific input or owner that should restart it (an id,
  a request token, the ViewModel). Do not key by a lambda, and avoid `Unit` or
  the whole `UiState` unless the whole state should restart the work.
- Use `rememberUpdatedState` only when a long-lived effect must see a callback
  or value that actually changes while the effect runs and the effect must not
  restart. Show what changes first. Stable method references such as
  `viewModel::onAction`, and lambdas memoized under strong skipping whose
  captures are stable, have nothing to update; do not wrap them. Read the
  `State` it returns inside the effect, never once eagerly in `remember { }`.
- Register listeners, receivers and observers from an effect with a matching
  dispose path. Do not create heavy platform resources in a composable body.
- Use `remember` for UI-local objects, expensive calculations and gesture or
  animation state. Cheap derived values can be recomputed.
- Never use a remembered boolean flag as a one-off event queue; one-off events
  come from the state holder's effect stream.
- Stay on the Compose surface: `stringResource`, `pluralStringResource`,
  `dimensionResource`, Compose state and effects. Do not pull View-era helpers
  such as `Context.getString()` into Compose code.

## UI State

- Model screen states explicitly (content, loading, empty, error, permission
  denied, offline) with immutable data classes or sealed types instead of
  scattered nullable values and boolean flags. The state shape itself is owned
  by [android-viewmodel-state](../../android-viewmodel-state/SKILL.md).
- Keep one-off effects separate from persistent state.
- Keep domain models free of Compose types (`Color`, `Dp`, `TextStyle`,
  painters, resource ids); map to UI models at the feature UI boundary.
- User-facing copy is owned by resources and the repo's localization rules,
  not by enums, validators or ViewModels.

## Component API Rules

- Order public parameters as required inputs, callbacks or slots, `modifier`,
  then optional visual defaults, unless the repo's ordering is stricter.
- Prefer plain values, immutable UI models, callbacks and slots. Use slots for
  caller-owned icons, actions, media and supporting content.
- Optional slots should be nullable when absence should not reserve space.
- Keep default parameters simple and side-effect free.
- Accessibility labels, roles, selected states, enabled states, and content
  descriptions are part of the component contract.
- `Defaults` objects and token holders are stable or immutable and read theme
  values through composable getters only when the value is theme-dependent.

## Verification

Choose the closest checks configured in the repo:

- compile check for changed modules
- rendered previews for every new or changed stateless composable
- IME open and closed on input screens: bottom action and last field visible,
  no leftover bottom gap
- ViewModel/state unit test for state transitions
- Compose UI test for interaction, semantics and navigation events
- screenshot validation for visual component changes
- accessibility: labels, roles, focus order, touch targets, text scaling

Record a manual or UI/screenshot check for anything that cannot run here.

Review the final diff for direct repository calls from UI, missing previews,
fixed heights on text containers, duplicated `Defaults` values, stateful logic
in leaf components, and shared components that absorbed product behavior.
