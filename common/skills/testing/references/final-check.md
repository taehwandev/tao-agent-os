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
3. Reuse a pass only while code, dependencies, config, toolchain, fixtures and
   external state match. Commit/fast-forward alone needs no rerun. Honor project
   freshness/integration checks; edits, conflicts, changed inputs, findings or
   uncertain provenance invalidate affected passes. Never reuse failed,
   incomplete or unobserved checks.
4. For revision-independent local `gate-batch` checks, `input_paths: []` covers
   all non-ignored files; otherwise list every dependency. Omit it when inputs
   or revision sensitivity are uncertain. Cite reuse provenance; add no reuse
   gate and never copy an old result as fresh.

For Python unittest, optional `<TAO_LAUNCHER> verify --project <TARGET_REPO>
--rules <TAO_ROOT> --test-pattern 'test_owner*.py'` runs the selection and
records its tests gate. It requires the bound active run, rejects zero tests,
failure, timeout or changed inputs, and leaves failure on interruption. Its
receipt covers only that selection; assess ignored artifacts and external state
normally. Keep the required runner and final review. Do not repeat a check
just to use this shortcut.

Read `current-guidance.md` only for unresolved test-boundary, fixture, scenario
or failure-classification decisions.
