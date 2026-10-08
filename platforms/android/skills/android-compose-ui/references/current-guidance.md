---
keyflow_id: sys_android_compose_ui
status: review
type: human-reviewed-needed
requires:
  - platforms/compose/nodes/ui-screen-structure.md
  - platforms/compose/nodes/ui-authoring-rules.md
  - platforms/compose/nodes/lifecycle-resource-ownership.md
---

# Android Compose UI

The Compose authoring contract on Android: which design-system API a screen or
component consumes, how holder and stateless content are named and split, how
the screen skeleton owns bars, insets and the keyboard, which modifier,
effect, lazy-list and animation APIs it uses, and which previews it ships
with. The platform-neutral rules live in the Compose nodes this file requires;
this file keeps the Android-only rules and the ordered procedure.

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

The layer shape Screen/Holder Composable -> Content Composable -> Section Composable
-> Feature Component -> Design-System Primitive, and what each layer may know,
are in `platforms/compose/nodes/ui-screen-structure.md`. On Android the holder
also wires the ViewModel, permission launchers and activity-result callbacks.

When a screen mixes Views and Compose, decide first which side owns the window
insets and the keyboard, and keep the bridge at an existing repo boundary.

## Design-System Consumption Gate

The five-level search order (finished component, primitives, tokens,
foundation layout, raw Material with a reason) and the `Defaults` rules are in
`platforms/compose/nodes/ui-authoring-rules.md`. A new shared component is a
[design-system](../../../../../common/skills/design-system/SKILL.md) decision.

## Stateful And Stateless

Naming and the holder/content contract are in
`platforms/compose/nodes/ui-screen-structure.md` (default `FooScreen` /
`FooContent`). In Navigation Compose `Route` names the destination type,
declared in the feature `api` module (see
[module-boundaries.md](../../android-module-structure/references/module-boundaries.md)).

Android holders:

- Collect `StateFlow` with `collectAsStateWithLifecycle()`.
- Prefer `LifecycleEventEffect` for a single lifecycle callback,
  `LifecycleStartEffect` for `ON_START`/`ON_STOP` work with cleanup, and
  `LifecycleResumeEffect` for `ON_RESUME`/`ON_PAUSE` work with cleanup. Use
  `LaunchedEffect` when the coroutine is tied only to composition lifetime.
- Translate permission and activity results into ViewModel actions.

Android stateless composables:

- Do not obtain ViewModels, repositories, activities, nav controllers,
  `LocalContext`-driven side effects or service locators. If a leaf needs a
  platform value, pass a plain value or callback.

## Component Split

Compose screens must be split into named composables by responsibility; the
split, file-placement and promotion rules are in
`platforms/compose/nodes/ui-screen-structure.md`. Promotion to the design
system: [screen-structure.md](screen-structure.md#reuse-decision).

## Composable Dependencies

Direct calls, renderer registries and `CompositionLocal` limits are in
`platforms/compose/nodes/ui-screen-structure.md`. On Android, do not inject a
renderer into the Activity, and release what a composable creates with
`DisposableEffect` `onDispose`, `AndroidView` `onRelease`, or a lifecycle
effect ([android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md)).

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

Modifier order and caller placement such as outer padding, deferred state
reads, lazy layouts, animation and effect keys are in
`platforms/compose/nodes/ui-authoring-rules.md`. Every domain-backed lazy item should have a stable key from server/domain data.
Android additions:

- `val state by viewModel.state.collectAsStateWithLifecycle()` in the holder is
  fine for screen state; keep high-frequency values as `State<T>`.
- Use lifecycle effects when cleanup follows `ON_STOP`/`ON_PAUSE`.
- Stay on the Compose surface: `stringResource`, `pluralStringResource`,
  `dimensionResource`. Do not pull View-era helpers such as
  `Context.getString()` into Compose code.

## UI State

Model screen states explicitly; the state shape is owned by
[android-viewmodel-state](../../android-viewmodel-state/SKILL.md) and
`platforms/compose/nodes/state-model-stability.md`, and the UI model boundary
by `platforms/compose/nodes/ui-screen-structure.md`.

## Component API Rules

Parameter order, `modifier`, slots (Optional slots should be nullable when
absence should not reserve space), `Defaults` holders and the rule that
Accessibility labels, roles, selected states, enabled states and content
descriptions are part of the contract are in
`platforms/compose/nodes/ui-authoring-rules.md`.

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
