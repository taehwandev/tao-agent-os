---
keyflow_id: sys_android_official_source_map
status: review
type: human-reviewed-needed
---

# Official Android Source Map

Use this reference when the task touches an official Android skill surface from
`https://github.com/android/skills`. Open the upstream `SKILL.md` first, then
open the reference group named below when the task changes implementation,
security posture, dependencies, public contracts, verification, or release
behavior.

Current snapshot: `07302ca15e21d827cab5ca64d46407fb51dbe0aa`.

## Build And Toolchain

### `build/agp/agp-9-upgrade/SKILL.md`

Read when migrating or reviewing AGP 9, Gradle 9, Kotlin, KSP/KAPT, Hilt,
Paparazzi, BuildConfig, or build-feature behavior.

Reference groups:

- AGP release notes: version-sensitive removals, DSL changes, built-in Kotlin
  behavior, and migration sequencing.
- `buildconfig.md`: BuildConfig generation and replacement decisions.
- `ksp-kapt.md`: annotation-processing migration order and plugin checks.
- `paparazzi-gradle-9.md`: screenshot test compatibility during Gradle 9
  upgrades.
- `recipes.md`: staged migration recipes by project shape.

Local rule: start with current toolchain discovery and use Upgrade Assistant or
a documented user override before direct edits. Verify with IDE sync,
`./gradlew help`, and dry-run/build checks; do not use AGP 9 guidance for KMP
unless the source explicitly supports it.

### `devtools/android-cli/SKILL.md`

Read when using the official Android CLI, SDK manager, emulator/device control,
APK install/run, screenshots, UI hierarchy inspection, journey tests, doc
search, or skill management.

Reference groups:

- `interact.md`: device interaction, input, screenshots, and UI inspection.
- `journeys.md`: repeatable journey-test structure and evidence capture.

Local rule: Android CLI work starts from explicit SDK/device/emulator state.
Capture screenshots or UI hierarchy when the task is visual; do not substitute
broad filesystem search for device-state evidence.

## Camera, Device AI, And Identity

### `camera/camera1-to-camerax/SKILL.md`

Read when removing Camera1, `SurfaceView`/`SurfaceHolder.Callback`, manual
camera lifecycle code, orientation matrix math, or custom preview/focus logic.

Reference groups: the skill body itself carries the implementation steps:
dependencies, legacy removal, `ProcessCameraProvider`, PreviewView versus
`CameraXViewfinder`, tap-to-focus, capture, camera switching, and constraints.

Local rule: CameraX owns lifecycle binding. Compose camera UI must account for
`SurfaceRequest`, tap coordinate transforms, target rotation, rebinding, and
closing `ImageProxy`.

### `device-ai/appfunctions/SKILL.md`

Read when adding or reviewing Android AppFunctions.

Reference groups:

- `feature-discovery-analysis.md`: decide which app capabilities are safe and
  useful to expose.
- `implementation-configuration.md`: config, manifest, app function
  declarations, and runtime wiring.
- `kdoc-refinement-optimization.md`: documentation quality for agent
  discoverability and safe invocation.
- `adb-interaction-testing.md`: device verification and invocation checks.

Local rule: expose only narrow, confirmable app actions. Destructive or
sensitive actions need explicit confirmation and testable ADB/device evidence.

### `identity/verified-email/SKILL.md`

Read when integrating Credential Manager verified email, digital credentials,
passkeys-adjacent flows, or WebView credential flows.

Reference groups:

- Credential Manager index: provider availability and request/response shape.
- Digital credential verifier and email verification docs: signed credential
  validation, issuer assumptions, and server-side verification.
- Email verification implementation docs: client flow and backend contract.
- Passkeys creation docs: overlap with sign-in flows.
- WebView credential manager docs: embedded-web credential boundary.

Local rule: the client integration is not proof of trust. Parse returned JSON
as untrusted input, validate cryptographically on the backend, and add a
freshness challenge when the provider/domain rules require it.

## Compose Migration, Adaptive UI, And Navigation

### Compose preview tooling and parameters

Read when Android Compose guidance or implementation changes preview creation,
preview sample data, `@PreviewParameter`, or preview case naming.

Reference groups:

- Compose preview tooling guide:
  `https://developer.android.com/develop/ui/compose/tooling/previews`
- `@PreviewParameter` API reference:
  `https://developer.android.com/reference/kotlin/androidx/compose/ui/tooling/preview/PreviewParameter`
- `PreviewParameterProvider` API reference:
  `https://developer.android.com/reference/kotlin/androidx/compose/ui/tooling/preview/PreviewParameterProvider`

Local ownership: this source map owns official links only. Apply the canonical
local preview policy from
`../../android-compose-ui/references/current-guidance.md` instead of restating
Compose preview rules here.

### `jetpack-compose/adaptive/SKILL.md`

Read when making phone/tablet/foldable/desktop-like Compose UI adaptive.

Reference groups:

- Flexbox docs: container behavior and item behavior.
- Grid docs: container and item properties.
- MediaQuery docs: responsive query boundaries.
- Compose tooling debug docs: layout verification support.
- Navigation 3 material list-detail recipe: scene strategy integration.

Local rule: add adaptive UI only after current UI verification. Use Navigation
3 scene strategies for list-detail/supporting-pane layouts and prove coverage
with screenshots across relevant window sizes.

### `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/SKILL.md`

Read when replacing XML Views with Compose.

Reference groups:

- `identify-optimal-xml-candidate.md`: choose one migration candidate and avoid
  broad rewrites.
- `xml-layout-migration.md`: migrate layout structure, state, and event flow.
- XML theme-to-Compose docs: theme/token bridge.
- Compose-in-Views and Views-in-Compose docs: interoperability boundaries.
- Compose dependency/compiler setup docs: version and plugin setup.

Local rule: migrate one candidate at a time. Capture old UI, create Compose
preview, compare parity, replace usages, and delete XML only after no references
remain.

### `jetpack-compose/theming/styles/SKILL.md`

Read when using experimental Compose Styles APIs or custom design-system style
surfaces.

Reference groups:

- custom design systems
- style fundamentals
- state animations
- styles versus modifiers
- theming

Local rule: confirm compile SDK and Compose foundation/BOM versions, opt in
explicitly, and use styles for custom design-system components only. Do not
apply the experimental API to Material components without source support.

### `navigation/navigation-3/SKILL.md`

Read when adopting or reviewing Navigation 3.

Reference groups:

- migration guide and index
- basic API, saveable state, common UI, animations, bottom sheets, dialogs
- conditional navigation, multiple back stacks, passing arguments, result
  events/state
- advanced deep links and type-safe destinations
- material list-detail/supporting-pane and scenes recipes
- modular Hilt recipe

Local rule: use typed route keys and explicit back-stack ownership. Advanced
deep links require synthetic back-stack and Up behavior evidence; modular
navigation needs module-boundary and DI wiring checks.

## Security

### `security/android-intent-security/SKILL.md`

Read for exported components, nested intents, `onNewIntent`, custom broadcasts,
`PendingIntent`, ContentProvider, and bound-service caller identity.

Reference groups: the skill body carries the detailed checklist.

Local rule: default components to non-exported; sanitize nested intents or
validate component/action/data/flags; use immutable explicit PendingIntents by
default; protect broadcasts with non-exported receivers or signature
permissions; verify bound service callers at sensitive binder transactions.

## Play, Billing, And Product SDKs

### `play/engage-sdk-integration/SKILL.md`

Read when adding Google Play Engage SDK integration.

Reference groups:

- FAQ, common behavior, clusters, patterns.
- vertical guides: food, health/fitness, listen, other, read, shopping, social,
  travel, watch, TV continue-watching, TV entitlements, TV recommendations.
- schema references by vertical.

Local rule: choose vertical and cluster before code generation. Keep publisher,
converter, request factory, worker, and receiver responsibilities separate.
Verify static and dynamic receiver registration where required.

### `play/play-billing-library-version-upgrade/SKILL.md`

Read when upgrading Play Billing Library.

Reference groups:

- billing release notes
- migration logic
- version checklist

Local rule: infer the effective legacy version from code and dependency files.
Use direct or stepped migration based on major-version distance, then verify
every version-specific checklist item.

## Performance And Profiling

### `performance/r8-analyzer/SKILL.md`

Read when reviewing R8 configuration, keep rules, shrinking, obfuscation, or
configuration analyzer output.

Reference groups:

- configuration analyzer and report format
- configuration flags
- keep-rule impact hierarchy
- redundant rules
- reflection guide
- app optimization docs
- UI Automator docs for verification where relevant

Local rule: prefer analysis/reporting before edits. Avoid blanket keep rules,
`-dontobfuscate`, and broad metadata keeps unless reflection or tooling proves
the need.

### `profilers/perfetto-sql/SKILL.md`

Read when generating Perfetto SQL.

Reference groups:

- `perfetto-stdlib.md`: standard modules and query helpers.

Local rule: use schema-backed SQL, stable `utid`/`upid`, idempotent views, exact
or `GLOB` matching, and overlap-safe interval logic. Validate execution through
`trace_processor`.

### `profilers/perfetto-trace-analysis/SKILL.md`

Read when analyzing trace files or explaining app/system performance.

Reference groups:

- domain hints: CPU, graphics, I/O, IPC, memory, power
- SQL reference and Perfetto stdlib

Local rule: keep a chain of evidence. Start with metrics, verify thread state
before claiming CPU work, follow blockers across threads/processes, and keep
searching for independent bottlenecks after the first anomaly.

## System UI, Testing, Wear, And XR

### `system/edge-to-edge/SKILL.md`

Read when applying edge-to-edge, IME, Scaffold, safe drawing, FAB, list, or text
input inset behavior.

Reference groups: the skill body carries the implementation sequence.

Local rule: locate all inset consumers first. Add `enableEdgeToEdge` and
exactly one inset strategy per container; avoid double padding between
Scaffold, IME, and safe drawing insets. Diverge from the upstream
`adjustResize` manifest step: a Compose screen uses `Modifier.imePadding()`
and `android:windowSoftInputMode="adjustResize"` stays XML-layout-only.

### `testing/testing-setup/SKILL.md`

Read when setting up or reviewing Android unit, Robolectric, UI, screenshot, or
E2E tests.

Reference groups:

- Compose common testing patterns
- Compose screenshot testing
- Hilt testing

Local rule: discover DI, frameworks, mocking style, Robolectric, UI framework,
screenshot, and E2E tools before adding tests. Prefer repo-local frameworks and
fakes before broad mocking.

### `wear/wear-compose-m3/SKILL.md`

Read when migrating or building Wear Compose Material 3 UI.

Reference groups:

- Wear Compose M3 migration guide.

Local rule: use version-matched samples and Material3 components. Prefer
`AppScaffold`, `ScreenScaffold`, `TransformingLazyColumn`, component defaults,
Wear previews, and Navigation3 Wear scene strategy where applicable.

### `xr/display-glasses-with-jetpack-compose-glimmer/SKILL.md`

Read when building projected display-glasses or Glimmer UI.

Reference groups:

- projected activity, hardware access, and hardware permission docs
- Glimmer component docs: buttons, cards, focus, icons, text, title chips
- source references: theme, typography, depth, HCT, surface, stack, list, card,
  button, title chip, icon, projected context, and related samples

Local rule: XR/Glimmer is not normal Material UI. Use `GlimmerTheme`, pure black
root background, Google Sans Flex defaults, depth tokens, one-dimensional focus,
minimum readable text, and projected Activity/hardware permission checks.
