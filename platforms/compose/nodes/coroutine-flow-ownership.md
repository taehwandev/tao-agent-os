---
keyflow_id: sys_compose_node_coroutine_flow_ownership
status: review
type: ai-generated
use_when: Choosing StateFlow, SharedFlow, Channel, suspend or cold Flow, or deciding which owner launches and cancels coroutine work for a Compose screen.
skip_when: The change adds no stream, coroutine launch, scope or dispatcher.
---

# Compose Coroutine And Flow Ownership

The state holder is an Android ViewModel, or a plain class with an injected
`CoroutineScope` on Compose Multiplatform desktop; "the holder's scope" means
that owner's scope.

## Rules

Choose the primitive by delivery contract and name the replay, buffering,
ordering and lifecycle behavior the screen needs:

| Primitive | Use for | Avoid when |
| --- | --- | --- |
| `StateFlow` | Durable, replayable latest UI state with a synchronous value: screen state, selected ids, load/error/content, permission state, form availability. | One-off navigation, notices, launches, or events that must not replay on recreation or to a late collector. |
| `SharedFlow(replay = 0)` | Broadcast one-off effects where zero replay is intentional, collected by one or more owners. Set buffer and overflow explicitly. | A serialized action queue, or durable state a late collector must see. |
| `Channel` / `receiveAsFlow()` | Single-consumer ordered work, actor-style reducers, one-off effects owned by one collector; buffered sends wait while no collector is attached. | Broadcast to several collectors, durable UI state, or events that must survive recreation by replay. |
| `suspend` | One-shot caller-owned work: load, submit, save, retry, refresh, repository and adapter calls. | Long-lived observation, shared state, callback-style buses, or work whose owner hides inside the callee. |
| cold `Flow` | Continuous data, subscriptions, paging windows, callback adapters, repository streams and platform signals whose collection the caller owns. | A single request/response command, which is simpler as `suspend`. |

- Input is the typed input method. Add a `Channel` or actor only when actions
  must be queued, serialized, cancelled, coalesced or tested as a stream.
- The state holder is the boundary that turns non-suspending UI events into
  suspending work: `scope.launch { }` for one-shot work,
  `onEach { }.launchIn(scope)` for long-lived subscriptions it owns.
- Repositories, use cases, data sources, SDK adapters and managers expose
  `suspend` functions or caller-owned `Flow`s and let the caller own the scope.
- Use `stateIn(scope, started, initial)` to turn a Flow into observed
  `StateFlow` instead of `launchIn` copying into mutable state. Define the
  initial value, sharing policy and stop timeout.
- Keep `stateIn`/`shareIn` as a stable owner property when the result is the
  observable contract; recreate it per call only in an intentional cold-flow
  factory.
- Inject dispatchers, clocks and schedulers so tests control them.

```kotlin
val items: StateFlow<ImmutableList<Row>> = repository.rows()
    .map { it.toRows() }
    .stateIn(scope, SharingStarted.WhileSubscribed(5_000), persistentListOf())
```

## Do Not

- Do not copy a primitive from a reference app without naming its delivery
  contract.
- Do not store a `CoroutineScope` in repository, use-case, data-source,
  manager or singleton classes unless the class proves cancellation, restart,
  error reporting and lifecycle ownership. Constructor or `init` launches there
  are review red flags.
- Do not create ad-hoc scopes (`CoroutineScope(...)`, `MainScope()`) in
  business, data or platform classes to fire and forget; invert the API to
  `suspend`, a caller-owned Flow, or an explicit lifecycle owner.
- Do not collect infinite flows inside use cases without a clear owner.
- Do not catch `Exception` or `Throwable`, or wrap suspend calls in
  `runCatching`, without rethrowing `CancellationException`.
- Do not replay one-off effects unless replay is the product contract.

## Verification

- Coroutine tests run with injected dispatchers and a deterministic clock.
- Tests cover state transitions, each one-off effect (emitted once, not
  replayed to a new collector), cancellation and stale-result suppression.
- Repository tests cover cache, mapper, error and source selection; use-case
  tests cover product rules and side-effect orchestration.
- Review the diff for stored or ad-hoc scopes, `stateIn` inside repeatedly
  called functions and swallowed cancellation.
