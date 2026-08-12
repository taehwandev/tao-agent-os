---
keyflow_id: sys_ios_figma_to_swiftui
status: review
type: ai-generated
---

# Figma To SwiftUI

Use when reading measurements, individual assets, and component structure
from a Figma handoff bundle and implementing them as SwiftUI or UIKit screens
in a target iOS repository, verified with previews, builds, and screenshots.

This skill never reimplements the raw Figma API. The shared handoff tool owns
the measurement source of truth; this skill applies it to the target iOS
design system and UI structure.

## Source Map

| Need | Source |
|---|---|
| Bundle creation, schema, AI execution modes | [figma-handoff](../../../../common/skills/figma-handoff/SKILL.md) |
| Deterministic CLI and validator | [figma-handoff tool](../../../../scripts/figma-handoff/README.md) |
| SwiftUI implementation and previews | [ios-swiftui-ui](../ios-swiftui-ui/SKILL.md) |
| UIKit bridges and structure | [ios-uikit-ui](../ios-uikit-ui/SKILL.md) |
| Architecture and module boundaries | [ios-architecture](../ios-architecture/SKILL.md) |

## Procedure

1. Read the target repository's nearest instructions, deployment target,
   SwiftUI/UIKit balance, navigation, design tokens, resource accessors, and
   preview rules.
2. Dry-run the node URL and produce the bundle with the shared figma-handoff
   skill; with an existing bundle, validate its schema instead of re-calling.
3. Use `summary/design-summary.json` as the measurement source of truth,
   `frames/` as the visual reference, and `assetInventory` plus exported files
   as the individual-asset source of truth.
4. Match Figma components/variants against existing reusable components
   first — by style, state, and action contract, never by name alone.
5. Map color, font, spacing, and radius to the target's semantic tokens. When
   no token exists, surface a new-token proposal and its impact instead of
   hiding a raw value.
6. Navigation, alerts, sheets, toasts, and loading/empty/error/permission
   states follow the product's sources and existing project contracts, not
   Figma.
7. Add previews (or the target repository's allowed exemption note) for
   screens and meaningfully changed components. Check accessibility, long
   text, Dynamic Type, and dark mode where applicable.
8. Build/test the narrowest module, then the app when needed, and compare the
   reference frame against an implementation screenshot.

## Do Not

- Never embed the full-frame PNG as the screen implementation.
- Never prioritize a Figma-drawn tab bar, status bar, or keyboard over
  platform system UI; exclusion is decided by the product's rules.
- Never estimate pixel values or assets from a screenshot alone.
- Never collect `FIGMA_TOKEN` from settings files or accept it via chat.

The completion report includes the bundle, implementation files, token/asset
mapping, missing states, warnings, and whether preview/build/test and real
screenshot comparison ran.
