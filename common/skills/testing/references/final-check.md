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
4. Reuse only observed passing results with matching covered code, dependencies,
   configuration, toolchain, fixtures and relevant external state. Commit or
   fast-forward integration alone needs no rerun if tested content is unchanged
   and the check is independent of checkout location and commit metadata.
   Preserve project freshness and post-integration requirements. Edits, conflict
   resolution, changed inputs/environment, new findings or uncertain provenance
   invalidate affected results; failed, incomplete or unobserved runs cannot
   pass. Cite reused results and provenance in existing evidence, never as a new
   execution or a separate receipt/gate.
5. A failed required check blocks completion. Unrelated passing checks do not
   replace it.

Load `current-guidance.md` only when choosing test boundaries, fixtures,
scenario coverage, failure classification, or another testing decision that
this final-check contract does not answer.
