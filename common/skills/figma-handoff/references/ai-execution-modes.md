---
keyflow_id: sys_common_figma_handoff_ai_execution_modes
status: review
type: ai-generated
---

# AI Execution Modes

This skill selects a path by real execution capability, not by AI product
name.

## A. AIs With Local Execution And Network

Run the Python CLI directly from this checkout. Confirm inputs with
`--dry-run`, and produce the bundle with the token the user keeps in their
local environment. For implementation requests, continue into the target
repository's instructions and verification.

Never hand the AI a token string. The AI confirms only that the environment
variable exists and passes the CLI the variable name.

## B. AIs That Read Files But Cannot Run Commands Or Use The Network

A link alone cannot produce a bundle. A user or automation with execution
capability must produce and hand over:

- Required: `summary/design-summary.json`
- Recommended: `summary/design-handoff.md`, `frames/`, `assets/`
- Only for precision issues: the needed scope of `raw/nodes.json`

The AI can interpret the bundle into an implementation plan, token mapping, a
component list, a QA checklist, or code suggestions. It never claims to have
called the real API or downloaded assets.

## C. AIs That Read Only Conversation Attachments

Upload in this order instead of the whole bundle:

1. `design-handoff.md` and the target frame images
2. `design-summary.json` when exact measurements are needed
3. The individual SVG/PNG assets the implementation needs

If attachment limits truncated the summary, state the missing scope. Never
reverse-estimate spacing or font values from a screenshot and report them as
JSON measurements.

## D. Automation Or Another Agent Producing The Bundle

The producer-consumer contract is this repository's CLI output structure and
schema. Never make a vendor command, slash command, or agent configuration
file the intermediate contract. The producer runs the CLI in a trusted
execution environment holding the token and hands the consumer only the
bundle.

This repository currently ships no server, MCP wrapper, runtime hook, or
per-AI adapter. If such an execution layer is added later, it must keep the
same CLI input/output and token safety boundary.

## Request Examples

An AI with execution capability:

```text
Use the figma-handoff skill to produce the handoff and individual assets for
this node-id Figma URL, then implement and verify it against the current UI
module's rules.
```

A bundle-reading AI:

```text
Using the attached design-summary.json as the measurement source, lay out the
component structure, token mapping, missing states, and implementation
differences. Use the full frame image only as a comparison reference.
```
