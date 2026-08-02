---
keyflow_id: sys_retrospective_skill_feedback
status: stable
type: human-reviewed-needed
---

# Successful-Task Skill Feedback

Use before finish on every workflow. The closeout check is required; the
follow-up flow begins only when successful completed work, review, or
verification exposed a reusable gap in a skill the agent actually loaded and
applied. A user correction that says a completed result was wrong belongs to
blocking failure repair instead. This Hermes-inspired follow-up starts as a
best-effort side channel. When the current run supplies the occurrence that
reaches the deterministic threshold, its remaining review and maintenance
become required closeout work:

```text
observe -> curate -> review -> stage -> maintain
```

Each arrow is an authority boundary. Work may pause and resume across those
boundaries, but an agent may not report successful finish while its current
threshold occurrence is unresolved. No stage may borrow authority from the
next one.

The separation is adapted from Hermes Agent's documented skill-creation and
periodic curator model, while Tao Agent OS adds stricter content-free records,
explicit caps, staging, and verification before canonical writes:

- <https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/>
- <https://hermes-agent.nousresearch.com/docs/user-guide/features/curator>

## 1. Evaluate Before Finish

After task verification and review, ask one bounded question: would a future
agent materially benefit from changing one skill actually used in this task?

- If no, record `outcome: no_reusable_gap` and `observation: not_needed` on the
  required `retrospective check` gate. Do not create a separate observation.
- If no skill was loaded and applied, record `outcome: no_skill_used`,
  `skills_checked: none`, and `observation: not_needed`.
- If yes, first record `outcome: reusable_gap` and `observation: deferred` on
  the required gate. Then emit at most one allowlisted, content-free observation
  through the optional `skill-feedback` hook. Replace the gate with
  `observation: recorded` only when the hook created or idempotently matched it.
- The caller may name only a skill actually loaded and applied in the completed
  task. The id must resolve to a canonical Tao Agent OS or allowlisted
  project-local bundle and must match `skills_checked` in the current successful
  retrospective record. Do not name an unrelated or merely adjacent skill.
- The hook derives an opaque occurrence key from the current preflight run. It
  never stores the raw run id.
- If the hook, store, or current preflight occurrence is unavailable before an
  observation is stored, record `observation: deferred`; that passive gap does
  not fail finish. After a stored current occurrence reaches the threshold,
  unavailable review or maintenance capacity pauses closeout instead of
  silently discarding the obligation.

The observation hook only records facts. It does not deduplicate recurrence,
queue review, ask a model to judge the skill, create a patch, or edit a
canonical file.

The finish check validates the structured retrospective result. It fails when
the evaluation is missing or when `reusable_gap` is paired with `not_needed`.
It does not fail merely because a valid reusable gap uses `observation:
deferred`. Separately, it derives the current occurrence from the preflight run
identity and fails when a matching candidate has at least two observations but
has not reached a terminal `no_change`, `applied`, or `rejected` record.

Structured gate fields are:

```text
skills_checked: <used skill id(s) or none>
outcome: <no_reusable_gap|reusable_gap|no_skill_used>
observation: <not_needed|recorded|deferred>
```

## Observation Schema

Use structured fields with exact validation:

```text
Skill observation:
- observation_id: <opaque id>
- candidate_id: <opaque identity derived from skill_id + signal>
- skill_id: <canonical safe skill id>
- signal: <schema-owned content-free signal identifier>
- occurrence_key: <opaque key derived from the current preflight run>
- status: observed
- created_at: <timestamp>
```

Observation records contain only content-free metadata. Do not store a raw run
id, prompts, responses, natural-language explanations, commands, paths, repo or
branch names, diffs, logs, source content, environment values, secrets, or
project-specific display names. Gap classification and change judgment do not
belong in the observation.

`signal` must be exactly one of:

- `missing_rule`
- `unclear_ownership`
- `weak_verification`
- `stale_guidance`
- `missing_platform_guidance`
- `ambiguous_decision`
- `execution_error`

The hook rejects every other signal. Do not accept arbitrary safe slugs and do
not merge near-looking text by similarity. A bounded shared vocabulary makes
the exact `skill_id + signal` recurrence identity reachable and auditable.
The CLI help and generated route hook command must enumerate these values from
the same catalog constant; `<safe_signal_slug>` is not a discoverable contract.

Historical records written before this vocabulary closed are compatibility
input, not permission for new legacy writes. The deterministic reader:

- validates the historical `candidate_id` against the exact stored signal,
- maps only entries present in the versioned exact compatibility table,
- groups a mapped record under the canonical `skill_id + signal` identity
  without rewriting the observation file, and
- retains and reports every unmapped safe legacy record.

Do not infer a mapping from spelling, semantic similarity, skill name, prose,
or whichever canonical category seems closest. New writes remain strict even
when a legacy mapping for the submitted slug exists.

## 2. Deterministic Curation

A separate curator processes observations without a model. It may run through
the explicit `skill-curate` hook or the existing bounded maintenance pass:

1. Validate the observation shape, canonical `skill_id`, and schema-owned
   `signal` identifier. For a historical signal, validate the original identity
   first and then apply only the exact versioned compatibility table.
2. Deduplicate replayed `observation_id` and opaque `occurrence_key` values.
3. Build the recurrence identity from exact canonical structured fields:
   `skill_id + signal`. Do not mutate the passive observation to achieve this.
4. Count only distinct valid occurrence keys. Queue review at exactly two
   distinct occurrences.
5. Queue one idempotent review item when the threshold is reached. Preserve its
   distinct-occurrence count and first/last observation timestamps in the queue
   record so later passive-history pruning does not erase the review basis.
6. Keep every state class bounded. The default implementation caps
   review-ready items at 100, staged items at 100, passive observations at 500,
   and completed records at 200. The observation cap is strict. If pruning
   removes a terminal record, it also removes that candidate's passive
   observations so an old `no_change`, `applied`, or `rejected` decision cannot
   be resurrected. Retention never deletes or rewrites canonical skills.
7. Report mapped and unmapped legacy counts. An unmapped record remains passive
   evidence for migration review; silently excluding it is not curation.

The lifecycle status is `observed -> review_ready -> no_change | staged_patch`,
followed later by `applied | rejected` only after bounded maintenance.

The curator must not infer truth, severity, similarity, or recurrence from
prose keywords, task text, prompt content, path names, model confidence, or
free-form explanations. It must not draft or apply a patch. If curation is
unavailable before recurrence can be established, leave passive observations
pending. If the current occurrence already has threshold evidence, finish
reports `curation_pending` and requires the agent to resume that step.

## 3. Bounded Review

A separate bounded reviewer consumes one queued recurrence item and the
canonical skill bundle. It chooses exactly one result:

- `no_change`: existing guidance already covers the issue, evidence is too
  weak, the signal is task-specific, or no testable improvement is justified.
- `staged_patch`: the reviewer supplies content-free `gap_type`, `change_type`,
  and `promotion_target` slugs and writes the decision to an isolated staging
  artifact for later maintenance.

Do not require or store those three reviewer judgments for `no_change`.

The reviewer does not write canonical skill files. A staged patch is a proposal,
not guidance and not promotion evidence. The review should prefer a focused
test, validator, routing rule, or concise decision rule over natural-language
keyword exceptions.

Default to one capable reviewer and the smallest relevant context. Add
independent review only when impact, ambiguity, or cross-owner scope justifies
it. If a reviewer or token budget is unavailable, leave the review queued and
pause the current closeout when that run owns one of the threshold occurrences.
Other tasks whose occurrences are unrelated to the queued candidate continue
normally.

## 4. Staged Maintenance

Canonical skill writes happen only in a bounded, explicitly authored
maintenance task after review. It may be the next resumed closeout checkpoint;
it is never performed implicitly by the observation or finish hook:

1. Revalidate the queued observations, reviewer result, canonical owner, and
   current skill contents.
2. Reject or restage stale, ambiguous, cross-owner, or unverifiable proposals.
3. Author and apply the canonical change only when the active task authorizes
   that maintenance and the applicable approval policy is satisfied.
   Project-local targets are limited to
   `.agents/shared/llm-skills/<skill>/**` and
   `.agents/local/skills/<skill>/**`; the bundle must contain `SKILL.md`, and
   the directory must match the staged promotion target. Do not write adapter
   paths (`.codex/skills`, `.claude/skills`) or a tracked runtime mirror through
   this maintenance hook.
4. Run focused verification plus normal Tao Agent OS documentation,
   workflow, review, and finish checks. The maintenance recorder accepts
   `applied` only when the named canonical target is currently changed, its
   path is structurally linked to the staged `promotion_target`, and one fixed
   verification kind (`workflow_validate`, `unittest`, `py_compile`, or
   `vibeguard`) returns zero.
5. Mark the review applied only after that structural check succeeds. Keep
   rejected and applied history within the documented completed-record cap.

No observation hook, curator, scheduled reviewer, background worker, or model
may automatically mutate canonical skill guidance. Scheduling maintenance is
not authority to apply it.

Do not expose a direct promotion API or a single-hop feedback-to-promotion
path, including for manual maintenance. Every applied improvement must traverse
review, staging, structural target linkage, and a live verification receipt.

## Stop Or Defer

- Defer without blocking when a first observation cannot be stored. Once the
  current run's stored occurrence reaches the threshold, unavailable curation,
  review, or maintenance capacity pauses closeout and preserves the resume
  action instead of allowing a successful finish.
- Return `no_change` when evidence does not justify a testable improvement.
- Stop staged maintenance when ownership is uncertain, the patch is stale,
  verification fails, approval is required but absent, or the proposed change
  would encode task-specific prose as shared policy.
- Never mark maintenance applied from a free-form verification description or
  a caller-supplied success word.
