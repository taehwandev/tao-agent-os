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
   checks invalidate only the affected checks. Name the changed input or the
   evidence that disproves that check's result before rerunning it. A separate
   failure, concurrent unrelated commit, or uncertain screenshot does not
   invalidate passing checks with unchanged covered inputs. Preserve valid
   results while repairing and rerunning the smallest affected selector.
4. `gate-batch` `input_paths: []` covers non-ignored project files; explicit
   paths must list every dependency. Omit it for uncertain or revision-sensitive
   checks. Cite provenance; add no reuse gate or fresh-result claim. The snapshot
   checks project/rules state, not ignored tools, artifacts, external state or
   task intent. Verify those separately or rerun.
5. Stop verification when the required checks covering the requested change
   pass with known provenance. Continue to the authorized review, finish,
   commit and integration; do not add another smoke check, capture, full build,
   or source inspection merely for reassurance. A new check needs a named
   missing requirement, changed input, project gate, or reproducible regression
   caused by the current diff. Record non-blocking observations separately.
6. Bound GUI and environment investigation. An obscured native screenshot or
   unavailable foreground focus is not proof of a product regression. Allow
   one targeted correction and affected rerun under the existing recovery
   contract; do not cycle through new rendering designs or repeatedly steal
   focus. If the same limitation remains, report the evidence and any unmet
   acceptance requirement accurately. Keep it separate from valid behavioral
   and geometry checks; never turn that limitation into a claimed visual pass
   or weaken a failed required check.

Optional `verify` runs standard Python unittest with the project's `.venv`
Python when present, otherwise the launcher's Python. For another interpreter
or a project-specific runner, use that runner and the existing tests gate.
Read `current-guidance.md` before choosing `verify`; it does not replace review.

Read `current-guidance.md` only for unresolved test-boundary, fixture, scenario
or failure-classification decisions.
