---
keyflow_id: sys_compose_node_lifecycle_resource_ownership
status: review
type: ai-generated
use_when: A change creates, registers, holds or releases a resource, listener, stream, file, player, pool or cache from Compose UI or its state holder.
skip_when: The change allocates nothing that outlives one function call and registers no listener, stream, file or cache.
requires:
  - platforms/compose/nodes/coroutine-flow-ownership.md
---

# Lifecycle And Resource Ownership

Every resource has exactly one owner and one release boundary. Applies to
Jetpack Compose and Compose Multiplatform; the platform reference names the
platform's owners and lifecycle APIs. Which owner launches and cancels
coroutine work is in `platforms/compose/nodes/coroutine-flow-ownership.md`.

## Rules

### Reuse First

Search for the repo's existing helper before hand-writing a platform API: a
lifecycle-gated collection helper, effect wrapper, player pool, image loader
or embedded-view holder. The rules below are the fallback.

### Owner And Release

| Resource or operation | Owner | Release boundary |
| --- | --- | --- |
| Listener, observer or callback registered from UI | `DisposableEffect` | `onDispose` on key change or composition exit |
| Keyed suspending UI work | `LaunchedEffect` | key change or composition exit |
| Stream, byte array or temporary file | the operation or worker | `use`/`finally` on success, failure and cancellation |
| Media player or large buffer | player/loader owner or pool | screen exit, eviction, cancellation, logout |
| Decoded image | image loader or decode owner | cache eviction or end of use |
| Pool, cache or singleton | an explicit retention policy | eviction and release paths, written down |

- Pair every allocation or registration with its release inside the same
  owner boundary.
- A `LaunchedEffect` key decides when the coroutine restarts; it is not a
  lifecycle gate. Gate collection that must pause off-screen with the
  platform's lifecycle API.

### Compose Rules

- `remember` is not an owner. An object created in `remember` that holds a
  platform resource still needs a `DisposableEffect` or lifecycle effect to
  release it.
- A DI scope is not a composition lifetime. Release what a composable creates
  from the composition, in its effect's dispose path.
- Do not create objects with side effects or register anything in the
  composable body.
- Do not pass raw lifecycle-bound streams into leaf components; collect at the
  stateful screen boundary.

### Heavy Resources

- Media players: define release, stop and buffer-clear behavior and the pool
  eviction policy when reused; release on exit or eviction, not only on
  success.
- Lists with media or embedded views: bound concurrent loads, release
  off-screen resources, and never create one player or view per item render.
- Image decode: at the target display size, off the main thread, through the
  repo's image loader and cache policy, with placeholder and error states.
- Streams, byte arrays and temporary files: close with `use` or `finally`
  including on cancellation and failure; delete temporary files on every exit
  path.
- Pools and singletons are safe only with explicit retention, eviction and
  release.

### Work That Outlives The Screen

- `runBlocking` only in tests, `main` entry points, and a documented
  synchronous callback that already runs off the main thread; never on the
  main thread. `GlobalScope` is never an owner.
- Durable work that must survive process death belongs to the platform's
  background-work owner, not to a UI scope.
- Retry, cancellation and failure paths release file handles, notifications,
  foreground work and temporary files.
- Logout, account switch and permission revocation clear sensitive caches and
  in-memory state and cancel work scoped to the old session.

## Do Not

- Store UI, window or composition references in a state holder, singleton,
  repository or callback registry.
- Treat compile success as proof of lifecycle safety.

## Verification

- Diff review pairs each allocation or registration with its release in the
  same owner boundary.
- Focused tests or harnesses cover retry, cancellation, failure, logout and
  owner end when those paths exist.
- Manual or UI checks cover enter/exit, background/foreground and off-screen
  scrolling as applicable; use the repo's leak or profiling tools when the
  change targets a leak.
- Report verified lifecycle paths separately from remaining manual checks.
