---
keyflow_id: sys_3ebdb5c993eb
status: stable
type: ai-generated
---

# Design System

Use when creating or changing shared UI primitives, tokens, patterns, component
defaults, or reusable interaction rules.

For general reusable-code extraction rules, also use
`common/skills/reusable-code-design/SKILL.md`. For Android Compose UI, also use
`platforms/android/skills/android-compose-ui/SKILL.md`.
For reusable component API shape, controlled/uncontrolled state, slots, and
caller-owned product policy, also use `component-api-design.md`.

## Direction

Build a design system as product infrastructure, not decoration. Start from
repeated product needs, then extract stable primitives. Do not create generic
components before real usage proves the contract.

For UI work, do not bypass the design system. If a repo already has tokens,
primitives, component variants, previews, or stories, use or extend them before
adding one-off styling in a screen. If no design-system layer exists and the
task creates a reusable control, repeated visual rule, or new app/screen
surface, create the smallest useful design-system layer first: semantic tokens,
one primitive, and an example or preview when the platform supports it.

Raw third-party or platform UI controls are implementation details of the design
system, not the default feature API. When a product adopts a button, input,
dialog, sheet, menu, table, toast, badge, or other foundational control from a
UI library, expose it through a repo/product-namespaced primitive such as
`<Product>Button`, `AppButton`, `DsButton`, or the repo's established prefix.
The wrapper must encode the product's tokens, accessibility, loading/disabled
states, density, slots, and variant names while keeping the underlying library
replaceable.

## Layers

```text
Tokens -> Primitives -> Composed Components -> Product Patterns -> Screens
```

Use the lowest layer that owns the decision:

- Tokens: semantic color, typography, shape, spacing, elevation, motion, density,
  and state values.
- Primitives: buttons, text, text fields, rows, icons, dividers, sheets,
  scaffold, navigation, loading indicators, and accessibility behavior.
- Composed components: reusable combinations with slots and typed state, but no
  product workflow.
- Product patterns: domain-aware reusable flows, cards, or sections owned by a
  feature/common layer rather than the primitive design system.
- Screens: route, product copy, data mapping, permissions, analytics, and
  workflow decisions.

## Rules

- Tokens are semantic: role, state, density, emphasis; not just color names.
- Primitives expose behavior and accessibility contracts, not product-specific copy.
- Components include loading, disabled, error, empty, focus, hover, pressed states.
- Product patterns may know domain workflow; primitives should not.
- Visual decisions must support scanning, comparison, repeated action, and accessibility.
- A new component needs usage examples and replacement guidance for old patterns.
- A reusable component needs a stable caller contract, examples or previews, and
  clear ownership of product-specific copy, routing, analytics, and policy.
- Component defaults should be stable, deterministic, and side-effect free. A
  theme-dependent default may read theme context through the platform idiom, but
  it should not read product state, globals, repositories, or runtime config.
- Prefer wrappers around platform UI libraries when the wrapper encodes a real
  product contract such as typography scale, touch target, loading behavior,
  accessibility semantics, or design tokens. Do not wrap only to rename an API.
- Treat visible number and unit display as a product UI contract. Shared metric,
  table, chart, badge, and summary components should receive formatted display
  strings or a typed numeric format policy that owns value, unit, scale,
  grouping, decimal precision, locale, and missing/invalid states.
- Keep design-system modules free of routes, feature ids, analytics names,
  permission policy, billing or entitlement rules, repository calls, fake data,
  and product-specific copy.
- Use slots for caller-owned icons, media, trailing actions, and rich content
  when the structure is reusable but content ownership belongs to the caller.
- Avoid boolean flag APIs that encode caller-specific variants. Split the
  component, keep it feature-local, or add a typed state when the modes represent
  real component states.
- Promotion from feature-local UI to the design system requires a stable name,
  at least two credible call sites or a foundational primitive need, examples or
  previews, and migration guidance for old usage.

## Caller and visual-variant gate

Before changing a shared card, footer, metadata row, button, token, or default,
write a caller/variant inventory. The inventory must identify the reference
frame, current owner, data owner, affected callers, unchanged callers, and the
visual evidence that will be used for each caller.

- Similar screenshots are not proof of a shared contract. Confirm the same
  slots, state model, action ownership, sizing rules, and accessibility
  behavior before commonizing or changing a shared component.
- A requirement that belongs to one card type stays in that product pattern or
  caller. Do not change a shared primitive to repair one screenshot when the
  other callers have not been checked.
- Keep semantically different fields in separate slots. Name, id, subtitle,
  count, and action buttons must not be joined with newline characters or
  invisible string padding to imitate a layout.
- Figma sample heights are not a text-container contract. Text surfaces grow
  from content and padding; fixed `height()`/`size()` is a review blocker when
  it can clip title, metadata, localization, or accessibility text. Use a
  minimum height only when it is an explicit component contract.
- Server-owned colors, labels, and options remain caller/data-model inputs. A
  screenshot is not permission to hardcode or promote them to global tokens.

The shared-component change is not ready until both the changed caller and the
unchanged callers have focused examples, previews, tests, or visual evidence.

## Component Structure

Reusable UI must have an explicit home. Put design-system primitives and
composed controls under the repo's design-system `components` or equivalent
package/folder. Put feature-only sections and feature components under that
feature's `components`, `sections`, `blocks`, or established equivalent.

Component folders must be split by capability from the start instead of using a
single large bucket:

```text
components/
  buttons/
  inputs/
  feedback/
  navigation/
  data-display/
  layout/
```

Each component must own a small public API file plus local implementation
parts, examples/previews, fixtures, and tests when the repo supports them. Do
not keep several named components in one source file once they can be imported,
previewed, tested, or reviewed independently.

Review blocker: a reusable UI change is not acceptable when it leaves named
components in a screen file, a flat catch-all component folder, raw library
usage in feature screens, or an unchanged pass-through wrapper as the product
API.

## Do Not

- Do not add raw colors, fonts, spacing, radii, shadows, motion, z-index, or
  component variants in a repeated UI surface when an existing token, primitive,
  or component can express the need.
- Do not create a screen-only "design-system" component that embeds product
  copy, routing, analytics names, permission policy, billing rules, repository
  calls, or feature DTOs.
- Do not create reusable-looking components, hooks, style helpers, or functions
  without a stable caller contract. A design-system API must be reusable by a
  second caller or be a foundational primitive.
- Do not import raw Material, SwiftUI, UIKit/AppKit, Radix, shadcn, MUI,
  Chakra, Bootstrap, or other third-party primitives directly throughout feature
  screens when a design-system wrapper must own the product contract.
- Do not expose the third-party API unchanged as the product API. A wrapper that
  only re-exports every prop, modifier, or style hook has not created a design
  system boundary.
- Do not skip design-system structure because "there is no design yet." Create
  the smallest extensible primitive with semantic variants and documented
  defaults instead of scattering raw library usage.
- Do not put all buttons, fields, cards, dialogs, tables, empty states, and
  feedback components in one `Components` file, one barrel export, one flat
  `components` folder, or one unstructured folder.
- Do not use boolean flags or nullable option bags to force unrelated product
  variants through one component. Split the component, keep it feature-local, or
  model the state explicitly.
- Do not let reusable UI primitives format counts, currency, percentages,
  units, measurements, or calculated metrics ad hoc. Use the shared
  locale-aware formatter or require a caller-owned display value that already
  includes the intended unit semantics.
- Do not replace multiple UI surfaces with a new primitive until the primitive
  has examples, previews, fixtures, stories, snapshots, or focused tests for the
  affected states.
- Do not leave a design-system change without adoption guidance when it replaces
  an existing pattern.

## Token Modeling

Prefer semantic tokens that describe role and state:

```text
surface/default, surface/raised, text/primary, text/secondary,
action/primary/enabled, action/primary/disabled, border/focus,
spacing/control-md, radius/card, motion/emphasis
```

Avoid exporting raw palette names as the main API when callers need semantic
meaning. Raw palette values can exist below the token layer, but components
must consume semantic roles.

For platform-specific design systems, keep token holders compatible with that
platform's stability model. For example, Compose token/default holders should be
immutable or stable; web token objects should avoid mutation during render.

## Component Contract

A reusable component API should define:

- required and optional state, including loading, disabled, selected, error,
  empty, read-only, and permission-denied states when relevant
- caller-owned actions and callbacks
- slot ownership for leading/trailing/media/action content
- accessibility labels, roles, focus behavior, and touch/click targets
- visible number and unit display ownership for counts, currency, percentages,
  rates, measurements, metric summaries, and accessibility labels that announce
  numeric values
- long text, localization, small screen, dark mode, and high-contrast behavior
- replacement guidance when it supersedes an older pattern

If the component needs a repository, route, whole screen state, feature-specific
DTO, or many caller flags, it is probably a product pattern or feature-local
component, not a design-system primitive.

## Previews And Examples

Every new or meaningfully changed token set, primitive, composed component, or
product pattern needs an example, preview, story, fixture, snapshot, or focused
test when the repo supports one.

Cover the states affected by the change:

- default, hover/pressed/focused, disabled, loading, error, empty, selected,
  expanded, destructive, and read-only when applicable
- light, dark, high-contrast, reduced-motion, density, and platform appearance
  variants when supported
- long localized text, missing icons/media, constrained containers, and small
  screens
- permission denied, unavailable, offline, or read-only states when the
  component displays product or platform capability

Do not use examples or previews that call network, persistence, credentials,
user-specific files, current time, randomness, or device-only services. Use
fixtures and deterministic state.

## Check

- Is this repeated in at least two places or clearly foundational?
- What is customizable, and what must stay fixed?
- Does it work with keyboard, screen readers, long text, localization, and small screens?
- Can product teams adopt it without rewriting feature logic?
- Are semantic tokens used instead of leaking one feature's exact visual
  decisions?
- Does the design-system boundary keep product policy in the caller?
- Are examples, previews, or focused tests covering common and edge states?
