---
keyflow_id: sys_web_figma_to_web
status: review
type: ai-generated
---

# Figma To Web

Use when producing a handoff bundle from a node-id Figma link and converting
it into Web components, tokens, assets, and responsive/accessibility
implementation criteria.

The shared root tool owns Figma API calls and asset extraction; this skill
owns the Web implementation mapping.

## Source Map

| Need | Source |
|---|---|
| Figma extraction procedure | [figma-handoff skill](../../../../common/skills/figma-handoff/SKILL.md) |
| Deterministic CLI and auth | [figma-handoff tool](../../../../scripts/figma-handoff/README.md) |
| Web styling and design system | [web-design-system](../web-design-system/SKILL.md) |
| React implementation, only when the target uses React | [web-react-ui](../web-react-ui/SKILL.md) |
| Accessibility | [web-accessibility-i18n](../web-accessibility-i18n/SKILL.md) |

## Framework Decision

Treat Web as the platform boundary, not as a synonym for React. Inspect the
target repository before loading a framework card:

| Target evidence | Additional guidance |
|---|---|
| React, Next.js, Remix, JSX, or TSX | Load [web-react-ui](../web-react-ui/SKILL.md). |
| Vue, Svelte, Angular, or another framework | Use that repository's framework, state, routing, rendering, and test guidance. |
| Plain HTML/CSS or Web Components | Keep this Web card and the repository's browser/component rules; do not load React guidance. |
| Framework unresolved | Produce or inspect the handoff, but stop before framework-specific implementation. |

## Procedure

1. Confirm the exact Figma file/node URL, the target screens, the framework,
   and the output directory.
2. Produce and validate screenshots, the normalized spec, assets, and the
   manifest through the shared figma-handoff procedure.
3. Find the target repository's theme/tokens/components and map Figma raw
   values onto existing semantic primitives.
4. Translate auto-layout into document flow/flex/grid and avoid fixed
   coordinate replication.
5. Specify viewport behavior, long text, loading/error/empty,
   hover/focus/pressed/disabled, and reduced motion explicitly.
6. Use provided vector assets; never substitute icons or text with
   lookalike characters.
7. After implementing, compare against the reference screenshot at the key
   viewports and run a keyboard/accessibility smoke.

Load framework-specific guidance only after the target framework is known.

## Do Not

- Do not create a separate `figma-to-react` skill merely to mirror a framework.
  Figma extraction belongs to the common handoff skill, Web mapping belongs
  here, and React implementation belongs to `web-react-ui`.
- Do not route `web-react-ui` from the Web platform name alone.
- Do not duplicate Figma API, authentication, parsing, or asset-export rules in
  a Web or framework card.
- Do not implement a screen as a full-frame image or fixed-coordinate replica.

## Stop If

- The target repository has no confirmed Web framework or has several possible
  UI stacks and the implementation destination is unresolved.
- The requested responsive behavior cannot be derived from Figma constraints,
  additional frames, product requirements, or existing repository patterns.
- A framework-specific rule would conflict with the target repository's local
  architecture or test conventions.

## Boundary

The Figma token is injected only through an environment variable. No
simplified parser or AI-specific configuration is required for canonical
execution.

## Verification

- Confirm a generic Web Figma request loads the common handoff and this card,
  without loading `web-react-ui`.
- Confirm an explicitly React Figma request additionally loads `web-react-ui`.
- Compare the implementation screenshot at key viewports and run keyboard and
  accessibility checks supported by the target repository.

## Report

Report the confirmed Web framework, the guidance cards loaded, responsive and
accessibility evidence, visual comparison performed, and any unresolved states.
