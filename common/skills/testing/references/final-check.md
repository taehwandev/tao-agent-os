---
keyflow_id: sys_common_testing_final_check
status: stable
type: ai-generated
---

# Final Test Check

For the final `tests` gate:

1. Pick the nearest falsifying check before editing; run it after with the
   project's required runner. Broaden only for a changed boundary, failure or
   project gate.
2. Record the check, exit/pass result, and count or selector. A failed required
   check blocks completion; unrelated passes cannot replace it.
3. Reuse a pass only while its code, dependencies, config, toolchain, fixtures,
   external state, selector and runner match. Commit/fast-forward needs no
   rerun; honor project freshness and integration checks. Rerun only checks
   whose named covered input changed or result is disproved; an unrelated
   failure, commit or uncertain screenshot invalidates nothing else.
4. `gate-batch` `input_paths: []` covers non-ignored project files; explicit
   paths list every dependency; omit it for uncertain or revision-sensitive
   checks. Cite provenance. It does not cover ignored tools, artifacts, external
   state or intent.
5. Stop once required checks covering the change pass with known provenance;
   then review, finish, commit and integrate. A new check needs a named
   missing requirement, changed input, gate or regression from this diff, not
   reassurance.
6. An obscured screenshot or unavailable focus is no product regression: one
   targeted fix and rerun, then report the limit. Never claim a visual pass from
   it or weaken a failed check.

`verify` runs Python unittest with the project `.venv` Python, else the
launcher's; other runners use the tests gate. Read `current-guidance.md` before
`verify` (no review substitute) or for an unresolved test-boundary,
fixture, scenario or failure-classification decision.
