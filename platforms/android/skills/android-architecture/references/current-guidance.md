---
keyflow_id: sys_f6093ac42517
status: review
type: ai-generated
---

# Android Architecture

Use for Compose/ViewModel/Flow, data, and Android platform boundary work.

Related cards (open their `SKILL.md` first):

- Compose state, Flow, repository, persistence, permissions, or lifecycle:
  [android-state-data](../../android-state-data/SKILL.md).
- ViewModel, `UiState`, Flow, repository, use case, persistence, and one-off
  events: [android-viewmodel-state](../../android-viewmodel-state/SKILL.md).
- Compose screen/component structure, stateful/stateless split, previews:
  [android-compose-ui](../../android-compose-ui/SKILL.md).
- Gradle module boundaries, `api`/implementation splits, package layout, and
  feature/core ownership:
  [android-module-structure](../../android-module-structure/SKILL.md).
- Credentials, deep links, exported components, WebView, or release builds:
  [android-security](../../android-security/SKILL.md).
- WorkManager, foreground services, alarms, notifications, sync, uploads, or
  downloads: [android-background-work](../../android-background-work/SKILL.md).
- Official skill surfaces such as Navigation 3, CameraX, AppFunctions,
  Credential Manager verified email, Play Engage, Play Billing, AGP, R8,
  Perfetto, Wear, XR/Glimmer, or Android CLI/device tooling:
  [android-external-skill-source-coverage](../../android-external-skill-source-coverage/SKILL.md)
  and [source-coverage](../../source-coverage/SKILL.md).

This card owns the Android architecture track for a feature (local UI, MVVM,
Clean Architecture, reducer), the layer boundaries between UI, ViewModel,
domain, data, and platform adapters, and where runtime capabilities such as
notice, routing, permissions, and launchers are placed.

## Steps

1. **Detect the repo's architecture convention.** Read one neighbouring
   feature end to end: its holder/content naming, ViewModel shape, result or
   error type, DI framework, and navigation library. The repo's convention wins;
   the defaults in the references are the fallback.
2. **Choose the smallest track.** MUST read
   [Feature Slice Baseline](#feature-slice-baseline) and
   [Boundaries](#boundaries) below and name the track before editing. Add use cases, repositories, reducers, or modules
   only when they protect a product rule, side effect, cache, permission, or
   test boundary.
3. **Place each boundary.** Apply [Rules](#rules) and
   [Boundary Placement](#boundary-placement) below: no `Context`,
   `Activity`, `NavController`, or UI hosts in the ViewModel; effects go through
   small capability interfaces.
4. **New module, feature slice, or shared runtime boundary.** MUST read
   [structure-baseline.md](structure-baseline.md) and then
   [android-module-structure](../../android-module-structure/SKILL.md) before
   creating a module or a shared runtime contract.
5. **DI wiring.** MUST read
   [runtime-composition.md](runtime-composition.md) before adding or
   changing Hilt scopes, modules, or the entries that assemble screens and
   Activities.
6. **Navigation and deep links.** MUST read
   [navigation-deep-links.md](navigation-deep-links.md) before
   changing routes, back stack behavior, or deep links.
7. **WebView.** MUST read [webview-surface.md](webview-surface.md)
   before embedding or hardening a WebView.
8. **Hand off detail work** to the related cards listed at the top for
   state, UI, security, and background work.

## Procedure Stop If

- You cannot name the track and the boundary that justifies each added layer.
- A shared runtime contract has no caller, forbidden import, and verification
  path (see Runtime Boundary Example Stops in
  [structure-baseline.md](structure-baseline.md)).
- The repo's convention contradicts a default here and you have not decided
  which one applies.

## Procedure Verification

Compile the changed modules and one consumer, test changed ViewModel state
transitions, and run the DI or navigation checks of the reference you read.

## Procedure Report

- Chosen track and why the smaller one was not enough.
- Boundaries added or moved, and the repo convention followed or the default
  used where none existed.
- Verification run and anything not run.

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

## Required References By Decision

Each reference below holds rules that this file does not repeat. When the
change makes that decision, reading the reference is required before editing.

- [structure-baseline.md](structure-baseline.md): before creating a module or
  feature slice, or placing a new runtime boundary.
- [runtime-composition.md](runtime-composition.md): before wiring Hilt scopes,
  modules, or the entries that assemble Compose screens and Activities.
- [navigation-deep-links.md](navigation-deep-links.md): before changing
  navigation routes, back stack behavior, or deep links.
- [webview-surface.md](webview-surface.md): before embedding or hardening a
  WebView.
