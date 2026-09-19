---
keyflow_id: sys_bugfix_debugging_workflow
status: stable
type: human-reviewed-needed
---

# Bugfix Debugging Workflow

Use when investigating a bug, regression, failing test, flaky behavior, or
production-like failure.

## Read

- `common/skills/agent-operating-skill/SKILL.md`
- `common/skills/testing/SKILL.md`
- `common/skills/verification-policy/SKILL.md`
- `common/skills/tool-failure-recovery/SKILL.md` when a command, compiler, linter, or test
  failure is part of the bug signal
- `common/skills/observability-error-handling/SKILL.md`
- `common/skills/defensive-boundaries/SKILL.md` when the bug involves external, persisted,
  generated, cached, or user-provided values
- matching platform architecture or review card from `index.md`
- security, persistence, API contract, or product-pattern cards when affected

## Feedback Loop And Hypothesis Discipline

For difficult, flaky, or performance-related failures, build a fast,
deterministic pass/fail feedback loop before investigating causes. Write three
to five ranked, falsifiable hypotheses and test one variable at a time. Put the
regression check at the seam that exercises the real failure; if no such seam
exists, record that architecture gap instead of accepting false confidence.
Remove temporary logs, probes, and harnesses, then rerun the original loop.

For non-deterministic failures, optimize for reproduction rate rather than a
perfect one-shot reproduction. Repeat or stress the trigger until the signal is
reliable enough to test against, while keeping the observation and input
controlled. A failing loop that is fast and repeatable is more useful than a
slow, broad smoke check.

## Steps

1. Reproduce or capture the failure with the smallest reliable command, log, or
   manual path.
2. Define expected versus actual behavior and the user or system impact.
3. Inspect the nearest ownership boundary before changing code.
   For optional product context, read the affected behavior's spec section
   before expanding to a whole PRD or ARD. Expand only for an unresolved
   contract; preserve explicitly required full-document reads.
4. Check whether invalid, missing, stale, duplicated, out-of-order, or extreme
   boundary data can produce the failure.
5. Fix the cause, not only the symptom, with the smallest behavior-preserving
   scope.
6. Add or adjust logs, metrics, diagnostics, or user-visible error handling when
   the failure would otherwise be hard to detect or support.
7. Add or update a focused regression check when practical.
8. Re-run the failing check and any nearby checks that prove the affected
   boundary.
9. Report reproduction, root cause, changed behavior, observability impact,
   verification, and remaining risk.

After the fix, remove tagged temporary instrumentation and throwaway harnesses,
rerun the original loop and regression check, and record the architectural gap
when no correct test seam existed. The final explanation should name the
confirmed hypothesis so the next diagnosis can start from evidence.

## Verification

A bug fix needs evidence for both the original failure and the protected
boundary:

- before/after failing test, command, log signal, or manual path when practical
- regression test for the failing input, state transition, platform event, or
  contract
- boundary cases for missing, malformed, stale, duplicated, cancelled, lower
  bound, upper bound, permission-denied, or unavailable values when relevant
- nearby integration or manual smoke when the failure crossed API, persistence,
  cache, auth, platform, release, or background-work boundaries

Do not call the fix verified only because the observed symptom disappeared once.
Name the root cause and the check that would fail if the bug returned.

For a combined diagnosis and refactoring request, track the outcomes separately.
An authorized extraction may be verified while the reported symptom remains
unreproduced. Name each outcome in the final report and any goal checkpoint;
do not mark the whole goal complete from refactor tests alone. Ask for the
smallest missing diagnostic (for example a redacted message or relevant stack),
not a broad log dump. A configured threshold is not proof of the observed
cause, and changing that threshold must not substitute for diagnosis.

## Stop If

- The failure cannot be reproduced and no reliable evidence points to a cause:
  stop speculative bug fixes, but independently authorized refactoring may
  continue with its own acceptance checks and an explicit unresolved symptom.
- The likely fix crosses auth, billing, data loss, migration, or release
  boundaries without enough context.
- The bug report conflicts with documented product behavior.
