---
keyflow_id: sys_common_figma_handoff_team_adoption
status: review
type: ai-generated
---

# Team Adoption

This repository owns the shared Figma handoff source. Teams never fork the CLI
or the skill body into per-team copies.

## Role Separation

- `common/skills/figma-handoff/`: when to extract and how to interpret and implement
- `scripts/figma-handoff/`: Figma REST execution, output schema, and self-verification
- The target team repository: product requirements, platform architecture, design tokens, assets, tests, and release rules

Target-team documents keep only a short entry pointer to this skill plus their
team-specific differences; they never restate the shared procedure.

## What A Team Prepares

1. Give the AI or automation read access to a complete checkout of this repository and the target repository.
2. Create a Figma personal access token in account settings and store it as
   `FIGMA_TOKEN` in a trusted execution environment. Use the CLI's hidden-prompt
   or secret-manager guidance; never place the value in a repository or agent
   prompt.
3. Identify the UI module, platform, design token, asset, accessibility, and test sources in the target repository's instructions.
4. Decide whether the handoff output location is temporary or a delivery/retention target.
5. Manage a small, stable, team-owned frame URL for real API smoke as a separate secret/config.

## AI-Neutral Contract

If the team's AI supports skill auto-discovery, this `SKILL.md` is the entry
point; otherwise instruct the AI to read
`common/skills/figma-handoff/SKILL.md` first. Give AIs without execution
capability an already-produced bundle per
[AI execution modes](ai-execution-modes.md).

Never add per-runtime or per-vendor configuration into this shared source.
Environment-specific wiring belongs to that environment, and execution always
converges on the in-repo CLI and the same bundle schema.

## Adoption Checks

- Runs without an external Figma CLI checkout or personal absolute paths.
- Switching AI products keeps the inputs (a Figma URL or a bundle) and the outputs (the same bundle/implementation evidence) unchanged.
- The team's tokens and product rules are never replicated into this shared source.
- A CLI update here needs no per-team copy redeployment.
