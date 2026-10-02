---
keyflow_id: sys_platforms_android_android_compose_ui_md_skill
status: review
type: ai-generated
required_contract: core
---

# Android Compose UI

Use when a change adds, changes, moves or reviews a Compose composable, screen
skeleton, modifier, effect, lazy list, animation or preview.

## Read

The core below is the required contract. Open `references/current-guidance.md`
only for an unresolved in-scope question: `## Compose Layers` for View/Compose
mixing; `## Design-System Consumption Gate` when no component fits;
`## Screen Skeleton` for IME owner choice; `## Authoring Rules` for effects or
deferred reads; `## Steps` for new-screen, inset and preview files.

## Must

- Classify each composable (holder, content, section, feature component,
  primitive); pass each layer the smallest stable model, not `UiState`.
- Design-system gate, stop at the first fit: finished component, primitives
  and shared modifiers, theme tokens, foundation layout, raw Material (reason
  in the change). Never reassemble an existing component's look; extend
  its API minimally and report it. Take padding, icon size, colors, styles
  from `FooDefaults`. No single-screen product-prefixed wrapper.
- Follow the repo's holder/stateless naming; default `FooScreen` holder and
  `FooContent` content, never `Route` as holder suffix.
- Holder: `collectAsStateWithLifecycle()`, lifecycle-aware effects for one-off
  commands, platform results to ViewModel actions.
- Stateless: `state`, callbacks, slots, `modifier`; no ViewModel, repository,
  activity, nav controller, `LocalContext` side effect or business coroutine.
- Split by responsibility into `private` same-file sections; own file on
  growth or reuse. No `Scaffold`,
  `BoxWithConstraints` or `SubcomposeLayout` inside lazy items.
- Call composables directly; renderer interface/DI only for two or more runtime
  implementations. No `CompositionLocal` for repositories, renderers or
  services. Register listeners and release composition-created resources via
  `DisposableEffect`, `AndroidView` `onRelease` or a lifecycle effect.
- One root `Scaffold` (or repo wrapper); body consumes inner padding; no
  hand-set bar heights. One IME owner per screen: `imePadding()` on
  the `Scaffold` (no `ime` in `contentWindowInsets`), on `bottomBar` content,
  or the repo wrapper. No `Box` overlay CTA with own `imePadding()`; no root
  `safeDrawingPadding()`.
- Modifier order: layout, `clip`, drawing, `clickable`; one fluent chain, no
  mutable modifier variables. `modifier: Modifier = Modifier` is the first
  optional parameter, applied once to the root. No fixed `height(x.dp)` on
  text containers; use `heightIn(min = ...)`. New custom modifiers use
  `Modifier.Node`.
- Read per-frame values in layout/draw (`offset { }`, `graphicsLayer { }`);
  pass them as `() -> T`. Never write state from a composable body in response
  to a value read in that composition.
- Lazy items: stable domain-id `key`, never index/random, `contentType`
  for mixed shapes; no `Flow<T>` parameters.
- Smallest animation API. Choose effects by lifetime; key by the
  specific input, never a lambda, `Unit` or whole `UiState`. Use
  `rememberUpdatedState` only for a value changing while a long-lived effect
  runs, not `viewModel::onAction`. No boolean flag as an event
  queue. Use `stringResource`, not `Context.getString()`.
- Model screen states explicitly, not scattered nullables/booleans; one-off
  effects stay separate. Domain models carry no Compose types.
- Public params: required, callbacks/slots, `modifier`, optional visuals;
  accessibility labels, roles and states are contract.
- Preview every new or changed renderable stateless composable; long-copy and
  large-fontScale variants for text containers.

## Stop If

- A mixed View/Compose screen has an unknown inset owner.
- The change alters unrequested navigation, scroll, keyboard or system-bar
  behavior.
- No component fits and the choice is a new shared component or a raw Material
  exception (`design-system`).

## Verification

- Compile changed modules; render changed previews.
- Input screens: IME open and closed, bottom action and last field visible, no
  bottom gap.
- State, Compose UI, screenshot, accessibility checks as configured; record
  a manual check for what cannot run.
- Review the diff against the Must rules (UI repository calls, stateful
  leaves, product behavior in shared components).
- Report classification, `Defaults` reused, Material exceptions, IME owner,
  previews, checks run.
