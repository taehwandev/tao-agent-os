---
keyflow_id: sys_compose_node_ui_screen_structure
status: review
type: ai-generated
use_when: Adding, splitting, moving or reviewing a Compose screen, section or feature component.
skip_when: The change touches no composable, or only edits a modifier, effect or value inside an existing composable without changing its shape.
requires:
  - platforms/compose/nodes/state-model-stability.md
---

# Compose Screen Structure

How a Compose screen is layered, how its stateful screen and stateless content
are named and split, and what each composable may depend on. Applies to
Jetpack Compose and Compose Multiplatform alike.

## Rules

### Layers

Use this shape unless the repo has a stricter local pattern:

```text
Screen (stateful) -> Content (stateless) -> Section -> Feature Component -> Design-System Primitive
```

| Layer | Owns | Must not know |
| --- | --- | --- |
| Screen `FooScreen` | state-holder collection, one-off effects, navigation callbacks, platform result translation, DI entry points | rendering detail beyond delegating to content |
| Content `FooContent` | renders the whole screen from immutable state plus callbacks | state holders, repositories, DI graph, navigation controllers |
| Section | one screen area, from only the state it needs | the full screen state |
| Feature component | product display models | repositories, state holders, routers |
| Design-system primitive | visual and interaction contract | product routes, analytics labels, fake data |

Each layer passes the smallest stable model or value set the next layer needs,
not the whole screen state.

### Naming

- Read two or three neighbouring screens first and follow the repo's existing
  stateful/stateless naming, whatever the suffixes are.
- Only without a convention, use `FooScreen` for the stateful composable and
  `FooContent` for the stateless one. Do not use `Route` as the stateful
  suffix: type-safe navigation uses `Route` for the destination type.

### Stateful Screen

- Collects the state holder's state with the platform's lifecycle-aware
  collector and passes values, never the stream, to content.
- Owns effects for one-off commands: navigation, snackbar, focus, permission
  request, external launch. Translates their results into holder actions.
- Delegates all rendering to `FooContent`.

### Stateless Content

- Takes `state`, explicit callbacks, slots and `modifier`, nothing else.
- Obtains no state holder, repository, navigation controller, service locator
  or platform-context side effect. A leaf that needs a platform value gets a
  plain value or callback.
- Launches no coroutine for business work.
- Keeps UI-local state only when it affects rendering or local interaction:
  scroll, focus, gesture, animation, expanded, selected tab, text-field draft.
- Exposes intent as callbacks (`onBackClick`, `onRetryClick`,
  `onQueryChange`) or one `onAction` when the action set is already typed;
  past three or four callbacks, consider a sealed action type.

### Component Split

Split by responsibility, not by reuse potential:

- When one composable assembles layout, derives state, renders rows, owns an
  input area and a bottom bar, split it into sections that each draw one
  thing: header, filters, form, list region, row, card, dialog,
  empty/error/loading surface, bottom action.
- Sections default to `private` composables below the public one in the same
  file; helper modifiers stay private too.
- Move a section to its own file when it outgrows easy review or gets a second
  caller. Create a feature-local `components/` package only when two or more
  files need the same piece.
- Promote to the design system only stable, domain-free controls.

### Composable Dependencies

- Call top-level composables directly, including ones from a module the
  feature already depends on. Express differences as data, callbacks or slots.
- Use a renderer interface or registry behind DI only for two or more real
  implementations chosen at runtime, or a registry features add to. One
  implementation behind `interface + Impl + binding` only hides a call.
- If the composable lives in a module you cannot depend on, revisit the module
  boundary or navigation entry instead of injecting a renderer.
- `CompositionLocal` carries tree-scoped UI values (theme, content color),
  never repositories, renderers or services.
- A DI scope is not a composition lifetime; release rules are in
  `platforms/compose/nodes/lifecycle-resource-ownership.md`.

### UI Model Boundary

The state model and its stability contract are in
`platforms/compose/nodes/state-model-stability.md`.

- Keep domain models free of Compose types (`Color`, `Dp`, `TextStyle`,
  painters, resource ids); map to UI models at the feature UI boundary.
- User-facing copy is owned by resources and the repo's localization rules,
  not by enums, validators or state holders.

## Do Not

- Keep distinct sections, rows, dialogs and actions inline in one large
  screen or content function.
- Split only to wrap another composable, only to name an unrepeated style, or
  under a name vaguer than its call site.
- Pass the full screen state into every section or leaf to avoid a smaller
  model.
- Use scaffolds, `BoxWithConstraints` or `SubcomposeLayout` as convenience
  wrappers inside lazy items.
- Add a generic "get any dependency" helper for composables.

## Verification

- Diff review: each changed composable is classified into one layer, content
  composables take only state, callbacks, slots and `modifier`, and no UI code
  calls a repository or state holder directly.
- Compile check for the changed modules; a rendered preview exists for every
  new or changed stateless composable.
- Report the naming convention found and any layer exception with its reason.
