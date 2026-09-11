---
keyflow_id: sys_task_intake_effort_routing
status: stable
type: human-reviewed-needed
---

# Task Intake And Effort Routing

Use at the start of an agent conversation or task when deciding whether the
request is clear enough, whether Grill-Me protocol clarification is required, and
how much model effort, context loading, and workflow depth the task deserves.

The goal is to use the lowest capable effort level without skipping safety,
verification, or repo-local rules.

## Read When Needed

This file holds the rules every intake applies. Open a sibling only when its
condition is true for the current request:

- `prd-creation-boundary.md` when requirements analysis or modification work
  has to decide between creating or updating a PRD and the PRD-skip checkpoint.
- `model-tier-selection.md` when a runtime chooses a model, reasoning level, or
  worker tier from the effort profile.
- `grill-me-protocol.md` when classification sets `grill_me: true` or legacy
  `question_drill: true`, the user asks for Grill-Me or requirements discovery,
  or blocker questions are the deliverable.

## Intake Decision

Classify the request before loading many documents or doing deep reasoning.
Do not rely only on a fixed phrase such as "Grill-Me", "feature", or "PRD".
Classify the request from the missing decision surface: target, intended
behavior, acceptance criteria, data/security/cost/external-state risk,
verification, and whether existing docs or code can answer the unknown.

| Class | Signal | Default Action |
| --- | --- | --- |
| `direct-question` | Asks for an explanation, timing, policy, status, or meaning without asking the agent to change files or run work. | Answer first. Do not start workflow routing, editing, or project-specific commands unless a separate action remains. If the question asks how to start app, product, or feature work, the answer must include the PRD -> ARD -> implementation path before lower-level coding steps. |
| `clear-exact` | Names a file, symbol, command, error, stack trace, failing test, or precise behavior. | Use quick or standard effort; inspect the named target first. |
| `clear-scoped` | Names a screen/component/feature and intended change, but local context is needed. | Use standard effort; inspect local code and route to the matching platform card. |
| `vague-action` | Asks the agent to act but lacks a precise target, intended behavior, inspection target, or acceptance criteria. This includes, but is not limited to, wording like "fix", "improve", "clean up", or "make better". | Use ambiguity gate or the Grill-Me protocol before implementation. |
| `broad-product` | Asks for a new feature, architecture, PRD, multi-screen flow, data model, billing/auth, or release behavior. | Use product/PRD route and deeper effort. |
| `risky-unclear` | Could affect data, security, money, permissions, destructive changes, migrations, deploys, or external state. | Stop for blocker questions or approval. |

Examples:

- "When does the agent run VibeGuard update?" -> `direct-question`; answer that
  update is only used after explicit approval to refresh an existing managed
  VibeGuard block, otherwise audit current guardrails.
- "Change the button on home" -> `vague-action`; ask which button, state, and
  expected behavior unless the repo has one obvious home button.
- "check", "review", "확인", or "이거 확인해줘" without a named target -> first
  resolve the target from the conversation (the work just reported or the
  artifact under discussion) and the repository state (the current diff, branch,
  or active run). It is `vague-action`, and the agent asks what to inspect, only
  when that still leaves no single plausible target.
- "Add profile saving and avatar presets" -> `vague-action` or
  `broad-product` unless an existing PRD/spec/code owner already answers
  storage, API, loading, error, and acceptance questions.
- "Check the overall documentation status" -> `clear-scoped`; audit the docs
  because the deliverable is inspection/status, not invented product behavior.
- "Improve the X button in `HomeScreen`" -> `clear-scoped`; inspect
  `HomeScreen`, nearby UI patterns, and platform UI cards.
- "Fix this compiler error: <error output>" -> `clear-exact`; inspect the
  referenced file and line before loading broad architecture cards.
- "Build invitations with roles and billing limits" -> `broad-product`; use PRD
  or product workflow with auth, invitation, and billing cards.
- "Show me how we build an app/feature in this repo" -> `direct-question` if
  answer-only, but the answer must front-load PRD -> ARD -> implementation. If
  the user asks to proceed, use the `product` route, not `feature`.

## Decision Rule

The selected route must protect the highest-risk part of the request, not the
last word the user used. If a request includes both a simple edit and auth,
data, billing, release, migration, external state, or architecture risk, route
for the risky surface.

Use `direct-question` only until the question is answered. If the same turn also
contains an actionable request, continue with the appropriate route after the
answer and keep the answer as request-intake evidence.

Do not downgrade effort only because a task names one file. If that file is a
composition point, public contract, migration, release config, app shell, or
security boundary, inspect the owner boundary and escalate.

Do not skip questions only because the request resembles a previously handled
phrase. If local context cannot determine user-visible behavior, acceptance
criteria, data ownership, permission/security handling, cost impact, or
verification, stop at triage or ambiguity and ask the smallest blocker
question.

Choose the lightest work route the evidence supports. Use `small-change` when
bounded inspection proves one existing owner, a clear requested outcome, at most
four changed files, and no risk-sensitive concern, as defined in
`common/skills/agent-operating-skill/references/small-change.md`. Use `task` or
the specific work route when scope is uncertain, crosses owners, or touches a
risk surface; do not send every terse request to `small-change`.

## Alignment Brief

For requirements analysis and modification routes, always provide a compact
alignment brief before drafting requirements or changing files. This is not the
same as invoking Grill-Me and it is not limited to PRD work. The brief must
surface what the agent and user appear to share, what may differ, and what is an
unsupported assumption or unknown. Ask only one to three blocker questions when
the answer changes behavior, risk, architecture, acceptance criteria, or
verification; otherwise state the default assumption. Do not satisfy this only
with private notes or finish-check evidence after the fact; the checkpoint must
be visible in the conversation before the work starts.

For prose work, the alignment brief must distinguish style evidence from genre
selection. Examples such as plain Korean endings, "not honorific", or "my
style" are not enough to choose retrospective, announcement, technical guide,
or opinion-piece structure unless the user says so or selects that option.

## Effort Profiles

Use runtime-specific model or reasoning controls only when the runtime supports
them. First choose an abstract model tier from the effort profile, then let the
active runtime map that tier to a concrete model id. If model selection is not
available, apply the same profile through context loading, planning depth, and
verification scope.

| Effort | Use When | Behavior |
| --- | --- | --- |
| `quick` | Clear exact target, low risk, one file/symbol/doc answer, or explicit error output. | Read local instructions plus the exact files/snippets; avoid broad planning; run the narrowest check. |
| `standard` | Scoped implementation, bugfix, refactor, or docs work with normal local context. | Use workflow route, relevant platform/common cards, focused plan, focused verification. |
| `deep` | Ambiguous product behavior, architecture choice, security/data/release risk, cross-module changes, or repeated failure. | Use ambiguity/product/multi-perspective routes, more context, explicit tradeoffs, stronger verification. |
| `specialist` | Platform/security/release/billing/auth/database/AI-tooling risk requires a specific skill or expert agent. | Route to the specialist card/agent and keep write scopes explicit. |

## Token Controls

- Start with repo-local instructions and this intake card; do not load the full
  library.
- Use `scripts/workflow.py classify "<request>"` for unclear, direct-question,
  or multi-step requests when the script is available; skip it only for clear,
  low-risk answer-only tasks after answering them.
- For multi-step work, run `<TAO_LAUNCHER> start` once with the selected
  command and current request. Open every route `required_docs` entry directly,
  run the review hook after meaningful changes, and run the finish hook before
  handoff. Direct `workflow.py route` is a lower-level diagnostic fallback when
  the hook is unavailable. If classification reports `direct-question`, answer
  before routing. If it reports `grill_me: true` or legacy
  `question_drill: true`, use `triage` or `ambiguity` and a Grill-Me
  `/grilling` session before work.
- Use `--request-classified` only as a delegated worker whose parent left a
  ready and valid execution capsule, and only after the direct question was
  answered or the ambiguity was actually resolved. Without that capsule the flag
  is not honored and the classifier runs on `--request` as for any other caller.
  Evidence that still says `vague-action`,
  `broad-product`, `risky-unclear`, `direct-question`, `answer_first`,
  `clarify_first`, `ambiguous`, `unclear`, `grill_me: true`, or
  `question_drill: true` and their obvious hyphen/space variants must not open
  a work route; route to `triage` or `ambiguity` first and record the answered
  question or blocker-question outcome.
- Work routes require a positive resolved-scope evidence phrase such as
  `clear-exact`, `clear-scoped`, `answered ... separate actionable`, or
  `blockers resolved`. Weak evidence such as `classified`, `done`, or `handled`
  is not enough, and blocker-open wording such as `not clarified`,
  `unresolved`, or `open questions` keeps the work route blocked. Generic
  resolution markers such as `clarified` or `no blockers` are not enough unless
  they name the resolved scope, decision, blocker-question outcome, or remaining
  separate action.
- Route after classification: load only the command/platform/concern cards that
  match the task.
- For exact errors, read the error output, referenced files, and nearby code
  before broad docs.
- For exact UI targets, inspect the named screen/component and nearby patterns
  before product-wide architecture.
- For broad product requests, spend tokens on PRD/acceptance criteria before
  implementation details. Do not collapse "app-making" or "feature delivery"
  into implementation-only steps.
- Summarize large files or command output; keep only evidence needed for the
  next decision.

## Escalation Triggers

Escalate from `quick` to `standard` or `deep` when:

- the named file is not the real owner of the behavior
- the change crosses modules, platforms, data, auth, billing, release, or
  external state
- tests fail for reasons unrelated to the narrow change
- user-facing behavior, acceptance criteria, or verification is unclear
- a command failure repeats after one focused correction
- a safety or VibeGuard gate reports a blocker

## Verification

Intake is verified when the route and effort explain:

- why the request is answer-only, exact, scoped, vague, broad, or risky
- which repo-local or Tao Agent OS documents must be read before work
- which gate or Grill-Me protocol use blocks implementation, if any
- which verification surface will prove the request when work is complete

When a scripted route is used, the route output and wrapper preflight evidence
are the intake record. When no route is needed, keep the classification implicit
unless it affects scope, safety, or user expectations.

## Report

When useful, report the classification briefly:

```text
Intake: clear-scoped / effort: standard
Reason: target screen and button are named, but local UI patterns need inspection.
Route: feature --platform <platform> --concern ui
```

For tiny tasks, do not over-report. The classification should reduce work, not
become a ceremony.
