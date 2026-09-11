---
keyflow_id: sys_task_intake_grill_me_protocol
status: stable
type: human-reviewed-needed
---

# Grill-Me Protocol

Read when classification sets `grill_me: true` or legacy `question_drill: true`,
the user asks for Grill-Me or requirements discovery, or blocker questions are
the deliverable. The alignment brief that every requirements or modification
route needs stays in `current-guidance.md`.

Grill-Me is the blocker-question protocol for pressure-testing a plan or
design before PRD, ARD, or implementation. Prefer an installed Grill-Me skill
when one exists; otherwise use the built-in protocol from this card. A
`/grilling` session asks one question at a time, gives a recommended answer,
waits for feedback, and continues until the decision tree is resolved. It is
not the default for every request. Use it when the user asks for Grill-Me,
wants requirements discovery, the request is `vague-action`, the request is
broad product or architecture work without already-known acceptance criteria,
or unknowns can change behavior, scope, risk, or verification.

Grill-Me rules:

- Invoke the actual Grill-Me skill when it is available.
- If an external Grill-Me skill is unavailable, run this built-in protocol
  instead of skipping the gate: state `Grill-Me protocol /grilling session`,
  ask the blocker question, include the recommended answer and tradeoff, wait
  for feedback, and record the decision/output as gate evidence.
- Do not treat unstructured ad hoc questions as Grill-Me evidence. The session
  must name Grill-Me or `/grilling`, include its output, and capture the
  blocker question or no-blocker decision.
- Feed Grill-Me only the minimum safe task summary and public or repo-safe facts
  needed to ask blocker questions.
- If an answer can be found by inspecting the codebase, inspect the code instead
  of asking the user to explain existing behavior.
- Ask only blocker questions returned by Grill-Me after checking available
  conversation and repo context.
- Ask one question at a time unless the skill output explicitly requires
  grouping.
- Include the skill's recommended answer and tradeoff when presenting the
  question.
- Wait for feedback before continuing Grill-Me.
- Ask one to three concise questions per pass only when the runtime requires a
  batched question format or the skill output is
  explicitly scoped otherwise.
- Prefer concrete choices with tradeoffs and a recommended default when the
  runtime allows structured choices.
- Stop Grill-Me when the task can be classified as `clear-exact`,
  `clear-scoped`, or `broad-product` with existing PRD/spec/ARD/source docs or
  known acceptance criteria.
- Do not invoke Grill-Me to delay a clear low-risk task.
- Do not ask questions that repo-local docs, code, tests, PRD/ARD docs, or error
  output can answer.

If the user explicitly asks for "grill me", "ask me questions", "help define
requirements", or equivalent wording, use Grill-Me as the deliverable until
enough decisions are captured. Treat "그릴미" as an explicit Grill-Me request.
When wrapper evidence is available, a route classification with
`grill_me: true` or legacy `question_drill: true` must finish with Grill-Me
protocol evidence such as `grill-me if needed=</grilling session/output
evidence>`.
Legacy `question drill if needed=<evidence>` is accepted only when the evidence
still names the Grill-Me protocol, skill, or `/grilling` session and output.
Missing Grill-Me evidence is `🐱🔴 FAIL` and requires missed-gate recovery plus
the retrospective workflow before final report, commit, release, or handoff.
