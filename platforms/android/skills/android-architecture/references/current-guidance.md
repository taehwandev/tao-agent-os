---
keyflow_id: sys_f6093ac42517
status: review
type: ai-generated
---

# Android Architecture

Use for Compose/ViewModel/Flow, data, and Android platform boundary work.

For Compose state, Flow, repository, persistence, permissions, or lifecycle details, also use `android-state-data.md`.

For ViewModel, `UiState`, Flow, repository, use case, persistence, and one-off event implementation details, also use `android-viewmodel-state.md`.

For Compose screen/component structure, stateful/stateless split, previews, or package layout, also use `android-compose-ui.md`.

For Gradle module boundaries, `api`/implementation splits, package layout, and feature/common/core ownership, also use `android-module-structure.md`.

For credentials, deep links, exported components, WebView, or release builds, also use `android-security.md`.

For WorkManager, foreground services, alarms, notifications, sync, uploads, or downloads, also use `android-background-work.md`.

For Android work that touches official skill surfaces such as Navigation 3,
CameraX, AppFunctions, Credential Manager verified email, Play Engage, Play
Billing, AGP, R8, Perfetto, Wear, XR/Glimmer, or Android CLI/device tooling,
also use `android-external-skill-source-coverage.md` and
`skills/source-coverage/SKILL.md`.

## Boundaries

```text
Screen/Composable/Fragment -> Action -> ViewModel
  -> effect interfaces/delegates for notice, routing, deep links, permissions, launchers
  -> Use Case -> Repository -> Data Source/Platform Adapter
```

Module boundaries should support this dependency direction instead of fighting
it. UI feature modules depend on repository/domain contracts, not repository
internals; shared core/design-system modules do not depend on feature
implementations.

Treat SOLID as the reason for these boundaries. Interface Segregation keeps
ViewModels talking to small capability interfaces for alert, toast/snackbar,
router, deep-link, permission, and launcher effects. Dependency Inversion keeps
those interfaces in API/core contracts while concrete implementations live in
app, runtime, data, or feature implementation modules. Delegates are a
composition pattern for sharing those capabilities without inheriting from broad
base ViewModels.

Minimal effect contract shape:

```kotlin
interface NoticeSink {
    fun showNotice(request: NoticeRequest)
}

interface RouteEventSink<E : Any> {
    fun tryEmit(event: E)
}

class NoticeDelegate(
    private val sink: MutableSharedFlow<NoticeRequest>,
) : NoticeSink {
    override fun showNotice(request: NoticeRequest) {
        sink.tryEmit(request)
    }
}
```

Use this shape when a ViewModel needs alert, snackbar/toast, router, deep-link,
permission, or external launcher behavior without depending on Android UI
classes. The delegate exists to compose a capability; it must not become a
hidden base ViewModel, global service locator, product policy owner, or screen
state owner.

Do not:

- Inject `Activity`, `Context`, `NavController`, `SnackbarHostState`, `Toast`,
  `AlertDialog`, `ActivityResultLauncher`, or SDK clients into ViewModels.
- Put every effect into one broad `UiEffectManager`.
- Emit server presentation hints directly from the network layer to Android UI.
- Hide route registration, deep-link parsing, repository calls, or analytics in
  a reusable Activity base.

## Feature Slice Baseline

Start every Android feature by naming the smallest architecture track that fits the behavior:

| Track | Use When | Required Shape |
| --- | --- | --- |
| Local UI | Local interaction only; no async data, persistence, permission, or navigation side effect. | Stateless composable plus local `remember` state where needed. |
| MVVM | Screen loads data, submits forms, handles permission state, emits navigation, or has testable UI logic. | `Screen holder -> ViewModel -> Content`; ViewModel owns `UiState`, actions, and effects. |
| Clean Architecture | Domain policy, offline/cache, auth/tenant/billing, sync, multiple clients, or risky side effects. | `Screen holder -> ViewModel -> UseCase -> Repository -> DataSource/Adapter`. |
| Reducer/MVI | Many actions, optimistic updates, replayable transitions, concurrency races, or complex undo/retry. | `Screen holder -> ViewModel/Store -> Reducer -> Effects/UseCases`. |

Do not add use cases, repositories, reducers, or modules only for ceremony. Add them when they protect a product rule, platform side effect, cache boundary, permission boundary, or test boundary.

## Rules

- Composable renders state and sends events.
- Split ViewModel-backed holder composables from stateless screen/content composables.
- ViewModel owns UI state and lifecycle-aware work.
- Model loading, empty, error, permission denied explicitly.
- Keep one-off events separate from persistent state.
- Wrap API, Room, DataStore, file, permission, notification APIs.
- Keep background work behind Worker/use-case boundaries.
- Validate exported components, deep links, and release build security surfaces.
- Follow the repo's existing DI style.

## Boundary Placement

- Parse route arguments at the `Screen` holder or navigation adapter boundary, then pass typed values into the ViewModel.
- Keep `Context`, `Activity`, `NavController`, permission launchers, `ActivityResultLauncher`, clipboard, files, notifications, sensors, and SDK calls out of stateless composables.
- Keep domain models free of Compose rendering types. Map domain to UI display models before the state reaches `Screen`.
- Keep repositories out of ViewModels only when a use case owns real product orchestration; pass-through use cases are optional, not mandatory.
- Keep data sources behind repositories or adapters. Room, DataStore, Retrofit, files, permissions, and SDK objects should not reach UI state directly.

## Refactor Signals

- Composable directly calls repository or API.
- ViewModel is tied to too many Android framework types.
- UI state is nullable values plus many flags.
- Navigation parsing and business rules are mixed.
- Background work is launched directly from UI without retry or cancellation policy.
- Exported components, WebView bridges, or deep links are added without a security review.
- A feature adds ViewModel state without previews or a visible-state test.
- A shared composable accepts product policy, routes, repositories, or a full screen `UiState` when smaller values would preserve reuse.

## Conditional References

Read one of these only when this change makes that decision. A change that does
not wire dependencies does not need the composition rules, and the boundary
contract above is complete without them.

- `references/structure-baseline.md` when creating a module or feature slice, or
  placing a new runtime boundary.
- `references/runtime-composition.md` when wiring Hilt scopes, modules, or the
  entries that assemble Compose screens and activities.
- `references/navigation-deep-links.md` when changing navigation routes, back
  stack behaviour, or deep links.
- `references/webview-surface.md` when embedding or hardening a WebView.
