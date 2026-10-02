---
keyflow_id: sys_common_component_api_design_md_skill
status: stable
type: ai-generated
required_contract: core
---

# Component API Design

Use when designing, splitting, promoting, or reviewing reusable UI components, view/section/block components, hooks, widgets, controls, SDK helpers, or other caller-facing component APIs.

## Read

The core below is the required contract. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## API Shape` for full prefer/avoid lists.
- `## Lifecycle-Contract Merge Gate` before merging look-alike components.
- `## Controlled State` for controlled vs uncontrolled precedence.
- `## View And Block Components` for split triggers, promotion.
- `## Product Boundary`, `## Naming`, `## Examples And States`: edge cases.
- SOLID/Interface Segregation: `solid-design-principles` skill.

## Must

- Make valid use easy, invalid use hard; keep product policy visible in the caller.
- Inputs: plain values, immutable view models, small parameter objects; intent callbacks; slots/children when the caller owns content; typed loading, empty, error, disabled, selected, permission states; one root customization hook (`modifier`, `className`, `style`, platform idiom); stable defaults without side effects.
- Segregate props, callbacks, slots, return values: each caller depends only on what it uses. No fat prop/context/hook-return objects forcing unrelated navigation, analytics, auth, persistence, lifecycle, or policy.
- Never pass repositories, routers, activities, controllers, stores, or service locators into reusable components. No hidden global config reads or environment-dependent behavior.
- No boolean flags encoding caller names, modes, or product variants. No component that fetches, navigates, logs analytics, enforces permissions, and renders at once.
- Reusable components never own product copy, route decisions, analytics event names, permission, billing/entitlement, tenant/user filtering, or network/cache/persistence; expose callback/state surface instead.
- Visible counts, currency, percentages, rates, units, sizes, durations, metrics take a typed formatting policy or a caller-formatted display string, never a bare number.
- Make state ownership explicit: caller-owned is value plus change callback; local state only for transient interaction (focus, hover, expanded, drag, animation, draft); external state via callbacks/commands, no remote mutation without a documented owner boundary.
- Merge look-alikes only when interaction and host lifecycle contract match; otherwise keep separate surfaces and share values via a defaults/token owner. No nullable-parameter merge.
- Split named components as soon as a region, interaction, state branch, or repeated control has its own responsibility; no screen file holding every header, row, dialog, empty/error state. One named reusable component per file.
- Feature-local UI goes in a role-subdivided `components`/`sections`/`blocks` folder (`inputs`, `dialogs`, ...), never a flat dump.
- Children get display models and callbacks, never a whole screen `UiState`, ViewModel, store, query result, or context object.
- Split locally first; promote only with two real callers or an intended design-system contract, caller-owned policy, and no caller-specific booleans. No one-caller reusable-looking APIs or perf-only splits coupled to one screen.
- Wrap external UI libraries in a product contract (semantic variants, slots, accessibility, states); never pass their full props through.
- A first wrapper still leaves room for tokens, loading/disabled/error, localization.
- Name by reusable role; callbacks by user intent (`onRetryClick`); slots by position or responsibility.

## Stop If

- Two look-alike surfaces differ in interaction or host lifecycle and a merge is requested.
- Promotion lacks a stable caller contract or would move feature policy into a shared component.
- Controlled and uncontrolled support is needed but precedence is undecided.

## Verification

- Each reusable component has an example, preview, fixture, story, snapshot, or focused test of the common state when the repo supports one, plus affected edge states (loading/disabled, empty/error, selected, long text, grouped/decimal numerics, missing media, read-only, small container).
- Review: second caller without flags? Caller owns policy and navigation? Inputs minimal, outputs typed, accessibility in the contract? Reject screen files holding nameable sections or dialogs.
