---
keyflow_id: sys_figma_handoff_fidelity_limits
status: review
type: ai-generated
---

# Fidelity And Limits

This document explains which Figma values can be reproduced from the bundle,
which values need the raw API payload, and which cases are limited by the Figma
REST API.

The layout skeleton (layout, text, color, and effects) is usually close to
one-to-one when implemented from `design-summary.json`. Some precise properties
also require `raw/nodes.json`, and some capabilities are unavailable through the
API.

## Tier 1 — Reliable From The Summary

- **Auto Layout**: `layoutMode`, `wrap`, primary/counter alignment,
  `counterAxisAlignContent`, sizing modes, `layoutSizing`, spacing, four-sided
  padding, corner radii, min/max sizes, constraints, clipping, and overflow
- **Size**: `absoluteBoundingBox` in pixels, rounded to two decimal places
- **Text**: font family/PostScript name/weight/size/italic, line-height units,
  letter spacing, horizontal and vertical alignment, auto-resize, decoration,
  case, truncation, and max lines; partial styles are preserved in `textRuns`
- **Color**: solid fill and stroke hex values (`#RRGGBBAA`) with paint alpha
  composed into the color value
- **Gradient geometry**: original stops and handle positions
- **Effect values**: shadow color/offset/radius/spread and blur radius
- **Visual properties**: `opacity`, `blendMode`, `isMask`, `maskType`,
  `rotation`, `strokeWeight`, `strokeAlign`, `individualStrokeWeights`, and
  `absoluteRenderBounds`

## Tier 2 — Summary Plus Raw Data Or Correction

- **Node opacity**: `layoutNodes[].opacity` is not included in color hex values;
  apply it separately to overlays and dimming layers
- **Rotated node size**: `absoluteBoundingBox` is the rotated node's enclosing
  box; use `size`, `rotation`, and `relativeTransform` to restore the shape
- **Gradient angle**: `angleDegrees` uses normalized coordinates and can differ
  from the visual angle on a non-square node; recompute it from handle positions
  and the actual width/height
- **Blend mode**: modes such as `MULTIPLY` do not match a simple color overlay;
  apply the composition mode
- **Stroke alignment**: `INSIDE`, `OUTSIDE`, and `CENTER` change occupied size;
  include them in layout calculations

## Tier 3 — API Or Tool Limits

- **Design-token names on non-Enterprise plans**: `/variables/local` may be
  unavailable; the bundle can contain empty variable metadata or `VariableID:…`
  references. Map those references manually to the target repository's semantic
  tokens. Remote library variables may remain unavailable as well.
- **Display P3**: P3 floats are recorded as sRGB hex values without profile
  conversion. Use the original floats in `raw/nodes.json` for precision work.
- **Image-fill bitmaps**: `--include-image-fills` stores the URL map but does not
  download the original bitmap. Obtain photo resources through a separate,
  authorized process.
- **Markdown truncation**: `design-handoff.md` caps long sections such as
  `layoutNodes`; use `design-summary.json` for exact values.

## Icons, Vectors, And Images

- The default run renders screen frames as PNG and records internal elements as
  `assetCandidates` with ids and names.
- `--export-assets` extracts individual assets:
  - pure vectors and boolean operations become SVG, including node opacity
  - image fills become PNG at the requested scale because Figma may not render
    those nodes as SVG
  - if a node cannot render alone, the tool tries its `renderFallbackIds`
    ancestor chain, excluding the screen frame
- Historical fixture measurements are not guarantees for another Figma file.
  Check the current bundle's `coverage_report` instead.
- System glyphs such as SF Symbols should be implemented with the target
  platform's native symbol set rather than exported as design assets.
- A nested leaf vector or glyph can be unavailable as a standalone REST render.
  If the exact path data is required, export the complete frame as SVG.

## Scale Guidance

The default scale is `2.0`. Use `--scale 3` when an Android xxhdpi-sized export
is needed, up to the Figma limit of `4.0`. Large sections can time out at high
scale; render individual frames separately when necessary.
