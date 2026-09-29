---
keyflow_id: sys_android_background_work
status: review
type: ai-generated
---

# Android Background Work

Detail for [the background-work card](../SKILL.md). Read it at the steps that
link here: WorkManager, foreground services, alarms, push notifications, sync,
uploads, downloads, and long-running jobs.

This card owns the choice between WorkManager, a foreground service, and an
owned coroutine scope, and the start, cancel, retry, duplicate, and recovery
policy of work that runs outside a visible screen: sync, uploads, downloads,
push handling, alarms, and long-running jobs.

## Steps

1. **Detect the repo's existing background owner.** Search for existing
   workers, a work scheduler wrapper, unique-work names, and upload or sync
   managers. Extend the existing owner before adding a new one.
2. **Choose the mechanism.**
   - Deferrable work that must survive process death: WorkManager.
   - User-visible ongoing work that cannot be deferred: foreground service,
     only when WorkManager cannot model it.
   - Work that may die with the screen or ViewModel: the owned coroutine scope.
     Production code never uses `GlobalScope`, and `runBlocking` only under
     the exception in [android-memory-lifecycle](../../android-memory-lifecycle/references/current-guidance.md#coroutine-scope).

   You MUST read [Mechanism Selection](#mechanism-selection)
   at this step.
3. **Model the policy before writing the worker.** Decide what starts, cancels,
   retries, and observes the work, the duplicate policy (unique work or an
   idempotency key), and what persists across process death. You MUST answer
   every question in
   [Survival Checks](#survival-checks).
4. **Place the boundary.** Enqueue from a use case, repository, or worker
   boundary reached through the ViewModel, never directly from a composable,
   View, or screen callback.
5. **Classify failures.** Map each failure to retry, permanent failure, or
   user-visible recovery, and require idempotency before any automatic retry.
   Apply the error sources in the Related table.
6. **Release resources and keep payloads private.** Files, cursors, players,
   observers, notifications, and temporary files are released on success,
   failure, and cancel. Worker input, progress, notifications, and logs carry
   no credentials or private payloads.
7. **Test the policy** with the cases in
   [Tests](#tests).

## Related

| Need | Source |
| --- | --- |
| Selection, survival checks, Do Not detail, tests | this card, below |
| Worker resource release, coroutine scope | [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md) |
| Main-thread blocking, IO dispatcher, dependency cost | [runtime-performance.md](../../android-review/references/runtime-performance.md) |
| Failure classification and user-visible error state | [android-viewmodel-state error handling](../../android-viewmodel-state/references/current-guidance.md), [error-modeling](../../../../../common/skills/error-modeling/SKILL.md) |
| Sensitive payloads, notifications, exported receivers | [android-security](../../android-security/SKILL.md) |

## Procedure Do Not

- Do not use a foreground service for polling, sync, or upload work that
  WorkManager can model.
- Do not enqueue work that can run twice without unique work, an idempotency
  key, dedupe state, or server-side duplicate handling.
- Do not start durable work from UI code without a worker or use-case boundary.
- Do not treat a passing happy-path worker test as proof for Doze, standby,
  metered network, notification permission, logout, or account switch.

## Procedure Stop If

- Two owners would schedule the same work, or the duplicate policy is unknown.
- The server side of a retried call is not idempotent and no dedupe key exists.
- The work needs a foreground service type or permission the app does not
  declare. Report it instead of adding the declaration silently.

## Procedure Verification

Compile success is not enough. Run the worker tests for success, retryable
failure, permanent failure, cancellation, and duplicate enqueue, and state the
manual checks for process death, network loss, and logout.

## Procedure Report

Name the mechanism and why, the unique-work or idempotency policy, the retry
classification, and the verified vs remaining lifecycle paths.

## Mechanism Selection

- Detect the repo's existing convention first: an existing worker base class,
  scheduler wrapper, unique-work naming scheme, or upload manager wins over the
  defaults below.
- **WorkManager** for deferrable, durable work that must survive process death.
  Use unique work with an explicit existing-work policy (keep, replace, or
  append) chosen for what a second request means to the product.
- Declare constraints (network type, charging, storage) on the request instead
  of checking them inside the worker and returning success.
- Use expedited work only for short, user-initiated work that must start
  promptly, and handle the quota fallback.
- **Foreground service** only when user-visible ongoing work cannot be deferred
  (for example active playback or an ongoing call). Declare the matching
  foreground service type and permission, and show a notification the user can
  act on. For long-running WorkManager work, prefer the worker's own foreground
  support over a separate service.
- **Owned coroutine scope** for work that may end with its screen or
  ViewModel. It is not durable; do not rely on it for uploads or sync.
- Exact alarms only for user-facing, time-critical events, and only with the
  permission and fallback the platform version requires.
- Keep background work behind a use case or worker boundary, not inside
  composables.
- Persist enough progress to recover after process death, but avoid storing
  sensitive payloads.

## Survival Checks

- What starts, cancels, retries, and observes this work?
- What happens on a second enqueue while the first run is pending or running?
- Can the job run twice without duplicate server effects? Name the unique work
  name or idempotency key.
- Which failures return retry (transient: timeout, network loss, server
  unavailable) and which return failure (permanent: validation, rejected
  request, missing input)? Is backoff set?
- What happens across rotation, process death, logout, account switch, and
  network loss? Is work for the old account cancelled?
- Does the user see progress, failure, and recovery actions?
- Are Doze, battery saver, metered network, app standby, and notification
  permission (a runtime permission on newer platform versions) respected?
- Are notifications clear, permission-aware, and free of private content?
- Are files, cursors, players, observers, and temporary files released on
  every exit path? See
  [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md).
- Does any blocking IO run on the main thread? See
  [runtime-performance.md](../../android-review/references/runtime-performance.md).

## Do Not

- Do not start durable background work directly from a composable, View, or
  screen callback without a worker/use-case boundary and duplicate policy.
- Do not use a foreground service for polling, sync, or upload work that can be
  modeled as deferrable WorkManager work.
- Do not enqueue jobs that can run twice without idempotency keys, unique work,
  dedupe state, or server-side duplicate handling.
- Do not auto-retry a non-idempotent call.
- Do not swallow a worker exception and return success; classify it.
- Do not store raw credentials, private payloads, or personal data in worker
  input, notifications, progress rows, or logs unless the repo has an accepted
  secure-storage design.
- Do not ignore notification permission, Doze, battery saver, metered network,
  app standby, logout, or account switch because the happy path worker test
  passes.

## Tests

Cover worker success, retryable failure, permanent failure, cancellation,
duplicate enqueue policy, and auth/session changes during work when applicable.
Use the WorkManager test helpers (a test driver or a synchronous executor) when
the repo has them, and list the process-death and network-loss checks that
remain manual.
