---
keyflow_id: sys_retrospective_failure_repair
status: stable
type: human-reviewed-needed
---

# Required Hook Or Gate Failure Repair

Use when a required hook, gate, or finish check fails, or when the user
explicitly reports that a previously completed result was wrong and asks to
correct that same result. This flow is blocking because the current task does
not yet satisfy its execution contract.

## Repair And Resume

1. Stop finalization and preserve the original task checkpoint. For a
   user-confirmed wrong completion, treat the earlier completion decision as the
   failed checkpoint even when its recorded gates were successful.
2. Record the observed failure, earliest failed checkpoint, and stable failure
   signature used to identify recurrence.
3. Separate facts, assumptions, missed signals, and unknowns. Name the root
   cause as a missing rule, unclear ownership, weak verification, stale docs,
   missing platform guidance, ambiguous decision, or execution error.
4. Select the canonical Tao Agent OS owner. When the failure exposes a reusable
   operating-rule gap, update the owning guidance before resuming executable
   work, then enforce it through the closest hook, validator, or focused test.
   If the owning guidance already states the exact rule, preserve it and repair
   the execution or verification surface instead of duplicating prose. A note
   or queued lesson alone is not a repair.
5. Verify the repair with the closest allowlisted documentation, workflow,
   hook, validator, or test check. Generate a structural repair receipt that
   binds the actual changed target hash, current preflight and route, recorded
   failure signature, checkpoint, verification kind, and zero exit status.
   Natural-language claims are not repair evidence. Stop if the receipt cannot
   be generated or validated.
6. Apply any safe task-local dependent fix, then resume the original task at
   `first_failed_checkpoint`. Do not replay the same action unchanged and do not
   restart unrelated earlier work.
7. Re-run the failed scope once. Stop if the same failure signature remains.

When a failed finish lists multiple missing route gates, preserve the earliest
failed checkpoint and repair the complete ordered set before resuming. Record
each missing gate with `gate` or `gate-batch`, rerun any required hook such as
`review`, then record the remaining closeout gates (`retrospective check` and
`report`) before invoking `finish` again. Do not treat one successful gate or a
second finish attempt as evidence for the other missing gates.

The successful-task observation threshold does not apply to this blocking
flow. A user-confirmed wrong completion repairs the current task immediately;
it is not queued as a first passive occurrence while the incorrect result
remains unresolved.

If the failure signature reports that a required guidance document changed
because a temporary instruction edit was reverted, keep the canonical restored
document and regenerate the start/preflight capsule before resuming. Never
reintroduce stale temporary guidance merely to match an earlier capsule hash.

If an authorized concurrent writer advances `HEAD` or changes a required
guidance document after startup, treat the capsule mismatch as real stale-input
evidence rather than reverting the concurrent change. Re-read the current
required guidance, revalidate the original task against the current worktree,
regenerate the start/preflight capsule, and resume at the failed checkpoint.
Record the observed old and current revisions in local evidence; do not weaken
the capsule hash check or reuse evidence bound to the earlier revision.

The same rule applies when the concurrent change lands after a successful
Review Hook but before finish: the review attestation is correctly stale. Do
not weaken or rewrite the attestation. Wait for the writer to settle when
necessary, re-read the current guidance, refresh start/preflight, rerun the
affected review, and only then rerun finish.

When the task itself creates the new commit after a successful working-tree
Review Hook, treat the commit as the changed revision even when no concurrent
writer exists. Do not carry the working-tree attestation into finish. Record
the commit/push/report state, then rerun review with `--review-scope
commit-range`, an immutable base, and the committed head under the same fresh
preflight binding. This makes the review subject and the finish-time worktree
binding refer to the same bytes.

When the changed guidance is outside the product checkout, keep the original
task's evidence path and failed checkpoint, verify this repair against the
current runtime guidance/test surface, then start a fresh preflight before
rerunning the affected review. Do not repair the stale attestation in place or
bind the new review to the old runtime snapshot.

If the stale attestation belongs to a run that is already terminal, do not try
to revive or refresh that run in place. Treat the terminal run as historical
evidence, record the stale-binding failure on the new active run, and perform
the review against a newly started run/preflight binding. This keeps a finished
run immutable while still requiring the current worktree to pass a fresh review.

## Executable Contract

```text
repair_cycle_limit: 1
repair_policy: retrospective_repair_verify_resume
resume_scope: first_failed_checkpoint
stop_condition: same_failure_after_repair_or_unsafe_repair
```

This is one repair-and-resume cycle, not a generic retry budget.

Generate the receipt first, then resume with its project-local path:

```text
tao-hook repair-verify \
  --project <TARGET_REPO> --rules <TAO_ROOT> \
  --repair-target <changed_file> \
  --resume-checkpoint <recorded_failed_checkpoint> \
  --repair-verification-kind <workflow_validate|unittest|py_compile|vibeguard>

tao-hook <failed_hook> \
  --repair-cycle 1 \
  --repair-target <same_changed_file> \
  --repair-evidence <project_local_receipt_path> \
  --resume-checkpoint <same_recorded_failed_checkpoint> ...
```

The verifier accepts only a changed file under the project or Tao Agent OS rules
root and fixed verification kinds. A receipt becomes invalid when its target,
preflight, route, failure signature, checkpoint, or result changes.

## Output

```text
Failure repair:
- trigger:
- earliest failed checkpoint:
- failure signature:
- root cause:
- canonical owner:
- durable repair:
- focused verification:
- resume checkpoint:
- repair cycle: 1/1
- stop condition:
```

## Stop If

- The repair needs product, security, release, data, or external-state authority
  that the current task does not grant.
- Canonical ownership is uncertain.
- The repair is unsafe, ambiguous, too broad, or cannot be verified.
- The same failure recurs after the verified repair.
- The single repair cycle is exhausted.
