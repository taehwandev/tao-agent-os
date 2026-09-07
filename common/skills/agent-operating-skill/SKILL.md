---
keyflow_id: sys_common_agent_operating_skill_md_skill
status: stable
type: ai-generated
---

# Agent Operating Skill

Use when routed to `common/skills/agent-operating-skill/SKILL.md` or when work needs this Tao Agent OS guidance area.

## Need-Driven Reading Contract

This is the shared reading rule for every Tao route and runtime. Apply it before
following this or another Tao document's reference links.

1. Read the target's applicable instructions and the route's `required_docs`.
   Preserve explicit applicable safety, platform, and verification dependencies;
   a reading budget never permits skipping a requirement.
2. Treat `reference_docs`, related-skill lists, routing tables, graph neighbors,
   and bare links as candidates, not a recursive reading queue. A topic appearing
   in the task is not by itself a reason to read every document about that topic.
   After successful routing, do not read `index.md` or another broad catalog to
   repeat document selection. Use a narrow lookup only for a concrete unresolved
   requirement; use the catalog fallback only when routing is unavailable.
3. Before an optional read, identify the unresolved question, why this document
   can answer it, and which in-scope decision or check depends on the answer.
   If none exists, do not read it. Keep this rationale in the existing work
   summary when useful; do not add a per-document hook, receipt, or gate.
4. Select the smallest relevant document first. Read selected instruction files
   completely, but do not automatically follow their optional links. Reuse a
   complete reading still available in context when the document is unchanged;
   re-read if its contents changed or the needed instructions are unavailable.
5. Stop optional discovery when the requested outcome, change owner, applicable
   constraints, and nearest verification are known. Reopen it only for a new
   concrete blocker, failed check, or changed requirement. An empty search is not
   permission to broaden the task or repeat equivalent searches.
6. Do not turn incidental findings into implementation scope. Keep unrelated
   cleanup, architecture changes, and environment tuning outside this task.
   If required selection itself is excessive, report the specific selection
   conflict and repair its owner only with task authority; do not silently omit
   required guidance or start an unrequested library-wide cleanup.

## Read

- `references/current-guidance.md` when the active lifecycle has an unresolved
  procedure or evidence requirement not answered by this entrypoint or route.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Apply the Need-Driven Reading Contract to additional context selection.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
- If a route requires the `handoff` gate, verify the worker handoff hook states that the route gate must be recorded separately.
