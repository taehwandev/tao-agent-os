---
keyflow_id: sys_android_figma_to_compose
status: review
type: ai-generated
---

# Figma To Compose

Use when converting a Figma design spec into Android Compose UI, or when a
node-id Figma link arrives for Android implementation or a design audit.

## Source Map

- Bundle creation and interpretation: [`common/skills/figma-handoff/SKILL.md`](../../../../common/skills/figma-handoff/SKILL.md)
- Measurement schema: [`scripts/figma-handoff/docs/design-summary-schema.md`](../../../../scripts/figma-handoff/docs/design-summary-schema.md)
- Figma API limits: [`scripts/figma-handoff/docs/fidelity-and-limits.md`](../../../../scripts/figma-handoff/docs/fidelity-and-limits.md)
- Compose implementation: [`../android-compose-ui/SKILL.md`](../android-compose-ui/SKILL.md)

## Step 0. Scope Gate

A Figma node can mix app screens, web screens, OS pickers, editors, result
previews, and reference prototypes. Separate the scope before implementing.

Classify each frame from the handoff's `Screens`, `Prototype Flow Edges`, and
`Prototype Interaction Details` as one of:

- **Android implementation target**: rendered directly by the app code
- **Existing-feature reuse target**: upload, media editing, shared components already implemented
- **OS/external screen**: system pickers, permission dialogs, browsers, in-WebView pages the app does not draw
- **Web/server/other-platform target**: rendered on the web or driven by API responses
- **Reference-only screen**: prototype-link confirmation outside the current ticket scope

Before editing code, share the scope in this shape:

```text
### Figma scope confirmation
- Included: ...
- Reusing existing features: ...
- Excluded: ...
- Needs confirmation: ...
```

If anything sits under "Needs confirmation", do not start implementing — run
the Grill-Me blocker-question protocol from
[`workflows/skills/ambiguity-gate/SKILL.md`](../../../../workflows/skills/ambiguity-gate/SKILL.md),
one question at a time with a recommended answer each. Mandatory Grill-Me
cases: app and web screens mixed in one node; screens the app does not draw
(pickers, permission dialogs); ambiguous reuse of an existing implemented
flow; copy/options that may come from an API rather than hardcoding; a
prototype's next screen possibly exceeding the ticket scope.

Fix non-goals explicitly: OS pickers, system galleries, and permission
screens stay out unless the user names them; WebView-internal or web-only UI
is never a Compose target; API-driven copy is never settled as hardcoded
without a confirmed fallback; an existing media-editing flow is reused, not
rebuilt.

Preserve existing flows: matching one Figma screen never silently changes the
established flow mechanics (sequential scroll, polling-then-advance, block
expand/collapse animation). Verify core scenarios, not only static
screenshots.

## Step 1. Design Analysis And Token Mapping

Read the layout, colors, typography, and padding. Map to the target
repository's theme tokens (color, typography, shape) before considering any
hardcoded value.

What the handoff gives reliably: sizes and layout (Auto Layout, padding,
itemSpacing, cornerRadius), color hex, typography (family/weight/size/line
height), and shadow/blur values extract accurately.

What it does not give: semantic color token NAMES. The handoff carries hex
values only — either the design never bound colors to Variables/Styles, or the
variables endpoint is unavailable on the current Figma plan and only a bare
`VariableID` remains. The implementer connects hex to the target repository's
design-token source: find the same hex with the same semantic role; when one
hex serves several semantics (text and border sharing a hex), the hex alone
cannot decide — choose by design intent or ask the designer. Never invent
token names for bare `VariableID` values.

API limits needing separate collection: photographic/bitmap image fills,
Display P3 exact color, and deep instance leaf vectors.

## Step 2. Structure Split (Route-Screen Pattern)

Never build one giant composable. Design a stateless `Screen` unit receiving
state and callbacks, and a `Route` unit injecting data, per the Compose card's
layer shape.

## Step 3. Apply The Compose UI Card

Implementation follows
[`../android-compose-ui/SKILL.md`](../android-compose-ui/SKILL.md):
component split, modifiers, state hoisting, edge-to-edge/IME handling, and
preview verification all follow that card.

## Step 4. Modifier Order

Assemble modifiers in Layout (padding, size) -> Shape (clip) -> Drawing
(background) -> Interaction (clickable) order.

## Step 5. State And Preview Verification

Hoist every state parameter so `Screen` composables stay stateless. Preview
coverage follows the Compose card's preview rules.
