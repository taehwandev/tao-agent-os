---
keyflow_id: sys_android_memory_lifecycle
status: review
type: human-reviewed-needed
---

# Android Memory And Lifecycle Guidance

Detect the repo's existing convention first. If the repo already has a
lifecycle-gated collection helper, an effect wrapper, a player pool, an image
loader, or a WebView holder, search for it and reuse it instead of
hand-writing the platform API below. The APIs in this file are the fallback
defaults when no such helper exists.

## Owner And Release Matrix

| Resource or operation | Typical owner | Release boundary |
| --- | --- | --- |
| Compose listener, observer, or receiver | `DisposableEffect` | `onDispose` on key change or composition exit |
| Single lifecycle event (for example `ON_RESUME` refresh) | `LifecycleEventEffect` | event delivery or composition exit |
| Start/stop paired work without suspend collection | `LifecycleStartEffect` | `onStopOrDispose` |
| Resume/pause paired work without suspend collection | `LifecycleResumeEffect` | `onPauseOrDispose` |
| Lifecycle-bound suspend Flow collection | `LaunchedEffect` + `repeatOnLifecycle(minActiveState)` | leaving `minActiveState`, or composition exit |
| UI state displayed on screen | `collectAsStateWithLifecycle()` | below `STARTED`, or composition exit |
| ViewModel coroutine | `viewModelScope` | ViewModel clear |
| Activity/Fragment view binding and listeners | view lifecycle (`viewLifecycleOwner`) | `onDestroyView` or listener removal |
| Activity result or permission launcher | registering Activity/Fragment, or `rememberLauncherForActivityResult` | owner destroy; register before `STARTED` |
| WebView | screen or holder | screen end, with explicit `destroy()` |
| Media player or large buffer | player/loader owner or pool | screen exit, eviction, cancellation, logout, or release policy |
| Bitmap | image loader or decode owner | cache eviction or end of use |
| File stream or temporary file | operation or worker | `use`/`finally` on success, failure, or cancellation |
| Worker foreground resource or notification | Worker/WorkManager | success, failure, or cancel path |

## Compose Lifecycle APIs

- A `LaunchedEffect` key is not a lifecycle gate. The key only decides when the
  coroutine restarts. While the screen is `STOPPED` but still in composition, a
  plain `flow.collect` keeps running and handles events off-screen.
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
- Use `rememberUpdatedState` only when a long-lived effect reads a value that
  changes and the effect must not restart. Do not add it to plain callback
  forwarding.
- `remember` is not a lifecycle owner. A platform object created in `remember`
  still needs a `DisposableEffect` or lifecycle effect to release it.
- Do not perform object creation or registration side effects in the composable
  body.
- Do not pass raw lifecycle-bound streams into leaf UI components; collect at
  the holder boundary.

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
- **Media player**: define release, stop, and buffer-clear behavior, and the
  pool eviction policy when players are reused. Release on screen exit or
  eviction, not only on success.
- **Lists with media or WebView**: bound the number of concurrent loads and
  release off-screen resources; do not create one player or WebView per item
  render.
- **Bitmap and image decode**: decode at the target display size, off the main
  thread, through the repo's image loader and cache policy. Handle placeholder
  and error states.
- **Streams, byte arrays, and temporary files**: close with `use` or `finally`,
  including on cancellation and failure. Delete temporary files on every exit
  path.
- **Pools and singletons**: safe only when retention, eviction, and release
  policy are explicit.

## Coroutine Scope

- Production code does not use `GlobalScope`, or `runBlocking` outside the
  exception below. Use the injected
  or owned scope: `viewModelScope`, a lifecycle-aware scope, a worker, or an
  existing documented repo-owned application scope.
- `runBlocking` is allowed only in tests, `main` entrypoints, and a documented
  synchronous framework callback that already runs off the main thread (for
  example an HTTP authenticator bridging to a suspend token refresh). Never on
  the main thread.
- Durable work that must survive process death belongs to WorkManager or the
  repo's existing background owner, not to a UI scope.
- Retry, cancellation, and failure paths must release file handles,
  notifications, foreground services, and temporary files.
- Logout, account switch, and permission revocation must clear sensitive
  caches and in-memory state, and cancel work scoped to the old session.

## Verification

- Diff review pairs each allocation or registration with its release in the
  same owner boundary.
- Focused tests or harnesses cover retry, cancellation, failure, logout, and
  owner end when those paths exist.
- Manual or UI checks cover enter/exit, rotation, background/foreground,
  off-screen scrolling, and account or permission changes as applicable.
- Use the repo's leak or profiling tools (for example LeakCanary or the
  Android Studio memory profiler) when the change targets a leak.
- Compile success alone is not proof of lifecycle safety.
- Report verified lifecycle paths separately from remaining manual checks.
