---
keyflow_id: sys_common_testing_final_check
status: stable
type: ai-generated
---

# Final Test Check

Use this compact contract for the final `tests` gate on ordinary code work.

1. Before editing, identify the nearest check that can falsify the requested
   behavior. Run that focused check after the change.
2. Broaden verification only when the changed boundary or a failure gives a
   concrete reason.
   Choose one execution owner for each check: a project orchestrator or a
   manual command. Inspect the orchestrator plan before running either; do not
   run its complete plan after manually running the same checks on unchanged
   bytes. If the project requires its runner, use that runner first and run
   only missing checks separately. Preserve every required gate.
3. Record the exact check, its exit status or pass/fail result, and a count or
   selector that makes the result reproducible.
4. Reuse a passing result while its covered code, dependencies, configuration,
   toolchain, fixtures and relevant external state still match. A commit or
   fast-forward merge alone does not require another test/build run: confirm
   that the tested content reached the target without additional changes and
   that the check does not depend on checkout location or commit metadata.
   Cite the original result as reused, never as a new execution. Preserve
   explicit project freshness and post-integration verification requirements.
   Edits, conflict resolution, changed test inputs, an environment mismatch,
   a new finding or uncertain provenance require the affected checks again;
   broaden only when the changed boundary warrants it. Failed, incomplete or
   unobserved runs are not reusable passing evidence. Keep the provenance in
   existing test evidence; add no separate receipt or gate.
5. A failed required check blocks completion. Unrelated passing checks do not
   replace it.

Load `current-guidance.md` only when choosing test boundaries, fixtures,
scenario coverage, failure classification, or another testing decision that
this final-check contract does not answer.
