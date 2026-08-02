---
keyflow_id: sys_error_modeling
status: stable
type: human-reviewed-needed
---

# Error Modeling

Use when designing, handling, mapping, logging, retrying, or displaying errors.

Error handling is part of the product contract. A failure should be traceable by
engineering, understandable by the user when visible, and safe for data,
security, privacy, and retries.

## Error Layers

Keep these layers separate:

```text
raw exception / transport failure
-> boundary error
-> domain failure
-> user-visible state/message
-> diagnostic log/metric/audit event
```

- Raw exceptions stay near the boundary that produced them.
- Boundary errors describe API, database, filesystem, platform, SDK, or network
  failure in typed form.
- Domain failures describe product meaning such as denied, unavailable,
  conflict, quota exceeded, invalid state, or not found.
- User-visible messages explain what happened and what the user can do next.
- Logs and metrics support debugging without leaking sensitive data.

## Async API Boundary

For async HTTP/API clients, prefer the language's normal success/failure
mechanism before inventing a result wrapper for every call:

```text
success -> return decoded value or normalized response
failure -> throw/raise a typed transport, protocol, or domain error
```

Use a `Result`, sealed `Success/Failure`, or equivalent response wrapper only
when failure is an expected value that most callers must compose, store, merge,
or partially render. Do not wrap every suspend/async API response in
`Success/Failure` only to re-express exceptions; it pushes unwrapping and
`when`/`switch` boilerplate into every caller.

Network adapters should normalize library-specific values only far enough to
hide the transport library:

```text
SDK/HTTP library response -> internal HttpResponse
SDK/transport exception -> typed transport exception/error
non-2xx response -> API/protocol exception/error with safe response metadata
```

Keep `OkHttp`, `Retrofit`, `Ktor`, `URLSession`, `fetch`, provider SDK
exceptions, raw response handles, and framework-specific cancellation details
behind the boundary that owns that library. Preserve status, headers needed for
policy, safe server error code, request/correlation id, retry metadata, and the
cause type where useful.

State owners such as ViewModels, reducers, stores, coordinators, or server
actions should catch typed failures and decide the user-visible state or effect
for the current workflow.

## Typed Shape

Prefer typed errors, result objects, or sealed failure models with fields such as:

```text
code
category
retryable
recoverable
status / transport status
field errors
correlation id
safe message key
cause
```

Do not rely on string matching unless the upstream API leaves no alternative;
if string matching is unavoidable, isolate it in one adapter and test it.

## Retry And Recovery

Classify failures before retrying:

- Retryable: timeout, temporary unavailable, rate limit with backoff, transient
  network loss.
- User-recoverable: invalid input, missing permission, expired session, conflict,
  quota exceeded.
- Non-retryable: forbidden, unsupported operation, validation impossible, missing
  required resource.
- Dangerous to retry: payment, destructive mutation, duplicate message, external
  side effect without idempotency.

Retries need idempotency, backoff, cancellation, duplicate handling, and a stop
condition.

## Handling Rules

- Do not swallow errors silently.
- Do not convert failure into success to make a command, UI path, or test pass.
- Preserve the cause when wrapping or mapping errors.
- Map boundary failures once at the boundary; do not duplicate mapping in every
  caller.
- Keep user-facing copy out of low-level error types when the repo has i18n or
  copy ownership.
- Never log secrets, tokens, credentials, private prompts, raw personal data, or
  full request/response bodies unless the repo explicitly permits redacted logs.
- If an error is intentionally ignored, keep the scope narrow and document why it
  cannot affect correctness, data integrity, security, billing, permissions, or
  user-visible completion.
- Global-policy failures have one global owner. Session expiry (401),
  maintenance mode, and auth refresh belong to the existing global handler such
  as an interceptor, authenticator, or app-level block state. Screens must not
  add per-screen branches for these failures or route them through local
  notices. Review checks that new error handling does not bypass the global
  owner.

## UI Failure States

User-visible failures should choose an explicit state:

```text
inline field error
blocking empty/error state
retryable banner/snackbar
permission denied state
offline/stale-content state
conflict resolution state
silent best-effort fallback
```

Silent fallback is acceptable only when the feature still satisfies the user goal
and diagnostics exist for unexpected failure.

## Success-Status Payload Violations

A success-status response with a missing required field, a required field that
is null, a type mismatch, or an unknown enum value is a contract violation, not
a success. Do not paper it over with silent defaults:

- Normalize it into the typed boundary failure and preserve the cause.
- Choose a fallback that matches the screen goal: keep existing content, show a
  default empty/error state, or offer a retry notice. User-facing copy is
  feature copy, never the low-level exception message.
- A fallback must not let dependent actions proceed on missing or invalid
  required data. Disable the action or enter an explicit blocked state instead
  of letting a submit or navigation run against defaults.
- Emit deduplicated diagnostics for repeated violations on the same
  endpoint/field, using a safe field allowlist: endpoint or API identifier, DTO
  name, field path, reason, status code, request/correlation id, cause class,
  and app version. Never include the raw body, tokens, cookies, headers, or
  full user input.

## Server-Driven Presentation Hints

When several clients share one server API, the server may include stable,
client-safe presentation and recovery hints in an error envelope, such as:

```text
code
message key or safe fallback message
presentation hint: inline, toast/banner, alert/dialog, full page
action label key
deep link or route intent
retryable / retry-after
request or correlation id
```

Treat these as a contract, not as arbitrary UI commands. The client still owns
the final mapping to platform controls, accessibility behavior, navigation
rules, localization, and whether the hint is appropriate in the current screen.
Use enums, message keys, deep links, route intents, and allowlisted actions
instead of server-provided component names, executable commands, raw HTML, or
client-specific class names.

Document which errors may carry presentation hints, which clients must honor
them, what the fallback is when a client does not support a hint, and whether the
action is safe to retry or can duplicate a side effect.

## Review Checklist

- Where is the raw failure converted into a typed error?
- Is the error retryable, recoverable, or terminal?
- Can retries duplicate side effects?
- What does the user see?
- What can support or engineering trace?
- Are sensitive values excluded from logs, analytics, crash reports, and audits?
- Are tests covering denied, invalid, timeout, stale, and conflict paths when
  relevant?
