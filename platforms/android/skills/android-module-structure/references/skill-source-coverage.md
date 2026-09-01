---
keyflow_id: sys_android_module_skill_source_coverage
status: review
type: human-reviewed-needed
---

# Android External Skill Source Surfaces

Use when an Android task touches AGP, R8, Perfetto, Navigation 3,
XML-to-Compose, adaptive layouts, CameraX, Credential Manager,
Play Billing, Play Engage, Wear, XR, or AppFunctions surfaces.

## Android Skill Source Coverage

When an Android task touches one of these surfaces, apply the corresponding
source-specific guidance in addition to this Tao Agent OS card. Do not copy
external skill files into the repo by default; distill the rule into the task
plan and cite the source when reporting. This section is a summary; the complete
source document list lives in `android-external-skill-source-coverage.md`.

- Android CLI and device inspection: use the Android CLI surface for SDK
  management, device runs, screenshots, layout inspection, doc lookup, and
  installed Android skill discovery before guessing tool behavior.
- AGP upgrades: check the current AGP version first, respect Gradle/JDK/Kotlin
  compatibility, do not use AGP 9 guidance for KMP projects, avoid `clean` as a
  default verification step, and verify with sync/help/dry-run style checks.
- R8 and keep rules: inspect Gradle/R8 configuration before editing, prefer
  quantitative analyzer evidence when available, treat broad package-wide keep
  rules as review risk, and validate runtime-sensitive removals with
  Macrobenchmark or focused smoke evidence.
- Perfetto SQL and trace analysis: use schema-backed queries, idempotent
  Perfetto SQL, `utid`/`upid` instead of recycled process/thread ids, `GLOB`
  instead of `LIKE`, metrics-first investigation, and chain-of-evidence notes
  before concluding root cause.
- Navigation 3: keep typed route keys and deep-link contracts in API
  boundaries, map them to `NavDisplay` entries in app/impl boundaries, use
  synthetic back stacks for advanced deep links, support multiple back stacks,
  conditional flows, results, dialogs, bottom sheets, and adaptive scenes only
  where the product behavior requires them.
- XML-to-Compose migration: migrate one XML candidate at a time, capture visual
  baseline or screenshots when possible, keep interop theming minimal, add a
  Compose preview, validate parity, then remove only unused XML resources.
- Adaptive Compose: require Compose and Navigation 3 first, verify form factors,
  adapt navigation areas with `NavigationSuiteScaffold`, use Navigation 3 scene
  strategies for list-detail/supporting panes, and add screenshot coverage for
  phone, foldable, tablet, and desktop-sized layouts when the repo supports it.
- Edge-to-edge and IME: make each Activity explicit with `enableEdgeToEdge()`
  before `setContent`, handle the soft keyboard with `Modifier.imePadding()` on
  Compose screens and keep `android:windowSoftInputMode="adjustResize"`
  XML-layout-only, pass `Scaffold` insets to scrollable `contentPadding`, keep
  one IME owner per screen, and verify text fields, FABs, lists, dialogs, and
  system bar icon contrast.
- Compose Styles: treat the Styles API as experimental, require the documented
  compileSdk/Foundation or BOM version and opt-in, use it only for custom
  components/themes, and validate with screenshot or preview parity before
  replacing direct style parameters.
- Testing setup: inventory existing DI, unit, mocking, Robolectric, Compose,
  Espresso, screenshot, and E2E tools before adding dependencies; prefer fakes
  over mocks for platform/data seams; cover navigation, deep links, restoration,
  window sizes, and changed visible states.
- CameraX migration: remove legacy Camera1/manual lifecycle code, bind use
  cases through `ProcessCameraProvider` and a `LifecycleOwner`, use
  `CameraXViewfinder` for Compose, update target rotation, and always close
  `ImageProxy`.
- Credential Manager and verified email: client parsing is not security
  validation. Generate a fresh nonce, send raw credential response and nonce to
  a server for cryptographic verification, and use WebView bridges only as a
  native handoff to Credential Manager.
- Play Billing: detect the effective library version from both dependency and
  deprecated API usage, plan direct or stepped migration, follow every relevant
  version checklist item, and verify builds/tests at migration boundaries.
- Play Engage: identify vertical, cluster, request structure, entity mapping,
  data source, worker/publisher/receiver responsibilities, and required static
  plus dynamic receiver registration before generating code.
- Wear Compose Material3: use latest stable compatible versions, sync before
  refactoring, read version-matched component samples, prefer
  `TransformingLazyColumn`, pass `ScreenScaffold` padding, and use Navigation 3
  `SwipeDismissableSceneStrategy` for new Wear navigation.
- XR/Glimmer: use a projected Activity and Glimmer components/theme instead of
  Material, keep a pure black root background for additive displays, respect
  minimum readable text and contrast, map one-dimensional inputs/focus, and
  show one primary piece of information at a time.
- AppFunctions: require the documented target/compile SDK level, discover
  high-value workflows before implementing, immediately refine KDoc for agent
  discovery, verify with ADB, and never expose sensitive or destructive actions
  without confirmation.

