---
keyflow_id: sys_kmp_design_system_module
status: review
type: ai-generated
---

# KMP Design-System Module

Use when creating or changing the shared Compose Multiplatform design-system
module, adding a token or component, deciding whether a composable belongs in
the design system or a feature, or reviewing raw colors, dimensions, and
primitives in feature code.

The platform-neutral rules (layers, semantic tokens, component contract,
caller/variant gate, previews) are in
[design-system](../../../../../common/skills/design-system/SKILL.md) and apply
as-is. The Android design-system rules also apply as-is to Compose
Multiplatform:

- [Design-System Consumption Gate](../../../../android/skills/android-compose-ui/references/current-guidance.md#design-system-consumption-gate)
- [package shape and reuse decision](../../../../android/skills/android-compose-ui/references/screen-structure.md#package-structure)

This card adds the KMP module contract: where the module sits, what it may
depend on, how target differences enter it, and how to verify features consume
it.

## Module Contract

Keep one design-system module, conventionally `:core:designsystem`. Do not add
a separate `:core:ui` unless the repo already has one; when it does, `:core:ui`
holds domain-aware shared UI (product patterns used by several features) and
depends on `:core:designsystem`, never the reverse.

```text
:core:designsystem
  commonMain   theme, tokens, components, icons, previews
  desktopMain  pointer icons, popup/window hosts, desktop font loading
  androidMain  ripple/indication, system bar colors, platform font loading
  iosMain      UIKit interop surfaces, platform font loading
```

Allowed dependencies:

- Compose runtime, foundation, UI, animation, and the Material library the repo
  wraps
- Compose Multiplatform resources, an icon library, font assets
- Kotlin stdlib and coroutines for UI-only state

Forbidden dependencies:

- any `:feature:*` module
- `:core:data`, `:core:domain`, repositories, DTOs, database types
- platform capability modules (process, terminal, device, browser engine,
  network, notifications)
- navigation libraries, DI frameworks, analytics, logging backends
- product model types from `:core:model`, except plain value types the repo
  explicitly marks as UI-safe

When a component needs a product value, take a display value or a slot instead
of the model.

## Token Layer

Tokens are exposed through the theme, not through top-level values:

```kotlin
@Immutable
data class AppSpacing(val xs: Dp, val sm: Dp, val md: Dp, val lg: Dp, val xl: Dp)

internal val LocalAppSpacing = staticCompositionLocalOf { DefaultAppSpacing }

object AppTheme {
    val spacing: AppSpacing
        @Composable @ReadOnlyComposable get() = LocalAppSpacing.current
}
```

- One file per token family under `tokens/`: color, typography, spacing,
  shape/radius, stroke, elevation, motion, density.
- Keep palettes and `CompositionLocal` keys `internal`; callers read
  `AppTheme.colors`, `AppTheme.spacing`, and so on. A public palette value or a
  public `Local*` key lets features bypass the theme and pin one palette.
- Name tokens by role (`surface.raised`, `text.secondary`, `spacing.md`), not
  by value or by the feature that introduced them.
- Theme variants (light, dark, high contrast, user-selected palettes) are
  palettes behind the same semantic color type; adding a variant never changes
  a call site.
- Every repeated dimension in feature code maps to a token. An off-scale value
  (6.dp next to a 4/8/12 scale) is either a missing token or a design bug;
  decide which and record it, do not leave the literal.
- Keep one naming prefix. A token or local renamed during a rebrand keeps no
  second spelling.

## Component Layer

- Components live in `components/<group>/` (buttons, inputs, feedback,
  navigation, layout, data, overlays). A flat `components/` package with
  dozens of files fails review the same way a flat feature package does.
- A component is a product-prefixed wrapper (`AppButton`, `AppTextField`) that
  owns variants, states, accessibility, and token use. Raw Material components
  are imported inside the design system, not in features.
- A component that only one feature uses, or that knows a product concept
  (a terminal cursor, an order card, a commit graph lane), is a feature
  component or a `:core:ui` product pattern. The test: can it be named and
  previewed without the product domain?
- Locale, language, and copy are not design-system concerns. A UI language
  setting or string table belongs to the app target or a resources/i18n owner;
  the design system only renders strings it is given.

## Target Differences

Desktop and mobile differ in pointer, hover, focus, context menu, window, and
density. Put the difference where the visual contract lives:

| Difference | Home |
| --- | --- |
| Hover/pressed visuals, focus ring, density | token or component parameter in `commonMain`, chosen by the theme per target |
| Pointer icon, cursor shape, resize handle | `expect`/`actual` in the design-system module |
| Popup, tooltip, context-menu, detachable-pane host | design-system desktop source set, exposed through a `commonMain` component API |
| Window chrome, menu bar, tray | app target, not the design system |
| Platform fonts | design-system target source set behind the typography token |

A component must render a sensible default on every target the module
compiles to. Desktop-only components still need a `commonMain` contract when a
shared screen calls them.

## Feature Consumption Rules

Feature modules depend on `:core:designsystem` from `commonMain` whenever they
render UI. Inside features:

- No `Color(0x...)` literals. Domain-driven colors (status, category, graph
  lanes) become semantic tokens or a palette the theme provides; data-provided
  colors stay data and pass through a mapping owned by the feature.
- No repeated `N.dp`/`N.sp` literals for spacing, radius, stroke, or text.
  Literal dimensions are acceptable only for one-off geometry tied to content
  (an icon's intrinsic size inside a drawing) and should be named constants.
- No local re-implementation of a primitive the design system has (a private
  `*Button`, `*Card`, `*Chip`, `*Badge`). Extend the design-system component
  with the missing variant, or keep a clearly product-specific composite in
  the feature built from design-system parts.
- No direct `androidx.compose.material*` imports for controls the design system
  wraps; a raw import needs a written reason in the change.
- A module that renders UI without depending on the design system is either
  not a UI module (move its UI to the feature that renders it) or is bypassing
  the theme.

## Previews And Catalog

- Each component has previews for its states in the design-system module, using
  deterministic fixtures and every theme variant the app ships.
- Keep a catalog screen or screenshot test that renders all components per
  theme; run it on at least one target in CI when the repo supports UI tests.
- Preview tooling differs by target; when a target cannot render previews, name
  the replacement (desktop screenshot test, UI test).

## Do Not

- Add a token or component to the design system for one caller.
- Make palettes, `CompositionLocal` keys, or default token instances public.
- Let the design system import feature, data, domain, or platform capability
  modules.
- Put product-specific composites, language settings, or copy in the design
  system.
- Leave hardcoded colors or dimensions in features when a token exists.

## Stop If

- A component needs a repository, route, feature state, or product model to
  render.
- A new token would only describe one feature's exact value.
- The change alters a shared component and the unchanged callers have no visual
  evidence (caller/variant gate in the common card).

## Review Checklist

- Does `:core:designsystem` depend only on Compose, resources, and icon/font
  libraries?
- Are tokens reachable only through the theme object?
- Is `components/` grouped, and is every component domain-free?
- Do features import design-system components instead of raw Material controls?
- Did the change add any `Color(0x`, or a repeated `.dp`/`.sp` literal, in a
  feature module?
- Are target differences in the design system's target source sets or app
  target, not in features?

## Verification

- Gradle edges: inspect `:core:designsystem` dependencies and confirm no
  `project(":feature:` / `project(":core:data` / capability module appears.
- Bypass search across feature modules, for example
  `rg "Color\(0x" feature/`,
  `rg "\b[0-9]+(\.[0-9]+)?\.(dp|sp)\b" feature/ -c`, and
  `rg "^import androidx\.compose\.material3\.(Button|Card|TextField|Surface)" feature/`.
  Compare counts before and after; a UI change should not raise them.
- Token-access search: `rg "Local[A-Z]\w*(Colors|Spacing|Typography)" feature/`
  should return nothing when tokens are read through the theme.
- Render previews or the catalog for every theme variant affected, on each
  target that supports it.
