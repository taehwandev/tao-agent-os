---
keyflow_id: sys_component_api_design
status: stable
type: human-reviewed-needed
---

# Component API Design

Use when designing reusable UI components, view components, hooks, widgets,
controls, SDK helpers, or any caller-facing component-like API.

For SOLID and Interface Segregation on caller-facing API surfaces, also use
`solid-design-principles.md`.

A component API should make valid use easy, invalid use hard, and product policy visible in the caller rather than hidden inside the component.

## API Shape

Prefer:

- Plain values, immutable view models, or small parameter objects.
- Explicit callbacks for user intent or command output.
- Slots/children/render callbacks when the structure is reusable but content belongs to the caller.
- Typed states for loading, empty, error, disabled, selected, and permission states.
- Segregated props, callbacks, slots, and return values so each caller depends
  only on the state and commands it actually uses.
- Stable defaults that do not perform side effects.
- One root customization hook such as `modifier`, `className`, `style`, or equivalent, following the platform idiom.

Avoid:

- Passing repositories, routers, activities, controllers, stores, or service locators into reusable components.
- Boolean flag APIs that encode caller names, modes, or product variants.
- Fat prop objects, context values, hook return objects, or callbacks that force
  callers to pass unrelated navigation, analytics, auth, persistence, lifecycle,
  or product-policy behavior.
- Components that fetch data, decide navigation, log analytics, enforce product permissions, and render UI at the same time.
- Hidden global config reads or environment-dependent behavior.
- Copying a whole screen state into a leaf component when a smaller model works.
- Creating reusable-looking components, hooks, callbacks, or helpers for one
  caller when there is no stable second use or explicit design-system contract.
- Moving feature-specific product policy into a component only to reduce the
  caller's line count.
- Accepting raw numbers for visible counts, currency, percentages, rates,
  units, measurements, storage sizes, durations, or metric summaries without
  either a typed formatting policy or a caller-owned formatted display string.
  A reusable component should not guess grouping, precision, unit labels, or
  accessibility text from a bare number.

## Lifecycle-Contract Merge Gate

Visual similarity justifies sharing tokens and defaults, not merging
components. Before merging two similar-looking components into one API,
classify each by its interaction and host lifecycle contract:

- Does the user act on it (dismiss, retry, confirm), or is it fire-and-forget?
- Which host or lifecycle owns it: a platform-managed transient surface, a
  composition- or DOM-hosted surface, an overlay/window, or a modal owner?

Components whose answers differ are different surfaces even when the designs
look alike; an action-less transient toast on the platform's toast lifecycle
and an action-carrying snackbar that needs a composition host are two
components, not one. Do not force different-lifecycle surfaces into one
nullable-parameter API, and do not re-implement one surface as another because
they share a visual family. A status icon or shared color treatment is not the
classification criterion. Share the numeric values through an explicit
defaults or token owner instead.

## Controlled State

Make ownership explicit:

- Caller-owned state: pass value plus change callback.
- Component-local state: keep only transient interaction state such as focus, hover, expanded, drag, animation, or draft text when persistence is not needed.
- External state: expose callbacks or commands; do not mutate remote data inside the component without a documented owner boundary.

If a component can be both controlled and uncontrolled, document the precedence or avoid supporting both until there is a real caller need.

## View And Block Components

Screen, view, section, and block components do not need to be reusable across features to be valuable. Their first responsibility is to keep rendering boundaries readable and policy-free.

UI work must split named components as soon as a visual region, interaction, state
branch, or repeated control has its own responsibility. A screen may compose
many local components; it must not contain every header, filter, list, row,
empty state, dialog, footer, and action control in one file.

Use a `components`, `sections`, `blocks`, or repo-local equivalent folder for
feature-local UI, and split it by role from the start with subfolders such as
`inputs`, `feedback`, `tables`, `cards`, `dialogs`, `navigation`, or
`data-display`. Do not begin with one flat dump of unrelated components.

Use a feature-local view or block when:

- a screen is too large to review as one unit
- a section has a clear visual or interaction responsibility
- the section needs a small view model slice rather than the whole screen state
- the section emits a few user intents but does not own data fetching or product policy
- the section updates at a different cadence or renders a more expensive tree
  than nearby sections
- the section can preserve local presentation state while the parent refreshes
  or replaces other screen state

Keep the block local when its copy, route decisions, permissions, tenant rules, billing rules, analytics names, or data shape are specific to one workflow.

Promote a block into a reusable component only when the caller contract is stable: at least two real callers exist or a design-system contract is intended, the caller still owns product policy, and the API can be expressed without caller-specific booleans or nullable feature flags.

Do not skip the feature-local block step. If the only problem is that one screen
or function is too large, split it into named local sections first. Promote to a
shared component only after the reusable role and caller contract are clear.

Reusable components, section views, and block components should receive display
models and callbacks, not a whole screen `UiState`, ViewModel, store, query
result, or context object. Passing the whole state tree through the component
graph hides ownership and makes every child depend on unrelated invalidation.

Split for performance only when the API boundary also makes ownership clearer.
Do not create a reusable-looking component only to quiet a render problem while
leaving it coupled to one screen's data shape. Prefer a feature-local section,
row model, selector, or small view model slice until the reusable caller
contract is stable.

Review blocker: reject UI code that keeps distinct screen sections, reusable
controls, dialogs, rows, cards, or feedback states inside one route/page/screen
file when they can be named as components.

Do not:

- Do not put all screen components, dialogs, table rows, empty/error states,
  cards, and form controls in the route/page/screen file.
- Do not keep multiple named reusable components in one file because they are
  "small"; split once they can be imported, previewed, tested, or reviewed on
  their own.
- Do not create a `components` folder that is just a storage bin. Subdivide by
  role up front so ownership, states, imports, and review paths are explicit.
- Do not pass through an external UI library's full prop surface unchanged.
  Wrap it in a product/component contract with semantic variants, slots,
  accessibility, and supported states.
- Do not design only for the current screen. Even the first button, input, or
  card wrapper must leave room for product tokens, loading/disabled/error
  states, localization, and future variants.

## Naming

- Name the component by its reusable role: `SearchField`, `MetricTile`, `PlacePreviewSheet`.
- Name callbacks by user intent: `onRetryClick`, `onQueryChange`, `onDismiss`.
- Name slots by position or responsibility: `leadingIcon`, `trailingContent`, `media`, `actions`.
- Avoid names tied to the first screen unless the component is feature-local.

## Product Boundary

Reusable components should not own:

- product-specific copy
- route decisions
- analytics event names
- permission policy
- billing or entitlement policy
- tenant/user data filtering
- network/cache/persistence behavior

Those decisions stay in the caller, state holder, domain policy, or integration adapter. The component exposes enough callback/state surface for the caller to make the decision.

## Examples And States

Every reusable component must have at least one example, preview, fixture, story,
snapshot, or focused test covering the common state when the repo supports one.
Add edge examples when affected:

- loading and disabled
- empty and error
- selected and unselected
- long text and localization
- grouped and decimal numeric values when the component displays counts,
  currency, percentages, rates, units, measurements, storage sizes, durations,
  or metric summaries
- missing media or icon
- permission denied or read-only
- small screen or constrained container

## Review Checklist

- Can this component be used by a second caller without feature flags?
- Does the caller still own product policy and navigation?
- Are inputs minimal but complete?
- Are outputs explicit and typed?
- Is accessibility part of the API contract?
- Can the component be tested or previewed in isolation?
