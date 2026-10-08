---
keyflow_id: sys_compose_node_state_holder_surface
status: review
type: ai-generated
use_when: Creating or changing a Compose screen state holder's public surface, its state/action/effect types, or how it reaches notices, routes and other runtime effects.
skip_when: The change only touches composable layout, theming or a local remember value with no state holder, action or effect involved.
---

# Compose State Holder Surface

The state holder is an Android ViewModel, or a plain class with an injected
`CoroutineScope` on Compose Multiplatform desktop. These rules hold for both.

## Rules

Use the repo's names when they exist; otherwise:

| Name | Holds | Not |
| --- | --- | --- |
| `FooUiState` | the durable, renderable screen state the holder exposes | callbacks, effects, platform objects |
| `FooAction` | typed user intents sent to the holder's input method | results, UI commands |
| `FooEffect` | one-off commands performed once (navigate, notice, launch) | anything a late collector must still see |
| `FooDraft` | unsaved user input for a form or editor | server state |
| `FooSnapshot` | an immutable copy captured for a request, diff or undo | the live state holder |

State ownership, unless the repo has a stricter local pattern:

```text
Screen holder/Composable -> Action -> state holder -> Use Case -> Repository
  -> DataSource/Adapter -> domain/repository entity
  -> state holder maps entity/failure to UiState + Effect
```

- The screen holder composable collects state, renders it, emits typed actions
  and performs one-off effects.
- The state holder receives actions through one typed input method such as
  `onAction(action)` or `onEvent(event)` (follow the repo), and owns screen
  state, cancellation and effect output.
- A use case owns product rules and orchestration when logic is reused, risky
  or independently testable; a repository owns source coordination, caching,
  DTO/domain mapping and error normalization; data sources and adapters own
  storage, files, sensors, SDKs and network clients.
- Add a use case or repository only when it protects a product rule, side
  effect, test boundary, cache boundary or platform API boundary, never as a
  pass-through. Request/response DTOs stay at the data boundary; `UiState` and
  one-off effects are the only presentation outputs.

Public surface: `state` (a `StateFlow`), `effects` (a `Flow` of typed one-off
commands) and the one typed input method. Keep `MutableStateFlow` private. One
coarse state stream is the default for small screens, not a mandate.

Output has two lanes:

| Lane | Use when |
| --- | --- |
| `UiState` field | a late collector, recreation or a restored window must still show it |
| typed effect | repeating it would be wrong (navigate, notice, launch) |
| durable pending state with an id and explicit consume/acknowledge | an effect must survive recreation; never replay a blind effect |

Runtime effects go through role-sized ports, not concrete UI, router or SDK
implementations:

```text
NoticeSink / NoticeEffectDelegate     toast, snackbar, alert, inline notice
RouteEventSink / RouteDispatcher      app route events and navigation requests
DeepLinkOpener                        allowlisted deep-link requests
PermissionRequester                   permission prompt requests
ExternalLauncher                      share, browser, file picker, settings
```

- Compose reusable behavior with delegates (a channel, shared flow, sink,
  mapper or small effect API). The holder still owns the action reducer and the
  state transition; the delegate owns only its capability.
- Before adding a feature-level notice, alert or route effect, search for an
  existing app-wide notice host or route host and use it. A second
  feature-local host for the same job splits ordering and dismissal rules.
- Confirmation results belong to the state owner: model confirm/cancel as a
  typed suspending notice request on the notice port
  (`val result = showNotice(Alert(...))`), then decide the transition, route
  or effect in the holder. A custom dialog host may render holder-owned typed
  state, but the decision stays in the holder.
- Feature actions stay feature-owned sealed values; pass one dispatch function
  from the stateful holder composable down to stateless content.

## Do Not

- Do not expose public getters the view polls, suspend functions the view
  awaits for a result, public `MutableStateFlow`/`MutableState`, or callbacks
  the view registers.
- Do not add helpers that return scroll, route, validation or notice values to
  the view; that is a third output channel.
- Do not create a base state-holder class only to inherit notice, routing,
  permission or coroutine helpers; inject small interfaces or delegates.
- Do not model confirmation with a screen-local `isDialogVisible` flag where
  the composable decides what confirm means.
- Do not create one global action type for unrelated screens, or let a reusable
  feedback model carry a generic action payload.
- Do not send raw strings, platform objects or generic event maps as input.

## Verification

- The holder's public API contains only `state`, `effects` and the one typed
  input method; no public mutable state or awaited results.
- Each effect has a test proving it is emitted once per triggering action, and
  each confirmation path has a test for both confirm and cancel outcomes.
- The diff shows no new feature-local notice or route host when an app-wide one
  exists.
