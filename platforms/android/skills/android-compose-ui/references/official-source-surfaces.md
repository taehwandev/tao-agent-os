---
keyflow_id: sys_android_compose_source_surfaces
status: review
type: human-reviewed-needed
---

# Official Android Compose Surfaces

Use when the surface is adaptive UI, XML-to-Compose migration, Compose Styles, CameraX in Compose, or XR/Glimmer, and load the matching official source bundle with it.

Split out of `current-guidance.md`, which keeps the Compose
authoring contract every UI change applies.

## Source-Specific Compose Surfaces

For Android Compose surfaces that are driven by official Android skills, keep
this card as the architecture baseline and load the matching source bundle
before implementation:

- Adaptive UI: verify screenshot coverage across form factors before changing
  navigation areas, multi-pane scenes, or grid/list adaptations. Use Navigation
  3 scene strategies when the source skill requires them.
- XML-to-Compose migration: migrate one XML candidate at a time, capture the old
  UI, keep XML theming for interoperability, add a Compose preview, compare
  visual parity, and remove XML only after usages are replaced.
- Compose Styles API: treat it as experimental and version-gated. Use it for
  custom design-system components only after compile SDK, Compose foundation or
  BOM, and opt-in requirements are confirmed.
- CameraX in Compose: keep camera provider/use-case binding lifecycle-aware,
  model `SurfaceRequest` state explicitly, update target rotation, and handle
  tap-to-focus through the correct coordinate transform.
- XR/Glimmer: treat display glasses as a separate form factor. Use Glimmer
  components and theme, pure black root background, projected Activity hardware
  checks, one-dimensional focus, and readable text sizing; do not substitute
  standard Material components.
