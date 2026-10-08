---
keyflow_id: sys_android_memory_lifecycle
status: review
type: human-reviewed-needed
requires:
  - platforms/compose/nodes/lifecycle-resource-ownership.md
---

# Android Memory And Lifecycle Guidance

Detect the repo's existing convention first. If the repo already has a
lifecycle-gated collection helper, an effect wrapper, a player pool, an image
loader, or a WebView holder, search for it and reuse it instead of
hand-writing the platform API below. The APIs in this file are the fallback
defaults when no such helper exists.

The platform-neutral owner-and-release rules (listeners, streams, temporary
files, media, decoded images, pools, `remember` is not an owner, work that
outlives the screen) are in
`platforms/compose/nodes/lifecycle-resource-ownership.md`. This file keeps the
Android owners.

## Owner And Release Matrix

| Resource or operation | Typical owner | Release boundary |
| --- | --- | --- |
| Single lifecycle event (for example `ON_RESUME` refresh) | `LifecycleEventEffect` | event delivery or composition exit |
| Start/stop paired work without suspend collection | `LifecycleStartEffect` | `onStopOrDispose` |
| Resume/pause paired work without suspend collection | `LifecycleResumeEffect` | `onPauseOrDispose` |
| Lifecycle-bound suspend Flow collection | `LaunchedEffect` + `repeatOnLifecycle(minActiveState)` | leaving `minActiveState`, or composition exit |
| UI state displayed on screen | `collectAsStateWithLifecycle()` | below `STARTED`, or composition exit |
| ViewModel coroutine | `viewModelScope` | ViewModel clear |
| Activity/Fragment view binding and listeners | view lifecycle (`viewLifecycleOwner`) | `onDestroyView` or listener removal |
| Activity result or permission launcher | registering Activity/Fragment, or `rememberLauncherForActivityResult` | owner destroy; register before `STARTED` |
| WebView | screen or holder | screen end, with explicit `destroy()` |
| Bitmap | image loader or decode owner | cache eviction or end of use |
| Worker foreground resource or notification | Worker/WorkManager | success, failure, or cancel path |

## Compose Lifecycle APIs

- A `LaunchedEffect` key is not a lifecycle gate. While the screen is
  `STOPPED` but still in composition, a plain `flow.collect` keeps running and
  handles events off-screen.
- For suspend collection that must pause below a lifecycle state, call
  `repeatOnLifecycle(minActiveState)` inside `LaunchedEffect`. Wrap the collect
  block in `try/finally` when it needs cleanup on each stop.

  ```kotlin
  // Wrong: keeps collecting while STOPPED.
  LaunchedEffect(id) { events.collect { handle(it) } }
  // Right: collection stops below STARTED and restarts on return.
  LaunchedEffect(id, lifecycleOwner) {
      lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) { events.collect { handle(it) } }
  }
  ```

- Choose the effect by shape: `LifecycleEventEffect` for one event,
  `LifecycleStartEffect` for start/stop cleanup, `LifecycleResumeEffect` for
  resume/pause cleanup, `DisposableEffect` for register/unregister that is not
  tied to a lifecycle state.
- Use `minActiveState = RESUMED` for owners that are only valid in the
  foreground: camera, sensors, media focus, and foreground-only hosts. The
  default for other collection is `STARTED`.
- Collect UI state with `collectAsStateWithLifecycle()`, not a hand-written
  collect into a local state.
- Direct composition-lifetime collection (a `LaunchedEffect` collect with no
  lifecycle gate) is allowed only when the stream must be received while
  `STOPPED`. Leave a comment at the call site that names the reason and pin it
  with a focused test.

## View, Fragment, And Activity Owners

- Release Fragment view binding, adapters, and listeners with the view
  lifecycle, not the Fragment lifecycle.
- Do not store Activity, Fragment, View, or Composition references in a
  ViewModel, singleton, repository, or callback registry.
- When a long-lived object needs a `Context`, pass the application context or a
  narrow platform adapter, never an Activity.
- `BroadcastReceiver`, activity result and permission launchers, and
  sensor/location callbacks need an owner lifecycle and an explicit
  unregister or release path.

## Heavy Resources

- **WebView**: define the owner, call `destroy()` on screen end, and state the
  JavaScript bridge, callback, and history/cache policy. Remove the bridge and
  clients before destroy.
- Media players, lists with media or WebView, image decode, streams, temporary
  files, pools and singletons follow
  `platforms/compose/nodes/lifecycle-resource-ownership.md`.

## Coroutine Scope

- Scope ownership is in `platforms/compose/nodes/coroutine-flow-ownership.md`;
  the `runBlocking` exception (tests, `main`, a documented off-main-thread
  synchronous callback such as an HTTP authenticator bridging to a suspend
  token refresh) is in `platforms/compose/nodes/lifecycle-resource-ownership.md`.
- On Android the owned scopes are `viewModelScope`, a lifecycle-aware scope, a
  worker, or a documented repo-owned application scope. Durable work that must
  survive process death belongs to WorkManager or the repo's existing
  background owner.

## Verification

- Diff review pairs each allocation or registration with its release in the
  same owner boundary.
- Manual or UI checks cover enter/exit, rotation, background/foreground,
  off-screen scrolling, and account or permission changes as applicable.
- Use the repo's leak or profiling tools (for example LeakCanary or the
  Android Studio memory profiler) when the change targets a leak.
- Report verified lifecycle paths separately from remaining manual checks.
