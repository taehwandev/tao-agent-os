---
keyflow_id: sys_state_modeling
status: stable
type: human-reviewed-needed
---

# State Modeling

Use when designing or reviewing UI state, application state, domain state,
async state, one-off effects, reducers, stores, ViewModels, hooks, or state
machines.

State design should make impossible states hard to represent.

## State Kinds

Separate these kinds of state:

- Persistent state: can survive refresh, process recreation, sync, or storage.
- Screen/UI state: what the user can currently see or interact with.
- Derived state: computed from source state and cheap to recompute.
- Draft state: local in-progress user input.
- Effect/event: one-time command such as navigation, toast, file picker,
  permission prompt, external launch, or analytics dispatch.
- Cache state: stale/fresh data with invalidation rules.

Do not store the same fact in multiple places without naming the source of truth.

## Explicit Async States

Model async surfaces explicitly:

```text
idle -> loading -> content -> empty -> error -> refreshing
permission denied -> offline -> conflict -> partial
```

Use only the states the feature needs, but make them typed. Avoid combinations
such as `isLoading`, `error`, `data`, `isEmpty`, and `isOffline` that can produce
contradictory states.

## Finite-Mode Decision Table

When a screen or flow has a finite set of input modes, such as create versus
edit or distinct entry variants, fill a decision table before implementing,
one row per mode:

```text
mode | precondition before I/O | which I/O to call | state merged on success | failure behavior
```

Rules:

- Each table row appears as one direct branch on the mode (`when`, `switch`,
  or pattern match) in the current owner. Never re-encode a finite mode as
  combinations of booleans or nullable flags such as `shouldLoadX` or
  `isNotY`.
- Preconditions knowable before I/O, such as launch arguments or current
  state, are checked before the first network or database call.
- When caller input and a server response are both needed, merge them in a
  single state change inside the success branch.
- When per-mode response contracts differ, parse each response separately and
  then merge into the common state. Do not hide the difference behind one
  generic response type widened with nullable fields.
- The initialization owner settles success or failure. Submit and retry paths
  must never silently re-run a failed initialization as compensation.
- Do not add guards stronger than the confirmed contract: arbitrary `> 0`
  checks, blank substitution, or invented defaults.

Verification: the decision-table row count equals the meaningful branch count
in code; tests directly prove each branch's I/O call count and final merged
state; a test proves submit/retry after a failed initialization branch does
not re-trigger initialization.

## Effects

One-off effects are not persistent state.

- Navigation, toast/snackbar, focus request, permission launch, external app
  launch, download, and analytics dispatch should be modeled as commands or
  effects.
- Effects should be consumed once and should not replay accidentally after
  rotation, refresh, retry, or process recreation.
- If an effect must be recoverable, persist the underlying intent instead of the
  UI event.
- Stream, subscription, or lifecycle-bound collection should happen at the
  state-holder, controller, hook, store, or adapter boundary that owns lifecycle
  and cancellation. Leaf UI should receive plain values and callbacks unless it
  explicitly owns the subscription contract.

## Ownership

- UI owns transient interaction state that only affects rendering.
- State holder owns screen state, async lifecycle, and effect emission.
- Domain owns product rules and mutation decisions.
- Data/cache owns freshness, invalidation, pagination cursors, and persistence.
- Platform adapter owns OS/runtime state such as permissions, network reachability,
  clipboard, filesystem handles, and app lifecycle.

## Performance And Observation Boundaries

`UiState` is also an observation contract. Do not treat it as a command to put
every visible value for a screen into one object, one stream, or one store slice.
Choose the state boundary by update cadence, render cost, lifecycle owner,
invalidation rule, and the smallest observer that needs to change.

Keep one coarse screen `UiState` when the screen is small, updates together, and
has low render cost. Split state when:

- one part changes far more often than the rest of the screen
- one part renders an expensive tree, virtualized list, media surface, canvas,
  map, editor, chart, or animation
- one part is owned by a different lifecycle, cache, subscription, or data
  source
- one part should preserve local interaction state while another part refreshes
- one part is reusable or testable as an independent view model, component,
  hook, reducer, or state holder

High-churn examples include chat or conversation messages, typing and presence,
read receipts, live cursors, playback progress, timers, sensor or location
streams, drag, scroll, hover, focus, animation state, and frequently updating
metrics. These should not invalidate a whole screen `UiState` when only a list
window, row, badge, composer, or status indicator needs to update.

For conversation-style UI, keep stable screen-level state such as title,
connection status, permissions, selected thread, composer availability, and
top-level loading or error in the screen `UiState`. Keep messages, typing,
presence, unread markers, pagination windows, row drafts, and delivery updates
behind list models, item models, selectors, local state, or cache-backed
streams that can update at their own cadence.

Do not split blindly. A static profile, settings page, or small form can keep
one typed state object when the update frequency and render cost are shared.
When claiming a split is for performance, name which observer, render node, or
state holder avoids extra invalidation. If that cannot be measured yet, describe
it as a structural risk reduction instead of a proven performance win.

## Naming

Prefer names that state the boundary:

```text
FooUiState
FooUiAction
FooUiEffect
FooDomainState
FooCacheState
FooDraft
```

Use repo-local names first, but keep persistent state, visible state, and
one-time effects distinguishable.

## Review Checklist

- What is the source of truth?
- Can loading and error exist with stale content, or are they exclusive?
- What happens on retry, refresh, logout, permission change, or account switch?
- Can the state survive lifecycle or process recreation when required?
- Are one-off effects separated from durable state?
- Are invalid, missing, stale, duplicated, lower-bound, and upper-bound cases
  represented or rejected?
- What changes most often, and which observer or render node should update for
  that change?
- Are high-churn lists, streams, drafts, progress values, and presence-style
  status separated from coarse screen `UiState` when they would invalidate
  unrelated UI?
- Is state split by real ownership, update cadence, render cost, or reuse
  contract instead of by arbitrary file or naming preference?

## Verification

Verify state transitions closest to the owner:

- reducer/store/ViewModel/hook tests for state transitions
- mapper tests for domain-to-UI state
- lifecycle or refresh tests for stale and retry behavior
- UI/component tests for visible states and emitted actions
