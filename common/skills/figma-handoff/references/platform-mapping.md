---
keyflow_id: sys_common_figma_handoff_platform_mapping
status: review
type: ai-generated
---

# Platform Mapping

Map Figma values to the target repository's existing components, design
tokens, navigation, and asset rules before any platform API. The table is a
concept correspondence, not an architecture mandate.

| Handoff concept | Android UI | Apple UI | Web UI | Other UI stacks |
|---|---|---|---|---|
| color hex/variable | Compose/View color token | SwiftUI/UIKit asset or semantic color | CSS variable/theme token | existing theme/token system |
| font, line height, tracking | `TextStyle` or text appearance | `Font`/attributed string | font properties/typography token | text style abstraction |
| padding, spacing, alignment | layout modifier/ViewGroup | stack/frame/constraint | flex/grid/box model | layout container and constraints |
| radius and clip | shape/outline | clip shape/layer | `border-radius`, overflow | shape and clipping API |
| node opacity | layer/modifier alpha | view/layer opacity | `opacity` | layer alpha |
| stroke and align | border/draw modifier | overlay/layer stroke | border/outline/box sizing | stroke-position-preserving drawing API |
| rotation/transform | graphics transform | affine/3D transform | CSS transform | matrix/transform API |
| gradient handles | brush/shader | gradient drawing | CSS/SVG gradient | shader taking normalized handles |
| HUG/FILL/FIXED | wrap/fill/fixed constraint | intrinsic/frame constraint | fit/flex/fixed size | intrinsic/flexible/fixed sizing |
| component variant | state/parameterized composable/view | parameterized view/control state | component props/variant | framework component parameters |

## Platform Identification

- Android: Gradle Android plugin, Android modules, Compose or View sources
- Apple: Xcode project/workspace, Swift Package, and SwiftUI/UIKit/AppKit sources
- Web: package manifest and browser UI sources
- Cross-platform: Flutter, React Native, KMP UI, and their framework sources and project instructions

File signals are supporting evidence. The user-named target, the nearest
instructions, and existing UI code win. With several UI stacks, settle the
target module first. In a repository without a UI target, never fabricate a
Web target — deliver only handoff outputs or confirm the destination.

## Implementation Principles

- When an existing target component fills the same role, check whether its
  variant/style extends before drawing anything new.
- When substituting a Figma asset with a native system icon, confirm meaning,
  weight, baseline, and platform conventions match.
- Density, display scale, color space, and font availability are per-platform
  verification items.
- Map a semantic token only after comparing its rendered output with the
  node-scoped solid alpha or complete gradient in `renderedPaints`; token
  names and visual proximity are not equality evidence.
- Navigation, state containers, dependency injection, naming, and test
  structure belong to the target repository's instructions, not the handoff.
- Never guess responsive/adaptive behavior from a single Figma frame; decide
  from additional frames, constraints, and product requirements.
