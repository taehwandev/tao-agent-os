---
keyflow_id: sys_platforms_android_android_memory_lifecycle_md_skill
status: review
type: ai-generated
---

# Android Memory And Lifecycle

This card owns who holds an Android resource, which lifecycle API gates it,
when it is released, and which coroutine scope runs work that can outlive a
screen, view, composition, or worker.

## Steps

1. **Classify the resource and name its owner.** Before you create or retain a
   listener, observer, receiver, launcher, WebView, player, Bitmap, stream,
   temporary file, or coroutine, pick its owner and release boundary. You MUST
   read the owner matrix in
   [current-guidance.md](references/current-guidance.md#owner-and-release-matrix).
2. **Reuse the repo's lifecycle helpers first.** Search for an existing
   lifecycle-gated collection helper, player pool, image loader, or WebView
   holder. Use it if it exists. Hand-write the platform API only when none
   exists, and state that you searched.
3. **Choose the Compose lifecycle API.** For any effect, Flow collection, or
   lifecycle callback in a composable, you MUST apply
   [Compose Lifecycle APIs](references/current-guidance.md#compose-lifecycle-apis).
   A `LaunchedEffect` key is not a lifecycle gate.
4. **Apply the View, Fragment, and Activity rules** when the change touches
   bindings, adapters, launchers, receivers, or sensor callbacks:
   [View And Activity Owners](references/current-guidance.md#view-fragment-and-activity-owners).
5. **Apply the per-type heavy-resource rule** for WebView, media player,
   Bitmap, stream, or list-item resources:
   [Heavy Resources](references/current-guidance.md#heavy-resources).
6. **Pick the coroutine scope.** You MUST apply
   [Coroutine Scope](references/current-guidance.md#coroutine-scope). Production
   code never uses `GlobalScope`, and `runBlocking` only under its narrow
   exception.
7. **Pair every allocation with its release** on dispose, key change,
   cancellation, failure, replacement, logout or account switch, and owner end.
8. **Verify the changed lifecycle path** with the matrix in
   [Verification](references/current-guidance.md#verification).

## Source Map

| Need | Source |
| --- | --- |
| Owner, API, scope, and resource rules | [current-guidance.md](references/current-guidance.md) |
| Compose state and effect boundaries | [android-compose-ui](../android-compose-ui/SKILL.md) |
| Durable work, retry, and worker cleanup | [android-background-work](../android-background-work/SKILL.md) |
| Main-thread, cache, and media cost | [runtime-performance.md](../android-review/references/runtime-performance.md) |
| Upstream effect and coroutine sources | [external source coverage](../android-external-skill-source-coverage/references/current-guidance.md#source-trigger-map) |

## Do Not

- Do not retain an Activity, Fragment, View, or Composition reference in a
  ViewModel, singleton, repository, or callback registry.
- Do not use `remember` as a lifecycle owner for a platform object.
- Do not create heavy resources on every recomposition or list-item render.
- Do not add a pool, singleton, or helper without an eviction and release owner.
  A pool with no eviction policy is a leak.
- Do not perform registration or allocation side effects in a composable body.

## Stop If

- The resource has no owner that outlives its use and ends before it leaks.
- The only fix you can find is a new global scope, a singleton, or a blocking
  call.
- The required cleanup path (logout, permission revoke, eviction) is owned by
  code outside the task scope. Report the gap instead of adding a second owner.

## Verification

Compile success is not proof of lifecycle safety. Review allocation and release
in the same owner boundary. Exercise the changed transition: enter/exit,
rotation, background/foreground, off-screen scroll, logout, or account switch,
with a focused test when a cleanup path exists.

## Report

List each resource with its owner, lifecycle API or scope, and release point.
Separate the lifecycle paths you verified from the manual checks that remain.

Route or frontmatter maintenance: validate links and keep this entrypoint
selected by the route.
