---
keyflow_id: sys_kmp_node_state_holder
status: review
type: ai-generated
use_when: Creating or changing a Compose Multiplatform screen state holder, its coroutine scope, or how a screen obtains and releases it, especially on desktop JVM targets.
skip_when: The app uses androidx ViewModel on Android only, or the change is local remember state with no holder.
refines:
  - platforms/compose/nodes/state-holder-surface.md
requires:
  - platforms/compose/nodes/coroutine-flow-ownership.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP State Holder

The parent node owns the holder surface (`state`, `effects`, one typed input).
This node fixes the holder shape for Compose Multiplatform when the repo does
not already use the multiplatform `lifecycle-viewmodel`.

## Rules

- Default shape: a plain class `FooStateHolder(scope: CoroutineScope, deps...)`
  exposing `val state: StateFlow<FooUiState>`, `val effects: Flow<FooEffect>`
  and `fun onEvent(event: FooEvent)`. It imports no Compose UI, window, AWT or
  DI-framework types.
- The holder never creates its own scope. The caller passes one, and the
  owner of that scope defines the holder's lifetime:

| Lifetime | Scope owner |
| --- | --- |
| one screen visit | the screen composable: `rememberCoroutineScope()` plus `remember(key) { factory(scope) }` |
| one window | the window owner; cancelled when the window closes |
| the app | the app-target scope; cancelled before `exitApplication()` |

- The scope uses a `SupervisorJob` so one failed child does not cancel the
  holder, and a `CoroutineExceptionHandler` or explicit catch maps failures to
  state. `Dispatchers.Main` on desktop is the Swing thread; heavy work moves
  to an injected IO dispatcher.
- Obtain holders through a factory provided by the composition root (for
  example a `fun interface FooStateHolderFactory { fun create(scope): FooStateHolder }`).
  The stateful `FooScreen` calls the factory; the stateless `FooContent`
  receives only state and an event callback.
- Key `remember` by the identity the holder serves (project id, task id). A
  key change cancels the old holder's work and creates a new one; do not keep
  one holder and re-`bind` it with new arguments.
- State that must survive closing a screen belongs to a longer-lived owner or
  a repository, not to a screen-scoped holder.
- If the repo already uses multiplatform `lifecycle-viewmodel`, follow it
  consistently instead of mixing both shapes in one module.

## Do Not

- Do not hold `Window`, `File`, `Process`, Swing components or repositories'
  internal handles in the holder or its state.
- Do not use `GlobalScope`, `MainScope()` or a scope created inside the holder.
- Do not perform IO in composition; a screen-level `LaunchedEffect` that calls
  a repository directly is a holder that was never written.

## Verification

- Holder tests run under `runTest`, pass `backgroundScope` (or a `TestScope`)
  as the holder scope and an injected test dispatcher, and assert state
  transitions and effects (Turbine or `first`/`toList`).
- A test or manual check proves leaving the screen (or closing the window)
  cancels in-flight work started by the holder.
