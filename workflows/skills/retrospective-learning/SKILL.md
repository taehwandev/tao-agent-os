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
  successful work reveals a reusable skill gap, when authoring the
  observation-time draft, or during a bounded skill-maintenance task.
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
   `observation` must be `not_needed` or `recorded`. Pair
   `no_reusable_gap` and `no_skill_used` with `not_needed`. For a reusable gap,
   record the bound observation before continuing; same-closeout maintenance
   cannot start from a deferred observation. A reusable gap may produce at most
   one content-free observation tied to an actually used skill.
6. For a reusable gap, also write the proposal through the `skill-draft` hook
   while this run still holds the context. Records carry only `skill_id`,
   `signal`, and counts; the draft carries the bounded rationale needed to
   author the change.
7. Keep observation, drafting, curation, review, staging, and canonical
   maintenance as separate authority boundaries, but complete them in the same
   closeout when `reusable_gap` is recorded. The runtime does not blindly write
   prose: the agent authors the canonical skill change, then the maintenance
   recorder verifies the changed target before finish.
8. Read the `Skill learning backlog` line that start and finish print whenever
   anything waits. It counts what earlier runs left in the review queue and in
   staging, and ages the oldest from when it was queued. It is a report, not a
   gate: unrelated historical items still never block the current run, so
   draining the queue is a task to schedule, not an obstacle to clear.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.
- Do not let an agent report successful closeout while the current reusable gap
  is still waiting for curation, review, or verified maintenance.
- Do not skip the retrospective check merely because no reusable gap is
  expected; record `no_reusable_gap` or `no_skill_used` explicitly.
- Do not route a user-confirmed wrong completion as an ordinary follow-up,
  optional improvement, or successful-task observation.
- Do not treat prose keywords as truth, recurrence, or promotion evidence.
- Do not let an observation hook, draft recorder, curator, or reviewer bypass the
  maintenance verifier when changing a canonical skill.
- Do not collapse the authority boundaries, even though the same closeout must
  complete them for a reusable gap.
- Do not treat an authored draft as proof of verification; the changed canonical
  target still needs the maintenance receipt.
- Do not put proposal prose into an observation, review-queue, staged, or
  completed record; those keep `safe_slugs_and_opaque_ids_only`.
- Do not enforce a precondition in a hook that cannot yet be satisfied. When two
  hooks each need the other's output, name one owning hook and check it once, at
  the later one. The observation-exists check is owned by finish, not by gate
  recording, because the order records the gate first and emits the observation
  second; enforcing it at gate time closed the loop and made every reusable gap
  unrecordable.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for all three references.
- If failure-repair ownership or output changes, prove the executable recovery
  policy names Tao Agent OS and not a reference Tao Agent OS checkout.
- If routing changes, prove every route requires `retrospective check`, its
  structured evidence is validated, and every skill-learning hook remains
  optional.
- Prove a reusable-gap observation queues same-closeout follow-up and blocks
  finish until `no_change`, `applied`, or `rejected` is recorded.
- Prove unrelated historical review-queue items never block the current run,
  and that start and finish still report how many wait and how old the oldest
  is, so a queue nothing drains cannot stay invisible.
- Prove a user-confirmed wrong completion enters blocking failure repair while
  an optional improvement or unrelated follow-up does not.
- Prove correction routing requires an explicit completed-result anchor, keeps
  `triage`, `ambiguity`, and read-only `analysis` available for diagnosis, and
  still refuses work routes that would bypass repair.
- Prove `observation: recorded` is refused until the current occurrence has a
  matching stored observation for one checked skill, and that this refusal lives
  in finish so the documented gate-then-observation order stays reachable.
- Prove every cross-hook precondition names its owning hook and is reachable by
  recording the full ordered sequence, so a later contract change cannot leave a
  check enforced where it cannot be satisfied.
- Prove new observations reject legacy signal slugs while the curator preserves
  historical records, applies only the versioned exact compatibility table, and
  reports every unmapped legacy record without fuzzy merging.
- Prove same-closeout staged maintenance is the only path that can write
  canonical skill files, subject to its verification and approval policy.
- Prove a recorded draft leaves the observation record content-free, that the
  draft store is capped and rejects unusable content, that staging binds the
  reviewed proposal by digest, and that staging requires a usable draft.
- Prove project-local maintenance is restricted to
  `.agents/shared/llm-skills/<skill>/**` and
  `.agents/local/skills/<skill>/**`, with a real bundle `SKILL.md` and matching
  promotion target.
