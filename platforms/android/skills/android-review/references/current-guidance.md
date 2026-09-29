---
keyflow_id: sys_775cd6266968
status: review
type: ai-generated
---

# Android Review

Read for every Android app, Compose/ViewModel, permission, background, and UI
flow review. [The review card](../SKILL.md) owns the order; this file holds the
checklist, the finding format, the completion gate, and the tools.

## Finding Format

Write every finding in this shape:

```text
Requirement: <the requirement or rule this change must satisfy>
Risk: <where the changed code departs from it, with file:line>
Failure scenario: <the concrete input, state, or transition that breaks>
Fix direction: <the smallest owner-boundary change that removes the risk>
```

Exclude comments based on taste, speculative future extensibility, and
refactors outside the requirement. A finding without a failure scenario is not
a finding.

## Lifecycle And Performance

- Run the [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md)
  Steps for every changed listener, receiver, launcher, effect, Flow
  collection, coroutine scope, WebView, player, Bitmap, stream, or foreground
  notification. Each needs an owner and a cleanup path on dispose, failure,
  cancellation, and owner end. A `LaunchedEffect` collect with no lifecycle
  gate is a finding unless it meets the documented STOPPED-receive exception
  in [android-memory-lifecycle](../../android-memory-lifecycle/references/current-guidance.md);
  `GlobalScope` in production code, or `runBlocking` outside that card's
  documented exception, is a finding.
- Run the [runtime performance](runtime-performance.md) classification for
  every change that claims or affects performance: main-thread work, startup,
  duplicate network calls, cache freshness and invalidation, media/WebView
  cost, dependency size, or build time. Do not accept broad refactors,
  dependency additions, or framework migrations as performance fixes without
  reproduction or measurement evidence.
- For Compose recomposition, stability, and lazy-list cost, apply
  [compose-performance.md](../../android-compose-ui/references/compose-performance.md).

## Review Checklist

- Check Compose state hoisting, ViewModel ownership, and stateful holder vs
  stateless screen/component boundaries.
- Check ViewModel, `UiState`, Flow, repository, and one-off event boundaries
  against [android-viewmodel-state](../../android-viewmodel-state/SKILL.md)
  when state or data changed.
- Check Compose-observed `UiState` and UI display models for truthful
  `@Immutable`/`@Stable` contracts, immutable collections, stable defaults, and
  absence of mutable/platform/repository objects.
- Check advanced stability opt-ins such as strong skipping configuration,
  stability configuration files, compiler metrics, and `@NonSkippableComposable`
  annotations for measured need and documented contracts.
- Check module/package boundaries against
  [android-module-structure](../../android-module-structure/SKILL.md) when new
  modules, package moves, API contracts, build logic, or repository splits are
  touched.
- Reject package/module splits that lack a boundary note naming owner, allowed
  imports, forbidden imports, callers, and focused verification. A package split
  that only creates one folder per type, mirrors a reference app, or moves files
  without changing dependency direction is structure churn, not architecture.
- For `api` / `impl` / `assertions`, verify that `api` exposes caller-facing
  contracts only, `impl` owns execution details, and `assertions` depends on
  `api` rather than production `impl` by default.
- Check design-system ownership when shared UI changes: tokens, wrappers,
  defaults, and accessibility contracts belong there; product copy, routes,
  analytics, permissions, fake data, and repository calls do not.
- Apply the canonical preview rule in
  [compose-previews.md](../../android-compose-ui/references/compose-previews.md)
  to changed renderable composables.
- Verify loading, empty, error, permission-denied, and offline states.
- Ensure repository/data source boundaries are not bypassed from UI.
- Check permission, activity result, navigation argument, and process
  recreation behavior.
- Confirm secrets and user data are not logged.
- Check WorkManager, foreground service, notification, and retry behavior
  against [android-background-work](../../android-background-work/SKILL.md)
  when background work is touched.
- Review exported components, nested intent redirection, `onNewIntent` handling,
  dynamic receivers, ContentProvider grants/queries, bound service caller
  verification, WebView bridges, `PendingIntent` mutability, and cleartext
  traffic against [android-security](../../android-security/SKILL.md) when
  security surfaces change.
- When the change touches AGP, R8, Perfetto, XML-to-Compose migration,
  adaptive layouts, edge-to-edge, Android CLI/device tooling, intent security,
  Compose Styles, CameraX, Credential Manager verified email, Play Billing,
  Play Engage, Wear Compose Material3, XR/Glimmer, testing setup, or
  AppFunctions, confirm the source-specific guidance from
  [external source coverage](../../android-external-skill-source-coverage/references/current-guidance.md)
  and [source-coverage](../../source-coverage/SKILL.md) was applied before
  accepting the implementation.
- When a call is moved onto a contract whose delivery depends on a host component
  installed by a base class — user-visible notices, screen-navigation dispatch, and
  similar app-wide contracts — name the base class each touched screen extends and
  confirm that screen installs the host. Several contracts often share one host, so a
  screen has all of them or none; checking one contract does not clear the others.
- Treat contracts that enqueue and return as silent on failure. A missing host makes
  the call a no-op with no exception, so unit tests and static analysis stay green.
  A change of that shape is not verified until the affected transitions are exercised
  on a device or emulator.

## Completion Gate: External State And Persisted Data

A change in any of these categories is not complete on a normal compile or a
unit-test pass alone:

- auth, session, permission, or privacy behavior
- persisted data, cache, database schema, or migration
- file upload, download, or media publish
- notification or background retry behavior
- release signing or build configuration

For each, leave evidence of at least one of: a dry run, a focused local check
of the changed transition, an explicit approval, or a stated rollback or
idempotency path. Network writes and file writes name what happens when the
operation runs twice or fails halfway. If automated verification is not
possible, write the manual scenario concretely and report the residual risk.

## Tools

- Static: Gradle lint, `ktlint` or `ktfmt` for formatting, and `detekt` for
  naming, complexity, size, and maintainability when configured. If the repo has
  no tool config, review against the strict static quality profile in
  [code-conventions](../../../../../common/skills/code-conventions/SKILL.md) and
  document the missing automation.
- Unit: JVM tests for mapper, validator, policy, ViewModel state.
- Instrumented: AndroidJUnitRunner for framework-dependent behavior.
- UI: Compose UI Test or Espresso for screen interactions.
- Screenshot: Paparazzi or screenshot tests if the repo uses them.
- Device observation: the host-driven device MCP in
  [device-mcp.md](../../../../../common/skills/local-tools/references/device-mcp.md)
  for a running screen — screenshot and UI hierarchy from the built app, and
  the taps, swipes and text entry that reach a state the other tools cannot
  reach. Reach for it from the diff, not from the request's wording: a change
  to a rendered surface — Compose screen or component, drawable, theme or
  token, animation or transition, insets — is what makes device evidence the
  check, and asking the user to say "on a real device" first is not a
  precondition. Preview, unit and screenshot tests stay the cheaper first
  checks and settle most of these; the device answers what they cannot — the
  assembled screen in the app, with real data, insets and navigation.
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
- Stateless UI preview coverage follows the canonical preview rule in
  [compose-previews.md](../../android-compose-ui/references/compose-previews.md).
- UI tests verify product interactions dispatch typed actions to the ViewModel.
  ViewModel tests verify the resulting network calls and route/toast/alert port
  requests, including alert confirmation/cancellation. A successful navigation
  smoke test alone does not prove this ownership boundary.
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

## Executable Action Boundary

The shared `scripts/agent-structure-check.py` and review hook reject recognizable
ViewModel bypasses in changed production Kotlin composables. A textual review
attestation cannot override these failures. Send product actions to the ViewModel;
do not silence a finding by renaming a callback or moving it to a UI helper.

The lexical check catches route/notice request constructors and singleton
references, conventional data service calls, direct navigation/notice/platform
dispatch, and known effect
callback forwarding. Direct dispatch is allowed in a `viewModel.effects`
collector (also explicitly ViewModel-typed parameters, `*ViewModel`, `uiEffects`,
and `sideEffects`), except inside a nested UI callback. The host must still
collect lifecycle-aware and execute only
the ViewModel's decision. Local scroll, focus and backdrop rendering are allowed.
Declared zero-argument leaf callbacks may be invoked or forwarded; their names
alone do not establish an effect decision. Review their holder mapping to actions.

This is a bounded guard, not Kotlin type or data-flow analysis: aliases of
receivers, arbitrary helper names, string interpolation, and indirect calls may
escape detection. Collection naming alone does not prove ownership or lifecycle
correctness. Review the UI callback → action → ViewModel → effect/data-port path
and retain tests for both the action and its effect. Existing untouched files
are outside the changed-file check. Do not claim an architecture migration is
complete solely because this check or a build passes.

## Structure Review Hook Evidence

These rules apply when the Tao structure review hook reports a package or owner
finding on the change. They govern hook evidence, not product behavior, and do
not replace the lifecycle, performance, state, or security findings above.

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
- A wrapper insertion can re-indent a large lifecycle body without adding a new
  responsibility. Before treating that whitespace churn as structural growth,
  compare the block with whitespace ignored and measure its final span. When
  the semantic diff is only the wrapper boundary, use that measured span as the
  smallest `--max-function-lines` exception and name both the wrapper and the
  unchanged responsibility in the structure review evidence.
