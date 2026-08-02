---
keyflow_id: sys_ambiguity_gate_workflow
status: stable
type: human-reviewed-needed
---

# Ambiguity Gate

Use before PRD, ARD, task breakdown, implementation plan, or code work when the request has unknowns that could change behavior, scope, risk, or verification.

For initial request clarity, effort level, token budget, and Grill-Me protocol
decisions, also use `../common/skills/task-intake-effort-routing/SKILL.md`.

When this route is executed through `scripts/workflow.py`, read its
`required_docs` directly before classifying unknowns or asking blockers.
Ambiguity handling is not a memory-only step; the current routed guidance must
be read before turning an unknown into an assumption.

## Core Rule

Do not turn unknowns into silent assumptions.

Inspect the current conversation, repo-local instructions, product docs, architecture docs, existing code, tests, and recent artifacts before asking the maintainer. Do not ask for information that is already available in the repo or conversation.

If an unknown is not answerable from that context and can change behavior,
scope, risk, acceptance criteria, or verification, it is a blocker. Ask before
editing. Do not proceed because the agent can imagine a plausible default.

## Unknown Classes

Classify each unknown as exactly one of these:

- `blocker`: The answer can change user-facing behavior, scope, architecture, permissions, privacy, data safety, release risk, or acceptance criteria.
- `researchable`: The answer should be found in repo docs, code, tests, platform docs, current artifacts, or local context before asking.
- `assumable`: The answer is a reversible implementation detail, follows local patterns, and does not change product meaning or risk.
- `out-of-scope`: The request conflicts with current product direction or should be deferred or rejected.

Ask the maintainer only for `blocker` unknowns.
When a blocker exists, asking is mandatory. Continuing into PRD, ARD, planning,
implementation, review, or commit without blocker-question evidence is a
workflow failure.

## Grill-Me Protocol

Use the Grill-Me protocol when the user asks the agent to refine the request,
when broad product or architecture work lacks known acceptance criteria, or
when the request is too vague to classify without inventing behavior. Prefer an
installed Grill-Me skill when available; otherwise run the built-in
blocker-question protocol from `common/skills/task-intake-effort-routing/SKILL.md`.

Examples:

- "Change the button on home" usually needs a drill unless the repo has one obvious home button and a reversible local pattern.
- "Improve the X button in `HomeScreen`" is usually scoped enough to inspect `HomeScreen` first and ask only if behavior or acceptance remains unclear.
- A pasted compiler/test/runtime error is usually clear enough for quick or standard debugging without Grill-Me.

Do not invoke Grill-Me as ceremony for clear low-risk tasks.

When Grill-Me is not needed, still record the alignment brief before
requirements analysis or modification work: what is understood the same way,
what may differ, and which unsupported assumption is safe by default. This brief
is the minimum check; Grill-Me is for blockers or explicit user request. When a
PRD is not created, this alignment brief is the PRD-skip checkpoint and must be
visible to the user before drafting or editing. Do not replace it with a private
note or after-the-fact finish evidence.

## Mandatory Blockers

Stop and ask when any of these are unclear:

- user problem or intended outcome
- scope and explicit non-goals
- writing genre, point of view, honorific level, audience, or voice target when
  the task drafts or rewrites prose and the choice would change the outline,
  author stance, or acceptance criteria
- visible UI behavior, entry point, or state model
- success, empty, loading, unavailable, permission-denied, and failure behavior
- persistence, destructive changes, migrations, rollback, or compatibility
- permissions, privacy, secrets, network access, external state, or release impact
- feasibility when the feature depends on fragile platform or third-party behavior
- acceptance criteria or verification strategy

## Question Pass

- Ask one to three concise questions by default.
- Ask up to five only when multiple high-risk blockers exist.
- Each question should name the decision being made and why it matters.
- Prefer concrete choices when the ambiguity is about direction, taste, voice,
  genre, scope, or architecture. Name the consequence of each option instead of
  asking the maintainer to invent the frame.
- When several blockers are open, map the dependencies among them and ask in
  dependency order so upstream decisions are settled before the questions that
  depend on them.
- Do not ask preference questions already settled by repo docs, product docs, architecture docs, existing UI, or platform constraints.
- Ask one Grill-Me question at a time with its recommended answer when the
  runtime supports that interaction pattern. Do not proceed into PRD, ARD, or
  implementation while blockers remain.

When blocked, use this shape:

```text
Decision: needs-clarification

Blocking unknowns:
- <category>: <why this changes behavior, risk, or verification>

Questions:
1. <decision question and consequence>

Safe assumptions:
- <only non-blocking assumptions, if any>
```

When request classification requires Grill-Me, the matching route gate evidence
must name the Grill-Me protocol or `/grilling` session and its output. Record
that evidence through `gate` or `gate-batch`; invalid manual-question-only
evidence is rejected there instead of being deferred to finish. That evidence
must name the actual Grill-Me questions shown to the user and the resolved
outcome; a generic completion phrase such as "questions completed" is not
valid evidence. Likewise, `source docs` gate evidence must record that the
entire route-pinned `required_docs` manifest was read directly — listing only
some of its documents is a failed checkpoint.

## Assumptions

If no blockers remain, record assumptions explicitly:

```text
Assumption: <specific default>
Reason: <repo pattern, product rule, or reversible implementation detail>
Risk: <what changes if this assumption is wrong>
```

When the maintainer asks the agent to proceed with assumptions, choose the smallest reversible option that matches existing product and architecture rules.

## PRD Conversion

After blockers are resolved:

- summarize maintainer decisions and repo-researched facts separately
- list assumptions separately from decisions
- write behavior scenarios in `Given / When / Then` form
- include success, empty, loading, unavailable, permission-denied, and failure states when relevant
- tie scenarios to acceptance criteria and verification

Close a clarification session with a fixed summary shape before any work
continues:

```text
Confirmed decisions:
- ...
Scope and non-goals:
- ...
Acceptance criteria:
- ...
Edge cases:
- ...
Dependencies and constraints:
- ...
```

Do not leave unresolved blockers as open questions. Open questions are allowed only for non-blocking future follow-up.

## Stop If

- A blocker unknown can change product behavior, security, data handling, release risk, or verification.
- The answer should exist in repo-local docs or code but has not been inspected.
- The maintainer asks for a PRD, ARD, task breakdown, or implementation while blocker unknowns remain.
- Proceeding would require inventing product policy, acceptance criteria, or permission behavior.
