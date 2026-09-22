---
keyflow_id: sys_common_testing_final_check
status: stable
type: ai-generated
---

# Final Test Check

Use this compact contract for the final `tests` gate on ordinary code work.

1. Before editing, identify the nearest check that can falsify the requested
   behavior. Run that focused check after the change.
2. Choose one execution owner per check. Inspect the project orchestrator's
   plan first; use its runner when required and run only missing checks
   separately. Do not repeat checks on unchanged inputs. Broaden for a changed
   boundary, a failure, or an explicit project gate.
3. Record the exact check, its exit status or pass/fail result, and a count or
   selector that makes the result reproducible.
4. Reuse observed passes only with matching code, dependencies, configuration,
   toolchain, fixtures and external state. Commit/fast-forward alone needs no
   rerun for unchanged tests independent of location and revision. Honor project
   freshness and integration checks. Edits, conflict resolution, changed inputs,
   new findings or uncertain provenance invalidate affected results. Failed,
   incomplete or unobserved checks never pass by reuse.
   In original local `gate-batch` records, use `input_paths: []` for checks
   independent of commit metadata (all non-ignored files), or a complete file
   dependency list. Omit for revision-sensitive/uncertain checks. Cite reused
   results and provenance; never copy them as fresh evidence or add a reuse gate.
5. A failed required check blocks completion. Unrelated passing checks do not
   replace it.

Load `current-guidance.md` only when choosing test boundaries, fixtures,
scenario coverage, failure classification, or another testing decision that
this final-check contract does not answer.
