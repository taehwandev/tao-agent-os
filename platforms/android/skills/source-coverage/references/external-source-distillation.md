---
keyflow_id: sys_android_external_source_distillation
status: review
type: human-reviewed-needed
---

# Android External Source Distillation

Use this reference as the source-family router after opening the source
manifest. It distills reusable rules from the current snapshots of:

- `https://github.com/android/skills`
- `https://github.com/skydoves/compose-performance-skills`
- `https://github.com/chrisbanes/skills`

This is not a copy of those repositories. Open the matching upstream `SKILL.md`
and reference docs for implementation details. For detailed no-omission checks,
read the split maps:

- `official-android-source-map.md`: 19 official Android skill entrypoints and
  their implementation-affecting reference groups.
- `compose-performance-source-map.md`: 26 Compose performance skill
  entrypoints, including measurement, stability, recomposition, lazy layout,
  effects, modifiers, R8, and hot reload.
- `chrisbanes-source-map.md`: 18 Chris Banes Compose/Kotlin/router skills.

Local coverage is complete only when both the source manifest and the split
maps are current. A matching file count alone is insufficient.

## Official Android Skills

### Build And Toolchain

- AGP migrations are source-driven. Check the current AGP, Gradle, JDK, Kotlin,
  KSP, Hilt, Paparazzi, and BuildConfig state before editing build files. Do not
  use AGP 9 guidance for KMP projects unless the source explicitly supports it.
- For AGP 9 work, prefer Android Studio Upgrade Assistant or a documented user
  override before direct migration. Verify with IDE sync, `./gradlew help`, and
  `./gradlew build --dry-run`; avoid `clean` unless the migration guide requires
  it.
- Android CLI/device work should start from explicit SDK/device/emulator state,
  not broad filesystem search. Capture screenshots, inspect UI, and run journey
  tests through the configured Android CLI path when the repo supports it.

### Platform SDK And Product Surfaces

- Camera migrations should remove Camera1/raw lifecycle ownership and use
  CameraX lifecycle-bound use cases. Compose camera work must account for
  `SurfaceRequest`, tap-to-focus coordinate transforms, target rotation, and
  lifecycle rebinding.
- AppFunctions work must include discovery, implementation/configuration, KDoc
  refinement for agent understanding, and ADB/device verification. Do not expose
  sensitive or destructive app actions without confirmation.
- Verified email through Credential Manager is client integration only. Backend
  cryptographic validation remains required; non-`@gmail.com` freshness may need
  an additional challenge. Treat returned credential JSON as untrusted until
  parsed and validated by the accepted flow.
- Play Engage integrations require a vertical/schema decision before code
  generation. Keep generated publisher, converter, request factory, worker, and
  receiver responsibilities separated. Verify both static and dynamic receiver
  registration when that SDK requires both.
- Play Billing upgrades must infer effective legacy version from code as well
  as dependency declarations. Use a direct or stepped migration path based on
  major-version distance, then verify every version-specific checklist item.

### Navigation, Adaptive UI, And Migration

- Navigation 3 work should use typed route keys/back stacks and the relevant
  recipe for scenes, multiple back stacks, deep links, results, and Hilt/module
  boundaries. Advanced deep links need synthetic back-stack and Up behavior
  evidence.
- Adaptive Compose work assumes Compose and Navigation 3. Add or verify
  screenshot coverage across phone, foldable, tablet, and desktop-like sizes
  before changing adaptive layout. Use Navigation 3 scene strategies for
  list-detail/supporting-pane layouts when the source requires them.
- XML-to-Compose migration is one candidate at a time. Capture the old UI,
  migrate only the necessary theme surface, add a preview, compare visual
  parity, replace usages, then remove XML only after no references remain.
- Compose Styles API work is experimental and version-gated. Confirm compile SDK
  and Compose foundation/BOM versions, opt in explicitly, and apply it to custom
  design-system components only; Material component styles are out of scope.

### Security

- Intent security includes exported components, nested intent redirection,
  `onNewIntent`, custom broadcasts, `PendingIntent`, ContentProvider, and bound
  service caller identity. Use `android-security.md` for local rules and open
  upstream `security/android-intent-security/SKILL.md` for detailed checks.
- Default to non-exported components and immutable `PendingIntent`. Mutable
  `PendingIntent` requires an explicit target and reason. Nested intents require
  sanitizer or explicit component/action/data/flag validation.
- Custom broadcasts need protected system broadcasts, non-exported dynamic
  receivers, or signature-level permissions. Bound services must verify callers
  on sensitive binder transactions, not only during bind.

### Performance And Profiling

- R8 work is usually analysis/reporting before edits. Check minification state,
  R8 version, full-mode flags, keep rules, and library consumer rules. Prefer
  quantitative analyzer output when the installed R8 supports it; otherwise use
  heuristic rule review.
- Perfetto trace analysis must keep a chain of evidence. Start with metrics and
  broad queries, verify thread states before claiming CPU work, follow blocking
  dependencies, and keep searching for independent bottlenecks before final
  conclusions.
- Perfetto SQL must use schema-backed queries. Prefer standard library modules,
  `utid`/`upid`, `GLOB` or exact matches, overlap-safe interval logic,
  idempotent table/view creation, and validated execution through
  `trace_processor`.

### Edge-To-Edge, Testing, Wear, And XR

- Edge-to-edge work starts by locating Activities, lists, FABs, and text inputs.
  Add `enableEdgeToEdge` and exactly one inset strategy per container. Avoid
  double padding across Scaffold, IME, and safe drawing insets. Diverge from the
  upstream `adjustResize` manifest step: a Compose screen uses
  `Modifier.imePadding()` and `android:windowSoftInputMode="adjustResize"` stays
  XML-layout-only.
- Android test setup begins with stack discovery: DI, unit framework, mocking,
  Robolectric, UI framework, screenshot framework, and E2E framework. Prefer
  repo-local frameworks; create fakes before mocks when platform dependencies
  block reliable tests.
- Screenshot coverage should include screen-level size combinations, font scale,
  themes, and component-level states when UI changes. Behavior tests should use
  semantics first and verify state restoration for Compose.
- Wear Compose Material3 work must use version-matched samples before component
  changes. Prefer `AppScaffold` plus `ScreenScaffold`,
  `TransformingLazyColumn`, component defaults, Wear previews, and Navigation3
  Wear scene strategy when applicable.
- XR/Glimmer work is a separate form factor. Use `GlimmerTheme`, pure black
  root background for additive displays, Google Sans Flex defaults, depth tokens,
  one-dimensional focus, minimum readable text, and projected Activity/hardware
  permission checks. Do not use Material components as the Glimmer target.

## Compose Performance Skills

- Use the measure -> diagnose -> fix one cause -> verify loop. Do not call a
  Compose change a performance fix without release-like measurement or a clearly
  labeled diagnostic-only source.
- Debug builds, emulators, and Layout Inspector counts are diagnostic for
  performance. Release or benchmark variants with R8 enabled and physical-device
  evidence are preferred for frame time, scroll, startup, and Baseline Profile
  claims.
- Lazy layouts need stable keys, `contentType` for heterogeneous rows, measured
  allocation fixes, and stable item models before prefetch tuning.
- Stability fixes should read compiler reports before adding annotations or
  config. Stability configuration is a codebase-wide promise; prefer immutable
  collections or UI wrappers first.
- Strong skipping is compiler behavior. Confirm the Kotlin/Compose toolchain
  before adding explicit configuration or escape hatches.
- State reads should move to the latest correct phase: composition for structural
  changes, layout for measurement/placement, draw for frame-rate visual changes.
- Side effects and Flow collection belong at the lifecycle-aware holder
  boundary. Do not pass raw `Flow<T>` through leaf composable parameters.
- Custom modifiers should prefer `Modifier.Node` for new code when supported.
  Keep modifier ordering intentional and caller placement in the caller.
- R8 for Compose should trust current consumer rules by default. Avoid blanket
  Compose keep rules, `-dontobfuscate`, and broad Kotlin metadata keeps unless
  a reflective consumer proves the need.

## Chris Banes Compose And Kotlin Skills

- Use `skills/using-chrisbanes-skills/SKILL.md` as a router when the Compose or
  Kotlin task is broad.
- Broad screen refactors start with state-holder/UI split, then add state,
  effects, layout, testing, or performance skills as needed.
- Component API work pairs modifier/layout style with slot API guidance when
  both placement and content flexibility are in play.
- ViewModel, Flow, navigation, snackbar, focus request, analytics, or one-off
  event work should combine state-holder/UI split, side effects, and Flow event
  modeling.
- KMP or platform-service work should use expect/actual only when a semantic
  common API and thin actuals are justified. Interfaces may be better when tests
  or DI matter.
- Value-class work should treat domain identity and Compose stability as API
  contracts; do not pack multiple values into one value class without evidence.

## Local Mapping

- `platforms/android/skills/android-compose-ui/SKILL.md`: Compose state, performance,
  deferred reads, lazy layouts, slots, modifiers, focus, animations, previews,
  adaptive layouts, Wear Material3, XR/Glimmer UI rules.
- `platforms/android/skills/android-architecture/SKILL.md`: Navigation 3, deep links,
  Activity route boundaries, AppFunctions, Credential Manager, Play SDK, CameraX
  runtime ownership.
- `platforms/android/skills/android-module-structure/SKILL.md`: AGP, KSP/KAPT, build logic,
  module boundaries, Navigation 3 modularization, test assertion boundaries.
- `platforms/android/skills/android-security/SKILL.md`: intent security, Credential Manager,
  WebView, exported components, providers, broadcasts, bound services.
- `platforms/android/skills/android-review/SKILL.md`: acceptance criteria across all Android
  source surfaces.
