---
keyflow_id: sys_workflows_retrospective_learning_md_skill
status: stable
type: ai-generated
---

# Retrospective Learning Workflow

Use at the closeout of every workflow, when a required hook or gate failed,
when the user explicitly reports that a previously completed result was wrong
and asks to correct that same result, or when completed work exposed a reusable
gap in a skill the agent actually used. This bundle is the single owner of the
failure-repair and skill-learning automation boundary.

## Read

- `references/current-guidance.md` for the two-flow decision boundary.
- `references/failure-repair.md` only after a required hook or gate fails.
- `references/skill-feedback.md` for the required closeout check, after
  successful work reveals a reusable skill gap, or during a bounded
  skill-maintenance task.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Classify the event as blocking failure repair or successful-task closeout.
   A user-confirmed wrong completion is blocking failure repair even when the
   earlier lifecycle recorded success; do not wait for recurrence or treat the
   correction as ordinary successful-task feedback.
2. Open only the matching focused reference.
3. Keep failure repair inside the bounded repair-and-resume cycle.
   Select the active Tao Agent OS root as the canonical repair owner. An
   upstream or reference Tao Agent OS checkout is not a repair target unless
   the user explicitly starts a runtime migration task.
4. After task verification and review, but before finish, inspect the skills
   actually loaded and applied and complete the required `retrospective check`.
5. Record the exact fields `skills_checked`, `outcome`, and `observation`.
   Every named skill must resolve to a canonical Tao Agent OS bundle or an
   allowlisted project-local bundle; normalize hyphens to underscores when
   binding it to the feedback record.
   `outcome` must be `no_reusable_gap`, `reusable_gap`, or `no_skill_used`.
   `observation` must be `not_needed`, `recorded`, or `deferred`.
   Pair `no_reusable_gap` and `no_skill_used` with `not_needed`. For a reusable
   gap, first record `deferred`, run the optional feedback hook, then replace it
   with `recorded` only when the hook created or deduplicated the bound
   observation. A reusable gap may produce at most one content-free observation
   tied to an actually used skill.
6. Keep observation, curation, review, staging, and canonical maintenance as
   separate authority boundaries. A first observation or unavailable storage
   remains non-blocking. Once an observation from the current run reaches the
   recurrence threshold, finish must require the bounded review and, for
   `staged_patch`, verified maintenance to reach a terminal result. This is a
   closeout obligation, not permission for a hook to edit canonical guidance.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.
- Do not let one passive observation or unavailable storage block completion.
- Do not let an agent report successful closeout while a threshold-reached
  candidate bound to the current run is still waiting for curation, review, or
  staged maintenance.
- Do not skip the retrospective check merely because no reusable gap is
  expected; record `no_reusable_gap` or `no_skill_used` explicitly.
- Do not route a user-confirmed wrong completion as an ordinary follow-up,
  optional improvement, or successful-task observation.
- Do not treat prose keywords as truth, recurrence, or promotion evidence.
- Do not let an observation hook, curator, or reviewer mutate a canonical skill.
- Do not collapse observation, deterministic curation, bounded review, staged
  patching, and canonical maintenance into one execution.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for all three references.
- If failure-repair ownership or output changes, prove the executable recovery
  policy names Tao Agent OS and not a reference Tao Agent OS checkout.
- If routing changes, prove every route requires `retrospective check`, its
  structured evidence is validated, and every skill-learning hook remains
  optional.
- Prove a first successful-task observation remains non-blocking, while the
  current run's threshold-reached candidate blocks closeout until `no_change`,
  `applied`, or `rejected` is recorded.
- Prove unrelated historical review-queue items never block the current run.
- Prove a user-confirmed wrong completion enters blocking failure repair while
  an optional improvement or unrelated follow-up does not.
- Prove correction routing requires an explicit completed-result anchor, keeps
  `triage`, `ambiguity`, and read-only `analysis` available for diagnosis, and
  still refuses work routes that would bypass repair.
- Prove `observation: recorded` is refused until the current occurrence has a
  matching stored observation for one checked skill.
- Prove new observations reject legacy signal slugs while the curator preserves
  historical records, applies only the versioned exact compatibility table, and
  reports every unmapped legacy record without fuzzy merging.
- Prove only later staged maintenance can write canonical skill files, subject
  to its verification and approval policy.
- Prove project-local maintenance is restricted to
  `.agents/shared/llm-skills/<skill>/**` and
  `.agents/local/skills/<skill>/**`, with a real bundle `SKILL.md` and matching
  promotion target.
