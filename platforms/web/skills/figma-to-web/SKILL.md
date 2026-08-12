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
| React implementation | [web-react-ui](../web-react-ui/SKILL.md) |
| Accessibility | [web-accessibility-i18n](../web-accessibility-i18n/SKILL.md) |

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

## Boundary

The Figma token is injected only through an environment variable. No
simplified parser or AI-specific configuration is required for canonical
execution.
