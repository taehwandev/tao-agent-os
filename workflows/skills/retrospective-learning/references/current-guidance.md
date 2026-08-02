---
keyflow_id: sys_retrospective_learning_workflow
status: stable
type: human-reviewed-needed
---

# Retrospective Learning Decision Boundary

This document owns the separation between failure recovery and successful-task
skill learning. They share a desire to prevent repeated mistakes, but they do
not share a trigger, completion effect, or automation budget.

## Choose One Flow

| Event | Flow | Completion effect | Detailed reference |
| --- | --- | --- | --- |
| A required hook, gate, or finish check fails | Failure repair | Blocking | `failure-repair.md` |
| The user explicitly reports that a previously completed result was wrong and asks to correct that same result | Failure repair | Blocking | `failure-repair.md` |
| Any workflow reaches successful closeout | Retrospective check | Required before finish | `skill-feedback.md` |
| The check reveals a reusable gap in a skill actually used | Skill observation | Non-blocking until the current occurrence reaches the review threshold | `skill-feedback.md` |

Failure repair protects the current task. It diagnoses the failed checkpoint,
improves a durable enforcement surface, verifies the repair, and resumes once.
A user-confirmed wrong completion is failure evidence even when every earlier
gate said success: the completion decision itself is the failed checkpoint.
This trigger does not require two occurrences.

The closeout check asks whether the skills actually used should change. The
check is required so a route cannot finish without making that decision. Skill
learning then improves future tasks through separate stages: observation,
deterministic curation, bounded review, staged patch, and later canonical
maintenance. Successful work emits at most one content-free observation tied
to a skill actually used. It does not create or edit guidance. Missing storage
may defer a first occurrence without changing the task result. Once the current
occurrence makes a candidate review-ready, bounded review and any staged
verified maintenance must reach a terminal result before successful finish.
Capacity limits may pause and resume that closeout; they no longer permit the
agent to report success while its own repeated candidate is abandoned.

## Ordering

1. Run the task work, verification, and required review.
2. If one fails, or if the user explicitly corrects a previously completed
   result, stop and use failure repair. Do not also treat that failure as
   ordinary successful-task feedback.
3. Before finish, inspect the skills actually loaded and applied, then record
   `no_reusable_gap`, `reusable_gap`, or `no_skill_used` on the required
   `retrospective check` gate.
   Record the exact fields `skills_checked`, `outcome`, and `observation`.
   `observation` is an enum, not a free-form summary: pair
   `no_reusable_gap` or `no_skill_used` with `not_needed`, and pair
   `reusable_gap` with `recorded` or `deferred`. Put task-specific correction
   details in the gate evidence text rather than inventing another observation
   value.
4. When the outcome is `reusable_gap`, first record the required gate with
   `observation: deferred`. The optional feedback hook accepts the observation
   only when its normalized skill id exists in a canonical bundle and matches
   that current successful retrospective record.
5. If the hook created or idempotently matched the observation, replace the
   gate with `observation: recorded`; otherwise keep `deferred`.
6. Run finish. Missing or invalid retrospective-check evidence fails finish;
   missing storage for a first passive observation does not. Finish derives the
   current run's opaque occurrence key and refuses success when that occurrence
   belongs to a threshold-reached candidate still awaiting curation, review, or
   staged maintenance.
7. Let a deterministic curator deduplicate observations by opaque occurrence
   key and queue review only after two distinct observations share the exact
   `skill_id + signal` identity.
8. Let a separate bounded reviewer choose `no_change` or `staged_patch`. When
   the current run is one of the threshold occurrences, this review is required
   closeout work rather than an indefinitely optional queue item.
9. Apply or explicitly reject a staged patch only in a bounded maintenance task
   that satisfies verification and approval policy. A hook still cannot author
   or mutate canonical guidance automatically.

## User-Correction Boundary

Classify a follow-up as blocking failure repair only when the available
conversation context establishes all three facts:

1. it refers to an earlier result that the agent reported as completed,
2. it explicitly states that result is wrong, broken, incomplete, or mistaken,
3. it asks to correct, redo, or repair that same result.

An optional improvement, an unrelated new request, a question without a
correction action, or a bare preference change remains an ordinary follow-up.
Words such as `previous`, `last`, `just`, `work`, `change`, or `output` are not
independent evidence that Tao completed the referenced result. The correction
trigger requires one phrase that explicitly binds a completion action to the
result, plus the failure statement and correction action.
For a terse runtime follow-up, the runtime adapter must keep the user's actual
correction verbatim in `--request` and pass the already-established target in
the separate bounded `--continuation-scope`. Tao must not concatenate prior
conversation prose into the current request or guess an earlier run from
whichever project run happens to be newest. Scope words provide target identity
only; the current request still has to establish the correction action and any
failure claim.

Once that trigger is established, work routes that could bypass repair fail
closed. `triage`, `ambiguity`, and read-only `analysis` remain available so an
agent can inspect uncertainty before entering `retrospective`; diagnosis must
not require pretending the correction is already understood.

## Automation Boundary

- Required gates and failure repair remain fail-closed.
- The `retrospective check` is required finish evidence on every route.
- Skill observation remains a best-effort side channel before recurrence. The
  observation hook is not required, but a stored current occurrence that
  reaches the deterministic threshold creates a required closeout follow-up.
- Observation hooks only append allowlisted content-free facts; they never
  decide recurrence, queue review directly, or edit canonical guidance.
- Curation is deterministic over structured identities and distinct opaque
  observation ids. It must not infer truth from prose, prompt text, keyword
  matches, or persuasive model output.
- A curator may queue review after two distinct opaque occurrence keys share the
  exact `skill_id + signal` identity. It must not draft or apply a skill edit.
- New observations must use one schema-owned signal from
  `missing_rule`, `unclear_ownership`, `weak_verification`, `stale_guidance`,
  `missing_platform_guidance`, `ambiguous_decision`, or `execution_error`.
  Reject other values; do not merge signals by prose similarity.
- Historical observations created before the closed vocabulary remain
  immutable input. The curator may translate one only through the explicit
  versioned legacy table owned by the signal catalog. It must retain and count
  an unmapped record instead of dropping, rewriting, or similarity-merging it.
- Curation and retention enforce explicit caps for observations, review-ready,
  staged, and completed records. Terminal pruning also removes the matching
  passive observations so completed decisions cannot be re-queued.
- The reviewer is a separate bounded step and emits only `no_change` or
  `staged_patch`. Reviewer or token unavailability may pause and resume the
  current closeout, but cannot convert an unresolved threshold candidate into
  a successful finish. Unrelated historical candidates remain non-blocking.
- A staged patch is not canonical guidance. Canonical writes happen only in a
  later bounded maintenance task with required verification and the applicable
  approval policy.
- `applied` is an observed state, not reviewer prose: it requires an actually
  changed canonical target linked to the staged promotion target and a zero
  exit status from an allowlisted verification kind.
- Project-local canonical writes are allowlisted only under
  `.agents/shared/llm-skills/<skill>/**` and
  `.agents/local/skills/<skill>/**`. Adapter paths such as `.codex/skills` and
  `.claude/skills`, and vendored runtime copies, are not maintenance targets.
- No successful-task hook may automatically mutate a canonical skill. The
  active agent authors an approved staged change and the maintenance recorder
  accepts it only after live verification.
- Prefer a focused test, validator, or clearer decision rule over an
  ever-growing list of natural-language exceptions.

## Source Ownership

This skill bundle is the canonical shared owner. Keep `AGENTS.md`, workflow
routes, hooks, and README files as thin consumers of this contract rather than
parallel policy owners. Repo-specific lessons stay in the target repo's local
instructions or source-of-truth docs.
