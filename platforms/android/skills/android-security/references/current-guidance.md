---
keyflow_id: sys_android_security
status: review
type: ai-generated
---

# Android Security

Use when Android work touches credentials, local storage, IPC, deep links, WebView, permissions, exported components, or release builds.

Also use `common/skills/secure-development-baseline/SKILL.md` for shared secret handling,
authorization, logging, diagnostics, and open-source repository safety rules.
Use `common/skills/runtime-url-configuration/SKILL.md` for environment-specific API origins,
deep link hosts, app link hosts, redirect/callback URLs, asset hosts, and
release-channel config.

For exported components, nested intents, `PendingIntent`, ContentProvider,
dynamic receiver, Credential Manager, verified email, WebView credential flows,
or bound-service caller validation, also use
`android-external-skill-source-coverage.md` and start with the official
`android/skills` `security/android-intent-security/SKILL.md`.

## Rules

- Store secrets with Android Keystore-backed storage or an accepted repo-local secure storage wrapper.
- Do not store access tokens, refresh tokens, private keys, or sensitive user data in plain SharedPreferences, logs, screenshots, or crash payloads.
- Keep local developer keys in ignored files such as `local.properties` or the
  repo-approved local config path; keep CI/release keys in the CI secret store.
- Treat `BuildConfig`, resources, manifest placeholders, assets, and generated
  config files as client-visible. They can hold restricted client keys, not
  server-only secrets.
- Put environment-specific API origins, callback URLs, app link hosts, and asset
  hosts in product flavors, manifest placeholders, generated resources, or the
  repo-approved config path instead of source literals.
- Restrict Android client keys by package name, signing certificate fingerprint,
  quota, API scope, or provider-specific controls when available.
- Treat Credential Manager and verified-email credentials as client-side
  assertions until backend validation succeeds. Non-`@gmail.com` verified-email
  claims may need a freshness challenge when the source flow says no freshness
  claim is available.
- Treat `Activity`, `Service`, `Receiver`, and `Provider` export settings as security boundaries.
- Explicitly set `android:exported="false"` for components that do not need
  inter-app entry. When a component must be exported, pair the export with a
  narrow manifest permission, signature-level permission, caller validation, or
  documented public contract.
- Validate deep links and app links before using embedded IDs, tokens, or redirect targets.
- Use explicit intents for sensitive flows and check `PendingIntent` mutability.
  Prefer immutable `PendingIntent` by default; require an explicit target and a
  documented reason when mutability is needed.
- Treat nested intents, `onNewIntent`, app links, custom schemes, and
  externally supplied extras as untrusted input. Sanitize or whitelist the
  action, component, data URI, categories, MIME type, flags, and extras before
  launching or trusting them.
- Apply the same intent validation in `onNewIntent` that `onCreate` uses, and
  update the Activity's current intent before processing the new payload.
- Prefer AndroidX `IntentSanitizer` when available for nested or redirected
  intents. If sanitizer support is unavailable, verify same-package or
  explicitly allowed targets, exported status, action/data/type/categories, and
  reject unexpected URI grant flags before launching.
- Protect exported services, receivers, and providers with the narrowest
  manifest permissions, caller validation, signature checks, or explicit
  non-exported configuration that the behavior allows.
- For custom broadcasts, prefer non-exported dynamic receivers or
  signature-level permissions. Do not use sticky broadcasts for sensitive state.
- For exported bound services, verify the caller UID/package signature inside
  sensitive binder transaction methods, not only during `onBind`.
- Keep `ContentProvider` projections, selections, sort orders, and URI grants
  constrained; do not pass caller-controlled SQL fragments or broad file URI
  grants through unchecked.
- Set internal providers non-exported. For exported providers, require
  read/write permissions, keep URI grants disabled unless the flow explicitly
  needs temporary grants, and parameterize selections instead of concatenating
  caller-controlled query strings.
- Keep WebView JavaScript bridges narrow, typed, and unavailable to untrusted content.
- For reusable WebView surfaces, define the allowlisted origin policy, JavaScript
  enablement, mixed-content policy, file/content access policy, external-browser
  fallback, and bridge availability before sharing the component across Activity
  and Compose wrappers.
- Do not let arbitrary server content enable a JavaScript bridge. Bind bridges
  only for trusted origins and keep bridge methods typed, minimal, and free of
  secrets, tokens, raw files, and direct navigation execution.
- Gate feature-dependent platform APIs on the explicit support check — a
  feature-availability API or OS version check — before calling them.
  Unsupported paths must degrade explicitly and observably: disable the
  capability and leave a diagnostic, never silently skip, and never auto-fall
  back to a known-unsafe legacy API (such as a raw JavaScript interface when a
  typed message-listener API is unsupported). Do not leave capability or
  API-level lint warnings bare; resolve them with a support gate, or when an
  invariant guarantees safety, isolate that logic in a helper and document the
  reason in a one-line comment next to a narrow suppression.
- Use a dedicated shared HTTP client for transfers against foreign domains —
  presigned URLs, CDNs, or any host that is not the app backend. Do not reuse
  the app-backend client: its auth, refresh, and availability interceptors
  leak app tokens to third-party domains and misinterpret file responses as
  backend states. Qualify one client per purpose, and never construct a new
  client per call site — each instance gets its own connection pool and
  threads, and timeout policy drifts.
- Prefer platform photo picker and scoped storage over broad file permissions.
- Keep cleartext traffic disabled unless the repo documents an accepted debug-only exception.

## Check

- Which Android component can receive this intent or data?
- Can another app trigger the action, read the file, or intercept the token?
- Is every exported component intentionally exported and guarded by permission,
  signature check, caller validation, or a public contract?
- Are nested intents, `onNewIntent` payloads, app links, custom schemes,
  dynamic receivers, and `PendingIntent` targets validated on every entry path?
- Does a Credential Manager or verified-email flow have server-side validation,
  freshness handling, and a safe fallback for unsupported account types?
- Can a provider query request unauthorized columns, inject selection grammar,
  or receive broad URI grants?
- Does permission denial have a user-visible and recoverable state?
- Are secrets excluded from logs, analytics, crash reports, notifications, and clipboard?
- Do release builds keep signing keys, API secrets, and debug endpoints out of the client?
- Do release builds use the intended API origin, callback URL, app link host,
  asset host, and provider app registration for that environment?

## Tests

Cover permission denied, revoked permission, malicious or malformed deep link,
nested intent redirection, `onNewIntent` warm-entry validation, mutable
`PendingIntent` target behavior, provider query constraints, exported service
caller rejection, process recreation after auth state change, safe degradation
of capability-gated APIs on unsupported providers or OS versions, and
release-build configuration when applicable.
