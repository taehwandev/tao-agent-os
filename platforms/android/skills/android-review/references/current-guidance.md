---
keyflow_id: sys_775cd6266968
status: review
type: ai-generated
---

# Android Review

Use for Android app, Compose/ViewModel, permission, and UI flow review.

## Review

- Check Compose state hoisting, ViewModel ownership, Flow collection, and lifecycle safety.
- Check platform or heavy resource ownership: listeners, receivers, WebView,
  media players, bitmaps, file handles, and foreground notifications should
  have a matching cleanup path on dispose, failure, cancellation, and owner end.
- Check ViewModel, `UiState`, Flow, repository, and one-off event boundaries
  against `android-viewmodel-state.md` when state/data changed.
- Check Compose-observed `UiState` and UI display models for truthful
  `@Immutable`/`@Stable` contracts, immutable collections, stable defaults, and
  absence of mutable/platform/repository objects.
- Check advanced stability opt-ins such as strong skipping configuration,
  stability configuration files, compiler metrics, and `@NonSkippableComposable`
  annotations for measured need and documented contracts.
- Check performance changes for the actual bottleneck category: Compose
  recomposition, main-thread work, startup, duplicate network calls, cache
  freshness, media/WebView cost, dependency size, or build-time cost. Do not
  accept broad refactors, dependency additions, or framework migrations as
  performance fixes without reproduction or measurement evidence.
- Check stateful holder vs stateless screen/component boundaries.
- Check module/package boundaries against `android-module-structure.md` when new
  modules, package moves, API contracts, build logic, or repository splits are
  touched.
- Reject package/module splits that lack a boundary note naming owner, allowed
  imports, forbidden imports, callers, and focused verification. A package split
  that only creates one folder per type, mirrors a reference app, or moves files
  without changing dependency direction is structure churn, not architecture.
- Even without a new package split or move, when a changed package is detected
  as carrying multiple roles together, write the structure review evidence with
  all of the labeled fields `owner`, `allowed imports`, `forbidden imports`,
  `callers/tests`, and `verification`. Recording only "no new boundary" is not
  evidence that the existing mixed-responsibility boundary was reviewed.
- Before merging files to satisfy a package ratchet, count the non-private
  top-level owners in the target file first. If the merged result would exceed
  the structure review limit (default 4), do not push code into a catch-all
  file; keep it in the existing owner file that directly supports its single
  caller, or choose a purpose-named split at a real responsibility boundary.
  Do not treat a package file-count audit pass and a file owner-count pass as
  interchangeable conditions.
- Do not extract a cohesive Compose renderer for the same card or screen into a
  separate file only to satisfy the owner count. If a newly added
  label/resource mapper or test seam pushed the file over the limit, keep that
  seam with its existing single-caller owner and verify it in that owner's
  named test instead of splitting the renderer. Create a purpose-named split
  only when a genuinely independent state, contract, or platform responsibility
  appears.
- When reviewing a surgical change that corrects only a few lines inside an
  existing oversized Activity/Fragment lifecycle method, first check whether
  the change grew the block or added a responsibility. If it did neither and
  the full refactor is outside the current scope, pass the smallest
  project-specific `--max-function-lines` value that accommodates the current
  block length before running the review hook, and record that judgment in the
  structure review evidence. Never use the raised limit to hide existing debt
  or admit new oversized owners; if the block grew or a responsibility was
  added, split the responsibility instead of raising the limit.
- For `api` / `impl` / `assertions`, verify that `api` exposes caller-facing
  contracts only, `impl` owns execution details, and `assertions` depends on
  `api` rather than production `impl` by default.
- Check design-system ownership when shared UI changes: tokens, wrappers,
  defaults, and accessibility contracts belong there; product copy, routes,
  analytics, permissions, fake data, and repository calls do not.
- Apply the canonical Compose preview rule from
  `../../android-compose-ui/references/current-guidance.md` when reviewing
  stateless UI previews.
- Verify loading, empty, error, permission-denied, and offline states.
- Ensure repository/data source boundaries are not bypassed from UI.
- Check permission, activity result, navigation argument, and process recreation behavior.
- Confirm secrets and user data are not logged.
- Check WorkManager, foreground service, notification, and retry behavior when background work is touched.
- Review exported components, nested intent redirection, `onNewIntent` handling,
  dynamic receivers, ContentProvider grants/queries, bound service caller
  verification, WebView bridges, `PendingIntent` mutability, and cleartext
  traffic when security surfaces change.
- When the change touches AGP, R8, Perfetto, XML-to-Compose migration,
  adaptive layouts, edge-to-edge, Android CLI/device tooling, intent security,
  Compose Styles, CameraX, Credential Manager verified email, Play Billing,
  Play Engage, Wear Compose Material3, XR/Glimmer, testing setup, or
  AppFunctions, confirm the source-specific Android skill guidance from
  `android-external-skill-source-coverage.md` and
  `platforms/android/skills/source-coverage/SKILL.md` and
  `android-module-structure.md` was applied before accepting the
  implementation.

## Tools

- Static: Gradle lint, `ktlint` or `ktfmt` for formatting, and `detekt` for
  naming, complexity, size, and maintainability when configured. If the repo has
  no tool config, review against the strict static quality profile in
  `common/skills/code-conventions/SKILL.md` and document the missing automation.
- Unit: JVM tests for mapper, validator, policy, ViewModel state.
- Instrumented: AndroidJUnitRunner for framework-dependent behavior.
- UI: Compose UI Test or Espresso for screen interactions.
- Screenshot: Paparazzi or screenshot tests if the repo uses them.
- Flow: Turbine or equivalent for stream behavior when configured.
- Performance: Macrobenchmark or baseline profile for startup and critical flows when configured.
- Runtime performance: trace, log timing, profiler, or focused manual evidence
  for main-thread IO, bitmap/JSON work, duplicate calls, cache invalidation, or
  media/WebView loading when those paths changed.
- Compose stability: compiler metrics, Layout Inspector recomposition counts, or
  a focused before/after manual inspection when the repo already uses those
  tools or the change targets recomposition.
- Compose performance: prefer release or benchmark variant, R8 enabled, and
  physical-device evidence for frame time, scroll, jank, startup, or baseline
  profile claims. Debug/emulator evidence must be labeled diagnostic only.
- Perfetto: schema-backed SQL, metrics-first trace review, `utid`/`upid`, and
  chain-of-evidence notes for root-cause claims.

## UI Test Focus

- Screen renders expected state from fake ViewModel/state.
- Stateless UI preview coverage follows the canonical Compose preview rule in
  `../../android-compose-ui/references/current-guidance.md`.
- User actions emit correct events or trigger expected navigation.
- Lists use stable keys/content types when items reorder, update independently,
  animate, or hold local state.
- High-frequency state reads are deferred to the smallest composable or
  lambda-based modifier that needs them, and composable bodies do not perform
  backwards writes to state they just read.
- Flow values are collected lifecycle-aware at the route/holder boundary; raw
  `Flow<T>` is not passed through leaf composable parameters.
- Side effects use the smallest lifecycle-correct API and are keyed by semantic
  inputs rather than broad `UiState` objects or stale `Unit` keys.
- Custom modifiers prefer `Modifier.Node` for new code, and `Modifier.composed`
  has a compatibility reason when introduced.
- Lazy item animations use stable keys; heterogeneous lazy lists provide
  `contentType`; expensive item allocations are not repeated inside item
  lambdas without measurement.
- Optional slots do not reserve space when absent, and reusable component APIs
  keep product policy, route decisions, and analytics in the caller.
- Permission denied and retry flows are covered.
- Rotation, process death, or lifecycle changes do not lose critical state.
- Background jobs do not duplicate side effects after retry or process death.
- Security-sensitive Android entrypoints reject malformed deep links, unsafe
  nested intents, unexpected URI grant flags, untrusted broadcast senders,
  broad provider queries, and untrusted bound-service callers.
- Platform SDK integrations name the verified source skill, installed version or
  source class, required setup, and the narrowest verification path instead of
  relying on remembered Android API behavior.
- Wear Compose Material3 changes use version-matched component samples,
  `AppScaffold`/`ScreenScaffold` structure, `TransformingLazyColumn` when
  scrolling is needed, component defaults instead of hard-coded styling, and
  Wear previews or screenshot coverage for affected states.
- Release build configuration does not expose debug endpoints, secrets, or broad exported components.
- API modules do not leak implementation dependencies, DTOs, database rows, SDK
  models, or feature implementation types.
- Shared design-system/core modules do not import feature modules or product
  policy.
