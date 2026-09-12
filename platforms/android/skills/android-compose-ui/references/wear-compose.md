---
keyflow_id: sys_android_wear_compose
status: review
type: human-reviewed-needed
---

# Wear Compose Material 3

Use for Wear OS Compose Material3 creation, updates, or migration.

Split out of `current-guidance.md`, which keeps the Compose
authoring contract every UI change applies.

## Wear Compose Material 3

For Wear OS Compose Material3 creation, updates, or migration, use the external
source manifest and start with `android/skills`
`wear/wear-compose-m3/SKILL.md` plus its migration reference before changing
code or dependencies.

- Confirm the Wear Compose Material3, Foundation, and Navigation versions from
  the repo dependency catalog or official Maven metadata before editing. Do not
  downgrade only because an editor initially reports unresolved references after
  a version change.
- Wear Compose Material3 work needs Kotlin 2.0 or newer and the Compose compiler
  Gradle plugin when the repo uses Kotlin 2.x. Keep `minSdk` at least 25 for
  Wear OS 2.0 unless repo-local policy is stricter.
- Before adding or migrating a Wear Material3 component, read the version-matched
  official component samples from the local Gradle cache or downloaded
  `-samples-sources.jar`. Library source alone is not enough for component slot,
  default, padding, and interaction decisions.
- Use one outer `AppScaffold` with `ScreenScaffold` children. Pass
  `ScreenScaffold` content padding into scrollable content instead of recreating
  padding locally.
- Prefer `TransformingLazyColumn` over `ScalingLazyColumn` for Material3 Wear
  lists. Use stable list state, transformation specs, component default padding,
  `transformedHeight`, and matching rotary/fling behavior when snapping is
  configured.
- Do not use Horologist Compose UI or Wear Material 2.5 components as the
  long-term target during a Material3 migration. Expect screenshot baselines to
  change because Material3 defaults are the source of truth.
- Use Wear-specific previews such as device and font-scale previews when the
  repo supports them, and avoid hard-coded colors, text sizes, and component
  spacing where `MaterialTheme` or component defaults own the contract.
- For Wear Navigation3, use the Wear navigation scene strategy required by the
  current Wear Compose Navigation library instead of assuming phone/tablet
  navigation defaults.
