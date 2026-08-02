---
keyflow_id: sys_request_triage_workflow
status: stable
type: human-reviewed-needed
---

# Request Triage Workflow

Use when the agent needs to decide whether a user request is clear, whether a
Grill-Me `/grilling` session is needed, and what effort level or route should be used
before planning or implementation.

## Read

When this route is executed through `scripts/workflow.py`, read its
`required_docs` directly before the triage decision. Triage is the decision
point that prevents bad work from starting, so it must not rely only on memory
of these rules.

- `common/skills/task-intake-effort-routing/SKILL.md`
- `common/skills/agent-interaction/SKILL.md`
- `workflows/skills/ambiguity-gate/SKILL.md` when blockers remain
- `index.md` only after the task is classified

## Steps

1. Identify the requested deliverable: answer, edit, review, PRD, plan,
   debugging, refactor, release, or handoff.
2. Classify clarity: `direct-question`, `clear-exact`, `clear-scoped`,
   `vague-action`, `broad-product`, or `risky-unclear`.
3. Select effort: `quick`, `standard`, `deep`, or `specialist`.
4. For requirements analysis, record the compact alignment brief before a
   Grill-Me session: shared understanding, possible mismatch, and
   unsupported assumptions or blocker questions. If the task will not create a
   PRD but will still analyze requirements or modify files, make this a
   user-visible PRD-skip checkpoint before drafting or editing.
5. If `direct-question`, answer before workflow routing, editing, or
   project-specific commands. Stop unless a separate actionable request remains.
6. If `clear-exact`, inspect the named target and avoid broad route loading.
   When restating exact review feedback for a follow-up route, preserve the
   concrete file path, error, or backticked symbol that makes the scope exact.
   Do not append broad PRD, architecture, or product language unless that wider
   work is genuinely part of the correction; a broader restatement must not
   turn a small regression fix into product discovery.
7. If an inspection verb such as `check`, `review`, `확인`, or `검토` has no
   named target, treat it as `vague-action` and ask what to inspect.
8. If `clear-scoped`, run the smallest matching workflow route.
9. If `vague-action` or `risky-unclear`, run Grill-Me or use the ambiguity gate.
10. If `broad-product`, use PRD/product workflow before implementation.
11. Do not reopen a work route with `--request-classified` while the stored
    evidence still says `vague-action`, `broad-product`, `risky-unclear`,
    `direct-question`, `answer_first`, `clarify_first`, `ambiguous`, `unclear`,
    `grill_me: true`, or `question_drill: true`, including obvious
    hyphen/space variants; capture the answered question or blocker-question
    outcome first.
12. For work routes, require positive evidence such as `clear-exact`,
    `clear-scoped`, `answered ... separate actionable`, or `blockers resolved`.
    Do not accept weak evidence such as `classified`, `done`, or `handled`, and
    keep blocking when evidence says `not clarified`, `unresolved`, or
    `open questions`. Generic resolution markers such as `clarified` or
    `no blockers` are not enough unless they name the resolved scope, decision,
    blocker-question outcome, or remaining separate action.
13. Record the selected route only when it changes the work.

## Grill-Me Output

Use when clarification is the deliverable or blockers prevent safe work:

```text
Grill-Me protocol /grilling session
Intake: vague-action / effort: deep-until-clarified
Blocking unknown:
- <the behavior, scope, risk, acceptance, or verification decision that blocks work>

Decision needed:
- A: <recommended concrete direction> - <tradeoff>
- B: <alternative> - <tradeoff>

Why this matters:
- <behavior, risk, verification, or scope impact>

Wait:
- Stop here until the user answers. Do not route to implementation, PRD, ARD,
  review, commit, or editing while this blocker remains open.

Evidence to record:
- grill-me if needed=Grill-Me protocol /grilling session output: <question,
  recommended answer, user decision, and resolved/no-blocker outcome>
```

Do not present a casual clarification question as Grill-Me. When the external
Grill-Me skill is unavailable, the built-in output must still name
`Grill-Me protocol /grilling session`, include a recommended answer and
tradeoff, wait for feedback, and leave finish-check evidence using the
`grill-me if needed=</grilling session/output evidence>` shape.

## Stop If

- The request could affect data, security, billing, release, destructive
  changes, or external state and the key decision is unclear.
- The user asked a direct question and the agent is about to start work without
  answering it.
- The user asked for requirements discovery and the agent is about to implement.
- The agent is about to use deep effort or a specialist agent for a clear
  low-risk request without a reason.
- The agent is about to answer a vague task with invented acceptance criteria.
