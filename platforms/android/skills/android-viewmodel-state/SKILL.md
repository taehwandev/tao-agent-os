---
keyflow_id: sys_platforms_android_android_viewmodel_state_md_skill
status: review
type: ai-generated
required_contract: core
---

# Android ViewModel And State

Use when creating, changing, moving, or reviewing Android ViewModels, typed actions, `UiState`, one-off effects, `Flow`, or state-facing error handling.

## Read

The core below is the required contract. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## State Holder Selection` for `remember` vs plain holder vs ViewModel vs reducer.
- `## ViewModel Contract` for the state model; `## Effect Interfaces And Delegates` for platform-object substitutes.
- `## Stream Primitive Selection` for replay/buffer choice or runtime permissions.
- `## UiState Split And High-Churn Streams` for chat, paging, playback, large lists.
- `## Error Handling` for the failure-to-UI table, retry classes.
- `## Navigation And Events`, `## Persistence And Cache` for route args or caches.

## Must

- Detect the repo convention: read one neighbouring ViewModel end to end (state, actions, effects, result type, text, notice/route host). Defaults apply only when none exists; a small fix keeps the existing path.
- Surface is `state` (`StateFlow`), `effects` (typed `Flow`), `onAction(action)`. Private `MutableStateFlow`; no polled getters, awaited suspend results, registered callbacks, or helpers returning values for the view (third channel).
- Never inject `Context`, `Application`, `Resources`, `Activity`, `NavController`, `SnackbarHostState`, `ActivityResultLauncher` or a View, incl. `@ApplicationContext`/`AndroidViewModel`. Use ports/delegates, not a `BaseViewModel`. The ViewModel decides confirm/cancel via the notice port, not a composable `isDialogVisible`.
- One state model: sealed status carrying content, or always-present content + `LoadStatus`; no nullable payload beside a `Content` status. Make loading, empty, error, permission denied, offline, submitting representable. No route booleans in `UiState`; map DTO/Room entities to UI models first.
- `UiState`: `@Immutable` data classes, `@Stable` sealed markers only when every leaf complies; no `var`, mutable collections, SDK objects, scopes, repositories, callbacks; `ImmutableList` when the repo uses it.
- Pick `StateFlow`/`SharedFlow`/`Channel`/`suspend`/cold `Flow` by delivery contract; effects do not replay after rotation unless replay is the product contract. Reuse an existing app-wide notice or route host. The holder owns permission launchers and sends the decision as an action.
- Text as values: validators/mappers return typed values; ViewModel emits `UiText` or resource ids; the renderer resolves them. No display strings in mappers, enums, `UiState`.
- Follow the repo's result type with exhaustive `when`; no `getOrThrow()`. Only the ViewModel decides the UI; composables never call repositories or see raw exceptions or envelopes.
- Never swallow a failure, make it a success value, lose its cause, or auto-retry a non-idempotent write. Silent fallback only for product-optional data, logged with cause. Rethrow `CancellationException` from `runCatching`/`catch`; never show it as an error.
- Transitions inside `update { }`; never write a stale snapshot back after suspension. Cancel/replace work on argument change; suppress stale results; recovery actions idempotent. Feed Compose state via `snapshotFlow` actions; never read Compose `State` in the ViewModel.
- `viewModelScope` owns work; lower layers expose `suspend`, no stored or ad-hoc scopes. `stateIn` as a stable property with initial value and stop timeout. Inject dispatchers.
- Restore launch arguments once at the entry boundary; no second `Initialize(args)` path. No pass-through `rememberFooViewModel` wrappers. Persist only durable inputs, never effects.

## Stop If

- The repo's result or effect convention conflicts with a default here and which applies is undecided.
- A state the flow can reach has no representation in `UiState`.
- A retry would repeat a write that has no idempotency guarantee.

## Verification

- ViewModel tests with injected dispatchers for each transition, effect, retry, permission denied, stale-result suppression, cancellation; reducer/mapper tests where present. Compile success does not verify state behavior.
- Review the diff for UI calling data sources, public mutable state, impossible states, replaying effects, no logout cleanup, untested timing.
- Report state model and why, convention or default, failure-to-UI mapping, tests run/not run.
