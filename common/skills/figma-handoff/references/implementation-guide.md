---
keyflow_id: sys_common_figma_handoff_implementation
status: review
type: ai-generated
---

# Handoff Implementation Playbook

Read this when implementing real UI from a produced or received Figma handoff
bundle. The exhaustive field definitions belong to the
[design-summary schema](../../../../scripts/figma-handoff/docs/design-summary-schema.md).

## Evidence Priority

1. `summary/design-summary.json`: source of truth for all measurements and structure
2. `raw/nodes.json`: precise conversions and original API values the summary could not keep
3. `frames/`: visual comparison reference
4. `summary/design-handoff.md`: quick-navigation summary

Markdown lists may truncate. The full-frame image is a reference for comparing
results, not an implementation asset.

## Structure To Recover First

1. Scope the screens and transitions to implement from `screens` and `flowInteractions`.
2. Treat `components` as a work list ordered by usage frequency. Variants sharing a
   `componentSetId` collapse into one code component with state parameters.
3. Recover internal structure from the representative subtree in
   `componentBlueprints`. Nested nodes with different `componentId` values stay
   separate components even when they look similar.
4. Apply parent, depth, layout, size, padding, spacing, positioning, and
   constraints from `layoutNodes`.
5. Deduplicate assets with `assetInventory` and connect blueprints to real files
   through `assetDedupKey`.

Rebuilding a whole screen as one eyeballed generic layout drifts component
boundaries and icon positions. Build components first, then compose instances.

## Measurements That Go Wrong

- `rotation` is in radians. Convert with `radians x 180 / pi` only for APIs that need degrees.
- Node `opacity` is not baked into fill/stroke hex. Apply it at the node layer separately from paint alpha.
- Resolve line height as `lineHeightPx` -> `lineHeightPercentFontSize` -> `lineHeightPercent`.
- For non-square gradients, `handlePositions x actual width/height` beats `angleDegrees`.
- A rotated node's `absoluteBoundingBox` is the circumscribed rectangle; use `size`, `rotation`, and `relativeTransform` for the real shape.
- `strokeAlign` and `individualStrokeWeights` affect occupied size and clipping.
- Never substitute `blendMode`, masks, or `clipsContent` with a plain color or border.

## Design Tokens And Text

Never scatter Figma hex and font values directly into target code. Map them to
the target repository's semantic color, typography, spacing, and radius tokens
first; only when no token matches, decide whether a new token or a local value
is warranted.

Variable names can be empty depending on the Figma plan and library scope. Do
not invent a name for a bare `VariableID`; connect it to the target team's
token source instead.

When `textRuns` exist, preserve partial styles inside one text node. Text or
emoji used as glyphs in Figma may not export as SVG; use the blueprint's real
string.

## Asset Handling

- Vector and boolean assets: the exported SVG or the platform's verified native/vector asset
- Image fills: the exported PNG with the density/scale policy
- System glyphs: the target platform's system icon, with the name and substitution reason recorded
- Render fallbacks: visually confirm crop and padding when an ancestor container rendered together

The final implementation never references the bundle's temporary absolute
paths. Copy needed files into the asset location the target repository owns and
reference them by relative path or asset-catalog id.

## Missing States And Verification

Never hide states absent from Figma as variations of the normal state.
loading, empty, error, validation, disabled, focus, dark mode, locale,
responsive, and accessibility states come from product requirements and
existing code, listed separately.

After implementing, verify in order:

1. The target repository's compile/test/lint rules
2. Previews/stories/examples for renderable screens and reusable components
3. Screenshot comparison at the same viewport, scale, and state
4. The visual impact of missing assets, font substitution, and API limits

Never claim "1:1" or "pixel perfect" without an executed pixel diff.
