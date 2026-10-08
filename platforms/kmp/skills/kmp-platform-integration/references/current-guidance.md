---
keyflow_id: sys_kmp_platform_integration
status: review
type: human-reviewed-needed
---

# KMP Platform Integration

Use when Kotlin Multiplatform work touches source sets, `expect`/`actual`,
native interop, platform services, files, shell/process execution, clipboard,
notifications, permissions, secure storage, background work, or app lifecycle.

For source-set hierarchy, shared module splits, and umbrella framework shape,
also use `platforms/kmp/skills/kmp-module-structure/SKILL.md`.

## Adapter Choice

Prefer the smallest boundary that keeps shared code honest:

| Boundary | Use When |
| --- | --- |
| Interface injection | The behavior needs fakes, multiple implementations, or dependency inversion. |
| `expect`/`actual` function or class | The API is small, stable, and truly target-specific. |
| Target source-set wrapper | The behavior belongs only to one target UI or shell. |
| Capability object | Some targets support the action and others must disable or explain it. |

Do not use `expect`/`actual` as a dumping ground for large services. Large
platform behavior is usually easier to test behind an interface.

## App Wiring

Target app entry points should be thin composition roots:

- Android starts platform DI and renders the shared app from the Activity or app
  shell while keeping Android lifecycle, permissions, splash, notifications, and
  intent/deep-link handling in Android source sets.
- iOS wraps the shared Compose entry through the Swift/UIViewController bridge
  and keeps signing, entitlements, push notification setup, and native lifecycle
  code in the iOS app target.
- Desktop starts the shared app from the desktop main/window owner and keeps
  tray/menu, file dialogs, process, shortcuts, and packaging concerns in desktop
  source sets.
- The shared app module may own theme, top-level navigation composition,
  state-holder wiring, and feature entry registration, but platform entry
  points own platform services and app lifecycle.
- Load dependency modules in an intentional order: core/platform adapters first,
  data implementations next, feature presentation/state owners next, and app
  overrides last. Do not make feature modules start global DI on import.

## Platform Adapter Patterns

- HTTP engines, database builders, DataStore/settings file paths, secure
  storage, permissions, connectivity, push notifications, clipboard, file
  pickers, and WebSocket/native callbacks should be exposed through small
  contracts with target implementations.
- Platform-specific debug tools, such as HTTP inspectors, belong only in debug
  source sets or debug dependencies and must have a release no-op or disabled
  path.
- Platform config files such as Android service JSON, Apple plist files,
  keystores, provisioning profiles, and signing config stay out of shared source
  and are handled by repo-local config or secret-store policy.
- Native callbacks and listeners must use structured ownership. `callbackFlow`
  or equivalent bridges need `awaitClose`/dispose cleanup and safe error
  mapping.

## Rules

- Every actual implementation must satisfy the same contract or return an
  explicit unsupported result.
- Platform adapters validate external inputs from files, URLs, shell output,
  clipboard, platform callbacks, notifications, permissions, and native APIs.
- Long-running adapters need cancellation, timeout, progress, retry policy, and
  cleanup on failure, cancellation, logout, app quit, or lifecycle teardown.
- File paths, environment variables, process execution, native handles, and
  credentials must not leak into shared models or user-safe errors.
- Keep platform resource ownership explicit: windows, monitors, jobs, file
  watchers, sockets, callbacks, notification listeners, and native pointers need
  an owner and release path.
- Add target-specific tests or smoke checks when actual implementations, Gradle
  targets, packaging, permissions, or native interop changed.

## Release And Packaging Checks

- Android release checks must cover minification/shrinking rules for
  serialization, database, DI, networking, generated config, and any reflection
  or codegen used by the repo.
- iOS checks must cover framework export shape, Swift surface compatibility,
  bundle id, signing, provisioning, associated domains, and native dependency
  setup when touched.
- Desktop checks must cover native distribution packaging, app identifiers,
  signing/notarization when required, file path policy, and update channels when
  present.
- Build cache, configuration cache, and convention plugins are build-time
  optimizations, not correctness proof. Release artifacts still need target
  smoke checks.

## Stop If

- A target cannot support required behavior and the product has no fallback,
  disabled state, or acceptance decision.
- The change requires credentials, signing, entitlements, release packaging, or
  external service setup that is not present in repo-local docs.
- A platform adapter would need to print, persist, or expose secrets to make the
  feature work.

## Verification

- Run compile/test tasks for affected source sets and app targets.
- Exercise unsupported-target behavior, permission denial, cancellation, and
  cleanup when they are reachable.
- Review the final diff for accidental broad platform API exposure in
  `commonMain`, silent no-op actuals, missing cleanup, and private detail in
  logs or user-visible errors.
