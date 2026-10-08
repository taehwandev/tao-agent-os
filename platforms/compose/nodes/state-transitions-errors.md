---
keyflow_id: sys_compose_node_state_transitions_errors
status: review
type: ai-generated
use_when: Writing or reviewing state holder transitions, failure mapping to UI, retry or recovery behavior, or bridging Compose state into the state holder.
skip_when: The change neither writes state after suspension nor handles a failure, retry or recovery path.
---

# Compose State Transitions And Errors

The state holder is an Android ViewModel, or a plain class with an injected
`CoroutineScope` on Compose Multiplatform desktop.

## Rules

State transitions operate on the freshest state:

- Transition on the parameter inside `update { state -> ... }`. Pure helpers
  take the current state and return the next state instead of reading the
  backing `MutableStateFlow` value.
- After any suspension (network, notice result, route result), re-check the
  latest state inside `update { }`, or guard the write with a request token,
  job cancellation/replacement, or a latest-only operator such as
  `flatMapLatest`.
- Cancel or replace in-flight work when query, account, permission or route
  arguments change, and suppress results from older requests.

Error layering: the data or API boundary turns transport, HTTP and parsing
failures into typed failures; the repository or use case adds domain meaning;
the state holder alone decides what the user sees. Follow the repo's result
type and branch with an exhaustive `when`; with no convention, return values
on success and throw typed failures normalized at the API boundary.

| Failure | Default UI | Retry |
| --- | --- | --- |
| Initial load failed, nothing to show | full-screen error state with retry | user-triggered |
| Refresh or paging failed, content shown | keep content, banner or snackbar with retry | user-triggered |
| Submit or save failed | keep the draft, inline or snackbar error, re-enable submit | user-triggered |
| Validation failed | inline field error from a typed validation value | none; fix input |
| Offline | offline state or banner; queue only safe-to-replay work | on reconnect, when idempotent |
| Session expired or unauthorized | the app's re-auth route, not a screen-local message | after re-auth |
| Permission denied | permission-denied state with the settings path | on grant |

Retry classes:

| Class | Examples | Automatic retry |
| --- | --- | --- |
| Transient | timeout, 5xx, connection lost | bounded backoff, only when idempotent (a read, or a write with an idempotency key or server dedupe) |
| Permanent | 4xx other than auth, validation, not found | never; show the state, let the user change something |
| Unknown | unclassified | treat as permanent; offer manual retry |

- A silent fallback (empty list, cached value, default) is allowed only when
  the product treats the data as optional and the failure is logged with its
  cause; otherwise the failure is visible.
- Notice-only surfaces such as toasts cannot own actions; use a snackbar,
  banner, dialog or full-page error when the user needs retry, dismiss or
  confirm/cancel.
- Server presentation hints (banner, alert, full page, retry, none, deep link)
  are API contract hints the holder maps to state or effects after validating
  the current screen context. `none` suppresses only the user-visible effect.
- Recovery actions (retry, refresh, re-auth return, reconnect) are idempotent:
  a second trigger while the first is in flight is ignored or replaces it and
  never duplicates a write or an effect.
- Turn Compose state (scroll position, text field state, visible item) into
  holder input with `snapshotFlow` collected in an effect keyed by its owner,
  then send typed actions.

## Do Not

- Do not read the state into a local, suspend, and write the stale snapshot
  back.
- Do not catch and drop an exception, or log it and continue as if it
  succeeded.
- Do not turn a failure into a success value (empty list, `false`, a default
  object) the UI cannot tell apart from real data.
- Do not lose the cause: keep the original exception for logging when mapping
  to a typed failure.
- Do not convert `CancellationException` into a user-visible error.
- Do not auto-retry a write that is not idempotent.
- Do not add `getOrThrow()` or a parallel exception path beside an existing
  result type, or invent `Success/Failure` wrappers only to re-wrap exceptions.
- Do not let composables inspect exceptions, raw server envelopes or transport
  responses, or read Compose `State` inside the state holder.

## Verification

- Tests cover each failure row the screen can reach, retry, stale-result
  suppression after an argument change, and a double-triggered recovery action.
- A test proves cancellation is not shown as an error.
- Review the diff for empty catch blocks, success-valued failures and writes
  of a snapshot captured before a suspension point.
