---
keyflow_id: sys_agent_skill_card_anatomy
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Agent Skill Card Anatomy

Use when creating, updating, or reviewing an Tao Agent OS common card,
workflow, platform card, product-pattern card, or agent-facing template.

The goal is to make each card executable by an agent: the card should say when
to load it, what to inspect, what decision to make, what not to do, and what
evidence proves the work.

## Use When

- A shared guidance card is added or materially changed.
- A workflow, platform, or product-pattern page is too broad to act on.
- A recurring mistake needs to become durable guidance.
- A document is expected to be read before code, review, release, or handoff.

Do not use this as a reason to rewrite unrelated cards. Apply it to the cards
that govern the current task or the recurring lesson being promoted.

## Decision Rule

A card is mature enough when an agent can answer these questions without
guessing:

- When should this card be loaded?
- What should be inspected before acting?
- What is the decision rule or ordered process?
- What actions are forbidden or should stop the work?
- What evidence verifies completion?
- What should the final report, review, PR, or handoff say?

If the card cannot answer those questions, either tighten the card or mark the
gap explicitly. Do not pad with generic advice.

## Card Contract

Prefer these sections for new or substantially revised cards:

1. `Use When`: trigger, scope, and exclusions.
2. `Inspect First` or `Read`: local docs, source files, contracts, examples, or
   related cards to load before action.
3. `Decision Rule` or `Process`: ordered behavior, not only principles.
4. `Common Rationalizations`: excuses agents use to skip the rule.
5. `Red Flags`: symptoms that should trigger review, escalation, or a stop.
6. `Do Not`: forbidden actions stated negatively and concretely.
7. `Stop If`: blockers that must prevent editing, release, or handoff.
8. `Verification`: smallest evidence that proves the changed surface.
9. `Report` or `Output`: what the final response or review must include.

Short review cards may combine sections, but they still need priority, checks,
evidence gaps, and output shape.

## Skill Bundle Layout

For new broad-use guidance, or when an existing card is becoming too large to
scan, prefer a skill bundle over a single long Markdown file. The canonical
layout and migration procedure are owned by
`docs/skills/tao-skill-bundle-migration/SKILL.md`.

```text
<area>/skills/<skill-name>/SKILL.md
<area>/skills/<skill-name>/references/<focused-detail>.md
```

This card owns the anatomy of an executable skill card. It does not own the full
bundle migration policy. Read the migration skill before restructuring a large
card family, changing workflow router paths, or cleaning duplicated
source-of-truth rules. For duplicate guidance cleanup, also read
`docs/skills/tao-skill-bundle-migration/references/source-of-truth-ownership.md`.

## Guidance Nodes

A node is one atomic rule set that a route can require on its own. Use a node
when a platform or concern shares most of its rules with another one and only
a delta differs, so the delta can refine the shared baseline instead of
copying it.

```text
<area>/nodes/<node-name>.md
```

Each node declares in frontmatter:

- `use_when` and `skip_when`: the trigger and the exclusion, one line each.
- `requires`: nodes that must be read with it. A route always promotes them.
- `refines`: the baseline node or card this node narrows. A route always
  promotes it, so the node states only the delta, never a copy.
- `verified_by`: the review checklist node that proves it. Only review and
  release routes promote it; implementation routes keep it as a reference.

A node body stays under 120 lines and ends with a `## Verification` section.
Workflow validation rejects a node without a trigger or exclusion, an oversized
node, an orphan node that no route rule or document reaches, a node backtick
reference to a missing document, a `requires`/`refines`/`verified_by` target
that does not exist in any document, and a `requires`/`refines` cycle.

`workflow-doc-surfaces.json` doc sets are entry-node lists. Set membership adds
no relation between members; a dependency between nodes belongs in the nodes'
own frontmatter.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "This is obvious, so no verification section is needed." | Add the smallest evidence that proves the rule. |
| "The positive rule already implies what not to do." | Add an explicit `Do Not`, `Stop If`, or `Red Flags` section. |
| "The card is shared, so examples should be broad." | Keep examples small and remove repo-specific names, commands, and policy. |
| "A new card is easier than updating the old one." | Check overlap first and update the existing source of truth when possible. |
| "More context will make the card safer." | Use progressive disclosure; link detailed references instead of loading everything by default. |
| "The old flat path is still there, so it can hold the real guidance." | Remove the flat path after canonical routing is updated; use a temporary stub only for a named compatibility dependency. |

## Red Flags

- A page describes ideals but has no decision rule, stop condition, or evidence.
- Multiple cards answer the same question with different language.
- A shared card encodes one product's role names, service setup, commands, or
  deployment model.
- A workflow page lacks entry criteria, ordered gates, stop signals, or
  completion evidence.
- A platform card lacks ownership boundaries, forbidden dependency leaks, state
  expectations, or target verification.

## Do Not

- Do not copy a third-party skill, vendor workflow, or repo-local policy
  wholesale into shared Tao Agent OS guidance.
- Do not add a new card when an existing card should be tightened or linked.
- Do not create separate "quick reference", "changelog", or auxiliary docs for
  a card unless the route explicitly needs a reference file.
- Do not put private paths, account names, product policy, commands, or service
  setup in shared guidance.
- Do not hide blockers only inside positive prose.

## Stop If

- The proposed card would become the source of truth for one product, team,
  account, deployment, or vendor-specific workflow.
- The source material is private or unavailable and the card would invent facts.
- The guidance conflicts with repo-local security, data, release, or
  verification policy.
- The card would require agents to load broad context for a narrow task.

## Verification

For document-only changes, run the repository's workflow validation and a diff
sanity check. For strict Tao Agent OS cards, validation should confirm
frontmatter and the required action sections.

When a route, concern, or command should load the card, add or update workflow
router tests that prove the card appears in the route manifest.

## Report

Report:

- cards added or tightened
- route, concern, or command wiring changed
- validation commands run
- remaining cards that still need anatomy cleanup
