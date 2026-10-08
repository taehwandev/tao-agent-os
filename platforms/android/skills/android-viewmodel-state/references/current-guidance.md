---
keyflow_id: sys_android_viewmodel_state
status: review
type: human-reviewed-needed
requires:
  - platforms/compose/nodes/state-holder-surface.md
  - platforms/compose/nodes/state-model-stability.md
  - platforms/compose/nodes/state-transitions-errors.md
  - platforms/compose/nodes/coroutine-flow-ownership.md
---

# Android ViewModel And State

Use when creating, changing, moving, or reviewing Android ViewModels, typed UI
actions, `UiState`, one-off effects, `Flow`, use cases, repositories, network
presentation hints, persistence, permission state, or navigation events.

For Compose screen/component structure, also read
[android-compose-ui](../../android-compose-ui/SKILL.md). For background work,
also read [android-background-work](../../android-background-work/SKILL.md).
For DTO, repository and persistence rules, read
[android-state-data](../../android-state-data/SKILL.md). For reusable
extraction, also read
[reusable-code-design](../../../../../common/skills/reusable-code-design/SKILL.md).


The platform-neutral rules (state holder surface, state model and stability,
transitions and errors, coroutine and Flow ownership) live in the shared
Compose nodes listed in this card's `requires` frontmatter. This card adds the
Android delta: the ViewModel as holder, `viewModelScope`, no Android platform
objects, permission flows, `@StringRes` text, persistence and
`SavedStateHandle` navigation.

## Steps

Follow these for every ViewModel, `UiState`, action or effect change, even
when the request names only one of them. Each step names the section or node
you MUST read at that step.

1. **Detect the repo convention.** Read one neighbouring ViewModel end to end
   and apply
   [Detect The Repo Convention First](#detect-the-repo-convention-first)
   and the naming table in
   [state-holder-surface](../../../../compose/nodes/state-holder-surface.md). A small fix keeps the
   existing path.
2. **Choose the holder.** `remember`, a plain state holder, a ViewModel, or a
   reducer, per
   [State Holder Selection](#state-holder-selection).
3. **Model the state.** Pick one model and make every reachable state
   (loading, empty, error, permission denied, offline, submitting)
   representable, per
   [state-model-stability](../../../../compose/nodes/state-model-stability.md).
4. **Define the surface.** `state`, `effects`, `onAction`, nothing else, per
   [state-holder-surface](../../../../compose/nodes/state-holder-surface.md). No Android platform
   objects in the ViewModel: apply
   [No Android Platform Objects In ViewModels](#no-android-platform-objects-in-viewmodels).
5. **Pick stream primitives** by delivery contract with
   [coroutine-flow-ownership](../../../../compose/nodes/coroutine-flow-ownership.md).
6. **Carry text as values.** Validators and mappers return typed values; the
   ViewModel emits `UiText` or resource ids, and the renderer resolves them
   ([Feature Actions, Feedback, And I18n Text](#feature-actions-feedback-and-i18n-text)).
7. **Handle failures.** Follow the repo's result type, then apply the
   failure-to-UI table and retry classes in
   [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md).
8. **Write transitions safely.** Update inside `update { }`, guard writes after
   suspension, and cancel stale work, per
   [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md)
   and [Flow And Coroutine Rules](#flow-and-coroutine-rules).
9. **Test** the transitions and effects listed in
   [Tests](#tests).

## Card Source Map

| Need | Source |
| --- | --- |
| Holder surface, naming, effect ports | [state-holder-surface](../../../../compose/nodes/state-holder-surface.md) |
| State model, stability, state split | [state-model-stability](../../../../compose/nodes/state-model-stability.md) |
| Transitions, errors, retry, recovery | [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md) |
| Stream primitives, coroutine ownership | [coroutine-flow-ownership](../../../../compose/nodes/coroutine-flow-ownership.md) |
| ViewModel, platform objects, permissions, text, navigation | this card, below |
| DTOs, repositories, nullability, persistence | [android-state-data](../../android-state-data/SKILL.md) |
| Holder and content composables, previews | [android-compose-ui](../../android-compose-ui/SKILL.md) |
| Lifecycle-aware collection and cleanup | [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md) |
| Work that outlives the screen | [android-background-work](../../android-background-work/SKILL.md) |

## Procedure Do Not

- Inject `Context`, `Application`, `Resources`, `Activity` or `NavController`
  into a ViewModel, including `@ApplicationContext` and `AndroidViewModel`.
- Expose mutable state, polled getters, or suspend functions the view awaits
  for results.
- Put display strings in validators, mappers, enums or `UiState`.
- Swallow a failure, turn it into a success value, or auto-retry a
  non-idempotent write.
- Read the state holder, suspend, and write the stale snapshot back.

## Procedure Stop If

- The repo's result or effect convention conflicts with a default here and you
  have not decided which one applies.
- A state the flow can reach has no representation in `UiState`.
- A retry would repeat a write that has no idempotency guarantee.

## Procedure Verification

ViewModel tests for each state transition, each effect, retry, stale-result
suppression, and cancellation, with injected dispatchers. Compile success alone
does not verify state behavior.

## Procedure Report

The state model chosen and why, the convention followed or the default used,
the failure-to-UI mapping, and the tests run and not run.

## Detect The Repo Convention First

Before applying any default in this card, read one neighbouring ViewModel end
to end and record: its state type and name, how actions arrive, the effect
primitive, the result or error type returned by repositories, how user-visible
text is carried, and any app-wide notice or route host. Follow that convention.
The defaults below apply only when the repo has none, and a small fix keeps the
existing path instead of migrating it.

## Naming

Moved to [state-holder-surface](../../../../compose/nodes/state-holder-surface.md) (naming table);
`FooUiState` is what the ViewModel exposes.

## State Ownership

The ownership chain lives in
[state-holder-surface](../../../../compose/nodes/state-holder-surface.md); on Android the ViewModel is
the state holder, and data sources/adapters own Room, DataStore, files,
sensors, permissions, notifications, SDKs and network clients.

## State Holder Selection

Choose the state holder by logic scope:

- Use local `remember` state for simple UI element state owned by one composable,
  such as expanded, focused, selected tab, gesture, animation, and scroll state.
- Use a plain UI state holder class when UI logic is complex but lifecycle
  dependent and does not need business/data-layer work. Examples include drawer,
  pager, sheet, text-field formatter, drag/drop, and focus orchestration.
- Use `ViewModel` when screen state is produced from data/domain layers, must
  survive configuration changes, handles user actions that affect app data, or
  emits navigation and platform effects.
- Use a reducer/store when the transition graph is complex enough that actions,
  state transitions, and effects should be testable without Android framework
  objects.

If a plain UI state holder needs data or domain information, pass the required
stable values from the ViewModel or screen state. Do not make lifecycle-dependent
UI logic depend directly on repositories or long-lived business state.

## ViewModel Contract

The public surface (`state`, `effects`, `onAction(action)`) is defined in
[state-holder-surface](../../../../compose/nodes/state-holder-surface.md). On Android, collect `state`
with lifecycle-aware collection (`collectAsStateWithLifecycle`) from the UI.

### Choose The State Model

Moved to [state-model-stability](../../../../compose/nodes/state-model-stability.md): pick sealed
status or always-present content + `LoadStatus`, never both.

## Effect Interfaces And Delegates

Role-sized ports, delegates, the app-wide host search and confirmation results
live in [state-holder-surface](../../../../compose/nodes/state-holder-surface.md). On Android, ports
replace concrete UI, router, `Activity` or SDK implementations, and a
`BaseViewModel` is never the vehicle for notice, routing or coroutine helpers.

### No Android Platform Objects In ViewModels

A ViewModel never holds or receives `Context`, `Application`, `Resources`,
`Activity`, `NavController`, `SnackbarHostState`, `ActivityResultLauncher`, or a
View. That includes `@ApplicationContext` injection and `AndroidViewModel`: an
application context is not leak-free by being long-lived, it hides platform
work that belongs elsewhere and makes the ViewModel untestable on the JVM.

| The ViewModel needs | Put it here instead |
| --- | --- |
| A localized string | a resource id or `UiText` in state or effect; the renderer resolves it |
| Files, DataStore, Room, clipboard, sensors | a repository or data source |
| Navigation | a typed effect or a route port |
| Snackbar, toast, dialog | a typed effect or the notice port |
| Permission or Activity result | the holder composable, which sends the decision as an action |
| System services, SDK clients | an adapter behind a small interface |

The ViewModel decides confirm/cancel through the notice port; see
"Confirmation results belong to the state owner" in
[state-holder-surface](../../../../compose/nodes/state-holder-surface.md).

## Stream Primitive Selection

Moved to [coroutine-flow-ownership](../../../../compose/nodes/coroutine-flow-ownership.md). On
Android, "recreation" includes rotation and process death: an effect that must
survive them is durable pending state, not a replayed effect.

### Runtime Permissions

For runtime permissions, prefer Compose-first request gates when the permission
is local to a screen. The Composable or route holder owns
`rememberLauncherForActivityResult`, rationale UI, duplicate request guards, and
`shouldShowRequestPermissionRationale` checks. The ViewModel should receive only
the user's intent and a pure decision such as `Granted`, `Denied`,
`PermanentlyDenied`, `Canceled`, or `Unavailable` when that decision affects
business state.

Use a ViewModel-facing `PermissionRequester` or runtime effect only when the
same permission flow is reused across several screens, must integrate with a
global router/notice host, or needs reusable assertion fakes across test
boundaries. Do not route every simple permission check through a ViewModel
side-effect stream only for architectural symmetry.

## Feature Actions, Feedback, And I18n Text

Feature actions stay feature-owned sealed values
([state-holder-surface](../../../../compose/nodes/state-holder-surface.md)). With Hilt, the route
acquires the ViewModel and passes one dispatch function down:

```kotlin
@HiltViewModel
class InboxViewModel @Inject constructor() : ViewModel() {
    fun send(action: InboxAction) {
        when (action) {
            InboxAction.Refresh -> refresh()
            InboxAction.RetryLoadClick -> retryLoad()
            InboxAction.DismissFeedbackClick -> dismissFeedback()
            is InboxAction.MessageClick -> openMessage(action.item)
        }
    }
}

@Composable
fun InboxScreen(viewModel: InboxViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    InboxContent(
        state = state,
        onAction = viewModel::send,
    )
}

@Composable
private fun InboxContent(
    state: InboxUiState,
    onAction: (InboxAction) -> Unit,
) {
    InboxMessageList(
        items = state.messages,
        onMessageClick = { item -> onAction(InboxAction.MessageClick(item)) },
        onRetryClick = { onAction(InboxAction.RetryLoadClick) },
    )
}
```

Keep user-visible text localizable at the UI/resource boundary. When the repo
has no convention, carry text as a small `UiText` value:

```kotlin
sealed interface UiText {
    data class Resource(@StringRes val id: Int, val args: List<Any> = emptyList()) : UiText
    data class Plural(@PluralsRes val id: Int, val count: Int) : UiText
    data class Raw(val value: String) : UiText // safe server fallback text only
}
```

Validators, mappers and use cases return typed values (`EmailError.TooShort`,
`PriceFormat.Free`), never display strings; the ViewModel maps them to
`UiText`, and the renderer resolves it with `stringResource` or
`pluralStringResource`. ViewModels may emit Android string resource ids, such as
`R.string.retry`, as stable message keys when the repo uses that convention. They should not resolve those ids with
`Context`, `Resources`, `getString()`, or `stringResource`, and should not
hardcode user-visible copy. The Screen holder, Activity, Fragment, or Composable
renderer resolves message keys into localized platform resources. Safe server
fallback messages may be carried as values only when the app's error policy
allows them.

Keep feature-owned copy in the module that owns the screen, and promote only
repeated generic copy to a design-system or app-ui resource owner. A dedicated
resources module is optional, not a default; naming prefixes, review rules, and
translation export can provide centralized management without turning one
resource module into a catch-all dependency.

Retry-capable feedback surfaces are chosen per
[state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md); feedback buttons
dispatch the feature action through `onAction(...)` or `viewModel.send(...)`.

## UiState Stability Contract

Moved to [state-model-stability](../../../../compose/nodes/state-model-stability.md). Never put
`Context`, `Activity` or `NavController` inside `UiState`.

## UiState Split And High-Churn Streams

Moved to [state-model-stability](../../../../compose/nodes/state-model-stability.md). Collect each
split stream with `collectAsStateWithLifecycle` at the owning route or section.

## Implementation Pattern

Use repo-local naming and DI first, but keep this contract intact:

```kotlin
@Immutable
data class ProfileUiState(
    val status: ProfileStatus = ProfileStatus.Loading,
    val canEdit: Boolean = false,
)

@Stable
sealed interface ProfileStatus {
    data object Loading : ProfileStatus
    data object Empty : ProfileStatus
    @Immutable
    data class Content(val profile: ProfileViewData) : ProfileStatus
    @Immutable
    data class Error(val message: UiText) : ProfileStatus
    data object PermissionDenied : ProfileStatus
}

sealed interface ProfileAction {
    data object RetryClick : ProfileAction
    data object BackClick : ProfileAction
    data object EditClick : ProfileAction
}

sealed interface ProfileEffect {
    data object NavigateBack : ProfileEffect
    data class OpenEditor(val id: ProfileId) : ProfileEffect
    data class ShowSnackbar(val message: UiText) : ProfileEffect
}
```

```kotlin
class ProfileViewModel(
    private val loadProfile: LoadProfileUseCase,
) : ViewModel() {
    private val _state = MutableStateFlow(ProfileUiState())
    val state: StateFlow<ProfileUiState> = _state.asStateFlow()

    // Channel(BUFFERED): one holder consumes each effect exactly once, and an
    // effect sent while no collector is attached (between STOP and START) waits
    // in the buffer instead of being dropped, as a SharedFlow without replay
    // would do. Use SharedFlow when several collectors must each see it.
    private val _effects = Channel<ProfileEffect>(Channel.BUFFERED)
    val effects: Flow<ProfileEffect> = _effects.receiveAsFlow()

    fun onAction(action: ProfileAction) {
        when (action) {
            ProfileAction.RetryClick -> load()
            ProfileAction.BackClick -> emitEffect(ProfileEffect.NavigateBack)
            ProfileAction.EditClick ->
                editTarget(_state.value)?.let { emitEffect(ProfileEffect.OpenEditor(it)) }
        }
    }

    private fun load() {
        viewModelScope.launch {
            _state.update { it.copy(status = ProfileStatus.Loading) }
            // Map domain result into typed UI state, including empty/error.
        }
    }

    // Pure: takes the state it decides on instead of reading the holder.
    private fun editTarget(state: ProfileUiState): ProfileId? =
        (state.status as? ProfileStatus.Content)?.profile?.id

    private fun emitEffect(effect: ProfileEffect) {
        viewModelScope.launch { _effects.send(effect) }
    }
}
```

Implementation rules:

- Keep notice, router, deep-link, permission, external launch, and platform
  outputs behind the ports in
  [state-holder-surface](../../../../compose/nodes/state-holder-surface.md). ViewModels must not import
  Android `Toast`, `SnackbarHostState`, `AlertDialog`, `NavController`,
  `ActivityResultLauncher`, or `Activity`.
- Effects should not replay after rotation unless replay is the product
  contract.
- Result convention and failure mapping follow
  [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md).
- When a Retrofit or HTTP stack exposes raw response handles, prefer a
  `CallAdapter`, client interceptor, or API boundary adapter that centralizes
  success, non-2xx, empty body, body conversion failure, network failure, and
  cancellation handling. Do not spread the same response parsing and exception
  wrapping across every repository method.
- Do not create forwarding composables or helpers whose only job is passing
  through ViewModel acquisition plus state collection once, such as
  `rememberFooViewModel` or `FooWithViewModel`. The route/holder composable
  already owns acquisition, collection, and callback wiring; a new layer must
  own real behavior such as lifecycle, stable identity, or effect handling.
- Persist only durable inputs needed for process recreation. Do not persist
  snackbars, transient navigation effects, or one-frame UI commands.

## State Transitions And Stale Snapshots

Moved to [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md).

## Error Handling

Moved to [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md)
(layering, failure-to-UI table, retry classes, do-not list).

## Compose State Bridges And Recovery

Moved to [state-transitions-errors](../../../../compose/nodes/state-transitions-errors.md)
(`snapshotFlow` bridge, idempotent recovery).

## Flow And Coroutine Rules

The neutral rules live in
[coroutine-flow-ownership](../../../../compose/nodes/coroutine-flow-ownership.md). Android delta:

- `viewModelScope` is the holder's scope: `viewModelScope.launch { }` for
  one-shot work, `launchIn(viewModelScope)` for owned subscriptions,
  `stateIn(viewModelScope, started, initial)` for derived state.
- Work that must outlive the ViewModel goes to WorkManager or another explicit
  lifecycle owner (see android-background-work), never an ad-hoc scope.

## Persistence And Cache

- Room entities, DataStore schemas, files, and cache records should not leak
  directly into UI state.
- Version persisted data that can survive app upgrades.
- Define cleanup on logout, account switch, org/workspace change, permission
  revoke, and downgrade.
- Define invalidation for offline caches and remote refresh.
- Handle corrupt DataStore/files, failed migrations, missing permissions, and
  storage quota or disk errors.

## Navigation And Events

- Parse navigation arguments at the route boundary and pass typed values to the
  ViewModel.
- Restore entry/launch arguments exactly once at the entry boundary: intent
  mapper, typed route arguments, `SavedStateHandle`, or assisted injection. Do
  not add a second sync path into the state owner, such as a
  `LaunchedEffect(args)` that re-sends an `Initialize(args)` action or a
  `bind(args)` call for values the ViewModel already restores. Launch arguments
  must not reach the state owner through two paths.
- Navigation, snackbar, permission prompt, file picker, and external app launch
  should be explicit outputs from the state owner.
- Events must not replay after rotation unless replay is the intended behavior.

## Tests

Choose the closest checks configured in the repo, together with the
Verification sections of the four Compose nodes:

- ViewModel tests for state transitions, retry, submit, permission denied,
  stale result suppression, and one-off effects.
- Reducer or action tests when the feature uses MVI-style state transitions.
- Compose UI tests for lifecycle collection, rendering state, and emitted
  actions.
- Mapper tests for request/response DTOs to entity/domain models and entity to
  `UiState`.
- Effect tests for supported server hints such as none, snackbar/toast, alert,
  full-page, retry, and deep-link action when the feature supports them.

Review the final diff for direct data-source calls from UI, public mutable
state, impossible UI state combinations, replaying one-off events, missing
logout cleanup, and untested coroutine timing.
