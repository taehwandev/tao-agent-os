---
keyflow_id: sys_android_viewmodel_state
status: review
type: human-reviewed-needed
---

# Android ViewModel And State

Use when creating, changing, moving, or reviewing Android ViewModels, typed UI
actions, `UiState`, one-off effects, `Flow`, use cases, repositories, network
presentation hints, persistence, permission state, or navigation events.

For Compose screen/component structure, also read `android-compose-ui.md`. For
background work, also read `android-background-work.md`. For reusable extraction,
also read `../../common/skills/reusable-code-design/SKILL.md`.

## State Ownership

Use this shape unless the repo has a stricter local pattern:

```text
View/Route/Composable -> Action -> ViewModel -> Use Case -> Repository
  -> DataSource/Adapter -> domain/repository entity
  -> ViewModel maps entity/failure to UiState + SideEffect
```

- View/Route/Composable collects state, renders it, emits typed actions, and
  handles lifecycle-aware UI effects.
- ViewModel receives actions through one explicit surface such as
  `onAction(action)`, owns screen state, cancellation, and event output.
- Use case owns product rules and orchestration when logic is reused, risky, or
  independently testable.
- Repository owns source coordination, caching, DTO/domain mapping, and error
  normalization.
- Data sources/adapters own Room, DataStore, files, sensors, permissions,
  notifications, SDKs, and network clients.

Do not add a use case or repository only as a pass-through. Add it when it
protects a product rule, side effect, test boundary, cache boundary, or platform
API boundary.

Clean Architecture is useful when a feature has real domain or integration
pressure. It is not a naming template. In that track, request/response DTOs stay
at the data/network boundary, entities or domain models cross into the
ViewModel/use-case boundary, and `UiState` plus one-off effects are the only
presentation outputs.

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

ViewModels should expose an explicit state contract and explicit intent methods
or typed actions. One coarse observable state stream is a useful default for
small screens, but it is not mandatory when performance, ownership, or update
cadence requires smaller streams.

```kotlin
@Immutable
data class ProfileUiState(
    val content: ProfileViewData? = null,
    val status: LoadStatus = LoadStatus.Loading,
    val permission: PermissionState = PermissionState.Unknown,
    val isSubmitting: Boolean = false,
)

sealed interface ProfileAction {
    data object Retry : ProfileAction
    data object Edit : ProfileAction
    data object DismissMessage : ProfileAction
}
```

Rules:

- Prefer immutable `data class` or sealed state over scattered `MutableState`
  and nullable fields.
- Keep `MutableStateFlow` private and expose `StateFlow`.
- Use lifecycle-aware collection from UI.
- Convert DTO/domain models into UI models before state reaches Compose.
- Keep permission denied, offline, empty, loading, error, disabled, and submitted
  states representable when the flow can reach them.
- Keep one-off effects separate from persistent state. Use a typed effect stream
  or route callback for navigation, snackbar, permission launch, external
  activity, and file/share actions.

## Effect Interfaces And Delegates

ViewModels should communicate with app/runtime effects through role-sized
interfaces, not concrete Android UI, router, Activity, or SDK implementations.
This keeps Dependency Inversion and Interface Segregation visible in the
ViewModel boundary.

Examples of role-sized ports:

```text
NoticeSink or NoticeEffectDelegate       toast, snackbar, alert, inline notice
RouteEventSink or RouteDispatcher        app route events and navigation requests
DeepLinkOpener or DeepLinkDispatcher     allowlisted deep-link requests
PermissionRequester                      permission prompt requests
ExternalActivityLauncher                 share, browser, file picker, settings
```

Use delegates to compose reusable behavior into a ViewModel without inheriting
from broad base classes. A delegate can own a channel, shared flow, sink, mapper,
or small effect API. The ViewModel still owns the screen action reducer and
state transition; the delegate only owns the reusable capability it represents.

Do not create a `BaseViewModel` only to inherit notice, routing, permission, or
coroutine helpers. Inject small interfaces or delegates instead.

Confirmation results belong to the state owner. When a dialog or alert needs a
confirm/cancel outcome, model it as a typed suspending notice request on the
notice port: the ViewModel calls `val result = showNotice(Alert(...))`,
inspects the result, and then decides the state transition, route, or effect.
Do not model the outcome with a screen-local `mutableStateOf(isDialogVisible)`
where the composable decides what confirm means. A custom dialog host may
render typed state owned by the ViewModel, but the decision stays in the state
owner.

## Stream Primitive Selection

Choose `StateFlow`, `SharedFlow`, `Channel`, `suspend`, or cold `Flow` by
delivery contract. Do not copy a primitive from a reference app without naming
what replay, buffering, ordering, and lifecycle behavior the screen needs.

| Primitive | Use For | Avoid When |
| --- | --- | --- |
| `StateFlow` | Durable, replayable latest UI state with a synchronous current value. Use for screen state, selected ids, loading/error/content state, permission state, and form availability. | One-off navigation, toast/snackbar, permission launches, Activity launches, or events that must not replay after rotation. |
| `SharedFlow(replay = 0)` | Broadcast one-off effects where zero replay is intentional, such as notice, route, analytics-safe UI effect, or runtime host events collected by one or more lifecycle owners. Set buffer/overflow explicitly. | A reducer/action queue where every input must be serialized, or a durable state that a late collector must see. |
| `Channel` / `receiveAsFlow()` | Single-consumer ordered work or action queues, actor-style reducers, and one-off effects where a single collector owns consumption. Use when backpressure and serialization matter. | Broadcast events to multiple collectors, durable UI state, or events that must survive process death/configuration by replay. |
| `suspend` | One-shot caller-owned work such as load, submit, save, retry, refresh, repository calls, and platform adapter calls invoked from a ViewModel action handler. | Long-lived observation, shared state, callback-style event buses, or work whose lifecycle owner is hidden inside the callee. |
| cold `Flow` | Continuous data, subscriptions, paging windows, callback adapters, repository streams, and platform signals whose collection lifecycle is owned by the caller. | A single request/response command that is simpler and safer as `suspend`. |

View to ViewModel input should normally be a typed `Action` method such as
`onAction(action)`. A direct method is enough when the caller is already on the
main thread and the ViewModel can branch immediately. Add a `Channel` or actor
only when actions must be queued, serialized, cancelled, coalesced, or tested as
an input stream. Keep the public API typed either way; the UI should not send
raw strings, Android objects, or generic event maps.

ViewModel to View output has two lanes: `UiState` for durable renderable state,
and typed side effects for work the renderer/runtime performs once. Use state
instead of side effects when a late collector, rotation, or process recreation
must still show the information. Use a side-effect stream when repeating it
would be wrong. If a side effect must survive recreation, model it as durable
pending state with an id and explicit consume/acknowledge behavior instead of
replaying a blind effect.

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

Feature events should stay feature-owned. Do not create one global action type
for unrelated screens, and do not make a reusable feedback model carry a generic
action payload. Actions are UI intents/events, similar to reducer or React-style
actions: clicks, retries, dismissals, item selections, and form changes are
modeled as feature-specific sealed values.

```kotlin
sealed interface InboxAction {
    data object Refresh : InboxAction
    data object RetryLoadClick : InboxAction
    data object DismissFeedbackClick : InboxAction
    data class MessageClick(val item: InboxMessageItem) : InboxAction
}
```

In Compose, pass one dispatch function down from the stateful route to the
stateless screen or components. The screen emits actions; the ViewModel handles
them:

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
fun InboxRoute(viewModel: InboxViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    InboxScreen(
        state = state,
        onAction = viewModel::send,
    )
}

@Composable
private fun InboxScreen(
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

Keep user-visible text localizable at the UI/resource boundary. ViewModels may
emit Android string resource ids, such as `R.string.retry`, as stable message
keys when the repo uses that convention. They should not resolve those ids with
`Context`, `Resources`, `getString()`, or `stringResource`, and should not
hardcode user-visible copy. The Route, Activity, Fragment, or Composable
renderer resolves message keys into localized platform resources. Safe server
fallback messages may be carried as values only when the app's error policy
allows them.

Keep feature-owned copy in the module that owns the screen, and promote only
repeated generic copy to a design-system or app-ui resource owner. A dedicated
resources module is optional, not a default; naming prefixes, review rules, and
translation export can provide centralized management without turning one
resource module into a catch-all dependency.

Toast-like effects are poor retry surfaces because they cannot reliably own
actions. Use snackbar, banner, dialog, alert, or full-page error effects when
the user needs retry, dismiss, confirm/cancel, or an alternative action.
Feedback buttons are UI triggers; they should dispatch the relevant feature
action through `onAction(InboxAction.RetryLoadClick)` or `viewModel.send(...)`
instead of becoming part of the action model itself. The renderer should not run
business logic directly.

## UiState Stability Contract

For Compose-observed state, make stability an explicit contract instead of an
afterthought:

- In Compose-aware UI modules, annotate top-level screen state and display-model
  data classes with `@Immutable` when every public property is immutable and
  equality represents the visible state.
- Annotate sealed UI-state marker interfaces such as `FooStatus` or `FooUiItem`
  with `@Stable` only when every implementation keeps the same stability
  contract. Annotate leaf data classes or data objects with `@Immutable`.
- Actions and effects can stay unannotated unless repo-local convention uses
  annotations for Compose-visible UI contracts. They should still be immutable
  value objects.
- Do not add Compose runtime annotations to pure domain, repository, or model
  modules only to satisfy UI stability. Keep those modules structurally immutable,
  then map to annotated UI models in the feature or design-system boundary.
- Avoid `var`, mutable collections, mutable maps, arrays, raw SDK objects,
  unguarded `Context`, `Activity`, `NavController`, `CoroutineScope`, or
  repository references inside `UiState`.
- Use immutable or persistent collections for lists that cross into Compose,
  especially high-churn `LazyColumn` or `LazyRow` models. If the repo uses
  `kotlinx.collections.immutable`, prefer `ImmutableList` plus `persistentListOf`
  for default states and mapper output.
- Keep callbacks and one-off commands out of `UiState`. Actions and effects are
  separate contracts.
- Treat `@Stable` and `@Immutable` as promises to the Compose compiler, not lint
  suppressions. Remove the annotation or fix the model when the promise is false.

Prefer deterministic default state owned by the state model or preview fixture:

```kotlin
@Immutable
data class ProfileUiState(
    val status: ProfileStatus = ProfileStatus.Loading,
    val items: ImmutableList<ProfileRow> = persistentListOf(),
    val canEdit: Boolean = false,
)

@Stable
sealed interface ProfileStatus {
    data object Loading : ProfileStatus

    @Immutable
    data class Content(val profile: ProfileViewData) : ProfileStatus

    @Immutable
    data class Error(val message: UiMessage) : ProfileStatus
}
```

## UiState Split And High-Churn Streams

The default "one observable state stream" contract is a starting point, not a
license to put every value into one `UiState`. Use one coarse screen state when
the values update together and the screen cost is low. Split state when update
cadence, rendering cost, lifecycle owner, cache owner, or list window ownership
differs.

A ViewModel may expose a coarse screen `StateFlow<FooUiState>` for top-level
status, title, permissions, selected ids, form availability, banners, and
submit or refresh state. Keep high-churn data in separate streams or holders
when it would recompose unrelated UI:

- chat or conversation messages, paging windows, delivery status, read receipts,
  typing indicators, and presence
- playback progress, timers, sensor or location values, live metrics, cursors,
  drag, scroll, focus, gesture, and animation state
- large `LazyColumn` or `LazyRow` item models where only rows or a visible
  window need to update

For conversation UI, a `ConversationUiState` can own metadata, connection
status, permission state, composer availability, and top-level failure states.
Messages should be a paged, cached, or otherwise separate item stream with
stable immutable ids. Typing, presence, delivery, and draft state should update
through the smallest state holder or composable that observes them.

Collect separate streams at the route or section boundary that owns the
observation, then pass stable row models or plain values down. Do not pass the
ViewModel, repository, `Flow`, callback bundle, mutable collection, or whole
screen `UiState` into repeated rows to avoid creating a smaller model.

Do not split state for ceremony. A simple profile, read-only settings page, or
small form can keep one `UiState` when the update cadence and render cost are
shared. When a split is justified as performance work, name which Compose read,
observer, or recomposition boundary becomes smaller. Prefer structural language
such as "reduces broad invalidation risk" unless measurement proves a runtime
performance improvement.

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
    data class Error(val message: UiMessage) : ProfileStatus
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
    data class ShowSnackbar(val message: UiMessage) : ProfileEffect
}
```

```kotlin
class ProfileViewModel(
    private val loadProfile: LoadProfileUseCase,
) : ViewModel() {
    private val _state = MutableStateFlow(ProfileUiState())
    val state: StateFlow<ProfileUiState> = _state.asStateFlow()

    private val _effects = Channel<ProfileEffect>(Channel.BUFFERED)
    val effects: Flow<ProfileEffect> = _effects.receiveAsFlow()

    fun onAction(action: ProfileAction) {
        when (action) {
            ProfileAction.RetryClick -> load()
            ProfileAction.BackClick -> emitEffect(ProfileEffect.NavigateBack)
            ProfileAction.EditClick -> openEditor()
        }
    }

    private fun load() {
        viewModelScope.launch {
            _state.update { it.copy(status = ProfileStatus.Loading) }
            // Map domain result into typed UI state, including empty/error.
        }
    }

    private fun openEditor() {
        val content = _state.value.status as? ProfileStatus.Content ?: return
        emitEffect(ProfileEffect.OpenEditor(content.profile.id))
    }

    private fun emitEffect(effect: ProfileEffect) {
        viewModelScope.launch { _effects.send(effect) }
    }
}
```

Implementation rules:

- Keep action handling centralized in the ViewModel or reducer; do not scatter
  business actions across composables.
- Treat the normal round trip as `Action -> ViewModel -> domain/data work ->
  entity or typed failure -> UiState and SideEffect`. Do not let a composable
  parse a server response, call a repository directly, or decide domain failure
  meaning.
- Keep notice, router, deep-link, permission, external launch, and platform
  outputs behind small interfaces or delegates. ViewModels may invoke those
  contracts, but they should not import concrete router implementations,
  Android `Toast`, `SnackbarHostState`, `AlertDialog`, `NavController`,
  `ActivityResultLauncher`, or `Activity`.
- Use `Channel`/`receiveAsFlow`, `SharedFlow`, or repo-local event primitives
  intentionally. Effects should not replay after rotation unless replay is the
  product contract.
- Convert repository/domain errors into typed UI messages or state. Do not pass
  raw exceptions to Compose.
- For `suspend` API calls, do not make sealed `Success/Failure` network results
  the default shape only to re-wrap exceptions. Let successful suspend calls
  return the value, normalize library-specific HTTP responses at the network or
  API boundary, and throw typed transport/protocol/domain exceptions for failure.
  The ViewModel or reducer should catch those typed failures and map them to
  screen state or one-off effects.
- When a Retrofit or HTTP stack exposes raw response handles, prefer a
  `CallAdapter`, client interceptor, or API boundary adapter that centralizes
  success, non-2xx, empty body, body conversion failure, network failure, and
  cancellation handling. Do not spread the same response parsing and exception
  wrapping across every repository method.
- Preserve cancellation semantics. Cancellation should escape as cancellation,
  not become a generic user-visible failure or retryable network error.
- If the server returns presentation hints such as toast/banner, alert/dialog,
  full-page error, retry metadata, no-op/none, or a deep-link action, treat them
  as API contract hints. The ViewModel maps supported hints into Compose
  state/effects; the feature UI should not parse raw server envelopes or
  transport responses.
- Put required content data inside the `Content` state, or use another explicit
  state shape when stale content can coexist with refresh/error. Avoid nullable
  payloads that contradict the status.
- Prefer a single `onAction(ProfileAction)` surface when a screen has many
  events. Explicit callbacks are fine for small screens.
- Do not create forwarding composables or helpers whose only job is passing
  through ViewModel acquisition plus state collection once, such as
  `rememberFooViewModel` or `FooWithViewModel`. The route/holder composable
  already owns acquisition, collection, and callback wiring; a new layer must
  own real behavior such as lifecycle, stable identity, or effect handling.
- Persist only durable inputs needed for process recreation. Do not persist
  snackbars, transient navigation effects, or one-frame UI commands.

## State Transitions And Stale Snapshots

State transitions must operate on the freshest state:

- Perform transitions on the state parameter inside `update { state -> ... }`.
  Pure helpers should take the current state as a parameter and return the next
  state instead of reading the raw backing `MutableStateFlow` value directly.
- Never read the state holder into a local, suspend on network, notice, or
  route results, and then write the stale snapshot back. After any suspension,
  re-check the latest state inside `update { }` or guard the write with a
  request token, job cancellation/replacement, or a latest-only operator such
  as `flatMapLatest`.
- Do not add helpers that read the raw state holder and return scroll, route,
  validation, or notice values so the view can continue the flow. The output
  contract stays two lanes: `UiState` fields and typed effects.
  Counter-increment-and-return helpers and getters the view polls are the same
  third-channel violation.

## Flow And Coroutine Rules

- Use `viewModelScope` for work owned by the ViewModel.
- Use `viewModelScope.launch { ... }` for one-shot suspend work such as loading,
  submit, retry, or save actions.
- Treat the ViewModel or equivalent UI state holder as the normal boundary that
  translates non-suspending UI events into suspending work. Repositories, use
  cases, data sources, SDK adapters, and managers should usually expose
  `suspend` APIs and let the caller own the coroutine scope.
- Do not store a `CoroutineScope` in repository, use-case, data-source, manager,
  or DI-singleton classes unless the class can prove cancellation, restart,
  error reporting, and lifecycle ownership. Constructor or `init` launches in
  those classes are review red flags because callers cannot await, cancel, or
  observe failure.
- Do not create ad-hoc scopes with `CoroutineScope(...)`, `MainScope()`, or
  similar inside business/data/platform classes to fire-and-forget work. Invert
  the API to `suspend`, a caller-owned Flow, WorkManager, or another explicit
  lifecycle owner.
- Use `onEach { ... }.launchIn(viewModelScope)` for long-lived Flow
  subscriptions owned by the ViewModel, such as event buses, repositories, or
  platform callbacks that should keep collecting while the ViewModel is active.
- Use `stateIn(viewModelScope, started, initial)` when a Flow is transformed
  into UI-observed `StateFlow`; do not use `launchIn` only to copy Flow values
  into mutable UI state when `stateIn` can express the state owner directly.
- Inject dispatchers, clocks, and schedulers when tests need control.
- Cancel or replace in-flight work when query, account, permission, or route
  arguments change.
- Suppress stale results from older requests.
- Use `stateIn` or `shareIn` intentionally; define initial value, sharing
  policy, and stop timeout.
- Keep `stateIn`/`shareIn` as a stable owner property when the resulting
  `StateFlow` or `SharedFlow` is the observable contract. Avoid recreating it
  inside a function that callers invoke repeatedly unless the function is
  intentionally a cold flow factory.
- Choose `StateFlow`, `SharedFlow`, or `Channel` by replay and delivery
  semantics. `StateFlow` is for latest observable state with a synchronous
  value; `SharedFlow` is for broadcast events with explicit replay/buffer
  choices; `Channel.receiveAsFlow()` can fit single-consumer one-off UI effects
  when exact broadcast replay is not desired.
- Avoid collecting infinite flows inside use cases without a clear owner.
- Map errors into user-visible state or typed domain errors before UI.
- Preserve structured cancellation. Do not catch `Exception`, `Throwable`, or
  use `runCatching` around suspend calls without rethrowing
  `CancellationException`.

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
- Do not hide route decisions in random booleans inside `UiState`.
- Navigation, snackbar, permission prompt, file picker, and external app launch
  should be explicit outputs from the state owner.
- Events must not replay after rotation unless replay is the intended behavior.
- Server-driven notice hints should become local effects only after the state
  owner validates the current screen context. A `none` hint means no user-visible
  effect; it should not suppress required state updates or diagnostics.

## Tests

Choose the closest checks configured in the repo:

- ViewModel tests for state transitions, retry, submit, permission denied,
  stale result suppression, and one-off effects.
- Reducer or action tests when the feature uses MVI-style state transitions.
- Use case tests for product rules, auth/tenant/billing policy, and side-effect
  orchestration.
- Repository tests for cache, mapper, error, migration, and source selection.
- Coroutine tests with injected dispatchers and deterministic clocks.
- Compose UI tests for lifecycle collection, rendering state, and emitted
  actions.
- Mapper tests for request/response DTOs to entity/domain models and entity to
  `UiState`.
- Effect tests for supported server hints such as none, snackbar/toast, alert,
  full-page, retry, and deep-link action when the feature supports them.

Review the final diff for direct data-source calls from UI, public mutable
state, impossible UI state combinations, replaying one-off events, missing
logout cleanup, and untested coroutine timing.
