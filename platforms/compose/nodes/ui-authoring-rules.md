---
keyflow_id: sys_compose_node_ui_authoring_rules
status: review
type: ai-generated
use_when: Writing or reviewing composable code: design-system use, modifiers, state reads, lazy lists, effects, animation or a component's public API.
skip_when: The change touches no composable code, or only moves files without editing composable bodies or signatures.
requires:
  - platforms/compose/nodes/ui-screen-structure.md
---

# Compose UI Authoring Rules

The defaults every composable follows in Jetpack Compose and Compose
Multiplatform. A platform reference adds only its platform APIs on top.

## Rules

### Design-System Consumption Gate

Before writing UI code, search the repo in this order and stop at the first
level that expresses the design: (1) a finished design-system component,
(2) design-system primitives and shared modifiers, (3) theme tokens (color,
typography, shape, spacing, elevation), (4) foundation layout (`Row`,
`Column`, `Box`, lazy layouts), (5) raw Material or platform widgets, only
with a reason written in the change.

- Do not reassemble an existing component's look from shape, color and text
  style; extend its API minimally for a missing variant or slot and say so.
- Take padding, icon size, colors and styles from a component's public
  `FooDefaults` at the call site; do not duplicate their numbers.
- A new shared component is a design-system decision, not a product-prefixed
  wrapper for one screen. A wrapper defines semantic variants, slots,
  accessibility, loading/disabled/error behavior and token ownership.

### Modifiers

- Order a chain layout -> shape -> drawing -> interaction so ripple and hit
  area follow the shape:
  `Modifier.padding(8.dp).size(48.dp).clip(shape).background(color).clickable { }`.
- Build a chain as one fluent value; no mutable modifier variables.
- Text-bearing containers (rows, cards, dialogs, sheets, banners, buttons with
  copy) never get a fixed height; use `heightIn(min = ...)` for a design
  minimum. Fixed or max widths are fine.
- In a custom `BasicTextField`, put the placeholder and `innerTextField()` in
  one decoration container with one alignment; do not nudge either alone.
- New custom modifiers use `Modifier.Node` (`ModifierNodeElement`);
  `Modifier.composed` only for legacy interop the Node API cannot express.

### Deferred State Reads

Read a value that changes every frame (animation, scroll, drag) in the layout
or draw phase, not in composition:

```kotlin
val offset = animateDpAsState(target)            // keep the State<T>
Box(Modifier.offset { IntOffset(offset.value.roundToPx(), 0) }) // read in layout
```

- Use `graphicsLayer { }`, `drawBehind { }`, `offset { }` and similar lambda
  modifiers for fast values; pass them across a boundary as `() -> T`.
- Delegating screen state with `by` at the screen is fine. Keep a
  high-frequency `State<T>` and read `.value` in the lowest scope that needs
  it. Reading in composition is correct when the value decides what to emit.
- Do not write Compose state from a composable body in response to a value
  read in the same composition, or from a layout/draw result into state a
  sibling reads in composition. Use a callback, effect or state holder.

### Lazy Layouts And Parameters

- Give every domain-backed lazy item its domain id as `key`, never an index or
  random value; add `contentType` when item shapes mix. `Modifier.animateItem()`
  needs those keys.
- Parameters are plain values, immutable UI models, callbacks and slots; the
  stability contract is in `platforms/compose/nodes/state-model-stability.md`.

### Effects And Remember

- Choose by lifetime: `LaunchedEffect` for keyed suspending work,
  `DisposableEffect` for register/unregister, the platform's lifecycle effect
  when cleanup follows a lifecycle state, `rememberCoroutineScope` for work
  started by a user event, `SideEffect` to publish after a successful
  composition, `snapshotFlow` to turn Compose state into a flow.
- Key an effect by the input or owner that should restart it (an id, a request
  token, the state holder). Never key by a lambda; avoid `Unit` or the whole
  state unless the whole state should restart the work.
- Use `rememberUpdatedState` only when a long-lived effect must see a value
  that changes while it runs without restarting; show what changes first.
  Stable method references and memoized lambdas with stable captures need no
  wrapping. Read the returned `State` inside the effect.
- Use `remember` for UI-local objects, expensive calculations and gesture or
  animation state; recompute cheap derived values.
- Read resources through Compose resource APIs (`stringResource`,
  `pluralStringResource`), not platform helpers.

### Animation

`animate*AsState` for one value; `updateTransition`/`rememberTransition` for
synchronized values; `AnimatedVisibility` to mount and unmount a subtree;
alpha or draw changes when it stays mounted; `AnimatedContent` with a
`contentKey` based on visual shape for content swaps.

### Component API

- Order public parameters: required inputs, callbacks or slots, `modifier`,
  then optional visual defaults, unless the repo's order is stricter.
- `modifier: Modifier = Modifier` is the first optional parameter, applied to
  the root layout exactly once; caller placement such as outer padding, fill
  or alignment belongs to the caller.
- Use slots for caller-owned icons, actions, media and supporting content;
  optional slots are nullable when absence must not reserve space.
- Defaults are simple and side-effect free. `Defaults` objects and token
  holders are immutable and read theme values through composable getters only
  when theme-dependent.
- Accessibility labels, roles, selected and enabled states and content
  descriptions are part of the component contract.

## Do Not

- Use a remembered boolean flag as a one-off event queue; one-off events come
  from the state holder's effect stream.
- Pass `Flow<T>` into composables; collect at the stateful screen.

## Verification

- Diff review for fixed heights on text containers, duplicated `Defaults`
  values, index or random lazy keys, lambda- or `Unit`-keyed effects and fast
  values read in composition; previews and the closest UI or screenshot test
  for changed visuals, including accessibility and text scaling.
- Report the components and `Defaults` reused and any raw-widget exception.
