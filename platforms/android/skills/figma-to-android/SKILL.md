---
keyflow_id: sys_android_figma_to_android
status: review
type: ai-generated
---

# Figma To Android

Use when reading measurements, assets, and component structure from a Figma
handoff bundle and implementing or auditing Android UI. This card supports
Compose, Views/XML, and repositories that intentionally use both.

The shared handoff tool owns Figma API access and the measurement source of
truth. This card selects Android implementation guidance only after the target
repository's UI toolkit is known.

## Source Map

| Need | Source |
|---|---|
| Bundle creation and interpretation | [figma-handoff](../../../../common/skills/figma-handoff/SKILL.md) |
| Measurement schema | [design-summary schema](../../../../scripts/figma-handoff/docs/design-summary-schema.md) |
| Figma API limits | [fidelity and limits](../../../../scripts/figma-handoff/docs/fidelity-and-limits.md) |
| Android architecture and boundaries | [android-architecture](../android-architecture/SKILL.md) |
| Compose implementation and previews | [android-compose-ui](../android-compose-ui/SKILL.md) |

## 1. Confirm Scope And Toolkit

Classify every requested frame before editing:

- **Android implementation target**: UI rendered by code in the target Android repository
- **Existing-feature reuse target**: a product flow or component that already exists and should be composed or extended
- **OS or external target**: system UI, browser UI, or content rendered outside the app
- **Other-platform target**: UI owned by Web, server output, or another client
- **Reference-only frame**: evidence for comparison but not part of the requested change

Record included, reused, excluded, and unresolved frames. If ownership or scope
is unresolved, use the blocker-question procedure in
[ambiguity-gate](../../../../workflows/skills/ambiguity-gate/SKILL.md) before
implementation.

Then identify the target toolkit from the nearest repository instructions and
existing code:

- **Compose**: load the Compose card and follow its component, state-hoisting,
  modifier, edge-to-edge, preview, and test rules.
- **Views/XML**: do not apply Compose APIs or Route/Screen conventions. Follow
  the repository's existing Fragment/View, XML, custom View, resource, binding,
  adapter, lifecycle, and test patterns.
- **Mixed**: state which screens or components belong to each toolkit and keep
  the bridge at an existing repository-owned boundary.

Do not infer Compose merely from the `android` platform label. If the toolkit
cannot be established, stop before writing UI code and ask one focused question.

## 2. Preserve Product Behavior

A visual match never authorizes a navigation, state, data-loading, validation,
or interaction-flow rewrite. Preserve the target repository's existing behavior
unless the user or an authoritative product source explicitly changes it.
Verify the affected interaction scenarios as well as the static rendering.

## 3. Map Structure, Tokens, And Assets

1. Use `summary/design-summary.json` for measurements and `frames/` only as the
   visual comparison reference.
2. Match Figma components and variants to existing Android components by role,
   state, and action contract before adding new owners.
3. Map colors, typography, spacing, shapes, and elevation to semantic resources
   or theme tokens. A bare `VariableID` never supplies a token name.
4. Apply individual exported assets through the repository's resource policy;
   never embed the full-frame image as the implementation.
5. Treat loading, empty, error, validation, disabled, dark-theme,
   accessibility, and adaptive behavior as product states, not values inferred
   from a single Figma frame.

## 4. Apply Toolkit-Specific Structure

For Compose, use stateless screen/component APIs with hoisted state and
callbacks when that matches the repository's Compose card. Modifier order,
previews, and semantics follow that card.

For Views/XML, preserve the repository's ownership and lifecycle model. Keep
layout resources, drawables, styles, adapters, custom Views, and controllers in
their existing layer; do not translate Compose-only terminology into View code.

For mixed UI, verify both sides of the bridge and avoid creating a second state
owner solely to mirror Figma structure.

## 5. Verify And Report

Run the target repository's narrowest approved build, test, preview, or render
checks, followed by an implementation screenshot comparison at the same state,
viewport, density, and font scale. Report:

- selected toolkit and evidence for it
- included, reused, excluded, and unresolved frames
- token, component, and asset mappings
- preserved behavior and separately authorized behavior changes
- missing states, API limits, and verification executed or not executed
