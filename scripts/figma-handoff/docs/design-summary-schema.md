---
keyflow_id: sys_figma_handoff_summary_schema
status: review
type: ai-generated
---

# `design-summary.json` Field Reference

Unlike `design-handoff.md`, which is a human-readable summary,
`summary/design-summary.json` is the source of truth for all measurements. The
Markdown output truncates long sections such as `layoutNodes`; always use the
JSON for exact values.

This document defines the units, coordinate systems, and meaning of the JSON
fields. Check the `schemaVersion` field in `manifest.json` to identify the
structure version (currently `3`).

## Common Rules

- **Rounding**: pixel and angle values are rounded to two decimal places by
  `round_number` in `figma_util.py`; values close to integers are stored as
  integers. The maximum rounding error is approximately `0.005px`.
- **Coordinates**: unless stated otherwise, values use the Figma canvas pixel
  coordinate system.
- **null**: a missing or null field means that Figma REST did not provide a
  value. Do not confuse it with zero.
- **Paths**: `screens[].imagePath` and `assetCandidates[].assetPath` are POSIX
  relative paths from the bundle root. They never depend on a personal absolute
  path or a Tao Agent OS checkout location.

## Top-Level Keys

| Key | Meaning |
|---|---|
| `meta` | `fileKey`, `startNodeId`, `sourceUrl`, and `generatedAt` (UTC ISO) |
| `screens` | Render targets with id, name, type, dimensions, and image path |
| `flowEdges` | Prototype transition edges (`from` to `to`) |
| `flowInteractions` | Trigger, action, navigation, and transition details |
| `designTokens` | Named color/text/effect styles and variables |
| `referencedStyles` | Style catalog recovered from node `styles` references |
| `components` | Components actually used by screens, ordered by usage |
| `componentBlueprints` | Representative internal subtree for each component |
| `colors` / `gradients` / `textStyles` / `effects` | Usage-ordered candidates |
| `textRuns` | Partial text-style override runs |
| `layoutMetrics` | Frequency summaries for padding, spacing, and alignment |
| `layoutNodes` | Per-node layout and visual properties |
| `assetCandidates` | Icon/vector/image-fill candidates and optional asset paths |
| `assetInventory` | Unique assets grouped by deduplication key |
| `warnings` | Items skipped or failed during this run |

## `layoutNodes[]` — Per-Node Properties

Each item contains `id`, `name`, `type`, `parentId`, and `depth`, plus fields
that exist on the source node.

### Component Identity (`INSTANCE` nodes)

- `componentId`: the master component node id referenced by this instance; it
  matches `components[].componentId` and uses normalized `slug:num` syntax
- `componentProperties`: variant, text, boolean, and instance-swap properties
  flattened from Figma's `{name: {value, type}}` shape

### Size, Position, And Rotation

- `absoluteBoundingBox` `{x,y,width,height}`: canvas-coordinate AABB. For a
  rotated node it is the enclosing rectangle, not the actual shape size.
- `absoluteRenderBounds` `{x,y,width,height}`: the rendered bounds including
  effects such as shadows and blur; it can exceed the bounding box.
- `size` `{x,y}`: the node's unrotated width and height. Use it with
  `rotation`/`relativeTransform` for rotated shapes when available.
- `rotation`: radians. Convert with `rotation * 180 / pi` only when an API needs
  degrees. `relativeTransform` is the authoritative 2x3 affine transform.
- `relativeTransform`: parent-relative transform matrix
  `[[a,c,tx],[b,d,ty]]`

### Auto Layout

- `layoutMode`: `HORIZONTAL`, `VERTICAL`, or `NONE`; `layoutWrap`:
  `WRAP` or `NO_WRAP`
- `primaryAxisAlignItems`, `counterAxisAlignItems`, and
  `counterAxisAlignContent` for wrapped-line alignment
- `primaryAxisSizingMode` and `counterAxisSizingMode`: `FIXED` or `AUTO`
- `layoutSizingHorizontal` / `layoutSizingVertical`: `FIXED`, `HUG`, or `FILL`
- `layoutPositioning`: `AUTO` or `ABSOLUTE`; `layoutAlign`; `layoutGrow`
- `itemSpacing`, `counterAxisSpacing`, and four-sided padding in pixels
- `minWidth`, `maxWidth`, `minHeight`, `maxHeight`
- `constraints` `{horizontal,vertical}`: `MIN`, `MAX`, `CENTER`, `STRETCH`, or
  `SCALE`

### Shape And Visual Properties

- `cornerRadius` or `rectangleCornerRadii` `[tl,tr,br,bl]`; individual radii win
- `clipsContent`, `overflowDirection`
- `opacity`: node-level opacity from `0` to `1`; it is not included in color hex
  values and must be applied separately
- `blendMode`: `PASS_THROUGH`, `MULTIPLY`, and other Figma blend modes
- `isMask` / `maskType`: mask and clipping information
- `strokeWeight`, `strokeAlign`, `individualStrokeWeights`, and `strokeDashes`

## `colors[]` — Hex Rules

- `hex`: `#RRGGBB` or `#RRGGBBAA`
- Alpha is composed as `paint.opacity * color.a`. Node-level opacity is not
  included.
- Alpha values at or above `0.995` use six-digit hex. Fully transparent colors
  are excluded from candidates.
- Display P3 values are recorded as sRGB hex without profile conversion; use
  the raw float values for precision.
- `boundVariableNames` and `boundVariableIds` identify variables when the fetch
  succeeds. Names can be absent while an id remains available.

## `gradients[]`

- `type`, `stops[]` with `position` and `hex`, and normalized
  `handlePositions[]` with `x` and `y`
- `angleDegrees` is recorded for linear gradients. `0°` is up and angles move
  clockwise. On non-square nodes, recompute the visual angle from the handles
  and actual dimensions.
- Radial, angular, and diamond gradients preserve handles without inventing an
  angle or radius interpretation.

## `textStyles[]`, `textRuns[]`, And `designTokens.textStyles`

- Font family, PostScript name, weight, size in pixels, and italic flag
- Line-height precedence: `lineHeightPx`, then
  `lineHeightPercentFontSize`, then `lineHeightPercent`; `lineHeightUnit` is
  preserved
- `letterSpacing` and `letterSpacingUnit`; a null unit is treated as pixels
- Horizontal/vertical alignment, auto-resize, decoration, case, truncation,
  max lines, and paragraph spacing
- `textRuns[]` stores partial styles as `range{start,end}`, `text`, and a
  `resolvedStyle` formed from base and override values

## `designTokens.variables`

- `collections[]`: `{id,name,modes[],defaultModeId}`
- `variables[]`: `{id,name,resolvedType,collectionId,valuesByMode}`
- `valuesByMode[modeId]` stores color values as `{hex,raw}` or aliases as
  `{alias,aliasId,aliasName,resolvedHex? | resolvedAliasName?}`
- Alias chains are resolved recursively with cycle protection and a default-mode
  fallback when a mode is missing.
- `/variables/local` may be unavailable on the current Figma plan. In that case,
  `variables` can be empty, while `colors[].boundVariableIds` retains opaque
  `VariableID:…` references. Do not invent semantic names for those ids; map
  them to the target repository's token source.

## `assetCandidates[]`

- `id`, `name`, `type`, `exportSettings`, and `imageRefs` for image fills
- `dedupKey`: a visual signature made from geometry, color, name, or image ref;
  the same key means the same asset candidate
- `nearestComponentName`: the closest enclosing component instance, when known
- `renderFallbackIds`: up to three ancestor containers to try when standalone
  rendering fails; screen frames are excluded
- With `--export-assets`, `assetPath` points to a bundle-relative file:
  image fills become PNG, and pure vectors/boolean operations become SVG

## `assetInventory[]` — Unique Asset Work List

`assetCandidates` are grouped by `dedupKey` so repeated icons are implemented
only once.

Each item contains:

- `dedupKey`, representative `name`, `type`, `usageCount`, and member `nodeIds`
- `nameUnclear`: true when all member names are generic; inspect an exported
  PNG before assigning a semantic name
- `nearestComponentName` and `imageRefs`, when available

The tool does not invent a semantic name such as “search icon.” If
`nameUnclear=true` and there is no nearest component name, inspect the rendered
asset before naming it.

## `componentBlueprints[]` — Internal Component Structure

Each distinct component is represented by the internal subtree of the instance
with the most children. Build the component once from this blueprint, then place
instances instead of rebuilding a generic screen by eye.

Each item contains `componentId`, `name` (the component-set name when present),
`usageCount`, `representativeInstanceId`, `size{w,h}`, and
`variantProperties`. Its `structure[]` entries contain `name`, `type`, `depth`,
`w`, and `h`, plus:

- `componentId` for a nested instance; nested components are references only and
  are not expanded
- `assetDedupKey` for an asset linked to `assetInventory` or `assetCandidates`
- `text` for a sample of a TEXT node's content, limited to 40 characters

Different nested `componentId` values remain different implementations even if
their icons look similar.

## `components[]` — Component Work List

This list groups components actually used by screen instances by `componentId`.
Use it as a usage-ordered work list so reusable Compose, SwiftUI, CSS, or other
platform components are defined before their screens.

Each item contains:

- `componentId`, `name`, and `usageCount`
- `usedInScreens`
- `componentSetId` / `componentSetName` when variants belong to one component set
- `variantProperties` for `VARIANT` properties such as `{state: on/off}`
- `description` and `remote`, when supplied by Figma

Variant members can appear as separate entries. Group them by `componentSetId`
when implementing one parameterized code component.

## Related Documents

- Use `raw/nodes.json` as the final source for radians, rotated geometry, and
  individual stroke widths.
- See `fidelity-and-limits.md` for values the tool cannot reproduce directly.
