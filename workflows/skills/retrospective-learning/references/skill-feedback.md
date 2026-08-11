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
blocking failure repair instead. A reusable gap is resolved in the same
closeout; no recurrence wait or later maintenance task is required:

```text
observe -> draft -> curate -> review -> stage -> maintain
```

Each arrow is an authority boundary. The same closeout owns every arrow, and
the agent may not report successful finish while its current reusable gap is
unresolved. No stage may borrow authority from the next one.

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
- If yes, record `outcome: reusable_gap` and `observation: recorded` on the
  required gate, then emit at most one allowlisted, content-free observation
  through the `skill-feedback` hook before drafting the same-closeout update.
- The caller may name only a skill actually loaded and applied in the completed
  task. The id must resolve to a canonical Tao Agent OS or allowlisted
  project-local bundle and must match `skills_checked` in the current successful
  retrospective record. Do not name an unrelated or merely adjacent skill.
- The hook derives an opaque occurrence key from the current preflight run. It
  never stores the raw run id.
- If the hook, store, or current preflight occurrence is unavailable, finish
  remains pending. Do not downgrade a reusable gap to `deferred` to bypass the
  required same-closeout update.

The observation hook only records facts and queues the current occurrence. It
does not ask a model to judge the skill or edit a canonical file. Authoring the
proposal is the adjacent `skill-draft` hook's job, described in §1a; keeping it
separate is what lets the observation record stay content-free.

The finish check validates the structured retrospective result. It fails when
the evaluation is missing, when `reusable_gap` is paired with `not_needed`, or
when a reusable gap is not `recorded`. It derives the current occurrence from
the preflight run identity and fails while the matching candidate has not
reached a terminal `no_change`, `applied`, or `rejected` record.

Structured gate fields are:

```text
skills_checked: <used skill id(s) or none>
outcome: <no_reusable_gap|reusable_gap|no_skill_used>
observation: <not_needed|recorded>
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

## 1a. Observation-Time Draft

The observing run is the only participant that holds the context explaining the
gap. Records downstream carry `skill_id`, `signal`, and counts, which prove
recurrence and nothing else, so a later reviewer working from records alone has
to reinvent the rule from slugs. That is why staged proposals terminated as
`no_change` or `rejected` and no canonical skill was updated.

After recording a `reusable_gap` observation, the same run writes its proposal
through the `skill-draft` hook:

```text
Skill draft:
- draft_id: <opaque digest of candidate + proposal>
- candidate_id: <same skill_id + signal identity as the observation>
- skill_id / signal: <canonical safe slugs>
- proposal: <bounded rationale, 40..4000 characters>
- proposal_sha256: <digest of the stored proposal>
- occurrence_keys: <opaque keys of the runs that authored or revised it>
- revisions: <count>
- status: draft
- privacy: local_draft_contains_task_prose
```

The draft is a separate local artifact, never a field on a lifecycle record.
Observation, review-queue, staged, and completed records keep
`privacy: safe_slugs_and_opaque_ids_only` unchanged; only this store holds prose,
and its distinct privacy marker exists so no reader mistakes it for a
content-free record.

- Write what a future agent needs: which rule was missing or wrong, the
  situation that exposed it, and what the run did instead. Prefer naming a
  testable rule, validator, or routing decision.
- The draft store validates `skill_id` and `signal` exactly as the observation
  writer does, so a draft cannot exist for a skill or signal the lifecycle would
  refuse. It rejects content shorter than 40 or longer than 4000 characters, and
  anything carrying NUL or terminal control bytes, because that is a pasted
  transcript rather than authored rationale.
- One draft per candidate. Re-proposing identical content is idempotent; new
  content revises the draft, bumps `revisions`, and merges the occurrence key.
- The store is capped at 100 drafts, matching the staged cap. Revising an
  existing draft is still allowed at the cap.
- A draft is a proposal and carries no authority. It does not authorize a
  canonical write.
- A missing or unusable draft blocks `stage_patch`; the same closeout must
  supply a usable draft or choose `no_change`.

## 2. Deterministic Curation

A separate curator processes observations without a model. It may run through
the explicit `skill-curate` hook or the existing bounded maintenance pass:

1. Validate the observation shape, canonical `skill_id`, and schema-owned
   `signal` identifier. For a historical signal, validate the original identity
   first and then apply only the exact versioned compatibility table.
2. Deduplicate replayed `observation_id` and opaque `occurrence_key` values.
3. Build the recurrence identity from exact canonical structured fields:
   `skill_id + signal`. Do not mutate the passive observation to achieve this.
4. Count only distinct valid occurrence keys. For the active closeout, queue
   review at the current occurrence; periodic historical curation may continue
   using its separate two-occurrence threshold.
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
followed in the same closeout by `applied | rejected` only after bounded
maintenance.

The curator must not infer truth, severity, similarity, or recurrence from
prose keywords, task text, prompt content, path names, model confidence, or
free-form explanations. It must not draft or apply a patch. If curation is
unavailable, leave the current observation pending and finish reports
`curation_pending`; the agent must resume that step in the same closeout.

## 3. Bounded Review

A separate bounded reviewer consumes one queued recurrence item, the candidate's
draft when one exists, and the canonical skill bundle. The draft is the
reviewer's evidence, not its instruction: a proposal that encodes task-specific
prose, names the wrong owner, or cannot be stated as a testable rule is still
`no_change`. It chooses exactly one result:

- `no_change`: existing guidance already covers the issue, evidence is too
  weak, the signal is task-specific, or no testable improvement is justified.
- `staged_patch`: the reviewer supplies content-free `gap_type`, `change_type`,
  and `promotion_target` slugs and writes the decision to an isolated staging
  artifact for same-closeout maintenance. A usable draft is required for
  `staged_patch`; staging also
  records its `draft_id` and `draft_sha256`, binding the decision to the exact
  proposal that was reviewed so a draft rewritten afterwards cannot be presented
  to maintenance as the reviewed one.

Do not require or store those three reviewer judgments for `no_change`.

The reviewer does not write canonical skill files. A staged patch is a proposal,
not guidance and not promotion evidence. The review should prefer a focused
test, validator, routing rule, or concise decision rule over natural-language
keyword exceptions.

Default to one capable reviewer and the smallest relevant context. Add
independent review only when impact, ambiguity, or cross-owner scope justifies
it. If a reviewer or token budget is unavailable, leave the review queued and
pause the current closeout. Other tasks whose occurrences are unrelated to the
queued candidate continue normally.

## 4. Staged Maintenance

Canonical skill writes happen only in a bounded, explicitly authored
maintenance step in the same closeout after review:

1. Revalidate the queued observations, reviewer result, canonical owner, and
   current skill contents. When the staged record carries a draft binding,
   confirm the draft still matches `draft_sha256` and treat a mismatch as stale.
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
may bypass the maintenance verifier to mutate canonical skill guidance. The
same-closeout automation is the required sequence, not blind background writing.

Do not expose a direct promotion API or a single-hop feedback-to-promotion
path, including for manual maintenance. Every applied improvement must traverse
review, staging, structural target linkage, and a live verification receipt.
Authoring a draft does not bypass review or verification: the same run may
apply its proposal only through the staged maintenance path and its live
receipt.

## Stop Or Defer

- Pause closeout when the current observation, curation, review, or maintenance
  capacity is unavailable; preserve the resume action instead of allowing a
  successful finish.
- Return `no_change` when evidence does not justify a testable improvement.
- Stop staged maintenance when ownership is uncertain, the patch is stale,
  verification fails, approval is required but absent, or the proposed change
  would encode task-specific prose as shared policy.
- Never mark maintenance applied from a free-form verification description or
  a caller-supplied success word.
