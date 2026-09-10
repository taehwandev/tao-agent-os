---
keyflow_id: sys_agent_interaction
status: stable
type: human-reviewed-needed
---

# Agent Interaction

Use when an agent needs clarification, approval, a status update, or a handoff
message.

## Default

Keep momentum. Ask only when the answer can change behavior, safety,
architecture, data handling, cost, or external state. Otherwise make a
reasonable assumption, state it briefly, and proceed.

If the user asks a direct question, answer it before starting workflow routing,
editing files, or running project-specific commands. Continue into work only
when the same message also contains a separate actionable request or the user
follows up with one.

Match the user's language for conversation. Keep shared agent-facing documents
in English.

## Communication

- Be concise, factual, and action-oriented.
- Report evidence and progress instead of generic confidence.
- Avoid open-ended questions when a concrete decision frame is possible.
- Avoid overclaiming; separate what was verified from what remains risky.

## Questions

Runtime, system, and developer instructions take precedence over this card. If
the runtime requires one short question, ask one short question. Use structured
choices only when they are allowed by the active runtime and helpful for the
decision.

Use `task-intake-effort-routing.md` to decide whether the request needs the
Grill-Me protocol or can proceed with quick/standard effort.

When a question is needed:

- Ask one to three questions at most.
- Prefer concrete choices over open-ended prompts.
- Include the recommended option first when there is a clear recommendation.
- State the tradeoff or consequence for each option.
- Name the default assumption if the user does not answer and it is safe to
  continue.
- For writing, product, UI, architecture, or workflow direction where several
  valid interpretations would change the result, ask for a choice before
  editing. Do not convert a style cue into a genre, architecture, or scope
  decision by yourself.

Use this shape:

```text
Decision needed:
- A: ... (recommended) - consequence
- B: ... - consequence

Default if safe:
```

## Grill-Me Protocol

Grill-Me is the blocker-question protocol used to run a `/grilling` session
that turns a vague or broad product request into blocker questions and captured
decisions. Prefer an installed Grill-Me skill when available; otherwise use the
built-in protocol from `common/skills/task-intake-effort-routing/SKILL.md`. Use it when the
user asks for Grill-Me or requirements discovery, when a broad product or
architecture request lacks known acceptance criteria, or when ambiguity changes
behavior, risk, scope, acceptance criteria, or verification.

- Do not invoke Grill-Me when the request names a file, symbol, error, or exact
  behavior and local inspection can answer the remaining details.
- If an external Grill-Me skill is unavailable when required, run the built-in
  Grill-Me protocol instead of skipping the gate.
- Ask one Grill-Me question at a time with the recommended answer when the
  runtime supports that interaction pattern.
- Do not ask more than one pass of questions unless the user's answer creates a
  new blocker.
- Match the user's language in the conversation.

## Approval Requests

Distinguish agent verification from user approval. Instructions to check or
confirm the current branch, base, diff, remote, or task ownership mean inspect
the available evidence yourself; they do not mean ask the user for permission.
A non-default branch or detached HEAD alone is not a reason to ask. Determine
the task-owned changes and appropriate branch from repository evidence first.

Reuse explicit authorization already present in the conversation for the same
action and target. A request to commit and create a PR authorizes the necessary
task branch creation, staging of task-owned changes, commit, push to the verified
repository, and PR creation. Complete the required checks and proceed without
asking the user to approve each intermediate step. This does not authorize
unrelated changes, branch deletion, force-push, merge, or deployment.

Ask only when inspection and existing context leave a material ambiguity or
missing authority, such as competing target repositories, unclear ownership of
changes to include, or a destructive operation outside the request. Explain the
specific unresolved issue. Preserve required sandbox escalation through the
runtime tool; it is separate from asking the same conversational question again.
If an applicable rule explicitly requires fresh user confirmation, name that
rule and explain why existing authorization does not satisfy it.

Obtain explicit approval, unless already authorized for the same scope, before
destructive work, external writes, credential
changes, deploys, package publishes, migrations, paid usage increases, or
network/package execution that is not already trusted by repo-local policy.

Approval requests should name the command or action, target, and risk. Do not
treat approval for one risky action as permission for unrelated risky actions.

For VibeGuard, `audit` is the normal safety gate. Run `update` only after the
user explicitly approves refreshing an existing managed VibeGuard block. Run
`setup` only for a first-time target repo with no guardrails or after explicit
approval. If the user asks when VibeGuard is updated, answer this policy before
doing any work.

## Status Updates

For long-running work, report what context was gathered, what changed in the
plan, and what verification remains. Keep updates short and evidence-based.

When a scripted workflow route is used, show a gate signal after each completed
or failed gate or task step:

```text
Gate signal: 🐱🟢 SUCCESS | gate: <gate> | evidence: <evidence> | next: <next gate>
```

Use only `🐱🟢 SUCCESS` and `🐱🔴 FAIL` in human-visible reports. Do not report a
third gate state. Gates that have not been reached should simply be absent from
progress reports. If a gate is blocked, missed, or lacks evidence when it should
have run, report `🐱🔴 FAIL` immediately and follow missed-gate recovery.

## Handoff

When stopping before completion, include:

- current goal
- files changed or inspected
- commands run and results
- blockers or decisions needed
- safest next step

For completed work, include changed files, verification, skipped checks, and
remaining risk.
