---
keyflow_id: sys_common_testing_final_check
status: stable
type: ai-generated
---

# Final Test Check

For the final `tests` gate:

1. Identify the nearest falsifying check before editing; run it afterward.
   Inspect the project orchestrator's plan, use its required runner, and run
   missing checks once. Broaden only for a changed boundary, failure or project
   gate.
2. Record the exact check, exit/pass result, and reproducible count or selector.
   A failed required check blocks completion; unrelated passes cannot replace it.
3. Reuse a pass only when code, dependencies, config, toolchain, fixtures and
   external state match. For `tests`, check that the prior `check`/result covers
   this task's selector and runner. Commit/fast-forward alone needs no rerun;
   honor project freshness and integration checks. Edits, conflicts, changed
   inputs, findings, uncertain provenance, or failed, incomplete or unobserved
   checks invalidate reuse.
4. `gate-batch` `input_paths: []` covers non-ignored project files; explicit
   paths must list every dependency. Omit it for uncertain or revision-sensitive
   checks. Cite provenance; add no reuse gate or fresh-result claim. The snapshot
   checks project/rules state, not ignored tools, artifacts, external state or
   task intent. Verify those separately or rerun.

Optional `verify` runs standard Python unittest with the project's `.venv`
Python when present, otherwise the launcher's Python. For another interpreter
or a project-specific runner, use that runner and the existing tests gate.
Read `current-guidance.md` before choosing `verify`; it does not replace review.

Read `current-guidance.md` only for unresolved test-boundary, fixture, scenario
or failure-classification decisions.
