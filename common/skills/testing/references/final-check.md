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
3. Record the exact check, its exit status or pass/fail result, and a count or
   selector that makes the result reproducible.
4. A failed required check blocks completion. Unrelated passing checks do not
   replace it.

Load `current-guidance.md` only when choosing test boundaries, fixtures,
scenario coverage, failure classification, or another testing decision that
this final-check contract does not answer.
