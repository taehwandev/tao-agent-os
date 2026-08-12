---
keyflow_id: sys_ios_figma_to_ios
status: review
type: ai-generated
---

# Figma To iOS

Use when reading measurements, individual assets, and component structure from
a Figma handoff bundle and implementing or auditing iOS UI. This card supports
SwiftUI, UIKit, and repositories that intentionally use both.

The shared handoff tool owns Figma API access and the measurement source of
truth. This card selects toolkit-specific guidance only after the target
repository's UI ownership is known.

## Source Map

| Need | Source |
|---|---|
| Bundle creation, schema, and AI execution modes | [figma-handoff](../../../../common/skills/figma-handoff/SKILL.md) |
| Deterministic CLI and validator | [figma-handoff tool](../../../../scripts/figma-handoff/README.md) |
| SwiftUI implementation and previews | [ios-swiftui-ui](../ios-swiftui-ui/SKILL.md) |
| UIKit implementation and bridges | [ios-uikit-ui](../ios-uikit-ui/SKILL.md) |
| Architecture and module boundaries | [ios-architecture](../ios-architecture/SKILL.md) |

## 1. Confirm Scope And Toolkit

Read the target repository's nearest instructions, deployment target,
navigation, design tokens, resource accessors, and preview/test rules. Identify
each requested screen or component as SwiftUI, UIKit, or an intentional mixed
boundary from existing code; the `ios` platform label alone selects none of
these toolkits.

- **SwiftUI**: load the SwiftUI card and follow its view ownership, state,
  navigation, preview, and accessibility rules.
- **UIKit**: load the UIKit card and follow its controller/view, Auto Layout,
  reuse, lifecycle, and test rules. Do not impose SwiftUI state or modifier
  conventions.
- **Mixed**: keep hosting and bridge ownership at an existing repository-owned
  boundary and state which side owns navigation and state.

If the toolkit or requested screen ownership remains ambiguous, stop before UI
edits and ask one focused blocker question.

## 2. Map The Handoff

1. Dry-run the node URL and produce the bundle with the shared handoff skill;
   with an existing bundle, validate its schema instead of re-calling Figma.
2. Use `summary/design-summary.json` as the measurement source of truth,
   `frames/` as the visual reference, and `assetInventory` plus exported files
   as the individual-asset source of truth.
3. Match Figma components and variants against existing reusable components by
   style, state, and action contract, never by name alone.
4. Map color, font, spacing, and radius to semantic tokens or asset resources.
   When no token exists, surface a new-token proposal and its impact.
5. Navigation, alerts, sheets, toasts, and loading, empty, error, validation,
   permission, and disabled states follow product sources and existing project
   contracts, not a single Figma frame.

## 3. Preserve Product Behavior

A visual match never authorizes a navigation, state, data-loading, validation,
or interaction-flow rewrite. Preserve existing behavior unless the user or an
authoritative product source explicitly changes it. Keep system-owned tab bars,
status UI, keyboards, and permission UI outside the app implementation unless
the target repository owns a custom replacement.

## 4. Verify And Report

Add previews, or the target repository's allowed exemption, for screens and
meaningfully changed components. Check accessibility, long text, Dynamic Type,
dark mode, and relevant size classes. Build and test the narrowest module, then
the app when needed, and compare the reference frame against an implementation
screenshot.

The completion report includes the selected toolkit, bundle, implementation
files, token and asset mapping, preserved behavior, missing states, warnings,
and whether preview, build, test, and screenshot comparison ran.

## Do Not

- Never embed the full-frame PNG as the screen implementation.
- Never estimate measurements or assets from a screenshot alone.
- Never accept a Figma token through chat or read it from settings files.
- Never apply SwiftUI-only or UIKit-only rules until the target toolkit is known.
