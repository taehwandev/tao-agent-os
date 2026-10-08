---
keyflow_id: sys_kmp_state_data
status: review
type: human-reviewed-needed
---

# KMP State And Data

Use when touching shared Kotlin state, coroutines, `Flow`, repositories,
persistence, sync, settings, caching, or one-off effects in a Kotlin
Multiplatform project.

For platform APIs and actual implementations, also use
`platforms/kmp/skills/kmp-platform-integration/SKILL.md`. For broader state shape rules, also use
`common/skills/state-modeling/SKILL.md` and `common/skills/error-modeling/SKILL.md`.
For repository module splits, source-set ownership, and umbrella/shared module
boundaries, also use `platforms/kmp/skills/kmp-module-structure/SKILL.md`.

## Defaults

- Shared state owners expose immutable UI state and explicit events.
- Model loading, content, empty, error, permission denied, offline, unsupported,
  and sync states explicitly.
- Keep one-off navigation, toast/snackbar, file picker, permission prompt, and
  window effects separate from persistent state.
- Repositories coordinate data sources and map platform or network failures into
  typed shared failures.
- Persistence, secure storage, settings, files, clocks, dispatchers, UUIDs, and
  network clients belong behind adapters when target behavior can differ.
- Inject coroutine dispatchers or schedulers when tests need deterministic
  execution.
- Keep target-specific lifecycle collection in target UI source sets. Shared
  state owners should expose streams without assuming Android lifecycle or a
  desktop window lifecycle.

## Offline-First Data Flow

When a feature is offline-first, choose one durable local source of truth and
make network sync update it:

```text
UI/state owner observes local Flow
repository fetches or receives network updates
repository validates and maps DTOs
repository upserts local store
local Flow emits new UI data
```

Rules:

- UI should observe local/cache flows for offline-first data, not render
  directly from one-off network responses.
- Repositories own source coordination, freshness, conflict handling, retry,
  pagination cursors, and cache invalidation.
- Network success updates the local store; network failure leaves cached content
  visible when safe and emits a typed error or sync status.
- Mutations must choose pessimistic, optimistic, or queued behavior explicitly.
  Optimistic and queued writes need rollback, conflict, duplicate, and retry
  rules.
- Connectivity observers, WebSocket clients, background sync, and retry/backoff
  handlers belong behind adapters or repositories with cancellation and cleanup.
- Local stores need schema/export ownership, migrations, corruption handling,
  logout/account-switch clearing, and stale-data policy.

## Network, Auth, And Session State

- Wrap HTTP clients behind small services or repositories. UI and domain code
  should not construct URLs, set auth headers, parse response bodies, or inspect
  transport exceptions.
- Map timeouts, unauthorized, conflict, rate-limit, no-internet,
  serialization, server, local-storage, and unknown failures into typed shared
  failures.
- Do not catch and consume `CancellationException`; rethrow it after cleanup.
- Token refresh logic must avoid refreshing on auth endpoints, clear cached
  provider tokens on logout/session expiry, and surface reauth state to the app.
- Session storage should expose a clear contract for observe, set, and clear.
  Credentials and refresh tokens require platform-appropriate secure storage or
  an explicit repo-local risk decision.
- WebSocket or streaming clients need explicit connect, send, reconnect,
  disconnect, backoff, auth refresh, and lifecycle ownership.

## Data Boundary Rules

- Version persisted data that can survive app upgrades.
- Treat cached, migrated, imported, synced, generated, or platform-provided data
  as untrusted until validated.
- Define what happens on logout, account switch, permission revoke, target
  unsupported, and offline startup.
- Keep platform DTOs, database entities, and native interop objects out of
  shared domain models unless the repo intentionally owns that contract.
- Avoid blocking I/O on UI dispatchers. Long work needs cancellation, progress,
  timeout, and user-visible failure state.

## Testing

- Use shared tests for pure domain rules, state transitions, mappers, repository
  contracts, retry/backoff logic, and typed error mapping.
- Use deterministic dispatchers or schedulers for coroutine tests.
- Use flow-testing tools or equivalent assertions for `StateFlow`, `SharedFlow`,
  `Channel`, database observation, and one-off effects when configured.
- Add platform tests or smoke checks for actual storage paths, secure storage,
  database builders, HTTP engines, permissions, connectivity, and WebSocket
  behavior when those adapters change.

## Check

- Can each target create the same initial state from equivalent inputs?
- Can process restart, app relaunch, window reopen, or target lifecycle changes
  restore the needed state?
- Are `StateFlow`, `SharedFlow`, `Channel`, callback, and suspend APIs chosen
  intentionally?
- Does each platform adapter map errors into the same shared failure contract?
- Do tests cover the shared state machine and at least one platform adapter path
  when adapter behavior changed?
- Does logout, token refresh failure, permission revoke, account switch, schema
  migration, offline startup, and reconnect produce explicit state?
